import json
import tempfile
import unittest
from pathlib import Path
from threading import Event

from configured_operations import Configuration
from test_operation_mcp import server


def anchor(path, line=1, identity='anchor', **evidence):
    return {'id': identity, 'text': 'untrusted caller excerpt',
            'evidence': [{'source': 'notes', 'locator': f'{path} start={line}', **evidence}],
            'context': {}, 'access': [], 'lineage': {'invocation': 'caller'}}


def expand(runner, anchors, parameters=None, cancelled=None):
    events = list(runner.invoke('notes', 'expand', parameters or {}, {'anchors': anchors}, cancelled=cancelled))
    return [e['record'] for e in events if e['type'] == 'record'], events[-1]['outcome']


class ExpansionTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.note = self.root / 'note.md'
        self.note.write_text('one\ntwo\nthree\nfour\nfive\n', encoding='utf-8')
        self.runner = Configuration({'sources': [{'plugin': 'notes', 'roots': [str(self.root)]}]}).runner()

    def test_overlaps_keep_anchor_and_read_continuation(self):
        anchors = [anchor(self.note, 1, 'a'), anchor(self.note, 2, 'b'), anchor(self.note, 5, 'c')]
        original = json.dumps(anchors)
        records, outcome = expand(self.runner, anchors, {'before_lines': 1, 'after_lines': 1})
        self.assertEqual([r['text'] for r in records], ['one\ntwo\n', 'one\ntwo\nthree\n', 'four\nfive\n'])
        self.assertEqual([r['context']['expansion']['anchor_id'] for r in records], ['a', 'b', 'c'])
        self.assertEqual([(r['context']['first_line'], r['context']['last_line']) for r in records], [(1, 2), (1, 3), (4, 5)])
        self.assertEqual([r['start'] for r in outcome['continuation']['anchors']], [3, 4])
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual(json.dumps(anchors), original)
        self.assertTrue(all(str(self.note).replace('\\', '/') in r['access'] for r in records))

    def test_invalid_anchors_fail_before_any_read(self):
        bad = [anchor(self.note, 0), anchor(self.note, 'abc'), anchor(self.note, -2)]
        missing = anchor(self.note)
        missing['evidence'][0]['locator'] = str(self.note)
        ambiguous = anchor(self.note)
        ambiguous['evidence'] *= 2
        foreign = anchor(self.note)
        foreign['evidence'][0]['source'] = 'git'
        for item in [*bad, missing, ambiguous, foreign]:
            with self.subTest(item=item):
                item['id'] = 'bad'
                records, outcome = expand(self.runner, [anchor(self.note), item])
                self.assertEqual(records, [])
                self.assertEqual(outcome['status'], 'unsupported')

    def test_changed_missing_empty_and_cancelled_remain_observable(self):
        records, outcome = expand(self.runner, [anchor(self.note, observed_at='2000-01-01T00:00:00Z')])
        self.assertEqual(outcome['code'], 'source_changed')
        self.assertEqual(records[0]['context']['expansion']['read_outcome']['code'], 'source_changed')
        self.assertEqual(expand(self.runner, [anchor(self.note, 100)])[1]['code'], 'empty_expansions')
        self.assertEqual(expand(self.runner, [anchor(self.root / 'missing.md')])[1]['code'], 'source_missing')
        self.assertEqual(expand(self.runner, [anchor(self.note)], {'before_lines': -1})[1]['code'], 'invalid_call')
        cancellation = Event()
        cancellation.set()
        self.assertEqual(expand(self.runner, [anchor(self.note)], cancelled=cancellation)[1]['status'], 'cancelled')

    def test_inline_anchor_cannot_bypass_a_personal_boundary(self):
        friend = self.root / 'spaces/friend'
        friend.mkdir(parents=True)
        (friend / 'humans.txt').write_text('[recall]\nopen = open\n', encoding='utf-8')
        secret = friend / 'closed.md'
        secret.write_text('private text', encoding='utf-8')
        runner = Configuration({'spaces': [str(self.root / 'spaces')],
                                'sources': [{'plugin': 'notes', 'roots': [str(friend)]}]}, reader=str(self.root / 'reader')).runner()
        records, outcome = expand(runner, [anchor(secret)])
        self.assertEqual(records, [])
        self.assertEqual(outcome['code'], 'access_denied')


class ExpansionMcpTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_expand_select_is_one_call_with_two_documents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.md').write_text('invoice marker\nrollback reason\nend\n', encoding='utf-8')
            (root / 'b.md').write_text('start\ninvoice marker\nrollback reason\n', encoding='utf-8')
            config = root / 'sources.json'
            config.write_text(json.dumps({'sources': [{'plugin': 'notes', 'roots': [str(root)]}]}), encoding='utf-8')
            steps = [
                {'name': 'found', 'plugin': 'notes', 'operation': 'search', 'parameters': {'query': 'invoice'}},
                {'name': 'nearby', 'plugin': 'notes', 'operation': 'expand',
                 'parameters': {'before_lines': 1, 'after_lines': 1}, 'inputs': {'anchors': 'found'}},
                {'name': 'selected', 'plugin': 'selector', 'operation': 'select',
                 'parameters': {'query': 'rollback'}, 'inputs': {'passages': 'nearby'}},
            ]
            async with server('--sources', str(config)) as session:
                response = await session.call_tool('operation_run', {'steps': steps, 'view': 'records', 'characters': 15000})
                self.assertFalse(response.is_error, response)
                result = response.structured_content
                self.assertEqual(result, json.loads(response.content[0].text))
                self.assertEqual(result['outcome']['status'], 'success', result)
                self.assertEqual([s['records'] for s in result['steps']], [2, 2, 2])
                self.assertTrue(all('rollback reason' in r['text'] for r in result['records']))
                self.assertEqual(len({r['context']['expansion']['anchor_id'] for r in result['records']}), 2)
                bounded = await session.call_tool('operation_run', {'steps': steps, 'characters': 1})
                self.assertEqual(bounded.structured_content['outcome']['code'], 'over_budget')
                self.assertNotIn('records', bounded.structured_content)


if __name__ == '__main__':
    unittest.main()
