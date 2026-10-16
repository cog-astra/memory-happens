import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from plugins.collect import Plugin as Collect
from recall_core import Recall, scan
from recall_operations import Evidence, Lineage, Record
from recall_runner import Runner
from source_operations import ranked


class SearchRankingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.words = ['recipe', 'soup', 'for', 'hours']
        self.target = self.root / 'lecture.md'
        self.target.write_text('Lecture: recipe for soup in 2 hours\n', encoding='utf-8')
        self.noise = self.root / 'session.md'
        self.noise.write_text('for\n' * 3000 + 'hours\n' * 600 + 'recipe\n' * 5 + 'soup\n', encoding='utf-8')

    def test_legacy_source_and_folder_prefer_terms_in_one_line(self):
        recall = Recall({'sources': [{'plugin': 'notes', 'roots': [str(self.root)]}], 'spaces': []})
        for results in (recall.search(self.words), recall.search_folder(self.root, self.words)):
            with self.subTest(title=results[0][0]):
                hits = results[0][1]
                self.assertEqual(Path(hits[0]['locator'].split(' start=')[0]), self.target)
                self.assertEqual([len(hit['matched']) for hit in hits], [4, 4])
                self.assertEqual([hit['total'] for hit in hits], [4, 3606])

    def hits(self):
        return [{**scan(path, self.words)[0], 'time': datetime(2026, 1, 1, tzinfo=timezone.utc), 'name': path.name}
                for path in (self.noise, self.target)]

    def test_operation_search_prefers_terms_in_one_line(self):
        self.assertEqual(ranked(self.hits(), 1)[0]['name'], 'lecture.md')

    def test_collection_keeps_the_same_preference(self):
        records = [Record(id=hit['name'], text=hit['excerpt'],
                          evidence=[Evidence(source='fixture', locator=hit['name'])],
                          context={'matched': hit['matched'], 'total': hit['total']},
                          access=[], lineage=Lineage(invocation='fixture', inputs=[])) for hit in reversed(self.hits())]
        events = list(Runner({'combine': Collect(['hits'])}).invoke(
            'combine', 'collect', {'order': 'relevance', 'limit': 1}, {'hits': records}))
        found = [event['record'] for event in events if event['type'] == 'record']
        self.assertEqual(found[0]['evidence'][0]['locator'], 'lecture.md')

    def test_more_distinct_words_still_outrank_locality(self):
        hits = [{'matched': ['rare-id'], 'total': 100, 'time': 2, 'excerpt': 'rare-id', 'name': 'partial'},
                {'matched': ['rare-id', 'expiry'], 'total': 2, 'time': 1, 'excerpt': 'rare-id', 'name': 'complete'}]
        self.assertEqual(ranked(hits, None)[0]['name'], 'complete')

    def test_collection_accepts_records_without_text(self):
        original = Record(id='empty', lineage=Lineage(invocation='fixture', inputs=[]))
        events = list(Runner({'combine': Collect(['hits'])}).invoke(
            'combine', 'collect', {'order': 'relevance'}, {'hits': [original]}))
        found = [event['record'] for event in events if event['type'] == 'record']
        self.assertEqual(len(found), 1)
        self.assertIsNone(found[0]['text'])
        self.assertEqual(events[-1]['outcome']['status'], 'success')

    def test_locality_ties_keep_occurrences_then_time_and_stable_order(self):
        hits = [{'matched': ['bolt'], 'total': total, 'time': time, 'excerpt': 'BOLT', 'name': name}
                for name, total, time in [('old', 3, 1), ('new', 3, 2), ('same', 3, 2), ('few', 2, 3)]]
        self.assertEqual([hit['name'] for hit in ranked(hits, None)], ['new', 'same', 'old', 'few'])


if __name__ == '__main__':
    unittest.main()
