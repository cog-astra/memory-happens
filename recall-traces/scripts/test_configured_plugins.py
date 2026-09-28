import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from configured_operations import Configuration
from test_configured_mcp import fixture
from test_operation_mcp import server


class ConfiguredPluginsTest(unittest.IsolatedAsyncioTestCase):
    def test_operations_container_requires_a_list(self):
        for value in ({}, '', None, False, 0, 1, 'trigram_selector', {'name': 'fuzzy'}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'operations must be a list'):
                Configuration({'operations': value})
        for cfg in ({}, {'operations': []}):
            with self.subTest(cfg=cfg):
                self.assertEqual(set(Configuration(cfg).plugins), {'folder', 'selector', 'collect'})

    async def test_invalid_operations_container_explains_repair_over_mcp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sources.json'
            for value in ({}, None):
                path.write_text(json.dumps({'operations': value}), encoding='utf-8')
                with self.subTest(value=value):
                    async with server('--sources', str(path)) as session:
                        for tool, arguments in [('operation_catalog', {}),
                                                ('search', {'query': 'cache', 'characters': 1000})]:
                            reply = await session.call_tool(tool, arguments)
                            self.assertTrue(reply.is_error, reply)
                            self.assertIn('operations must be a list', reply.content[0].text)
                            self.assertIn('restart the server', reply.content[0].text)

    async def test_configured_transform_runs_after_different_sources_with_options(self):
        with tempfile.TemporaryDirectory(prefix='recall plugin ') as directory:
            base = Path(directory)
            path, cfg, _, _ = fixture(base)
            (base / 'third_party.py').write_text(textwrap.dedent('''\
                from recall_operations import Operation, Outcome, Passage

                class Plugin:
                    def __init__(self, options):
                        self.prefix = options.get('prefix', 'Default: ')

                    def catalog(self):
                        return [Operation('join', 'Join supplied passages.', inputs=('passages',), requires_text=True)]

                    def invoke(self, operation, parameters, inputs, context):
                        records = inputs['passages']
                        yield Passage(text=self.prefix + '\\n'.join(r.text for r in records),
                                      evidence=[e for r in records for e in r.evidence])
                        yield Outcome(status='success')
                '''), encoding='utf-8')
            cfg['operations'] = [{'name': 'joined', 'module': 'third_party', 'options': {'prefix': 'Combined: '}},
                                 {'name': 'empty_options', 'module': 'third_party', 'options': {}},
                                 {'name': 'fuzzy', 'module': 'trigram_selector'}]
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path), import_paths=[base]) as session:
                catalog = await session.call_tool('operation_catalog', {})
                catalog_text = catalog.content[0].text
                self.assertIn('joined', catalog_text)
                self.assertIn('fuzzy', catalog_text)
                for source in ('notes', 'sessions'):
                    steps = [{'name': 'found', 'plugin': source, 'operation': 'search', 'parameters': {'query': 'cache'}},
                             {'name': 'joined', 'plugin': 'joined', 'operation': 'join', 'inputs': {'passages': 'found'}}]
                    result = await session.call_tool('operation_run', {'steps': steps, 'characters': 10000, 'view': 'records'})
                    self.assertFalse(result.is_error, result)
                    body = result.structured_content
                    self.assertEqual(body['outcome']['status'], 'partial' if source == 'notes' else 'success', body)
                    if source == 'notes':
                        self.assertEqual(body['outcome']['code'], 'policy_filtered')
                    record = body['records'][0]
                    self.assertTrue(record['text'].startswith('Combined: '))
                    self.assertEqual({e['source'] for e in record['evidence']}, {source})
                    self.assertTrue(record['access'])
                    self.assertTrue(record['lineage']['inputs'])
                    bounded = await session.call_tool('operation_run', {'steps': steps, 'characters': 1})
                    self.assertEqual(bounded.structured_content['outcome']['code'], 'over_budget')
                    self.assertNotIn('records', bounded.structured_content)
                steps[-1]['plugin'] = 'empty_options'
                empty_options = await session.call_tool('operation_run', {'steps': steps, 'characters': 10000, 'view': 'passages'})
                self.assertTrue(empty_options.structured_content['records'][0]['text'].startswith('Default: '))
                preset = await session.call_tool('search', {'query': 'cache', 'characters': 30000})
                self.assertNotIn('joined.join', json.dumps(preset.structured_content['steps']))
                self.assertEqual({r['evidence'][0]['source'] for r in preset.structured_content['records']},
                                 {'notes', 'sessions', 'memory', 'git'})

    def test_registry_rejects_collisions_before_importing_operations(self):
        for alias in ('folder', 'selector', 'collect', 'notes'):
            with self.subTest(alias=alias), self.assertRaisesRegex(ValueError, 'must not replace'):
                Configuration({'sources': [{'plugin': 'notes'}],
                               'operations': [{'name': alias, 'module': 'does_not_exist'}]})
        with self.assertRaisesRegex(ValueError, 'unique'):
            Configuration({'operations': [{'name': 'same', 'module': 'does_not_exist'}] * 2})

    def test_invalid_plugin_and_ignored_options_are_not_silently_accepted(self):
        for entry in ({'name': 'bad/name', 'module': 'trigram_selector'},
                      {'name': 'x', 'module': 'trigram_selector', 'options': {'unused': True}},
                      {'name': 'x', 'module': 'trigram_selector', 'options': {}},
                      {'name': 'x', 'module': 'json'},
                      {'name': 'x', 'module': 'trigram_selector', 'typo': True}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                Configuration({'operations': [entry]})


if __name__ == '__main__':
    unittest.main()
