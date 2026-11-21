import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugins import memory, notes
from recall_core import Recall, Source
from recall_mcp import render_search


class TimeBudgetTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.notes = self.base / 'notes'
        self.notes.mkdir()
        for day in range(1, 6):
            path = self.notes / f'n{day}.md'
            path.write_text('lanternword', encoding='utf-8')
            stamp = datetime(2026, 1, day, 12, tzinfo=timezone.utc).timestamp()
            os.utime(path, (stamp, stamp))
        self.cfg = {'sources': [{'plugin': 'notes', 'roots': [str(self.notes)]}]}

    def recall(self):
        return Recall(self.cfg, reader=str(self.base))

    def test_without_a_budget_nothing_changes(self):
        recall = self.recall()
        found, _ = recall.search_with_scope(['lanternword'])
        self.assertEqual(len(dict(found)['notes']), 5)
        self.assertEqual(recall.unfinished, [])

    def test_a_generous_budget_finds_everything_and_reports_nothing(self):
        recall = self.recall()
        found, _ = recall.search_with_scope(['lanternword'], budget=60)
        self.assertEqual(len(dict(found)['notes']), 5)
        self.assertEqual(recall.unfinished, [])

    def test_expiry_keeps_the_newest_files_and_names_the_rest(self):
        calls = iter([False, False, True])
        recall = self.recall()
        with patch.object(Source, 'expired', lambda self: next(calls, True)):
            found, _ = recall.search_with_scope(['lanternword'], budget=60)
        labels = sorted(hit['label'] for hit in dict(found)['notes'])
        self.assertEqual(labels, ['n4.md', 'n5.md'])
        self.assertEqual(recall.unfinished, [('notes', 'files last changed on or before 2026-01-03')])

    def test_a_spent_budget_starts_nothing(self):
        recall = self.recall()
        found, _ = recall.search_with_scope(['lanternword'], budget=0)
        self.assertEqual(dict(found), {'notes': []})
        self.assertEqual(recall.unfinished, [('notes', 'not started')])

    def test_cheap_sources_run_first_and_results_keep_configured_order(self):
        memory_root = self.base / 'memory'
        (memory_root / 'proj' / 'memory').mkdir(parents=True)
        (memory_root / 'proj' / 'memory' / 'm.md').write_text('lanternword', encoding='utf-8')
        cfg = {'sources': [{'plugin': 'memory', 'roots': [str(memory_root)]}, *self.cfg['sources']]}
        ran = []
        for module in (memory, notes):
            original = module.Plugin.search
            module.Plugin.search = (lambda original: lambda self, *args: (ran.append(self.title), original(self, *args))[1])(original)
            self.addCleanup(setattr, module.Plugin, 'search', original)
        found, _ = Recall(cfg, reader=str(self.base)).search_with_scope(['lanternword'], budget=60)
        self.assertEqual(ran, ['notes', 'project memory'])
        self.assertEqual([title for title, _ in found], ['project memory', 'notes'])

    def test_a_source_that_is_off_is_reported_as_off_not_as_late(self):
        cfg = {'sources': [*self.cfg['sources'], {'plugin': 'git', 'repos': []}]}
        recall = Recall(cfg, reader=str(self.base))
        recall.search_with_scope(['lanternword'], opt_in=False, budget=0)
        self.assertEqual(recall.skipped, ['git'])
        self.assertEqual(recall.unfinished, [('notes', 'not started')])

    def test_the_answer_says_what_was_not_reached_even_when_empty(self):
        text = render_search([('notes', [])], ['x'], 8, 4000, unfinished=[('sessions', 'not started'),
                             ('git', '3 of 9 repositories, least recently active')], budget=30)
        self.assertIn('[not finished within 30 s: sessions - not started; git - 3 of 9 repositories', text)
        self.assertIn('Nothing found', text)


if __name__ == '__main__':
    unittest.main()
