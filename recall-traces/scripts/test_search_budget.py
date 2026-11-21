import unittest
from datetime import datetime, timezone

from recall_mcp import render_search


def hit(label, locator=None):
    return {'time': datetime(2026, 1, 1, tzinfo=timezone.utc), 'label': label,
            'matched': ['recipe'], 'total': 1, 'places': [], 'excerpt': 'recipe',
            'locator': locator or label}


class SearchBudgetTest(unittest.TestCase):
    def test_first_findings_from_each_source_precede_second_round(self):
        groups = [('sessions', [hit('noise-' + str(i)) for i in range(8)]),
                  ('notes', [hit('target')]), ('skills', [hit('guide')])]
        output = render_search(groups, ['recipe'], 8, 500)
        self.assertIn('read: target\n', output)
        self.assertIn('read: guide\n', output)
        self.assertIn('[not shown: sessions:', output)
        self.assertLessEqual(len(output), 500)

    def test_oversized_first_source_does_not_hide_later_source(self):
        groups = [('oversized', [hit('large', 'x' * 2000)]), ('notes', [hit('target')])]
        output = render_search(groups, ['recipe'], 8, 500)
        self.assertIn('read: target\n', output)
        self.assertIn('[not shown: oversized: 1;', output)
        self.assertNotIn('x' * 100, output)
        self.assertLessEqual(len(output), 500)

    def test_large_budget_preserves_source_and_hit_order_and_reports_limit(self):
        groups = [('sessions', [hit('first'), hit('second'), hit('third')]),
                  ('notes', [hit('target')])]
        output = render_search(groups, ['recipe'], 2, 5000)
        self.assertLess(output.index('read: first'), output.index('read: second'))
        self.assertLess(output.index('read: second'), output.index('read: target'))
        self.assertNotIn('read: third', output)
        self.assertIn('[not shown: sessions: 1;', output)
        complete = render_search(groups, ['recipe'], 8, 5000)
        self.assertIn('read: third', complete)
        self.assertNotIn('[not shown:', complete)


if __name__ == '__main__':
    unittest.main()
