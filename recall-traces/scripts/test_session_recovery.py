from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from source_operations import Sessions
from plugins.sessions import refresh_hint


class SessionRecoveryTest(unittest.TestCase):
    def test_incomplete_or_unknown_store_does_not_offer_a_default_command(self):
        store = {'corpus': '/synthetic/archive/sessions-corpus', 'archiver': 'archive_claude.py'}
        self.assertIn('live source', refresh_hint(store))
        self.assertIn('no matching refresh destination', refresh_hint({**store, 'live': '/synthetic/live',
                                                                     'corpus': '/synthetic/renamed'}))
        self.assertIn('arguments are unknown', refresh_hint({**store, 'archiver': 'custom.py'}))
        self.assertIsNone(refresh_hint({'corpus': store['corpus']}))

    def test_suggested_commands_populate_the_configured_corpus(self):
        for kind in ('claude', 'codex'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "space & dollar$ apostrophe'"
                source = root / 'live'
                live = source / 'sessions' if kind == 'codex' else source
                live.mkdir(parents=True)
                row = ({'type': 'response_item', 'timestamp': '2026-09-01T10:00:00Z',
                        'payload': {'type': 'message', 'role': 'user',
                                    'content': [{'type': 'input_text', 'text': 'recoverycanary'}]}}
                       if kind == 'codex' else
                       {'type': 'user', 'timestamp': '2026-09-01T10:00:00Z',
                        'message': {'role': 'user', 'content': 'recoverycanary'}})
                (live / 'session.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
                corpus = root / 'custom archive' / 'sessions-corpus'
                store = {'corpus': str(corpus), 'live': str(live), 'archiver': f'archive_{kind}.py'}
                reader = Sessions({'stores': [store]})
                now = datetime.now(timezone.utc)
                outcome = reader.coverage(now).outcome('sessions')
                self.assertEqual(outcome.code, 'corpus_missing')
                hint = outcome.next_steps[0]
                self.assertIn('--source', hint)
                self.assertIn('--destination', hint)
                command = hint.partition(': ')[2]
                if os.name == 'nt':
                    script = Path(temporary) / 'refresh.ps1'
                    script.write_text(command + '\nexit $LASTEXITCODE\n', encoding='utf-8-sig')
                    args = ['powershell', '-NoProfile', '-NonInteractive', '-File', str(script)]
                else:
                    args = ['sh', '-c', command]
                completed = subprocess.run(args, capture_output=True, timeout=30,
                                           creationflags=0x08000000 if os.name == 'nt' else 0)
                self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors='replace'))
                self.assertEqual(reader.coverage(now).outcome('sessions').status, 'success')
                hits = list(reader.legacy.search(['recoverycanary'], None))
                self.assertEqual(len(hits), 1)
                self.assertTrue(hits[0]['locator'].startswith(str(corpus)))
                status = corpus.parent / 'status.json'
                status.write_text(json.dumps({'checked_at': (now - timedelta(hours=2)).isoformat()}),
                                  encoding='utf-8')
                warnings = list(reader.legacy.health(now))
                self.assertTrue(any(hint in warning for warning in warnings))


if __name__ == '__main__':
    unittest.main()
