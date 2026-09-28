import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from configured_operations import Configuration
from plugins import memory, notes, sessions
from recall_time import TimeWindow
import test_source_operations as source_tests
from test_configured_mcp import fixture
from test_operation_mcp import server
from test_source_operations import DAY1, DAY2, git, line_of


class TimeWindowTest(unittest.TestCase):
    setUp = source_tests.SourceOperationsTest.setUp
    runner = source_tests.SourceOperationsTest.runner
    run_op = source_tests.SourceOperationsTest.run_op

    def test_session_window_selects_messages_not_whole_day_or_file_mtime(self):
        os.utime(self.claude, (1, 1))
        start = DAY1 + timedelta(minutes=5)
        end = DAY1 + timedelta(minutes=9)
        parameters = {'start': start.isoformat(), 'end': end.isoformat()}
        with patch.object(sessions.Plugin, 'recent', side_effect=AssertionError('No recent fallback')):
            records, outcome = self.run_op(self.runner(), 'sessions', 'during', parameters)
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual(len(records), 1)
        found = records[0]
        self.assertIn('Blue it is, two coats.', found['text'])
        self.assertNotIn('paint the lighthouse', found['text'])
        self.assertNotIn('railing', found['text'])
        self.assertNotIn('topics (', found['text'])
        self.assertIsNone(found['context']['topics'])
        self.assertEqual(found['context']['event_time'], start.isoformat())
        self.assertEqual(found['context']['day_start'], start.isoformat())
        self.assertEqual(found['evidence'][0]['locator'],
                         f'{self.claude} start={line_of(self.claude, "[assistant]")}')
        detail = self.run_op(self.runner(), 'sessions', 'read', {'evidence': found['evidence'][0], 'lines': 3})[0]
        self.assertIn('Blue it is, two coats.', detail[0]['text'])
        offset = timezone(timedelta(hours=3))
        shifted = {key: value.astimezone(offset).isoformat() for key, value in [('start', start), ('end', end)]}
        equivalent = self.run_op(self.runner(), 'sessions', 'during', shifted)[0]
        self.assertEqual(found['evidence'], equivalent[0]['evidence'])
        self.assertEqual(found['text'], equivalent[0]['text'])

    def test_file_window_checks_both_mtime_bounds_before_reading(self):
        interval = TimeWindow(DAY1, DAY1 + timedelta(minutes=1))
        for alias, source, path in [('notes', notes, self.cape), ('memory', memory, self.memory_note)]:
            with self.subTest(alias=alias):
                os.utime(path, (DAY1.timestamp(), DAY1.timestamp()))
                with patch.object(source.Plugin, 'recent', side_effect=AssertionError('No recent fallback')):
                    records, _ = self.run_op(self.runner(), alias, 'during', interval.parameters())
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]['context']['modified_at'], DAY1.isoformat())
                self.assertNotIn('event_time', records[0]['context'])
                os.utime(path, (interval.end.timestamp(), interval.end.timestamp()))
                records, _ = self.run_op(self.runner(), alias, 'during', interval.parameters())
                self.assertEqual(records, [])

    def test_author_time_is_independent_of_committer_time(self):
        interval = TimeWindow(DAY1, DAY2)
        with patch.dict(os.environ, {'GIT_COMMITTER_DATE': '2000-01-01T00:00:00+00:00'}):
            git(self.work, 'commit', '--amend', '--no-edit', '--date', DAY1.isoformat())
        expected = git(self.work, 'rev-parse', 'HEAD')
        parameters = interval.parameters()
        records, _ = self.run_op(self.runner(), 'git', 'during', parameters)
        self.assertEqual([r['evidence'][0]['revision'] for r in records], [expected])
        self.assertEqual(records[0]['context']['event_time'], DAY1.isoformat())
        with patch.dict(os.environ, {'GIT_COMMITTER_DATE': DAY1.isoformat()}):
            git(self.work, 'commit', '--amend', '--no-edit', '--date', DAY2.isoformat())
        self.assertEqual(self.run_op(self.runner(), 'git', 'during', parameters)[0], [])

    def test_policy_missing_source_and_invalid_windows(self):
        interval = TimeWindow(DAY2, DAY2 + timedelta(hours=2))
        records, outcome = self.run_op(self.runner(), 'sessions', 'during', interval.parameters())
        self.assertEqual(outcome['code'], 'policy_filtered')
        self.assertNotIn('private lighthouse', json.dumps(records))
        self.assertTrue(any('open lighthouse' in r['text'] for r in records))
        absent = {'plugin': 'notes', 'roots': [str(self.base / 'missing')]}
        self.assertEqual(self.run_op(self.runner(notes=absent), 'notes', 'during', interval.parameters())[1]['status'], 'unavailable')
        for start, end in [('invalid', DAY2.isoformat()), ('2026-01-01T10:00:00', DAY2.isoformat()),
                           (DAY2.isoformat(), DAY1.isoformat()), (DAY1.isoformat(), DAY1.isoformat())]:
            records, outcome = self.run_op(self.runner(), 'notes', 'during', {'start': start, 'end': end})
            self.assertEqual(records, [])
            self.assertEqual(outcome['status'], 'failed')

    def test_recent_resolves_one_interval_for_all_sources(self):
        cfg = {'sources': [dict(options, name=name) for name, options in self.options.items()]}
        configuration = Configuration(cfg)
        interval = TimeWindow(DAY1, DAY2)
        with patch('recall_time.TimeWindow.past', return_value=interval) as clock:
            recipe = configuration.recipe('recent', {'days': 1, 'where': None})
        clock.assert_called_once_with(1)
        self.assertEqual({step['operation'] for step in recipe[:-1]}, {'during'})
        self.assertTrue(all(step['parameters'] == {**interval.parameters(), 'where': None} for step in recipe[:-1]))
        with patch('recall_time.TimeWindow.past', return_value=interval):
            recent = self.run_op(self.runner(), 'sessions', 'recent', {'days': 1})[0]
        absolute = self.run_op(self.runner(), 'sessions', 'during', interval.parameters())[0]
        self.assertEqual([(r['text'], r['evidence']) for r in recent], [(r['text'], r['evidence']) for r in absolute])


