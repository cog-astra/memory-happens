import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_claude import archive


def row(content, role='user', **extra):
    return (json.dumps({'type': role, 'sessionId': 's1', 'cwd': 'C:/work',
                        'message': {'role': role, 'content': content}, **extra},
                       ensure_ascii=False) + '\n').encode('utf-8')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'projects'
        self.destination = Path(temporary.name) / 'archive'
        self.path = self.source / 'C--work' / 'session.jsonl'
        self.path.parent.mkdir(parents=True)
        self.raw = self.destination / 'projects' / 'C--work' / 'session.jsonl'
        self.corpus = self.destination / 'sessions-corpus' / 'C--work' / 'session.md'

    def run_archive(self):
        return archive(self.source, self.destination)

    def test_projection_keeps_dialogue_and_tool_intent_but_not_commands(self):
        data = (row('привет')
                + row([{'type': 'thinking', 'thinking': 'hidden'}, {'type': 'text', 'text': 'reply'},
                       {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'secret-tool'}},
                       {'type': 'tool_use', 'name': 'Bash',
                        'input': {'command': 'secret-tool --x', 'description': 'проверить экспорт отчёта'}},
                       {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'C:/work/a.py', 'old_string': 'secret-tool'}}],
                      'assistant')
                + row([{'type': 'tool_result', 'content': 'tool output'}])
                + row('meta note', isMeta=True))
        self.path.write_bytes(data)
        self.assertEqual(self.run_archive()['copied'], 1)
        self.assertEqual(self.raw.read_bytes(), data)
        text = self.corpus.read_text(encoding='utf-8')
        self.assertIn('привет', text)
        self.assertIn('L2:B1', text)
        self.assertIn('project: C:/work', text)
        self.assertIn('[tool:Bash] проверить экспорт отчёта', text)
        self.assertIn('[tool:Edit] C:/work/a.py', text)
        for hidden in ('hidden', 'secret-tool', 'tool output', 'meta note'):
            self.assertNotIn(hidden, text)
        self.assertEqual(self.run_archive()['unchanged'], 1)
        self.path.unlink()
        self.corpus.unlink()
        report = self.run_archive()
        self.assertEqual(report['projected'], 1)
        self.assertEqual(self.raw.read_bytes(), data)

    def test_partial_tail_is_deferred_then_exported(self):
        first, second = row('one'), row('two')
        self.path.write_bytes(first + second[:25])
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 25)
        self.assertNotIn('two', self.corpus.read_text(encoding='utf-8'))
        self.path.write_bytes(first + second)
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 0)
        self.assertIn('two', self.corpus.read_text(encoding='utf-8'))
        self.assertFalse((self.destination / 'revisions').exists())

    def test_rewrite_keeps_original_revision(self):
        original = row('original')
        self.path.write_bytes(original)
        self.run_archive()
        self.path.write_bytes(b'{invalid}\n')
        self.assertEqual(len(self.run_archive()['errors']), 1)
        versions = list((self.destination / 'revisions').rglob('*.jsonl'))
        self.assertEqual([p.read_bytes() for p in versions], [original])
        self.assertIn('original', self.corpus.read_text(encoding='utf-8'))

    def test_subagent_transcripts_are_archived(self):
        child = self.source / 'C--work' / 'session' / 'subagents' / 'agent-a1.jsonl'
        child.parent.mkdir(parents=True)
        child.write_bytes(row('child task', isSidechain=True))
        self.path.write_bytes(row('main'))
        self.assertEqual(self.run_archive()['projected'], 2)
        self.assertIn('child task', (self.destination / 'sessions-corpus' / 'C--work' / 'session'
                                     / 'subagents' / 'agent-a1.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
