import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

import synthetic_history

SCRIPT = Path(__file__).with_name('recall_mcp.py')
LOOK = [{'name': 'history', 'plugin': 'git', 'operation': 'history'},
        {'name': 'found', 'plugin': 'selector', 'operation': 'select',
         'parameters': {'query': 'cache stale'}, 'inputs': {'passages': 'history'}}]


def read(evidence):
    return [{'name': 'read', 'plugin': 'git', 'operation': 'read', 'parameters': {'evidence': evidence}}]


@asynccontextmanager
async def server(*arguments, env=None):
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT), *arguments], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams, read_timeout_seconds=60) as session:
        await session.initialize()
        yield session


class OperationMCPTest(unittest.IsolatedAsyncioTestCase):
    async def run_recipe(self, session, steps, characters, **options):
        reply = await session.call_tool('operation_run', {'steps': steps, 'characters': characters, **options})
        self.assertFalse(reply.is_error, reply)
        text = reply.content[0].text
        self.assertEqual(json.loads(text), reply.structured_content)
        self.assertEqual(len(text), reply.structured_content['size']['characters'])
        return reply.structured_content, text

    async def test_first_look_then_details_with_both_selectors(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repo'
            facts = await asyncio.to_thread(synthetic_history.build, repo)
            for selector in ('plugins.select_literal', 'trigram_selector'):
                async with server('--repo', str(repo), '--selector', selector) as session:
                    look, text = await self.run_recipe(session, LOOK, 4000)
                    self.assertEqual(look['outcome']['status'], 'success')
                    self.assertLessEqual(len(text), 4000)
                    history, found = look['steps']
                    self.assertEqual(history['records'], facts['commits'])
                    self.assertEqual(history['outcome']['message'], f'all {facts["commits"]} commits on HEAD.')
                    self.assertEqual({month['month']: month['count'] for month in history['time']}, facts['months'])
                    self.assertEqual(sum(month['count'] for month in found['time']), found['records'])
                    self.assertEqual(found['records'], len(look['records']))
                    self.assertTrue(all(set(item) == {'headline', 'event_time', 'evidence'} for item in look['records']))
                    rollback = next(item['evidence'][0] for item in look['records']
                                    if item['evidence'][0]['revision'] == facts['revisions']['rollback'])

                    detail, _ = await self.run_recipe(session, read(rollback), 20000, view='passages')
                    self.assertEqual(detail['outcome']['status'], 'success')
                    self.assertIn('The cache key omitted the row revision.', detail['records'][0]['text'])

    async def test_budget_is_required_exact_and_withholds_content(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subject = 'Кэш убран 🧠: ревизия строки не входила в ключ'
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Demo', '-c', 'user.email=demo@example.invalid',
                            'commit', '-q', '--allow-empty', '-m', subject], check=True)
            async with server('--repo', str(repo)) as session:
                missing = await session.call_tool('operation_run', {'steps': LOOK[:1]})
                self.assertTrue(missing.is_error)

                full, text = await self.run_recipe(session, LOOK[:1], 999)
                exact = len(text)
                self.assertEqual((full['records'][0]['headline'], len(str(exact))), (subject, 3))
                same, _ = await self.run_recipe(session, LOOK[:1], exact)
                self.assertEqual((same['outcome']['status'], same['size']['characters']), ('success', exact))

                over, text = await self.run_recipe(session, LOOK[:1], exact - 1)
                self.assertEqual((over['outcome']['status'], over['outcome']['code']), ('partial', 'over_budget'))
                self.assertEqual(over['size']['would_be'], exact)
                self.assertNotIn('records', over)
                self.assertNotIn('Кэш', text)
                self.assertTrue(over['outcome']['next_steps'])

                tiny, text = await self.run_recipe(session, LOOK[:1], 1)
                self.assertEqual(tiny['outcome']['code'], 'over_budget')
                self.assertGreater(len(text), 1)

                echoes = {'absentword': ([{**LOOK[1], 'parameters': {'query': 'absentword' * 3000}, 'inputs': {'passages': []}}], 'success'),
                          'sensitive-locator': (read({'source': 'git', 'locator': 'sensitive-locator-' * 2000}), 'unsupported')}
                for echo, (steps, status) in echoes.items():
                    with self.subTest(echo):
                        result, text = await self.run_recipe(session, steps, 1000)
                        self.assertEqual((result['outcome']['code'], result['recipe']['status']), ('over_budget', status))
                        self.assertLessEqual(len(text), 1000)
                        self.assertNotIn(echo, text)

    async def test_outcomes_stay_distinguishable(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repo'
            facts = await asyncio.to_thread(synthetic_history.build, repo)
            vendor = {'source': 'git', 'locator': facts['revisions']['vendor']}
            async with server('--repo', str(repo)) as session:
                cases = {
                    'empty selection': ([LOOK[0], {**LOOK[1], 'parameters': {'query': 'submarine'}}], 'success', '', 'success'),
                    'over budget': (read(vendor), 'partial', 'over_budget', 'success'),
                    'unsupported read': (read({**vendor, 'source': 'unconnected'}), 'unsupported', 'incompatible_evidence', 'unsupported'),
                    'failed step': ([{**LOOK[1], 'inputs': {'passages': []}, 'parameters': {'limit': 0}}], 'failed', 'invalid_call', 'failed'),
                    'invalid recipe': ([{**LOOK[1], 'inputs': {'passages': 'nowhere'}}], 'failed', 'invalid_recipe', None),
                }
                for label, (steps, status, code, step_status) in cases.items():
                    with self.subTest(label):
                        result, _ = await self.run_recipe(session, steps, 8000, view='passages')
                        self.assertEqual((result['outcome']['status'], result['outcome']['code']), (status, code))
                        self.assertEqual(result['steps'][-1]['outcome']['status'] if result['steps'] else None, step_status)

    async def test_default_mode_keeps_legacy_tools(self):
        async with server() as session:
            self.assertEqual({tool.name for tool in (await session.list_tools()).tools}, {'recent', 'search', 'read'})

    async def test_demo_has_no_legacy_file_tools_or_source_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'sources.json'
            config.write_text('not valid JSON', encoding='utf-8')
            async with server('--demo', env={**os.environ, 'RECALL_CONFIG': str(config)}) as session:
                names = {tool.name for tool in (await session.list_tools()).tools}
                self.assertEqual(names, {'operation_catalog', 'operation_run'})
                look, _ = await self.run_recipe(session, LOOK, 4000)
                self.assertEqual((look['steps'][0]['records'], look['outcome']['status']), (4, 'success'))
                missing = await session.call_tool('read', {'path': str(config)})
                self.assertTrue(missing.is_error)


if __name__ == '__main__':
    unittest.main()
