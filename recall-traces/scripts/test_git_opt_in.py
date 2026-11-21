import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plugins import git as git_source
from recall_core import Recall
from recall_mcp import render_search
from test_recall_core import commit, git


class GitOptInTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.notes = self.base / 'notes'
        self.notes.mkdir()
        (self.notes / 'a.md').write_text('lanternword in a note', encoding='utf-8')
        self.repos = {}
        for name in ('alpha', 'beta'):
            repo = self.base / 'code' / name
            repo.mkdir(parents=True)
            git(repo, 'init', '-q')
            commit(repo, 'f.txt', name, f'lanternword change in {name}')
            self.repos[name] = repo
        self.cfg = {'sources': [{'plugin': 'notes', 'roots': [str(self.notes)]},
                                {'plugin': 'git', 'repos': [str(path) for path in self.repos.values()]}]}

    def titles(self, found):
        return {title: len(hits) for title, hits in found}

    def test_library_default_still_searches_everything(self):
        found, _ = Recall(self.cfg, reader=str(self.base)).search_with_scope(['lanternword'])
        self.assertEqual(self.titles(found), {'notes': 1, 'git': 2})

    def test_git_is_skipped_unless_asked_and_the_answer_says_so(self):
        recall = Recall(self.cfg, reader=str(self.base))
        found, outside = recall.search_with_scope(['lanternword'], opt_in=False)
        self.assertEqual(self.titles(found), {'notes': 1})
        self.assertEqual(recall.skipped, ['git'])
        text = render_search(found, ['lanternword'], 8, 4000, outside_where=outside, skipped=recall.skipped)
        self.assertIn('[not searched: git', text)
        empty = render_search([], ['lanternword'], 8, 4000, skipped=['git'])
        self.assertIn('[not searched: git', empty)
        self.assertIn('Nothing found', empty)

    def test_where_naming_a_repository_turns_git_on_for_it_alone(self):
        recall = Recall(self.cfg, reader=str(self.base))
        found, _ = recall.search_with_scope(['lanternword'], where='alpha', opt_in=False)
        self.assertEqual(recall.skipped, [])
        self.assertEqual(self.titles(found)['git'], 1)
        self.assertIn('alpha', dict(found)['git'][0]['label'])

    def test_where_that_is_no_repository_does_not_turn_git_on(self):
        recall = Recall(self.cfg, reader=str(self.base))
        recall.search_with_scope(['lanternword'], where='notes', opt_in=False)
        self.assertEqual(recall.skipped, ['git'])

    def test_history_of_a_closed_space_is_not_walked(self):
        (self.repos['beta'] / 'humans.txt').write_text('[recall]\nopen =\n', encoding='utf-8')
        walked = []
        original = git_source.commits
        with patch.object(git_source, 'commits', lambda repo, *a, **k: (walked.append(repo.name), original(repo, *a, **k))[1]):
            found, _ = Recall({**self.cfg, 'spaces': [str(self.base / 'code' / 'beta')]},
                              reader=str(self.base)).search_with_scope(['lanternword'])
        self.assertEqual(walked, ['alpha'])
        self.assertEqual(self.titles(found)['git'], 1)


if __name__ == '__main__':
    unittest.main()
