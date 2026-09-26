import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_codex import archive


def row(text, role='user', phase=None):
    return (json.dumps({'type': 'response_item', 'payload': {
        'type': 'message', 'role': role, 'phase': phase,
        'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}],
    }}, ensure_ascii=False) + '\n').encode('utf-8')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'codex'
        self.destination = Path(temporary.name) / 'archive'
        self.path = self.source / 'sessions' / '2026' / 'session.jsonl'
        self.path.parent.mkdir(parents=True)
        self.raw = self.destination / 'raw' / self.path.relative_to(self.source)
        self.corpus = self.destination / 'sessions-corpus' / self.path.relative_to(self.source).with_suffix('.md')

    def run_archive(self):
        return archive(self.source, self.destination)

    def test_round_trip_projection_and_no_deletion(self):
        data = row('привет') + row('reply', 'assistant', 'final_answer') + row('private', 'developer')
        self.path.write_bytes(data)
        self.assertEqual(self.run_archive()['copied'], 1)
        self.assertEqual(self.raw.read_bytes(), data)
        text = self.corpus.read_text(encoding='utf-8')
        self.assertIn('привет', text)
        self.assertIn('reply', text)
        self.assertIn('L2:B0', text)
        self.assertNotIn('private', text)
        self.assertEqual(self.run_archive()['unchanged'], 1)
        self.path.unlink()
        self.assertEqual(self.run_archive()['archived_files'], 1)
        self.assertEqual(self.raw.read_bytes(), data)

    def test_partial_tail_is_preserved_then_exported_after_completion(self):
        first, second = row('one'), row('two')
        self.path.write_bytes(first + second[:25])
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 25)
        self.assertEqual(self.raw.read_bytes(), first + second[:25])
        self.assertNotIn('two', self.corpus.read_text())
        self.path.write_bytes(first + second)
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 0)
        self.assertIn('two', self.corpus.read_text())
        self.assertFalse((self.destination / 'revisions').exists())

    def test_rewrite_keeps_original_and_bad_record_is_visible(self):
        original = row('original')
        self.path.write_bytes(original)
        self.run_archive()
        self.path.write_bytes(b'{invalid}\n')
        report = self.run_archive()
        self.assertEqual(len(report['errors']), 1)
        self.assertEqual(self.raw.read_bytes(), b'{invalid}\n')
        versions = list((self.destination / 'revisions').rglob('*.jsonl'))
        self.assertEqual([p.read_bytes() for p in versions], [original])
        self.assertIn('original', self.corpus.read_text())
        self.assertEqual(len(self.run_archive()['errors']), 1)

    def test_archived_sessions_and_missing_projection(self):
        self.path.write_bytes(row('main'))
        moved = self.source / 'archived_sessions' / 'child.jsonl'
        moved.parent.mkdir()
        moved.write_bytes(row('child'))
        self.assertEqual(self.run_archive()['copied'], 2)
        self.corpus.unlink()
        self.assertEqual(self.run_archive()['copied'], 1)


if __name__ == '__main__':
    unittest.main()
