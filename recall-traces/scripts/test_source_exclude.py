import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from datetime import datetime, timezone

from recall_core import Recall, slug
from recall_mcp import preface
from test_recall_core import commit, git


class ExcludeTest(unittest.TestCase):
    def test_excluded_roots_are_never_walked(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            for folder in ('kept', 'skipped'):
                (base / 'notes' / folder).mkdir(parents=True)
                (base / 'notes' / folder / 'n.md').write_text('lanternword', encoding='utf-8')
            for folder in ('alpha', 'beta'):
                repo = base / 'code' / folder
                repo.mkdir(parents=True)
                git(repo, 'init', '-q')
                commit(repo, 'f.txt', folder, 'lanternword in ' + folder)
            skipped = [str(base / 'notes' / 'skipped'), str(base / 'code' / 'beta')]
            cfg = {'sources': [{'plugin': 'notes', 'roots': [str(base / 'notes')], 'exclude': skipped},
                               {'plugin': 'git', 'repos': [str(base / 'code' / 'alpha'), str(base / 'code' / 'beta')],
                                'exclude': skipped}]}
            found = dict(Recall(cfg).search_with_scope(['lanternword'])[0])
            self.assertEqual([hit['label'] for hit in found['notes']], ['kept/n.md'])
            self.assertEqual([hit['label'].rsplit('/', 1)[-1] for hit in found['git']], ['alpha'])
            plain = dict(Recall({'sources': [{**cfg['sources'][0], 'exclude': []}]}).search_with_scope(['lanternword'])[0])
            self.assertEqual(len(plain['notes']), 2)

class ExcludeEverySourceTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.hidden = self.base / 'work' / 'hidden'
        self.shown = self.base / 'work' / 'shown'
        corpus = self.base / 'corpus'
        corpus.mkdir()
        for name, project in (('a', self.hidden), ('b', self.shown)):
            (corpus / f'{name}.md').write_text(
                f'# Claude session {name}.jsonl\nsession: {name}\nproject: {project}\norigin: cli\n\n'
                f'## 2026-01-02T10:00:00Z [user] L1:B1\nlanternword in {name}\n', encoding='utf-8')
        memory = self.base / 'memory'
        for project in (self.hidden, self.shown):
            folder = memory / slug(project) / 'memory'
            folder.mkdir(parents=True)
            (folder / 'note.md').write_text('lanternword', encoding='utf-8')
        self.cfg = {'sources': [
            {'plugin': 'sessions', 'stores': [{'corpus': str(corpus)}], 'exclude': [str(self.hidden)]},
            {'plugin': 'memory', 'roots': [str(memory)], 'exclude': [str(self.hidden)]}]}

    def test_sessions_and_project_memory_of_an_excluded_directory_are_not_read(self):
        found = dict(Recall(self.cfg).search_with_scope(['lanternword'])[0])
        self.assertEqual([hit['label'] for hit in found['sessions']], [f'claude · {self.shown}'])
        self.assertEqual([hit['label'] for hit in found['project memory']], [f'{slug(self.shown)} · note'])

    def test_the_answer_counts_excluded_roots_without_naming_them(self):
        text = preface(Recall(self.cfg))
        self.assertIn('excluded by configuration: 1 roots', text)
        self.assertNotIn('hidden', text)
        self.assertNotIn('excluded', preface(Recall({'sources': []})))

    def test_recent_leaves_out_excluded_sessions(self):
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        traces = Recall(self.cfg).recent(since, None)
        self.assertTrue(traces)
        self.assertFalse(any('hidden' in str(trace['where']) for trace in traces))


class AliasTest(unittest.TestCase):
    def test_an_excluded_root_given_through_an_alias_still_excludes(self):
        with tempfile.TemporaryDirectory() as name:
            base = Path(name).resolve()
            (base / 'real' / 'skipped').mkdir(parents=True)
            (base / 'real' / 'kept').mkdir()
            for folder in ('skipped', 'kept'):
                (base / 'real' / folder / 'n.md').write_text('lanternword', encoding='utf-8')
            alias = base / 'alias'
            try:
                os.symlink(base / 'real', alias, target_is_directory=True)
            except OSError:
                made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(base / 'real')], capture_output=True)
                if made.returncode:
                    self.skipTest('no symlink or junction available')
            for roots, skipped in (([base / 'real'], alias / 'skipped'), ([alias], base / 'real' / 'skipped')):
                cfg = {'sources': [{'plugin': 'notes', 'roots': [str(root) for root in roots], 'exclude': [str(skipped)]}]}
                found = dict(Recall(cfg).search_with_scope(['lanternword'])[0])
                self.assertEqual([hit['label'] for hit in found['notes']], ['kept/n.md'])


if __name__ == '__main__':
    unittest.main()
