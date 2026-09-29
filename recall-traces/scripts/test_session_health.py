import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

import archive_claude
from plugins.sessions import Plugin
from recall_bounds import Bounds
from recall_runner import Runner
import source_operations


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

    def test_bad_manifest_preserves_search_and_falls_back_only_with_live_source(self):
        manifest = self.destination / 'manifest.json'
        os.utime(self.source, None)
        for payload in ('{', '[]', '{"session":null}', '{"session":{"source_stamp":[1]}}',
                        '{"session":{"source_stamp":[1,"bad"]}}',
                        '{"session":{"source_stamp":[1,true]}}',
                        '{"session":{"source_stamp":[1,1e100]}}'):
            for live in (False, True):
                with self.subTest(payload=payload, live=live):
                    manifest.write_text(payload, encoding='utf-8')
                    store = {'corpus': str(self.corpus)}
                    if live:
                        store['live'] = str(self.live)
                    options = {'plugin': 'sessions', 'stores': [store]}
                    warnings = list(Plugin(options).health(datetime.now(timezone.utc)))
                    if live:
                        self.assertTrue(any('manifest unavailable' in text for text in warnings))
                        self.assertTrue(any('the corpus at' in text for text in warnings))
                    else:
                        self.assertEqual(warnings, [])
                    places = source_operations.Places(Bounds([], str(self.root)), [options])
                    runner = Runner({'sessions': source_operations.Plugin('sessions', options, places)})
                    events = list(runner.invoke('sessions', 'search', {'query': 'original'}))
                    self.assertEqual(len([e for e in events if e['type'] == 'record']), 1)
                    self.assertEqual(events[-1]['outcome']['status'], 'partial' if live else 'success')


if __name__ == '__main__':
    unittest.main()
