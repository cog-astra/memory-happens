import importlib
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import Field

import recall_recipe
from plugins.git_operations import Plugin as GitReader
from recall_runner import Runner


HEADLINE = 160
INSTRUCTIONS = '''Recall from one explicitly connected Git repository.
Start with operation_catalog, then compose a recipe in operation_run. Steps run inside the call:
an input port names an earlier step, so intermediate records never pass through you.
Every call states characters. The reply never carries more content than that: if the output
would be larger, you get its size, no records, and next steps for a narrower recipe.
Begin with the default first_look view. For each step it gives the record count, its scope and
a month-by-month time breakdown; for the output it lists headlines with evidence. For details,
run git.read on chosen evidence with the passages view. Check the outcome even when records
are present. The selector searches words, not meanings: try words from the headlines if the
first query misses. Only the configured repository is connected; no conversation archives are loaded.'''
RUN = '''Run a finite recipe of catalog operations inside one call and return only its last step,
projected by view, within characters. Example first look:
steps=[{"name": "history", "plugin": "git", "operation": "history"},
       {"name": "found", "plugin": "selector", "operation": "select",
        "parameters": {"query": "cache stale"}, "inputs": {"passages": "history"}}]
Details: steps=[{"name": "read", "plugin": "git", "operation": "read",
                 "parameters": {"evidence": <evidence from the first look>}}], view="passages".'''


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def encode(result):
    """The reported size is the length of the very text it is part of."""
    size = result['size']
    while True:
        text = dumps(result)
        if size['characters'] == len(text):
            return text
        size['characters'] = len(text)


def headline(text):
    line = next((line.strip() for line in (text or '').splitlines() if line.strip()), '')
    return line if len(line) <= HEADLINE else line[:HEADLINE - 1] + '…'


def project(record, view):
    if view == 'records':
        return record
    if view == 'passages':
        return {key: record[key] for key in ('text', 'evidence', 'context')}
    return {'headline': headline(record['text']), 'event_time': record['context'].get('event_time'),
            'evidence': record['evidence']}


def brief(outcome):
    return {key: outcome[key] for key in ('status', 'code')}


def over_budget(result, would_be, characters):
    """A fixed-shape summary: names, counts, statuses and codes, never parameters, messages or records."""
    items = result['records']
    next_steps = [f'Repeat with characters >= {would_be}.']
    if result['view'] != 'first_look':
        next_steps.append('Use the first_look view: headlines and evidence only.')
    if 'trace' in result:
        next_steps.append('Leave out trace.')
    next_steps.append('Narrow the recipe: lower a step limit, select before the last step, or shorten parameters.')
    return {
        'outcome': {'status': 'partial', 'code': 'over_budget', 'next_steps': next_steps,
                    'message': f'Output would be {would_be} characters; characters={characters}. Only this summary was returned.'},
        'recipe': brief(result['outcome']),
        'steps': [{key: step[key] for key in ('name', 'operation', 'records')} | {'outcome': brief(step['outcome'])}
                  for step in result['steps']],
        'view': result['view'],
        'size': {'characters': 0, 'limit': characters, 'would_be': would_be, 'records': len(items),
                 'largest_record': max((len(dumps(item)) for item in items), default=0)},
    }


def create_server(repo, selector='plugins.select_literal'):
    root = Path(repo).resolve()
    module = importlib.import_module(selector)
    select = module if callable(getattr(module, 'catalog', None)) and callable(getattr(module, 'invoke', None)) else module.Plugin()
    plugins = {'git': GitReader('git', root), 'selector': select}

    def runner():
        return Runner(plugins, policy=lambda resources: all(
            Path(resource).resolve().is_relative_to(root) for resource in resources))

    server = MCPServer('recall', instructions=INSTRUCTIONS)

    @server.tool(structured_output=True, description='List the connected operations, parameter schemas and input ports. Start here to compose a recipe for operation_run.')
    def operation_catalog() -> dict[str, Any]:
        return {'operations': runner().catalog()}

    @server.tool(description=RUN)
    def operation_run(
        steps: Annotated[list[dict], Field(description='Ordered steps {name, plugin, operation, parameters?, inputs?}. '
                                           'An input port holds the name of an earlier step, or a list of complete records.')],
        characters: Annotated[int, Field(ge=1, description='Required. Maximum length of the returned JSON text in Unicode '
                                         'code points; everything returned counts, including trace.')],
        view: Annotated[Literal['first_look', 'passages', 'records'], Field(
            description='first_look: headline, time and evidence per record. passages: text, evidence and context. '
                        'records: complete records with the runner envelope.')] = 'first_look',
        trace: Annotated[bool, Field(description='Include the runner trace of every step')] = False,
    ) -> CallToolResult:
        execution = runner()
        records, summaries, outcome = recall_recipe.run(execution, steps)
        result = {'outcome': outcome.model_dump(), 'steps': summaries, 'view': view,
                  'records': [project(record, view) for record in records]}
        if trace:
            result['trace'] = execution.trace
        result['size'] = {'characters': 0, 'limit': characters}
        text = encode(result)
        # The fixed-shape summary is returned even when it alone exceeds a very small budget.
        if len(text) > characters:
            text = encode(over_budget(result, len(text), characters))
        return CallToolResult(content=[TextContent(type='text', text=text)], structured_content=json.loads(text))

    return server
