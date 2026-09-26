import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_operations import Context, Evidence, Lineage, Outcome, Passage, Record, passage
import trigram_selector
from trigram_selector import SELECT, SelectParameters


def record(id, text, evidence=(), context=None):
    return Record(id=id, lineage=Lineage(invocation='fixture'), text=text,
                  evidence=list(evidence), context=context or {})


def select(records, query, operation=SELECT, cancelled=False, **parameters):
    context = Context(policy=lambda dependencies: True)
    if cancelled:
        context.cancelled.set()
    values = SelectParameters.model_validate({'query': query, **parameters}).model_dump()
    events = list(trigram_selector.invoke(operation, values, {'passages': records}, context))
    *passages, outcome = events
    assert isinstance(outcome, Outcome), events
    assert all(type(item) is Passage for item in passages), events
    return passages, outcome


NOTE = record(
    'note', 'Lighthouse keeper notes: the garden optimization was abandoned.',
    [Evidence(source='notes', locator='garden/lighthouse.md#line=9,12',
              revision='sha256:9f2c4e0d')],
    {'actor': 'alice', 'event_time': '2026-09-20'})
TRANSCRIPT = record(
    'transcript', 'We dropped the garden optimization because watering got slower.',
    [Evidence(source='voice', locator='2026-09/2026-09-26_14-02-11.wav#t=12.5,20.1',
              observed_at='2026-09-26T14:02:11Z'),
     Evidence(source='transcripts', locator='2026-09-26_14-02-11.json#line=3')],
    {'actor': 'visitor', 'capture_time': '2026-09-26T14:02:11Z'})


class TrigramSelectorTests(unittest.TestCase):
    def test_catalog_offers_the_replaceable_select(self):
        [operation] = trigram_selector.catalog()
        self.assertEqual((operation.name, operation.inputs, operation.requires_text),
                         ('select', ('passages',), True))
        self.assertEqual(SelectParameters.model_validate({'query': 'garden'}).model_dump(),
                         {'query': 'garden', 'limit': 5})
        for invalid in ({'query': ''}, {'query': 'garden', 'limit': 0},
                        {'query': 'garden', 'mode': 'fuzzy'}):
            with self.assertRaises(ValidationError):
                SelectParameters.model_validate(invalid)

    def test_note_and_audio_transcript_pass_through_unchanged(self):
        before = [item.model_dump_json() for item in (NOTE, TRANSCRIPT)]
        passages, outcome = select([NOTE, TRANSCRIPT], 'garden optimization')
        self.assertEqual(outcome.status, 'success')
        self.assertEqual([item.model_dump() for item in passages],
                         [passage(NOTE).model_dump(), passage(TRANSCRIPT).model_dump()])
        self.assertEqual(passages[1].evidence[0].locator,
                         '2026-09/2026-09-26_14-02-11.wav#t=12.5,20.1')
        self.assertEqual([item.model_dump_json() for item in (NOTE, TRANSCRIPT)], before)

    def test_evidence_is_neither_parsed_nor_searched(self):
        odd = Evidence(source='no such source', locator='C:\\x?#t=nope&line=-1 ☃ garden')
        hidden = record('hidden', 'Nothing relevant here.', [odd], {'topic': 'garden'})
        kept = record('kept', 'A garden.', [odd])
        passages, _ = select([hidden, kept], 'garden')
        self.assertEqual([item.evidence for item in passages], [[odd]])

    def test_inflected_words_meet_and_closer_passages_come_first(self):
        records = [
            record('one', 'Оптимизация сада отложена.'),
            record('two', 'Оптимизация полива в саду отменена.'),
            record('none', 'Маяк на месте.'),
            record('three', 'Полив сада без оптимизации.'),
        ]
        passages, outcome = select(records, 'оптимизацию полива', limit=2)
        self.assertEqual(outcome.status, 'success')
        self.assertEqual([item.text for item in passages],
                         [records[1].text, records[3].text])

    def test_equal_resemblance_keeps_input_order(self):
        records = [record(str(i), f'garden {i}') for i in range(3)]
        passages, _ = select(records, 'gardens')
        self.assertEqual([item.text for item in passages], ['garden 0', 'garden 1', 'garden 2'])

    def test_nothing_selected_is_a_success(self):
        self.assertEqual(select([NOTE], 'submarine'), ([], Outcome(status='success')))
        self.assertEqual(select([], 'garden'), ([], Outcome(status='success')))
        self.assertEqual(select([NOTE], '?!'),
                         ([], Outcome(status='success', code='no_searchable_words')))

    def test_cancellation_and_unknown_operation_are_distinct_outcomes(self):
        self.assertEqual(select([NOTE], 'garden', cancelled=True)[1].status, 'cancelled')
        self.assertEqual(select([NOTE], 'garden', operation='summarize')[1].status, 'unsupported')


if __name__ == '__main__':
    unittest.main()
