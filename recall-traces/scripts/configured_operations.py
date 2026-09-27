import importlib
import re
from pathlib import Path
from typing import Annotated, Literal

from mcp.types import CallToolResult
from pydantic import Field

from operation_mcp import create_operation_server, reply
from plugins.collect import Plugin as Collection
from recall_bounds import Bounds
from recall_core import load_config
from recall_operations import Outcome
from recall_recipe import run
from recall_runner import Runner


INSTRUCTIONS = '''Recall across connected sources. Start with recent or search, then read the returned evidence.
These tools execute recipes through the same operations listed by operation_catalog. For custom workflows,
use operation_run; an input port names an earlier step. Intermediate records stay inside the call.
Every call states characters. Oversized output is replaced by a diagnostic, never silently truncated.
Check outcomes and source coverage even when records are present. Missing sources do not mean no history.
Word search is case-insensitive substring matching; try source words, stems, another period or folder.
Read can continue with the parameters in its outcome. The legacy installed server remains independent.'''
RUN = '''Run connected source and transform operations from operation_catalog.
Each step has name, plugin, operation, parameters and inputs. An input port names an earlier step.
Independent source steps may set on_error="continue" to collect other sources while reporting partial coverage.
Without that option failures stop the recipe; cancellation always stops. Only the last step is returned.'''


class Configuration:
    def __init__(self, cfg, reader=None, selector='plugins.select_literal'):
        from source_operations import FolderPlugin, Plugin

        self.bounds = Bounds(cfg.get('spaces', []), reader)
        self.entries, self.plugins = {}, {}
        for entry in cfg.get('sources', []):
            stem = Path(entry['plugin']).stem
            alias = entry.get('name', stem)
            if 'name' not in entry and alias in self.entries:
                alias = f'{stem}_{len(self.entries) + 1}'
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', alias) or alias in self.plugins or alias in ('folder', 'selector', 'collect'):
                raise ValueError(f'Invalid or duplicate source name: {alias}')
            self.entries[alias] = entry
            self.plugins[alias] = Plugin(alias, entry, self.bounds)
        self.plugins['folder'] = FolderPlugin('folder', self.bounds)
        module = importlib.import_module(selector)
        self.plugins['selector'] = module if callable(getattr(module, 'catalog', None)) else module.Plugin()
        self.plugins['collect'] = Collection(self.entries)

    def runner(self):
        return Runner(self.plugins, policy=lambda resources: all(not self.bounds.hides(path) for path in resources))

    def recipe(self, operation, parameters, limit=None):
        names = {alias: f'source_{index}' for index, alias in enumerate(self.entries)}
        steps = [{'name': names[alias], 'plugin': alias, 'operation': operation, 'parameters': parameters,
                  'on_error': 'continue'} for alias in self.entries]
        steps.append({'name': 'combined', 'plugin': 'collect', 'operation': 'collect',
                      'parameters': {'order': 'relevance' if operation == 'search' else 'recent',
                                     'limit': limit, 'per_source': operation == 'search'},
                      'inputs': names})
        return steps

    def evidence(self, path):
        target = path.removeprefix('read: ').split(' start=')[0]
        for alias, entry in self.entries.items():
            if entry['plugin'] == 'git' and re.match(r'^.+@[0-9a-fA-F]{6,40}$', target):
                return {'source': alias, 'locator': path}
            roots = entry.get('roots', []) + [store['corpus'] for store in entry.get('stores', [])]
            if any(Path(target).resolve().is_relative_to(Path(root).resolve()) for root in roots):
                return {'source': alias, 'locator': path}
        return {'source': 'folder', 'locator': path}


def create_server(config_path, reader=None, selector='plugins.select_literal'):
    cfg = load_config(config_path)

    def configured():
        return Configuration(cfg, reader, selector)

    def runner():
        return configured().runner()

    server = create_operation_server(runner, INSTRUCTIONS, RUN)

    def execute(configuration, steps, characters, view):
        records, summaries, outcome = run(configuration.runner(), steps)
        return reply(records, summaries, outcome, characters, view)

    @server.tool(description='Recent activity across configured sources, through their operations. Time is event time where known; file changes are modification time.')
    def recent(
        characters: Annotated[int, Field(ge=1)],
        days: Annotated[int, Field(ge=1)] = 7,
        where: str | None = None,
        limit: Annotated[int | None, Field(ge=1)] = None,
        view: Literal['first_look', 'passages', 'records'] = 'passages',
    ) -> CallToolResult:
        configuration = configured()
        return execute(configuration, configuration.recipe('recent', {'days': days, 'where': where}, limit), characters, view)

    @server.tool(description='Search connected sessions, memory, notes and Git. With root, search that folder and its relocated archives. Findings carry evidence for read.')
    def search(
        query: str,
        characters: Annotated[int, Field(ge=1)],
        days: Annotated[int | None, Field(ge=1)] = None,
        where: str | None = None,
        root: str | None = None,
        limit: Annotated[int, Field(ge=1)] = 8,
        view: Literal['first_look', 'passages', 'records'] = 'first_look',
    ) -> CallToolResult:
        configuration = configured()
        parameters = {'query': query, 'days': days, 'where': where}
        steps = ([{'name': 'folder', 'plugin': 'folder', 'operation': 'search',
                   'parameters': {**parameters, 'root': root, 'limit': limit}}] if root else
                 configuration.recipe('search', parameters, limit))
        return execute(configuration, steps, characters, view)

    @server.tool(description='Read returned evidence, or a legacy read: path, through its connected source. Use start and lines for windows and inspect continuation.')
    def read(
        characters: Annotated[int, Field(ge=1)],
        evidence: dict | None = None,
        path: str | None = None,
        start: Annotated[int, Field(ge=1)] = 1,
        lines: Annotated[int, Field(ge=1)] = 80,
    ) -> CallToolResult:
        if (evidence is None) == (path is None):
            return reply([], [], Outcome(status='failed', code='invalid_read',
                                         next_steps=['Give either evidence from a finding or a path.']), characters)
        configuration = configured()
        evidence = evidence if evidence is not None else configuration.evidence(path)
        steps = [{'name': 'read', 'plugin': evidence.get('source', ''), 'operation': 'read',
                  'parameters': {'evidence': evidence, 'start': start, 'lines': lines}}]
        return execute(configuration, steps, characters, 'passages')

    return server
