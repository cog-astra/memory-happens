import tempfile
import unittest
from pathlib import Path

from demo_operations import fixture
from plugins.git_operations import Plugin as GitReader
from plugins.select_literal import Plugin as Selector
from recall_operations import Evidence, Lineage, Operation, Outcome, Passage, Record
from recall_recipe import run, timeline
from recall_runner import Runner


def history_then_select(query='cache'):
    return [{'name': 'history', 'plugin': 'git', 'operation': 'history'},
            {'name': 'found', 'plugin': 'select', 'operation': 'select',
             'parameters': {'query': query}, 'inputs': {'passages': 'history'}}]


class RecipeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        self.revisions = fixture(self.repo)
        self.guide = (self.repo / 'GUIDE.md').as_posix()

    def runner(self, policy=None):
        return Runner({'git': GitReader('demo', self.repo), 'select': Selector()}, policy=policy)

    def test_records_flow_between_steps_inside_the_call(self):
        records, steps, outcome = run(self.runner(), history_then_select('stale'))
        self.assertEqual(outcome.status, 'success')
        self.assertEqual([step['records'] for step in steps], [4, 1])
        self.assertEqual(steps[0]['outcome']['message'], 'all 4 commits on HEAD.')
        self.assertEqual(records[0]['evidence'][0]['revision'], self.revisions['rollback'])

    def test_invalid_recipe_runs_nothing(self):
        class Spy(Selector):
            def invoke(self, *arguments):
                raise AssertionError('Must not run')
        runner = Runner({'select': Spy()})
        cases = [[], [{'name': 'a', 'plugin': 'select', 'operation': 'select', 'inputs': {'passages': 'later'}}],
                 [{'name': 'a', 'plugin': 'select', 'operation': 'select'}] * 2,
                 [{'name': 'bad name', 'plugin': 'select', 'operation': 'select'}],
                 [{'name': f's{i}', 'plugin': 'select', 'operation': 'select'} for i in range(11)]]
        for steps in cases:
            with self.subTest(steps=steps):
                records, summaries, outcome = run(runner, steps)
                self.assertEqual((records, summaries, outcome.code), ([], [], 'invalid_recipe'))

    def test_step_outcomes_survive_and_stop_the_recipe(self):
        records, steps, outcome = run(self.runner(), history_then_select() + [
            {'name': 'read', 'plugin': 'git', 'operation': 'read',
             'parameters': {'evidence': {'source': 'elsewhere', 'locator': self.revisions['rollback']}}},
            {'name': 'never', 'plugin': 'select', 'operation': 'select', 'parameters': {'query': 'x'},
             'inputs': {'passages': 'read'}}])
        self.assertEqual((records, outcome.status, outcome.code), ([], 'unsupported', 'incompatible_evidence'))
        self.assertEqual([step['outcome']['status'] for step in steps], ['success', 'success', 'unsupported'])

    def test_outcomes_keep_their_next_steps_and_continuation(self):
        class Pages:
            def __init__(self, outcome):
                self.outcome = outcome

            def catalog(self):
                return [Operation('page', 'Probe outcomes.')]

            def invoke(self, operation, parameters, inputs, context):
                yield Passage(text='page one')
                yield self.outcome
        finished = Outcome(status='success', code='finished_page', message='Page 1.',
                           next_steps=['Read page 2.'], continuation={'page': 2})
        hidden = Outcome(status='partial', code='policy_filtered', message='1 hidden.', next_steps=['Ask for access.'])
        runner = Runner({'hidden': Pages(hidden), 'finished': Pages(finished)})

        _, steps, outcome = run(runner, [{'name': 'last', 'plugin': 'finished', 'operation': 'page'}])
        self.assertEqual((outcome.status, outcome.code, outcome.message, outcome.next_steps, outcome.continuation),
                         ('success', 'finished_page', 'Step last: Page 1.', ['Read page 2.'], {'page': 2}))
        _, steps, outcome = run(runner, [{'name': 'first', 'plugin': 'hidden', 'operation': 'page'},
                                         {'name': 'last', 'plugin': 'finished', 'operation': 'page'}])
        self.assertEqual((outcome.status, outcome.code, outcome.next_steps), ('partial', 'policy_filtered', ['Ask for access.']))
        self.assertEqual([step['outcome']['next_steps'] for step in steps], [['Ask for access.'], ['Read page 2.']])
        self.assertEqual(steps[1]['outcome']['continuation'], {'page': 2})

    def test_policy_holds_in_any_order_and_through_literal_records(self):
        runner = self.runner(policy=lambda resources: self.guide not in resources)
        records, steps, outcome = run(runner, history_then_select('row'))
        self.assertEqual((outcome.status, outcome.code), ('partial', 'policy_filtered'))
        self.assertIn('1 excluded by the configured access policy', steps[0]['outcome']['message'])
        self.assertNotIn(self.revisions['guide'], str(records))

        denied = {'source': 'demo', 'locator': self.revisions['guide']}
        carried = Record(id='caller:1', lineage=Lineage(invocation='caller'), text='row lookup',
                         access=[self.guide], evidence=[Evidence(**denied)]).model_dump()
        select = {'name': 'found', 'plugin': 'select', 'operation': 'select', 'parameters': {'query': 'row'}}
        recipes = {'read first': [{'name': 'read', 'plugin': 'git', 'operation': 'read', 'parameters': {'evidence': denied}},
                                  {**select, 'inputs': {'passages': 'read'}}],
                   'records by value': [{**select, 'inputs': {'passages': [carried]}}]}
        for label, steps in recipes.items():
            with self.subTest(label):
                records, _, outcome = run(runner, steps)
                self.assertEqual((records, outcome.status, outcome.code), ([], 'failed', 'access_denied'))

    def test_timeline_keeps_gaps_and_counts(self):
        dated = [{'context': {'event_time': moment}} for moment in
                 ('2024-01-03T10:00:00Z', '2024-01-19T10:00:00Z', '2024-08-02T10:00:00+02:00')]
        self.assertEqual(timeline(dated + [{'context': {}}]), [
            {'month': '2024-01', 'count': 2, 'first': '2024-01-03', 'last': '2024-01-19'},
            {'month': '2024-08', 'count': 1, 'first': '2024-08-02', 'last': '2024-08-02'},
            {'month': 'undated', 'count': 1}])


if __name__ == '__main__':
    unittest.main()
