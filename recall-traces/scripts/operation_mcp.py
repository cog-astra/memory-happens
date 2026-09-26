import importlib
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from plugins.git_operations import Plugin as GitReader
from recall_runner import Runner


INSTRUCTIONS = '''Recall from one explicitly connected Git repository.
Start with operation_catalog to discover operations and their parameters.
Use git.history to obtain records; pass those records by value to selector.select
through its passages input; pass a selected record's evidence to git.read.
Calls do not keep record handles. The result includes records, a terminal outcome,
and a trace. Check the outcome even when records are present.
The selector searches words, not meanings: try words from the returned history
if the first query misses. You can read evidence directly without selecting.
Only the configured repository is connected; no conversation archives are loaded.'''


def create_server(repo, selector='plugins.select_literal'):
    root = Path(repo).resolve()
    module = importlib.import_module(selector)
    select = module if callable(getattr(module, 'catalog', None)) and callable(getattr(module, 'invoke', None)) else module.Plugin()
    plugins = {'git': GitReader('git', root), 'selector': select}

    def runner():
        return Runner(plugins, policy=lambda resources: all(
            Path(resource).resolve().is_relative_to(root) for resource in resources))

    server = MCPServer('recall', instructions=INSTRUCTIONS)

    @server.tool(structured_output=True, description='List the connected operations, parameter schemas and input ports. Start here to compose a recall workflow.')
    def operation_catalog() -> dict[str, Any]:
        return {'operations': runner().catalog()}

    @server.tool(structured_output=True, description='Run one catalog operation. Pass records from an earlier result by value in the named input port; use evidence in git.read parameters. Returns structured records, outcome and trace.')
    def operation_invoke(
        plugin: Annotated[str, Field(description='Plugin alias from operation_catalog')],
        operation: Annotated[str, Field(description='Operation name from operation_catalog')],
        parameters: Annotated[dict | None, Field(description='Parameters matching the catalog schema')] = None,
        inputs: Annotated[dict | None, Field(description='Named ports mapped to finite lists of complete records')] = None,
    ) -> dict[str, Any]:
        execution = runner()
        events = list(execution.invoke(plugin, operation, parameters, inputs))
        terminal = events[-1]
        return {'records': [event['record'] for event in events if event['type'] == 'record'],
                'outcome': terminal['outcome'], 'invocation': terminal['invocation'],
                'trace': execution.trace}

    return server
