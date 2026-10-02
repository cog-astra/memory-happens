import copy
import json
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event
from unittest.mock import patch

from plugins import ollama_embed
from recall_operations import Context, Record
from recall_runner import Runner
from test_operation_mcp import server


INPUTS = [
    {'id': 'a:1', 'lineage': {'invocation': 'a'}, 'text': 'A yellow lighthouse.',
     'evidence': [{'source': 'notes', 'locator': 'opaque:start=8', 'revision': 'abc'}],
     'context': {'event_time': '2026-01-01T00:00:00Z', 'nested': {'keep': [1, 2]}}, 'access': ['resource:a']},
    {'id': 'a:2', 'lineage': {'invocation': 'a'}, 'text': 'Garden work.',
     'evidence': [{'source': 'sessions', 'locator': 'opaque:start=30'}], 'access': ['resource:b']},
    {'id': 'a:3', 'lineage': {'invocation': 'a'}, 'text': 'Another lighthouse.', 'evidence': []},
]
VECTORS = {INPUTS[0]['text']: [10, 0], INPUTS[1]['text']: [0, 2], INPUTS[2]['text']: [3, 0]}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        body = json.loads(raw)
        self.server.requests.append((self.path, body, len(raw)))
        self.server.entered.set()
        time.sleep(self.server.delay)
        if self.server.replies:
            status, payload = self.server.replies.pop(0)
        else:
            status, payload = 200, {'embeddings': [VECTORS.get(text, [1, 0]) for text in body['input']]}
        payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        if status == 302:
            self.send_header('Location', self.server.redirect)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            pass


class EndpointFixture:
    def setUp(self):
        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        self.http.daemon_threads = True
        self.http.requests, self.http.replies, self.http.delay = [], [], 0
        self.http.entered = Event()
        self.endpoint = f'http://127.0.0.1:{self.http.server_address[1]}'
        self.http.redirect = self.endpoint + '/elsewhere'
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def plugin(self, **options):
        return ollama_embed.Plugin({'model': 'synthetic-embed', 'endpoint': self.endpoint, **options})

    def select(self, inputs=INPUTS, cancelled=None, parameters=None, policy=None, **options):
        events = list(Runner({'embed': self.plugin(**options)}, policy=policy).invoke(
            'embed', 'select', parameters or {'query': 'beacon', 'limit': 2}, {'passages': inputs}, cancelled))
        return [event['record'] for event in events if event['type'] == 'record'], events[-1]['outcome']


