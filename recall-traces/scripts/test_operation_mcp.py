import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from demo_operations import fixture


SCRIPT = Path(__file__).with_name('recall_mcp.py')


class OperationMCPTest(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, session, plugin, operation, **arguments):
        reply = await session.call_tool('operation_invoke', {
            'plugin': plugin, 'operation': operation, **arguments})
        self.assertFalse(reply.is_error, reply)
        self.assertIsInstance(reply.structured_content, dict)
        self.assertEqual(json.loads(reply.content[0].text), reply.structured_content)
        return reply.structured_content

    async def test_both_selectors_over_stdio_and_fresh_server_read(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repo'
            revisions = fixture(repo)
            evidence = None
            for selector in ('plugins.select_literal', 'trigram_selector'):
                params = StdioServerParameters(command=sys.executable,
                    args=[str(SCRIPT), '--repo', str(repo), '--selector', selector])
                async with stdio_client(params) as streams, ClientSession(*streams, read_timeout_seconds=20) as session:
                    await session.initialize()
                    catalog = await session.call_tool('operation_catalog')
                    operations = catalog.structured_content['operations']
                    self.assertEqual({(op['plugin'], op['name']) for op in operations}, {
                        ('git', 'history'), ('git', 'read'), ('selector', 'select')})
                    if evidence:
                        reread = await self.invoke(session, 'git', 'read', parameters={'evidence': evidence})
                        self.assertEqual(reread['outcome']['status'], 'success')
                    history = await self.invoke(session, 'git', 'history')
                    selected = await self.invoke(session, 'selector', 'select',
                        parameters={'query': 'cache stale', 'limit': 1}, inputs={'passages': history['records']})
                    evidence = selected['records'][0]['evidence'][0]
                    self.assertEqual(evidence['revision'], revisions['rollback'])
                    read = await self.invoke(session, 'git', 'read', parameters={'evidence': evidence})
                    self.assertIn('-cache = {}', read['records'][0]['text'])
                    self.assertIn('The cache key omitted the row revision.', read['records'][0]['text'])
                    self.assertEqual(len({result['invocation'] for result in (history, selected, read)}), 3)
                    failed = await self.invoke(session, 'selector', 'select', parameters={'limit': 0})
                    self.assertEqual(failed['outcome']['code'], 'invalid_call')
                    unknown = await self.invoke(session, 'missing', 'unknown')
                    self.assertEqual(unknown['outcome']['status'], 'unsupported')
                    foreign = {**evidence, 'source': 'unconnected'}
                    denied = await self.invoke(session, 'git', 'read', parameters={'evidence': foreign})
                    self.assertEqual(denied['outcome']['code'], 'incompatible_evidence')

    async def test_default_mode_keeps_legacy_tools(self):
        params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT)])
        async with stdio_client(params) as streams, ClientSession(*streams, read_timeout_seconds=20) as session:
            await session.initialize()
            self.assertEqual({tool.name for tool in (await session.list_tools()).tools}, {'recent', 'search', 'read'})

    async def test_demo_has_no_legacy_file_tools_or_source_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'sources.json'
            config.write_text('not valid JSON', encoding='utf-8')
            params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT), '--demo'],
                env={**os.environ, 'RECALL_CONFIG': str(config)})
            async with stdio_client(params) as streams, ClientSession(*streams, read_timeout_seconds=20) as session:
                await session.initialize()
                names = {tool.name for tool in (await session.list_tools()).tools}
                self.assertEqual(names, {'operation_catalog', 'operation_invoke'})
                history = await self.invoke(session, 'git', 'history')
                self.assertEqual(len(history['records']), 4)
                self.assertEqual(history['outcome']['status'], 'success')
                missing = await session.call_tool('read', {'path': str(config)})
                self.assertTrue(missing.is_error)


if __name__ == '__main__':
    unittest.main()
