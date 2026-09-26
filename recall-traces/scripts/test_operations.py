import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from demo_operations import call, fixture, recall_change
from plugins.git_operations import Plugin as GitReader
from plugins.select_literal import Plugin as Selector
from recall_operations import Evidence, Lineage, Operation, Outcome, Passage, Record
from recall_runner import Runner
from recall_core import Recall


def external(text='cache', locator='note.md#line=0,1', access=None):
    return Record(text=text, evidence=[Evidence(source='notes', locator=locator)], id='caller:1',
                  lineage=Lineage(invocation='caller'), access=access or []).model_dump()


class OperationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.revisions = fixture(self.repo)

    def test_git_selection_and_fresh_read(self):
        result = recall_change(self.repo, Selector())
        reference = result['selection'][0]['evidence'][0]
        self.assertEqual(reference['revision'], self.revisions['rollback'])
        patch = result['patches'][0]['text']
        self.assertIn('-cache = {}', patch)
        self.assertIn('+    return rows.get(key)', patch)
        self.assertIn('The cache key omitted the row revision.', patch)
        self.assertEqual(len({item['invocation'] for item in result['trace']}), 3)

    def test_selector_preserves_note_and_audio_evidence(self):
        inputs = [external(locator='note.md#line=0,1'), external(locator='speech.wav#t=12.5,20.1')]
        records = call(Runner({'select': Selector()}), 'select', 'select', {'query': 'cache'}, {'passages': inputs})
        self.assertEqual([record['evidence'] for record in records], [record['evidence'] for record in inputs])
        self.assertTrue(all(record['lineage']['input_origin'] == 'caller_supplied' for record in records))

    def test_validation_precedes_plugin_execution(self):
        class Spy(Selector):
            def invoke(self, *args):
                raise AssertionError('Must not execute')
        runner = Runner({'select': Spy()})
        cases = [({'limit': 0, 'query': 'x'}, {'passages': []}, 'failed'),
                 ([], {'passages': []}, 'failed'),
                 ({'query': 'x'}, {'wrong': []}, 'failed'),
                 ({'query': 'x'}, {'passages': [external(text=None)]}, 'unsupported')]
        for params, inputs, expected in cases:
            with self.subTest(inputs=inputs, params=params):
                events = list(runner.invoke('select', 'select', params, inputs))
                self.assertEqual(events[-1]['outcome']['status'], expected)
                self.assertNotEqual(events[-1]['outcome']['code'], 'operation_failed')

    def test_empty_failure_interruption_and_partial_are_distinct(self):
        class Source:
            def catalog(self):
                return [Operation('read', 'Exercise terminal outcomes.')]

            def invoke(self, operation, parameters, inputs, context):
                yield Passage(text='first')
                if self.mode == 'fail':
                    raise RuntimeError('secret body must not reach trace')
                if self.mode == 'cancel':
                    context.cancelled.set()
                    yield Passage(text='not released')
        source = Source()
        for mode, status in [('fail', 'failed'), ('missing', 'partial'), ('cancel', 'cancelled')]:
            source.mode = mode
            runner = Runner({'source': source})
            events = list(runner.invoke('source', 'read'))
            self.assertEqual(events[-1]['outcome']['status'], status)
            self.assertEqual(events[-1]['records'], 1)
            self.assertNotIn('secret', json.dumps(runner.trace))
        empty = list(Runner({'select': Selector()}).invoke('select', 'select', {'query': 'absent'}, {'passages': []}))
        self.assertEqual(empty[-1]['outcome']['status'], 'success')
        self.assertEqual(empty[-1]['records'], 0)

    def test_access_union_survives_selection_and_denied_input_never_runs(self):
        inputs = [external(access=['allowed']), external(text='no match', access=['restricted'])]
        allowed = call(Runner({'select': Selector()}), 'select', 'select', {'query': 'cache'}, {'passages': inputs})
        self.assertEqual(allowed[0]['access'], ['allowed', 'restricted'])
        denied = list(Runner({'select': Selector()}, policy=lambda paths: 'restricted' not in paths)
                      .invoke('select', 'select', {'query': 'cache'}, {'passages': inputs}))
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[-1]['outcome']['code'], 'access_denied')

    def test_read_checks_policy_after_evidence_roundtrip(self):
        reference = {'source': 'demo', 'locator': self.revisions['rollback']}
        denied_file = (self.repo / 'lookup.py').as_posix()
        runner = Runner({'git': GitReader('demo', self.repo)}, policy=lambda paths: denied_file not in paths)
        events = list(runner.invoke('git', 'read', {'evidence': json.loads(json.dumps(reference))}))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['outcome']['code'], 'access_denied')

    def test_consumer_close_records_incomplete_trace(self):
        runner = Runner({'git': GitReader('demo', self.repo)})
        stream = runner.invoke('git', 'history')
        next(stream)
        stream.close()
        self.assertEqual(runner.trace[-1]['code'], 'consumer_closed')

    def test_unknown_operation_and_cancel_before_start(self):
        runner = Runner({'git': GitReader('demo', self.repo)})
        self.assertEqual(list(runner.invoke('git', 'missing'))[-1]['outcome']['status'], 'unsupported')
        cancelled = Event()
        cancelled.set()
        self.assertEqual(list(runner.invoke('git', 'history', cancelled=cancelled))[-1]['outcome']['status'], 'cancelled')

    def test_legacy_view_uses_the_same_reader_and_policy(self):
        legacy = Recall({'spaces': [], 'sources': [{'plugin': 'git_operations_legacy', 'repo': str(self.repo)}]})
        recent = list(legacy.recent(datetime(2025, 1, 1, tzinfo=timezone.utc)))
        self.assertEqual(len(recent), 4)
        hits = legacy.search(['stale'])[0][1]
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0]['locator'].endswith('@' + self.revisions['rollback']))
        self.assertIn('-cache = {}', legacy.read(hits[0]['locator']))
        legacy.plugins[0].runner.policy = lambda resources: False
        with self.assertRaises(RuntimeError):
            legacy.read(hits[0]['locator'])


if __name__ == '__main__':
    unittest.main()
