import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from demo_operations import call, fixture, recall_change
from plugins.git_operations import Plugin as GitReader
from plugins.select_literal import Plugin as Selector
from recall_operations import AccessDenied, Evidence, Lineage, Operation, Outcome, Passage, Record, passage
from recall_runner import Runner
from recall_core import Recall
import trigram_selector


def external(text='cache', locator='note.md#line=0,1', access=None, id='caller:1'):
    return Record(text=text, evidence=[Evidence(source='notes', locator=locator)], id=id,
                  lineage=Lineage(invocation='caller'), access=access or []).model_dump()


class OperationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.revisions = fixture(self.repo)

    def test_git_selection_and_fresh_read(self):
        for selector in (Selector(), trigram_selector):
            with self.subTest(selector=selector):
                result = recall_change(self.repo, selector)
                reference = result['selection'][0]['evidence'][0]
                self.assertEqual(reference['revision'], self.revisions['rollback'])
                patch = result['patches'][0]['text']
                self.assertIn('-cache = {}', patch)
                self.assertIn('+    return rows.get(key)', patch)
                self.assertIn('The cache key omitted the row revision.', patch)
                self.assertEqual(len({item['invocation'] for item in result['trace']}), 3)

    def test_selector_preserves_note_and_audio_evidence(self):
        inputs = [external(locator='note.md#line=0,1'), external(locator='speech.wav#t=12.5,20.1', id='caller:2')]
        for selector in (Selector(), trigram_selector):
            with self.subTest(selector=selector):
                records = call(Runner({'select': selector}), 'select', 'select', {'query': 'cache'}, {'passages': inputs})
                self.assertEqual([record['evidence'] for record in records], [record['evidence'] for record in inputs])
                self.assertTrue(all(record['lineage']['input_origin'] == 'caller_supplied' for record in records))

    def test_passage_edits_do_not_change_its_input(self):
        record = Record.model_validate(external())
        record.context['nested'] = {'words': ['original']}
        copied = passage(record)
        copied.evidence[0].locator = 'changed'
        copied.evidence.clear()
        copied.context['nested']['words'].append('changed')
        self.assertEqual(record.evidence[0].locator, 'note.md#line=0,1')
        self.assertEqual(record.context['nested']['words'], ['original'])

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
        inputs = [external(access=['allowed']), external(text='no match', access=['restricted'], id='caller:2')]
        allowed = call(Runner({'select': Selector()}), 'select', 'select', {'query': 'cache'}, {'passages': inputs})
        self.assertEqual(allowed[0]['access'], ['allowed', 'restricted'])
        denied = list(Runner({'select': Selector()}, policy=lambda paths: 'restricted' not in paths)
                      .invoke('select', 'select', {'query': 'cache'}, {'passages': inputs}))
        self.assertEqual(len(denied), 1)
        self.assertEqual(denied[-1]['outcome']['code'], 'access_denied')

    def test_history_records_carry_only_their_own_access(self):
        repo = self.repo.resolve()
        records = call(Runner({'git': GitReader('demo', repo)}), 'git', 'history')
        for record in records:
            revision = record['evidence'][0]['revision']
            names = subprocess.run(['git', '-C', str(repo), 'diff-tree', '--root', '--no-commit-id', '--name-only', '-r', revision],
                                   capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(record['access'], sorted({repo.as_posix()} | {(repo / name).as_posix() for name in names}))

    def test_evidence_scoped_access_survives_prefetch_and_never_carries_over(self):
        class Prefetching:
            def catalog(self):
                return [Operation('read', 'Probe evidence-scoped access.')]

            def invoke(self, operation, parameters, inputs, context):
                a, b, c = (Evidence(source='probe', locator=name) for name in 'abc')
                context.require('shared')
                context.require('b-file', evidence=b)
                context.require('a-file', evidence=a)
                try:
                    context.require('denied-file', evidence=c)
                except AccessDenied:
                    pass
                for evidence in (a, b, c):
                    yield Passage(text=evidence.locator, evidence=[evidence])
                yield Outcome(status='success')

        class Unscoped(Prefetching):
            def invoke(self, operation, parameters, inputs, context):
                for name in 'ab':
                    context.require(f'{name}-file')
                    yield Passage(text=name, evidence=[Evidence(source='probe', locator=name)])
                yield Outcome(status='success')

        policy = lambda resources: 'denied-file' not in resources
        scoped = call(Runner({'p': Prefetching()}, policy=policy), 'p', 'read')
        self.assertEqual([record['access'] for record in scoped],
                         [['a-file', 'shared'], ['b-file', 'shared'], ['shared']])
        unscoped = call(Runner({'p': Unscoped()}, policy=policy), 'p', 'read')
        self.assertEqual([record['access'] for record in unscoped], [['a-file'], ['a-file', 'b-file']])

    def test_root_policy_cache_lasts_one_policy(self):
        from unittest.mock import patch
        import operation_mcp
        seen, root = [], self.repo.resolve()
        resource = (root / 'lookup.py').as_posix()
        original = Path.resolve
        with patch.object(Path, 'resolve', lambda path, *a, **k: seen.append(path) or original(path, *a, **k)):
            first = operation_mcp.root_policy(root)
            self.assertTrue(first((resource,)) and first((resource,)))
            self.assertEqual(len(seen), 1)
            operation_mcp.root_policy(root)((resource,))
            self.assertEqual(len(seen), 2)

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

    def test_plugin_faults_do_not_blame_the_call_or_policy(self):
        class Broken:
            def catalog(self):
                return [Operation('read', 'Probe a failing source.')]

            def invoke(self, operation, parameters, inputs, context):
                yield Passage(text='first')
                raise self.fault('Internal plugin fault')
        for fault in (ValueError, TypeError, PermissionError, FileNotFoundError):
            with self.subTest(fault=fault):
                plugin = Broken()
                plugin.fault = fault
                events = list(Runner({'source': plugin}).invoke('source', 'read'))
                self.assertEqual(events[-1]['outcome']['code'], 'operation_failed')
                self.assertEqual(events[-1]['records'], 1)

    def test_invalid_plugin_value_has_its_own_outcome(self):
        class Broken:
            def catalog(self):
                return [Operation('read', 'Probe invalid output.')]

            def invoke(self, operation, parameters, inputs, context):
                item = Passage(text='initial')
                item.text = 12
                yield item
        events = list(Runner({'source': Broken()}).invoke('source', 'read'))
        self.assertEqual(events[-1]['outcome']['code'], 'invalid_output')
        self.assertEqual(events[-1]['records'], 0)

    def test_duplicate_input_ids_are_rejected_before_execution(self):
        class Spy(Selector):
            def invoke(self, *args):
                raise AssertionError('Must not execute')
        events = list(Runner({'select': Spy()}).invoke('select', 'select', {'query': 'cache'},
                                                      {'passages': [external(), external()]}))
        self.assertEqual(events[-1]['outcome']['code'], 'duplicate_input_ids')

    def test_denied_commit_does_not_hide_older_allowed_commits(self):
        guide = (self.repo / 'GUIDE.md').as_posix()
        runner = Runner({'git': GitReader('demo', self.repo)}, policy=lambda paths: guide not in paths)
        events = list(runner.invoke('git', 'history'))
        records = [event['record'] for event in events if event['type'] == 'record']
        self.assertEqual([record['evidence'][0]['revision'] for record in records],
                         [self.revisions[key] for key in ('rollback', 'cache', 'base')])
        self.assertEqual(events[-1]['outcome']['status'], 'partial')
        self.assertEqual(events[-1]['outcome']['code'], 'policy_filtered')
        self.assertTrue(all(guide not in record['access'] for record in records))


if __name__ == '__main__':
    unittest.main()