class TimeWindowMCPTest(unittest.IsolatedAsyncioTestCase):
    async def test_historical_window_and_reopen_without_recent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, cfg, _, _ = fixture(Path(directory))
            corpus = Path(cfg['sources'][0]['stores'][0]['corpus'])
            (corpus / 'old.md').write_text(
                '# Codex session old\nproject: fixture\norigin: cli\n\n'
                '## 2020-04-08T09:49:00Z [user] L1:B0\n\nBefore the window.\n\n'
                '## 2020-04-08T10:00:00Z [user] L2:B0\n\nThe remote endpoint accepted the first request.\n\n'
                '## 2020-04-08T10:10:00Z [assistant] L3:B0\n\nAfter the window.\n', encoding='utf-8')
            async with server('--sources', str(path)) as session:
                names = {tool.name for tool in (await session.list_tools()).tools}
                self.assertIn('during', names)
                response = await session.call_tool('during', {'start': '2020-04-08T11:50:00+02:00',
                                                              'end': '2020-04-08T12:10:00+02:00', 'characters': 20000})
                self.assertFalse(response.is_error)
                result = response.structured_content
                self.assertEqual(json.loads(response.content[0].text), result)
                self.assertEqual(result['outcome']['status'], 'success')
                self.assertEqual(len(result['records']), 1)
                record = result['records'][0]
                self.assertIn('remote endpoint', record['text'])
                self.assertNotIn('Before the window', record['text'])
                self.assertNotIn('After the window', record['text'])
                self.assertTrue(all(step['operation'].endswith('.during') for step in result['steps'][:-1]))
                detail = await session.call_tool('read', {'evidence': record['evidence'][0], 'lines': 3, 'characters': 8000})
                self.assertIn('remote endpoint', detail.structured_content['records'][0]['text'])
                invalid = await session.call_tool('during', {'start': '2020-01-01', 'end': '2020-01-02', 'characters': 8000})
                self.assertEqual(invalid.structured_content['outcome']['code'], 'invalid_time_window')


if __name__ == '__main__':
    unittest.main()