class OllamaEmbedTest(EndpointFixture, unittest.TestCase):
    def test_cosine_ranking_stable_ties_exact_passages_and_runner_envelope(self):
        before = copy.deepcopy(INPUTS)
        records, outcome = self.select(batch_size=2, query_prefix='Search: ')
        self.assertEqual(outcome['status'], 'success')
        for actual, original in zip(records, (INPUTS[0], INPUTS[2])):
            expected = Record.model_validate(original)
            self.assertEqual({key: actual[key] for key in ('text', 'evidence', 'context')},
                             expected.model_dump(include={'text', 'evidence', 'context'}))
            self.assertEqual(actual['access'], ['resource:a', 'resource:b'])
            self.assertEqual(actual['lineage']['inputs'], ['a:1', 'a:2', 'a:3'])
            self.assertNotEqual(actual['id'], original['id'])
        self.assertEqual(INPUTS, before)
        calls = self.http.requests
        self.assertEqual([body['input'] for _, body, _ in calls],
                         [['Search: beacon'], [INPUTS[0]['text'], INPUTS[1]['text']], [INPUTS[2]['text']]])
        self.assertTrue(all(path == '/api/embed' and body['truncate'] is False
                            and body['model'] == 'synthetic-embed' for path, body, _ in calls))

    def test_copy_does_not_mutate_inputs_and_repeated_calls_recompute(self):
        plugin = self.plugin()
        inputs = [Record.model_validate(item) for item in INPUTS]
        for _ in range(2):
            result = list(plugin.invoke('select', {'query': 'beacon', 'limit': 1},
                                        {'passages': inputs}, Context(lambda _: True)))
            result[0].context['nested']['keep'].append(3)
            self.assertEqual(inputs[0].context['nested']['keep'], [1, 2])
        self.assertEqual(len(self.http.requests), 4)

    def test_byte_budget_splits_batches_and_rejects_single_oversize_before_network(self):
        plugin = self.plugin()
        budget = max(len(plugin.body([text])) for text in ['beacon', *(i['text'] for i in INPUTS)])
        records, outcome = self.select(max_batch_bytes=budget)
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual(len(self.http.requests), 4)
        self.assertTrue(all(size <= budget for _, _, size in self.http.requests))
        self.http.requests.clear()
        records, outcome = self.select(inputs=[*INPUTS, {**INPUTS[0], 'id': 'a:4', 'text': 'x' * 500}],
                                       max_batch_bytes=budget)
        self.assertEqual((records, outcome['code']), ([], 'model_input_too_large'))
        self.assertEqual(self.http.requests, [])

    def test_empty_invalid_text_invalid_parameters_and_policy_denial_do_not_call_server(self):
        cases = [({'inputs': []}, 'empty_input'),
                 ({'inputs': [{**INPUTS[0], 'text': None}]}, 'text_required'),
                 ({'inputs': [{**INPUTS[0], 'text': '\ud800'}]}, 'invalid_input_text'),
                 ({'parameters': {'query': ''}}, 'invalid_call'),
                 ({'parameters': {'query': 'q', 'limit': 0}}, 'invalid_call'),
                 ({'parameters': {'query': 'q', 'model': 'untrusted'}}, 'invalid_call'),
                 ({'policy': lambda _: False}, 'access_denied')]
        for arguments, code in cases:
            with self.subTest(code=code):
                records, outcome = self.select(**arguments)
                self.assertEqual((records, outcome['code']), ([], code))
        self.assertEqual(self.http.requests, [])

    def test_bad_payloads_and_vectors_never_emit_partial_selection(self):
        payloads = [b'not json', b'\xff', [], {}, {'embeddings': []}, {'embeddings': [[1], [2]]},
                    {'embeddings': [None]}, {'embeddings': [[]]}, {'embeddings': [[0, 0]]},
                    {'embeddings': [[True, 1]]}, {'embeddings': [['1', 1]]},
                    {'embeddings': [[float('nan'), 1]]}, {'embeddings': [[float('inf'), 1]]},
                    {'embeddings': [[10 ** 400, 1]]}]
        for payload in payloads:
            with self.subTest(payload=str(payload)[:70]):
                self.http.replies = [(200, payload)]
                records, outcome = self.select()
                self.assertEqual((records, outcome['code']), ([], 'invalid_embeddings'))
        for last in ([[1]], [[1, 2, 3]]):
            self.http.replies = [(200, {'embeddings': [[1, 0]]}),
                                 (200, {'embeddings': [[1, 0], [0, 1]]}),
                                 (200, {'embeddings': last})]
            records, outcome = self.select(batch_size=2)
            self.assertEqual((records, outcome['code']), ([], 'invalid_embeddings'))

    def test_finite_extreme_magnitudes_are_normalized_without_overflow(self):
        self.http.replies = [(200, {'embeddings': [[1e308, 1e308]]}),
                             (200, {'embeddings': [[1e-300, 1e-300], [-1e308, -1e308], [1e308, 0]]})]
        records, outcome = self.select()
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual([r['text'] for r in records], [INPUTS[0]['text'], INPUTS[2]['text']])

    def test_server_errors_redirect_and_response_budget_are_distinct(self):
        cases = [(404, {'error': 'missing model'}, {}, 'model_missing'),
                 (404, b'404 page not found', {}, 'model_missing'),
                 (400, {'error': 'input length exceeds maximum context length'}, {}, 'model_input_too_large'),
                 (500, {'error': 'backend failed'}, {}, 'model_error'),
                 (200, {'error': 'backend failed'}, {}, 'model_error'),
                 (302, b'', {}, 'model_redirect_refused'),
                 (200, b'x' * 1000, {'max_response_bytes': 100}, 'model_response_too_large')]
        for status, payload, options, code in cases:
            self.http.replies = [(status, payload)]
            count = len(self.http.requests)
            records, outcome = self.select(**options)
            self.assertEqual((records, outcome['code']), ([], code))
            self.assertEqual(len(self.http.requests), count + 1)

    def test_outage_and_total_deadline(self):
        with socket.socket() as closed:
            closed.bind(('127.0.0.1', 0))
            dead = f'http://127.0.0.1:{closed.getsockname()[1]}'
        records, outcome = self.select(endpoint=dead)
        self.assertEqual((records, outcome['code']), ([], 'model_server_unavailable'))
        self.http.delay = 0.1
        records, outcome = self.select(timeout=0.05)
        self.assertEqual((records, outcome['code']), ([], 'model_timeout'))
        self.http.delay = 0.04
        records, outcome = self.select(timeout=0.13, batch_size=1)
        self.assertEqual((records, outcome['code']), ([], 'model_timeout'))

    def test_cancellation_before_start_and_while_waiting_discards_all_output(self):
        cancelled = Event()
        cancelled.set()
        records, outcome = self.select(cancelled=cancelled)
        self.assertEqual((records, outcome['status']), ([], 'cancelled'))
        self.assertEqual(self.http.requests, [])
        cancelled.clear()
        self.http.delay = 0.15
        timer = threading.Timer(0.05, cancelled.set)
        timer.start()
        self.addCleanup(timer.cancel)
        started = time.monotonic()
        records, outcome = self.select(cancelled=cancelled, timeout=0.1)
        self.assertEqual((records, outcome['status']), ([], 'cancelled'))
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(len(self.http.requests), 1)

    def test_environment_proxies_are_not_used(self):
        with patch.dict('os.environ', {'http_proxy': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1',
                                       'no_proxy': '', 'NO_PROXY': ''}):
            self.assertEqual(self.select()[1]['status'], 'success')

    def test_configuration_is_explicit_and_bounded(self):
        for options in ({}, {'model': ''}, {'model': True}, {'model': 'x', 'typo': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ollama_embed.Plugin(options)
        for key, values in {'batch_size': [0, 257, True, 2.5],
                            'max_batch_bytes': [0, 67_108_865], 'max_response_bytes': [-1],
                            'timeout': [0, 901, 10 ** 400, float('nan'), float('inf'), True, '5'],
                            'query_prefix': [None, 2],
                            'endpoint': ['file:///secret', 'http://user:pass@localhost', 'http://localhost/?x=1',
                                         'http://localhost/#x', 'http://localhost:99999', 'http://local\nhost']}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    self.plugin(**{key: value})


class OllamaEmbedMCPTest(EndpointFixture, unittest.IsolatedAsyncioTestCase):
    async def test_fresh_stdio_explicit_configuration_catalog_invoke_and_outage(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'sources.json'
            config.write_text(json.dumps({'sources': [], 'operations': [
                {'name': 'semantic', 'module': 'plugins.ollama_embed',
                 'options': {'model': 'synthetic-embed', 'endpoint': self.endpoint}}]}), encoding='utf-8')
            async with server('--sources', str(config)) as session:
                catalog = await session.call_tool('operation_catalog', {})
                self.assertFalse(catalog.is_error, catalog)
                self.assertIn('semantic', catalog.content[0].text)
                self.assertIn('query', catalog.content[0].text)
                self.assertEqual(self.http.requests, [])
                steps = [{'name': 'selected', 'plugin': 'semantic', 'operation': 'select',
                          'parameters': {'query': 'beacon', 'limit': 1},
                          'inputs': {'passages': [{**item, 'access': []} for item in INPUTS]}}]
                reply = await session.call_tool('operation_run', {'steps': steps, 'characters': 10000, 'view': 'records'})
                self.assertFalse(reply.is_error, reply)
                self.assertEqual(reply.structured_content['outcome']['status'], 'success')
                selected = reply.structured_content['records'][0]
                self.assertEqual({key: selected[key] for key in ('text', 'evidence', 'context')},
                                 Record.model_validate(INPUTS[0]).model_dump(include={'text', 'evidence', 'context'}))
                self.http.shutdown()
                self.http.server_close()
                failed = await session.call_tool('operation_run', {'steps': steps, 'characters': 10000, 'view': 'records'})
                self.assertFalse(failed.is_error, failed)
                self.assertEqual(failed.structured_content['outcome']['code'], 'model_server_unavailable')
                self.assertEqual(failed.structured_content['records'], [])


if __name__ == '__main__':
    unittest.main()
