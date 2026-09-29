import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

import archive_claude
from plugins.sessions import Plugin


class SessionHealthTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.live = self.root / 'live'
        self.live.mkdir()
        self.source = self.live / 'session.jsonl'
        self.source.write_text(json.dumps({
            'type': 'user', 'sessionId': 'synthetic', 'cwd': str(self.root),
            'timestamp': '2026-09-01T10:00:00Z',
            'message': {'role': 'user', 'content': 'Keep the original note.'},
        }) + '\n', encoding='utf-8')
        self.old = time.time() - 7200
        os.utime(self.source, (self.old, self.old))
        self.destination = self.root / 'archive'
        archive_claude.archive(self.live, self.destination)
        self.corpus = self.destination / 'sessions-corpus'
        self.projection = self.corpus / 'session.md'
        os.utime(self.projection, (self.old, self.old))
        self.plugin = Plugin({'stores': [{'corpus': str(self.corpus), 'live': str(self.live)}]})

    def warnings(self):
        return list(self.plugin.health(datetime.now(timezone.utc)))

    def test_acknowledged_touch_without_content_change_is_not_stale(self):
        before = self.projection.read_bytes()
        stamp = self.projection.stat().st_mtime_ns
        os.utime(self.source, None)
        result = archive_claude.archive(self.live, self.destination)
        self.assertEqual(result['copied'], 0)
        self.assertEqual(result['projected'], 0)
        self.assertEqual(self.projection.read_bytes(), before)
        self.assertEqual(self.projection.stat().st_mtime_ns, stamp)
        self.assertEqual(self.warnings(), [])

    def test_new_content_not_yet_archived_still_warns(self):
        with self.source.open('a', encoding='utf-8') as stream:
            stream.write('{}\n')
        self.assertTrue(any('silent' in warning for warning in self.warnings()))

    def test_recent_acknowledgement_does_not_hide_archive_errors(self):
        os.utime(self.source, None)
        archive_claude.archive(self.live, self.destination)
        status = self.destination / 'status.json'
        data = json.loads(status.read_text(encoding='utf-8'))
        data['errors'] = [{'error': 'Synthetic projection failure'}]
        status.write_text(json.dumps(data), encoding='utf-8')
        self.assertTrue(any('1 errors' in warning for warning in self.warnings()))


if __name__ == '__main__':
    unittest.main()
