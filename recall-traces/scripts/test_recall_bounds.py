import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_bounds import Bounds, slug, spaces
from recall_core import Recall


class NestedBoundsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / 'home'
        self.outsider = self.base / 'elsewhere'

    def space(self, relative, rules):
        root = self.home / relative
        (root / 'open').mkdir(parents=True)
        (root / 'closed').mkdir()
        (root / 'humans.txt').write_text(rules, encoding='utf-8')
        (root / 'open/note.md').write_text('OPEN boundarycanary', encoding='utf-8')
        (root / 'closed/note.md').write_text('CLOSED boundarycanary', encoding='utf-8')
        return root

    def test_depth_does_not_change_policy_for_read_search_or_project_memory(self):
        roots = [self.space(name, '[recall]\nopen = open\nguests = guests\n')
                 for name in ('alice', 'team/people/bob', 'one/two/three/four/five/carol')]
        cfg = {'spaces': [str(self.home)],
               'sources': [{'plugin': 'notes', 'roots': [str(self.home)]}]}
        recall = Recall(cfg, reader=str(self.outsider))
        hits = dict(recall.search(['boundarycanary']))['notes']
        self.assertEqual(len(hits), 3)
        self.assertTrue(all(hit['excerpt'] == 'OPEN boundarycanary' for hit in hits))
        for root in roots:
            with self.subTest(root=root):
                self.assertTrue(recall.read(str(root / 'closed/note.md')).startswith('Closed:'))
                self.assertIn('OPEN boundarycanary', recall.read(str(root / 'open/note.md')))
                self.assertFalse(recall.bounds.hides(root / 'humans.txt'))
                self.assertTrue(recall.bounds.hides_project(slug(root / 'closed')))
                self.assertFalse(recall.bounds.hides_project(slug(root / 'open')))
                self.assertFalse(Bounds([self.home], reader=str(root)).hides(root / 'closed/note.md'))
                self.assertTrue(Bounds([self.home], reader=str(root / 'guests')).hides(root / 'closed/note.md'))

    def test_nested_private_rules_survive_open_parent_and_overlapping_bases(self):
        parent = self.space('parent', '[recall]\nopen = .\n')
        child = self.space('parent/one/two/child', '[recall]\nopen = .\nprivate = closed\n')
        bounds = Bounds([self.home, parent, child], reader=str(self.outsider))
        self.assertEqual(len(spaces([self.home, parent, child])), 2)
        self.assertTrue(bounds.hides(child / 'closed/note.md'))
        self.assertFalse(bounds.hides(child / 'open/note.md'))
        self.assertFalse(bounds.hides(parent / 'closed/note.md'))

    def test_open_child_does_not_reopen_a_closed_parent(self):
        parent = self.space('parent', '[recall]\nopen =\n')
        child = self.space('parent/one/two/child', '[recall]\nopen = .\n')
        bounds = Bounds([self.home], reader=str(self.outsider))
        self.assertTrue(bounds.hides(child / 'open/note.md'))
        self.assertTrue(bounds.hides(parent / 'closed/note.md'))

    def link(self, path, target):
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(path), str(target)],
                           check=True, capture_output=True)
            self.addCleanup(path.rmdir)
        else:
            path.symlink_to(target, target_is_directory=True)
            self.addCleanup(path.unlink)

    def test_directory_aliases_are_checked_without_following_cycles_forever(self):
        root = self.space('team/people/bob', '[recall]\nopen = open\n')
        alias = self.base / 'alias'
        self.link(alias, self.home)
        self.link(root / 'back', self.home)
        bounds = Bounds([alias], reader=str(self.outsider))
        self.assertEqual(len(bounds.closed), 1)
        self.assertTrue(bounds.hides(root / 'closed/note.md'))
        self.assertTrue(bounds.hides(alias / 'team/people/bob/closed/note.md'))
        self.assertFalse(bounds.hides(root / 'open/note.md'))

    def test_aliases_preserve_owner_and_guest_access(self):
        root = self.space('owner', '[recall]\nopen = open\nguests = guests\n')
        (root / 'guests').mkdir()
        parent = self.home / 'elsewhere/one/two'
        parent.mkdir(parents=True)
        alias = parent / 'owner_alias'
        self.link(alias, root)
        guest_alias = self.base / 'guest_alias'
        self.link(guest_alias, root / 'guests')
        cfg = {'spaces': [str(self.home)], 'sources': []}
        for reader in (root, alias):
            with self.subTest(owner=reader):
                recall = Recall(cfg, reader=str(reader))
                for route in (root, alias):
                    self.assertIn('CLOSED boundarycanary', recall.read(str(route / 'closed/note.md')))
                    self.assertFalse(recall.bounds.hides_project(slug(route / 'closed')))
        for reader in (root / 'guests', alias / 'guests', guest_alias, self.outsider):
            with self.subTest(guest=reader):
                recall = Recall(cfg, reader=str(reader))
                for route in (root, alias):
                    self.assertTrue(recall.read(str(route / 'closed/note.md')).startswith('Closed:'))
                    self.assertIn('OPEN boundarycanary', recall.read(str(route / 'open/note.md')))
                    self.assertTrue(recall.bounds.hides_project(slug(route / 'closed')))

    def test_unreadable_subtree_does_not_silently_omit_rules(self):
        root = self.space('one/two/three', '[recall]\nopen =\n')
        scandir = os.scandir

        def denied(path):
            if Path(path) == root:
                raise PermissionError('synthetic unreadable subtree')
            return scandir(path)

        with patch('recall_bounds.os.scandir', denied):
            with self.assertRaises(PermissionError):
                Bounds([self.home], reader=str(self.outsider))

    def test_guest_route_cannot_reenter_owner_through_a_link(self):
        root = self.space('owner', '[recall]\nopen = open\nguests = guests\n')
        guests = root / 'guests'
        guests.mkdir()
        alias = self.base / 'alias'
        self.link(alias, root)
        self.link(guests / 'back', root)
        for policy_root in (root, alias):
            cfg = {'spaces': [str(policy_root)], 'sources': []}
            for reader in (guests, guests / 'back', alias / 'guests/back'):
                with self.subTest(policy=policy_root, reader=reader):
                    recall = Recall(cfg, reader=str(reader))
                    for route in (root, alias):
                        self.assertTrue(recall.read(str(route / 'closed/note.md')).startswith('Closed:'))
                        self.assertIn('OPEN boundarycanary', recall.read(str(route / 'open/note.md')))


if __name__ == '__main__':
    unittest.main()
