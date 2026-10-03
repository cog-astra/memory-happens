import importlib
import re
import sys
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import Field

import recall_archive
from operation_mcp import create_operation_server, reply
from plugins.collect import Plugin as Collection
from recall_bounds import Bounds
from recall_core import load_config
from recall_operations import Operation, Outcome, Value
from recall_recipe import run
from recall_runner import Runner
from recall_query import DESCRIPTION
from recall_time import TimeWindow
from source_operations import query_error


INSTRUCTIONS = '''Recall across connected sources. Start with recent or search, then read the returned evidence.
For a historical interval, use during(start, end) with explicit timezone offsets; start is included, end excluded.
For an event's neighborhood, around(time, seconds) uses seconds on EACH side of its timezone-aware time.
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


REPORTED = set()


class ConfiguredOperation(Value):
    name: str = Field(pattern=r'^[A-Za-z0-9_.-]{1,40}$')
    module: str = Field(min_length=1)
    options: dict = Field(default_factory=dict)


def load(entry):
    try:
        module = importlib.import_module(entry.module)
    except Exception as error:
        return Unloaded(entry, error)
    has_options = 'options' in entry.model_fields_set
    if callable(getattr(module, 'Plugin', None)):
        try:
            plugin = module.Plugin(entry.options) if has_options else module.Plugin()
        except Exception as error:
            return Unloaded(entry, error)
    elif not has_options:
        plugin = module
    else:
        raise ValueError(f'{entry.module} needs a Plugin factory to accept options.')
    if not all(callable(getattr(plugin, method, None)) for method in ('catalog', 'invoke')):
        raise ValueError(f'{entry.module} must supply catalog and invoke.')
    return plugin


class Unloaded:
    def __init__(self, entry, error):
        self.reason = f'{entry.module}: {type(error).__name__}: {error}'[:300]
        self.step = (f"Fix the module or options of the operations entry '{entry.name}', or remove the entry; "
                     'configuration edits take effect when the server restarts.')

    def catalog(self):
        return [Operation('unavailable', f'Not loaded: {self.reason}. {self.step}')]

    def invoke(self, operation, parameters, inputs, context):
        yield Outcome(status='unavailable', code='operation_not_loaded', message=self.reason, next_steps=[self.step])


class Configuration:
    def __init__(self, cfg, reader=None, selector='plugins.select_literal'):
        from source_operations import FolderPlugin, Places, Plugin

        self.bounds = Bounds(cfg.get('spaces', []), reader)
        places = Places(self.bounds, cfg.get('sources', []))
        self.entries, self.plugins = {}, {}
        for entry in cfg.get('sources', []):
            stem = Path(entry['plugin']).stem
            alias = entry.get('name', stem)
            if 'name' not in entry and alias in self.entries:
                alias = f'{stem}_{len(self.entries) + 1}'
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,40}', alias) or alias in self.plugins or alias in ('folder', 'selector', 'collect'):
                raise ValueError(f'Invalid or duplicate source name: {alias}')
            self.entries[alias] = entry
            self.plugins[alias] = Plugin(alias, entry, places)
        self.plugins['folder'] = FolderPlugin('folder', places)
        module = importlib.import_module(selector)
        self.plugins['selector'] = module if callable(getattr(module, 'catalog', None)) else module.Plugin()
        self.plugins['collect'] = Collection(self.entries)
        entries = cfg.get('operations', [])
        if not isinstance(entries, list):
            raise ValueError('operations must be a list; use [] for no additional operations.')
        operations = [ConfiguredOperation.model_validate(entry) for entry in entries]
        names = [entry.name for entry in operations]
        if len(set(names)) != len(names) or set(names) & self.plugins.keys():
            raise ValueError('Operation names must be unique and must not replace sources or built-ins.')
        for entry in operations:
            plugin = self.plugins[entry.name] = load(entry)
            notice = f"recall: operation '{entry.name}' not loaded: {plugin.reason}" if isinstance(plugin, Unloaded) else ''
            if notice and notice not in REPORTED:
                REPORTED.add(notice)
                print(notice, file=sys.stderr)

    def runner(self):
        return Runner(self.plugins, policy=lambda resources: all(not self.bounds.hides(path) for path in resources))

    def recipe(self, operation, parameters, limit=None):
        if operation == 'recent':
            operation, parameters = 'during', {**TimeWindow.past(parameters['days']).parameters(),
                                                'where': parameters.get('where')}
        names = {alias: f'source_{index}' for index, alias in enumerate(self.entries)}
        steps = [{'name': names[alias], 'plugin': alias, 'operation': operation, 'parameters': parameters,
                  'on_error': 'continue'} for alias in self.entries]
        steps.append({'name': 'combined', 'plugin': 'collect', 'operation': 'collect',
                      'parameters': {'order': 'relevance' if operation == 'search' else 'recent',
                                     'limit': limit, 'per_source': operation == 'search'},
                      'inputs': names})
        return steps

    def evidence(self, path):
        locator = path.removeprefix('read: ')
        target = locator.split(' start=')[0]
        if re.match(r'^.+@[0-9a-fA-F]{6,40}$', target):
            for alias, entry in self.entries.items():
                if entry['plugin'] == 'git' and self.plugins[alias].source.repository(target)[0] is not None:
                    return {'source': alias, 'locator': locator}
        path = Path(target)
        resolved = recall_archive.resolve(path)
        for alias, entry in self.entries.items():
            source = self.plugins[alias].source
            if entry['plugin'] != 'git' and source is not None and source.owns(path, resolved):
                return {'source': alias, 'locator': locator}
        return {'source': 'folder', 'locator': locator}


def create_server(config_path, reader=None, selector='plugins.select_literal'):
    cfg = load_config(config_path)

    def configured():
        try:
            return Configuration(cfg, reader, selector)
        except ValueError as error:
            raise ToolError(f'Invalid source configuration: {error}'[:1000]
                            + ' Fix the configuration file and restart the server.') from error

    def runner():
        return configured().runner()

    server = create_operation_server(runner, INSTRUCTIONS, RUN)

    def execute(configuration, steps, characters, view):
        records, summaries, outcome = run(configuration.runner(), steps, max_steps=len(configuration.entries) + 1)
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

    @server.tool(description='Activity in [start, end), using ISO timestamps with timezone offsets. Sessions use message time, Git author time, notes/memory modification time.')
    def during(
        start: str,
        end: str,
        characters: Annotated[int, Field(ge=1)],
        where: str | None = None,
        limit: Annotated[int | None, Field(ge=1)] = None,
        view: Literal['first_look', 'passages', 'records'] = 'passages',
    ) -> CallToolResult:
        try:
            interval = TimeWindow.parse(start, end)
        except ValueError as error:
            return reply([], [], Outcome(status='failed', code='invalid_time_window', message=str(error),
                                         next_steps=['Give start < end as ISO timestamps with explicit timezone offsets.']), characters)
        configuration = configured()
        return execute(configuration, configuration.recipe('during', {**interval.parameters(), 'where': where}, limit), characters, view)

    @server.tool(description='Activity around a known event time. Seconds apply on EACH side: 600 means ten minutes before and after. Same half-open interval and source time bases as during.')
    def around(
        time: Annotated[str, Field(description='Center ISO timestamp with an explicit timezone offset.')],
        seconds: Annotated[int, Field(ge=1, description='Positive seconds on each side of time.')],
        characters: Annotated[int, Field(ge=1)],
        where: str | None = None,
        limit: Annotated[int | None, Field(ge=1)] = None,
        view: Literal['first_look', 'passages', 'records'] = 'passages',
    ) -> CallToolResult:
        try:
            interval = TimeWindow.around(time, seconds)
        except ValueError as error:
            return reply([], [], Outcome(status='failed', code='invalid_time_window', message=str(error),
                                         next_steps=['Give an ISO time with an explicit timezone offset and positive seconds within the datetime range.']), characters)
        return during(**interval.parameters(), characters=characters, where=where, limit=limit, view=view)

    @server.tool(description='Search connected sessions, memory, notes and Git. ' + DESCRIPTION + ' With root, search that folder and its relocated archives. Findings carry evidence for read.')
    def search(
        query: Annotated[str, Field(description=DESCRIPTION)],
        characters: Annotated[int, Field(ge=1)],
        days: Annotated[int | None, Field(ge=1)] = None,
        where: str | None = None,
        root: str | None = None,
        limit: Annotated[int, Field(ge=1)] = 8,
        view: Literal['first_look', 'passages', 'records'] = 'first_look',
    ) -> CallToolResult:
        if error := query_error(query):
            return reply([], [], error, characters, view)
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
        start: Annotated[int | None, Field(ge=1)] = None,
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
