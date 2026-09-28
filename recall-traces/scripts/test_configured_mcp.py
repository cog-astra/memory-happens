import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import recall_bounds
from test_operation_mcp import server
from test_recall_core import commit, git


def fixture(base):
    project = base / 'work'
    project.mkdir()
    git(project, 'init', '-q')
    commit(project, 'cache.txt', 'revision is part of the cache key\n', 'Remove stale lookup cache')
    now = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    corpus = base / 'corpus'
    corpus.mkdir()
    for agent in ('Claude', 'Codex'):
        (corpus / f'{agent}.md').write_text(
            f'# {agent} session fixture\nproject: {project}\norigin: cli\n\n'
            f'## {now} [user] L1:B0\n\nWhy was the cache removed?\n\n'
            f'## {now} [assistant] L2:B0\n\nThe cache key omitted the row revision.\n', encoding='utf-8')
    memory = base / 'projects' / recall_bounds.slug(project) / 'memory'
    memory.mkdir(parents=True)
    (memory / 'lesson.md').write_text('---\ndescription: cache lesson\n---\nCache keys must include revision.\n', encoding='utf-8')
    notes = base / 'notes'
    notes.mkdir()
    (notes / 'cache.md').write_text('# Cache investigation\nThe cache was stale.\nNext: version every row.\n', encoding='utf-8')
    private = base / 'spaces' / 'private'
    private.mkdir(parents=True)
    (private / 'humans.txt').write_text('[recall]\nopen =\n', encoding='utf-8')
    (private / 'secret.md').write_text('# Forbidden cache\nsecret sentinel\n', encoding='utf-8')
    cfg = {'spaces': [str(base / 'spaces')], 'sources': [
        {'plugin': 'sessions', 'stores': [{'corpus': str(corpus)}]},
        {'plugin': 'memory', 'roots': [str(base / 'projects')]},
        {'plugin': 'notes', 'roots': [str(notes), str(private)]},
        {'plugin': 'git', 'repos': [str(project)]}]}
    path = base / 'sources.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    return path, cfg, notes, private


class ConfiguredMCPTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, session, name, **arguments):
        response = await session.call_tool(name, arguments)
        self.assertFalse(response.is_error, response)
        text = response.content[0].text
        result = response.structured_content
        self.assertEqual(json.loads(text), result)
        self.assertEqual(len(text), result['size']['characters'])
        return result

    async def test_all_sources_search_read_fresh_server_and_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            path, cfg, notes, private = fixture(Path(directory))
            async with server('--sources', str(path)) as session:
                found = await self.call(session, 'search', query='cache', characters=20000)
                self.assertNotIn('secret sentinel', json.dumps(found))
                self.assertEqual({r['evidence'][0]['source'] for r in found['records']},
                                 {'sessions', 'memory', 'notes', 'git'})
                note = next(r['evidence'][0] for r in found['records'] if r['evidence'][0]['source'] == 'notes')
                recent = await self.call(session, 'recent', days=7, characters=30000)
                self.assertEqual({r['evidence'][0]['source'] for r in recent['records']},
                                 {'sessions', 'memory', 'notes', 'git'})
                empty = await self.call(session, 'search', query='nonexistentquokka', characters=10000)
                self.assertEqual(empty['records'], [])
                folder = await self.call(session, 'search', query='version', root=str(notes), characters=10000)
                self.assertEqual(len(folder['records']), 1)
            async with server('--sources', str(path)) as session:
                detail = await self.call(session, 'read', evidence=note, start=2, lines=1, characters=10000)
                self.assertIn('The cache was stale.', detail['records'][0]['text'])
                self.assertNotIn('Next: version', detail['records'][0]['text'])
                self.assertIsNotNone(detail['outcome']['continuation'])
                denied = await self.call(session, 'read', path=str(private / 'secret.md'), characters=10000)
                self.assertEqual(denied['records'], [])
                self.assertNotEqual(denied['outcome']['status'], 'success')

    async def test_search_exposes_outside_scope_counts_in_source_outcomes(self):
        with tempfile.TemporaryDirectory() as directory:
            path, _, _, _ = fixture(Path(directory))
            async with server('--sources', str(path)) as session:
                result = await self.call(session, 'search', query='cache', where='no-such-project', characters=20000)
                self.assertEqual(result['records'], [])
                self.assertEqual(result['outcome']['status'], 'success')
                steps = {step['operation']: step['outcome'] for step in result['steps']}
                for source, count in {'sessions': 2, 'memory': 1, 'notes': 1, 'git': 1}.items():
                    outcome = steps[f'{source}.search']
                    self.assertEqual(outcome['message'], f'Matching records outside where: {count}.')
                    self.assertEqual(outcome['next_steps'], ['Repeat this source search without where to include them.'])

    async def test_partial_source_and_cross_source_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            path, cfg, notes, private = fixture(Path(directory))
            cfg['sources'].append({'plugin': 'notes', 'name': 'missing', 'roots': [str(Path(directory) / 'absent')]})
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path)) as session:
                found = await self.call(session, 'search', query='cache', characters=30000)
                self.assertEqual(found['outcome']['status'], 'partial')
                self.assertTrue(found['records'])
                steps = [{'name': 'notes', 'plugin': 'notes', 'operation': 'search', 'parameters': {'query': 'cache stale'}},
                         {'name': 'sessions', 'plugin': 'sessions', 'operation': 'search', 'parameters': {'query': 'cache revision'}},
                         {'name': 'merge', 'plugin': 'collect', 'operation': 'collect',
                          'inputs': {'notes': 'notes', 'sessions': 'sessions', 'memory': [], 'git': [], 'missing': []}},
                         {'name': 'select', 'plugin': 'selector', 'operation': 'select',
                          'parameters': {'query': 'revision stale', 'limit': 10}, 'inputs': {'passages': 'merge'}}]
                combined = await self.call(session, 'operation_run', steps=steps, characters=30000, view='passages')
                self.assertEqual({r['evidence'][0]['source'] for r in combined['records']}, {'notes', 'sessions'})
                oversized = await self.call(session, 'search', query='cache', characters=1)
                self.assertEqual(oversized['outcome']['code'], 'over_budget')
                self.assertNotIn('records', oversized)

    async def test_built_in_search_covers_ten_configured_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'note.md').write_text('A cache lesson.\n', encoding='utf-8')
            cfg = {'sources': [{'plugin': 'notes', 'name': f'notes_{i}', 'roots': [str(base)]} for i in range(10)]}
            path = base / 'sources.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path)) as session:
                result = await self.call(session, 'search', query='cache', characters=30000)
                self.assertEqual(result['outcome']['status'], 'success')
                self.assertEqual({r['evidence'][0]['source'] for r in result['records']}, {f'notes_{i}' for i in range(10)})

    async def test_legacy_addresses_keep_their_window_and_choose_the_connected_git_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path, cfg, notes, _ = fixture(base)
            second = base / 'second'
            second.mkdir()
            git(second, 'init', '-q')
            commit(second, 'notes.txt', 'A second repository.\n', 'Distinct second repository decision')
            revision = subprocess.check_output(['git', '-C', str(second), 'rev-parse', 'HEAD'], text=True).strip()
            cfg['sources'].insert(0, {'plugin': 'notes', 'name': 'broad_notes', 'roots': [str(base)]})
            cfg['sources'].append({'plugin': 'git', 'name': 'second_git', 'repos': [str(second)]})
            (notes / 'plain.txt').write_text('A text file outside the notes pattern.\n', encoding='utf-8')
            path.write_text(json.dumps(cfg), encoding='utf-8')
            async with server('--sources', str(path)) as session:
                detail = await self.call(session, 'read', path=f'read: {notes / "cache.md"} start=2', lines=1, characters=10000)
                self.assertEqual(detail['records'][0]['text'], 'The cache was stale.\n')
                found = await self.call(session, 'read', path=f'read: {second}@{revision}', characters=10000)
                self.assertIn('Distinct second repository decision', found['records'][0]['text'])
                self.assertEqual(found['records'][0]['evidence'][0]['source'], 'second_git')
                fallback = await self.call(session, 'read', path=str(notes / 'plain.txt'), characters=10000)
                self.assertEqual(fallback['records'][0]['text'], 'A text file outside the notes pattern.\n')
                self.assertEqual(fallback['records'][0]['evidence'][0]['source'], 'folder')


if __name__ == '__main__':
    unittest.main()
