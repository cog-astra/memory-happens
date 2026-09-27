import json
import tempfile
import unittest
from pathlib import Path

from test_configured_mcp import fixture
from test_operation_mcp import server


class UnloadedOperationTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, session, name, **arguments):
        response = await session.call_tool(name, arguments)
        self.assertFalse(response.is_error, response)
        return response.structured_content

    async def test_an_unloadable_operation_names_itself_and_leaves_sources_working(self):
        with tempfile.TemporaryDirectory() as directory:
            path, cfg, notes, _ = fixture(Path(directory))
            cfg['operations'] = [{'name': 'missing', 'module': 'plugins.no_such_operation'},
                                 {'name': 'reduce', 'module': 'plugins.ollama_reduce', 'options': {}},
                                 {'name': 'fuzzy', 'module': 'trigram_selector'}]
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path)) as session:
                catalog = (await self.call(session, 'operation_catalog'))['operations']
                unloaded = {entry['plugin']: entry['purpose'] for entry in catalog if entry['name'] == 'unavailable'}
                self.assertEqual(set(unloaded), {'missing', 'reduce'})
                self.assertIn('plugins.no_such_operation', unloaded['missing'])
                self.assertIn('ModuleNotFoundError', unloaded['missing'])
                self.assertIn('ValueError', unloaded['reduce'])
                self.assertIn("operations entry 'reduce'", unloaded['reduce'])
                self.assertIn(('fuzzy', 'select'), {(entry['plugin'], entry['name']) for entry in catalog})

                found = await self.call(session, 'search', query='cache', characters=20000)
                self.assertEqual({r['evidence'][0]['source'] for r in found['records']},
                                 {'sessions', 'memory', 'notes', 'git'})
                recent = await self.call(session, 'recent', days=7, characters=30000)
                self.assertTrue(recent['records'])
                note = next(r['evidence'][0] for r in found['records'] if r['evidence'][0]['source'] == 'notes')
                detail = await self.call(session, 'read', evidence=note, start=2, lines=1, characters=10000)
                self.assertIn('The cache was stale.', detail['records'][0]['text'])

                source = {'name': 'found', 'plugin': 'notes', 'operation': 'search', 'parameters': {'query': 'cache stale'}}
                for plugin, operation, expected in (('missing', 'unavailable', ('unavailable', 'operation_not_loaded')),
                                                    ('reduce', 'summarize', ('unsupported', 'unknown_operation'))):
                    steps = [source, {'name': 'next', 'plugin': plugin, 'operation': operation, 'parameters': {},
                                      'inputs': {} if operation == 'unavailable' else {'passages': 'found'}}]
                    result = await self.call(session, 'operation_run', steps=steps, characters=10000)
                    self.assertEqual((result['outcome']['status'], result['outcome']['code']), expected, plugin)
                    self.assertEqual(result['records'], [])
                selected = await self.call(session, 'operation_run', characters=10000, steps=[
                    source, {'name': 'picked', 'plugin': 'fuzzy', 'operation': 'select',
                             'parameters': {'query': 'stale'}, 'inputs': {'passages': 'found'}}])
                self.assertIn(selected['outcome']['status'], ('success', 'partial'))
                self.assertTrue(selected['records'])

    async def test_a_malformed_entry_still_stops_the_configuration_but_says_why(self):
        with tempfile.TemporaryDirectory() as directory:
            path, cfg, _, _ = fixture(Path(directory))
            cfg['operations'] = [{'name': 'x', 'module': 'json'}]
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path)) as session:
                for tool, arguments in (('search', {'query': 'cache', 'characters': 1000}), ('operation_catalog', {})):
                    response = await session.call_tool(tool, arguments)
                    self.assertTrue(response.is_error, tool)
                    self.assertIn('Invalid source configuration: json must supply catalog and invoke.',
                                  response.content[0].text)


if __name__ == '__main__':
    unittest.main()
