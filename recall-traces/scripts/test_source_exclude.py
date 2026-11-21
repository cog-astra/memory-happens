import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_core import Recall
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


if __name__ == '__main__':
    unittest.main()
