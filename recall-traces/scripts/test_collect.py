import unittest

from plugins.collect import Plugin
from recall_operations import Evidence, Lineage, Operation, Outcome, Passage, Record
from recall_recipe import run
from recall_runner import Runner


def record(identifier, source, **context):
    return Record(id=identifier, text=identifier, evidence=[Evidence(source=source, locator=identifier)],
                  context=context, lineage=Lineage(invocation='fixture', inputs=[]), access=[source])


class CollectionTest(unittest.TestCase):
    def test_rank_then_limit_per_source_preserves_evidence(self):
        first = record('note', 'notes', modified_at='2026-01-01T00:00:00Z', matched=['cache'], total=9)
        second = record('session', 'sessions', event_time='2025-01-01T00:00:00Z', matched=['cache', 'stale'], total=2)
        lower = record('other', 'notes', modified_at='2025-01-01T00:00:00Z', matched=['cache'], total=3)
        events = list(Runner({'collect': Plugin(['notes', 'sessions'])}).invoke(
            'collect', 'collect', {'order': 'relevance', 'limit': 1, 'per_source': True},
            {'notes': [first, lower], 'sessions': [second]}))
        records = [event['record'] for event in events if event['type'] == 'record']
        self.assertEqual([r['text'] for r in records], ['session', 'note'])
        self.assertEqual(records[0]['evidence'], [e.model_dump() for e in second.evidence])
        self.assertEqual(records[0]['access'], ['notes', 'sessions'])
        self.assertNotIn('event_time', records[1]['context'])

    def test_continue_is_explicit_and_failed_partial_content_is_discarded(self):
        class Source:
            def __init__(self, failed):
                self.failed = failed

            def catalog(self):
                return [Operation('read', 'Fixture source.')]

            def invoke(self, operation, parameters, inputs, context):
                yield Passage(text='discard' if self.failed else 'keep')
                yield Outcome(status='unavailable' if self.failed else 'success', code='missing' if self.failed else '')

        runner = Runner({'missing': Source(True), 'present': Source(False), 'collect': Plugin(['a', 'b'])})
        steps = [{'name': 'a', 'plugin': 'missing', 'operation': 'read'},
                 {'name': 'b', 'plugin': 'present', 'operation': 'read'},
                 {'name': 'c', 'plugin': 'collect', 'operation': 'collect', 'inputs': {'a': 'a', 'b': 'b'}}]
        records, summaries, outcome = run(runner, steps)
        self.assertEqual((records, len(summaries), outcome.status), ([], 1, 'unavailable'))
        steps[0]['on_error'] = 'continue'
        records, summaries, outcome = run(runner, steps)
        self.assertEqual([r['text'] for r in records], ['keep'])
        self.assertEqual((outcome.status, outcome.code), ('partial', 'incomplete_sources'))
        self.assertEqual(summaries[0]['outcome']['status'], 'unavailable')

    def test_cancellation_stops_collection_even_when_cleanup_fails(self):
        class Source:
            def catalog(self):
                return [Operation('read', 'Fixture source.')]

            def invoke(self, operation, parameters, inputs, context):
                try:
                    context.cancelled.set()
                    yield Passage(text='cancelled')
                finally:
                    raise RuntimeError('cleanup failed')

        runner = Runner({'source': Source()})
        steps = [{'name': 'first', 'plugin': 'source', 'operation': 'read', 'on_error': 'continue'},
                 {'name': 'never', 'plugin': 'source', 'operation': 'read'}]
        records, summaries, outcome = run(runner, steps)
        self.assertEqual((records, len(summaries), outcome.status), ([], 1, 'cancelled'))
        self.assertTrue(runner.trace[0]['close_failed'])

    def test_internal_recipe_can_cover_more_sources_without_relaxing_custom_calls(self):
        class Source:
            def catalog(self):
                return [Operation('read', 'Fixture source.')]

            def invoke(self, operation, parameters, inputs, context):
                yield Passage(text='found')
                yield Outcome(status='success')

        aliases = [f's{i}' for i in range(12)]
        runner = Runner({'source': Source(), 'collect': Plugin(aliases)})
        steps = [{'name': alias, 'plugin': 'source', 'operation': 'read'} for alias in aliases]
        steps.append({'name': 'all', 'plugin': 'collect', 'operation': 'collect',
                      'inputs': {alias: alias for alias in aliases}})
        self.assertEqual(run(runner, steps)[2].code, 'invalid_recipe')
        records, summaries, outcome = run(runner, steps, max_steps=len(aliases) + 1)
        self.assertEqual((len(records), len(summaries), outcome.status), (12, 13, 'success'))


if __name__ == '__main__':
    unittest.main()
