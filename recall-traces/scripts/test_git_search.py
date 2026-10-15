import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from plugins import git as git_source
from test_operation_mcp import server


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                           '-c', 'user.email=test@example.invalid', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


class GitSearchTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='recall git search ')
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        self.messages = ['Fix [WIP] tokenizer crash', 'Release v1.2.0',
                         'Bump v102 schema', 'Wipe temp files', 'Handle a[ literally']
        for message in self.messages:
            (self.repo / 'note.txt').write_text(message, encoding='utf-8')
            git(self.repo, 'add', '.')
            git(self.repo, 'commit', '-q', '-m', message)
        self.config = self.base / 'sources.json'
        self.config.write_text(json.dumps({'sources': [
            {'name': 'work', 'plugin': 'git', 'repos': [str(self.repo)]}]}), encoding='utf-8')
        self.queries = {'[wip]': {self.messages[0]}, 'v1.2': {self.messages[1]},
                        'a[': {self.messages[4]}, 'TOKENIZER': {self.messages[0]},
                        '[wip] v1.2': set(self.messages[:2]), 'absentword': set()}

    def test_literal_queries_override_git_regex_configuration(self):
        git(self.repo, 'config', 'grep.patternType', 'extended')
        for query, expected in self.queries.items():
            with self.subTest(query=query):
                found = list(git_source.commits(self.repo, words=query.casefold().split()))
                self.assertEqual({item['subject'] for item in found}, expected)

    async def test_literal_queries_through_both_mcp_interfaces(self):
        for configured in (False, True):
            args = ('--sources', str(self.config)) if configured else ()
            async with server(*args, env={'RECALL_CONFIG': str(self.config)}) as session:
                for query, expected in self.queries.items():
                    with self.subTest(configured=configured, query=query):
                        arguments = {'query': query, 'characters': 20000}
                        if configured:
                            arguments['view'] = 'passages'
                        reply = await session.call_tool('search', arguments)
                        self.assertFalse(reply.is_error, reply)
                        if configured:
                            body = reply.structured_content
                            self.assertEqual(body['outcome']['status'], 'success', body)
                            texts = '\n'.join(record['text'] for record in body['records'])
                        else:
                            texts = reply.content[0].text
                        found = {message for message in self.messages if message in texts}
                        self.assertEqual(found, expected, texts)
                        if not expected and not configured:
                            self.assertIn('Nothing found', texts)

    def test_empty_repository_is_a_successful_empty_search(self):
        empty = self.base / 'empty'
        empty.mkdir()
        git(empty, 'init', '-q')
        self.assertEqual(list(git_source.commits(empty, words=['a['])), [])

    def test_git_failure_keeps_exit_status_and_stderr(self):
        with self.assertRaises(subprocess.CalledProcessError) as raised:
            git_source.git(self.repo, 'log', '--not-a-real-option')
        self.assertNotEqual(raised.exception.returncode, 0)
        self.assertTrue(raised.exception.stderr)

    async def test_git_failure_is_not_a_successful_empty_mcp_search(self):
        notes = self.base / 'notes'
        notes.mkdir()
        (notes / 'example.md').write_text('The tokenizer note is still readable.', encoding='utf-8')
        cfg = json.loads(self.config.read_text(encoding='utf-8'))
        cfg['sources'].append({'name': 'notes', 'plugin': 'notes', 'roots': [str(notes)]})
        self.config.write_text(json.dumps(cfg), encoding='utf-8')
        (self.repo / '.git' / 'HEAD').write_text('broken\n', encoding='utf-8')
        async with server(env={'RECALL_CONFIG': str(self.config)}) as session:
            reply = await session.call_tool('search', {'query': 'tokenizer'})
            self.assertTrue(reply.is_error, reply)
        async with server('--sources', str(self.config)) as session:
            reply = await session.call_tool('operation_run', {
                'steps': [{'name': 'found', 'plugin': 'work', 'operation': 'search',
                           'parameters': {'query': 'tokenizer'}}],
                'characters': 20000, 'view': 'passages'})
            body = reply.structured_content
            self.assertEqual(body['outcome']['status'], 'failed', body)
            self.assertEqual(body['outcome']['code'], 'operation_failed', body)
            self.assertEqual(body['records'], [])
            reply = await session.call_tool('search', {'query': 'tokenizer', 'characters': 20000,
                                                      'view': 'passages'})
            body = reply.structured_content
            self.assertEqual(body['outcome']['status'], 'partial', body)
            self.assertEqual(body['outcome']['code'], 'incomplete_sources', body)
            self.assertEqual({record['evidence'][0]['source'] for record in body['records']}, {'notes'})
            failed = next(step for step in body['steps'] if step['operation'] == 'work.search')
            self.assertEqual(failed['outcome']['status'], 'failed', body)


if __name__ == '__main__':
    unittest.main()
