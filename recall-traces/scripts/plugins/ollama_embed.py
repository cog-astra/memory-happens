import http.client
import json
import math
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import Field

from recall_operations import Operation, Outcome, Value, passage


class Parameters(Value):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, gt=0)


class Failure(Exception):
    def __init__(self, status, code, message=''):
        super().__init__(message)
        self.outcome = Outcome(status=status, code=code, message=message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def positive_integer(options, name, default, maximum):
    value = options.get(name, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer between 1 and {maximum}')
    return value


def unit_vector(vector, dimensions):
    if not isinstance(vector, list) or not vector or (dimensions is not None and len(vector) != dimensions):
        raise Failure('failed', 'invalid_embeddings', 'Embedding dimensions must be nonempty and consistent.')
    try:
        valid = all(type(value) in (int, float) and math.isfinite(value) for value in vector)
    except OverflowError:
        valid = False
    if not valid:
        raise Failure('failed', 'invalid_embeddings', 'Embeddings must contain finite numbers.')
    scale = max(abs(value) for value in vector)
    if scale == 0:
        raise Failure('failed', 'invalid_embeddings', 'Embeddings must have nonzero magnitude.')
    scaled = [value / scale for value in vector]
    norm = math.sqrt(math.fsum(value * value for value in scaled))
    return [value / norm for value in scaled]


class Plugin:
    def __init__(self, options=None):
        options = dict(options or {})
        known = {'model', 'endpoint', 'query_prefix', 'batch_size', 'timeout',
                 'max_batch_bytes', 'max_response_bytes'}
        if options.keys() - known:
            raise ValueError(f'Unknown ollama_embed options: {sorted(options.keys() - known)}')
        self.model = options.get('model')
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('ollama_embed needs a model in its configuration')
        self.endpoint = options.get('endpoint', 'http://127.0.0.1:11434')
        if not isinstance(self.endpoint, str) or any(ord(char) <= 32 for char in self.endpoint):
            raise ValueError('endpoint must be an HTTP(S) URL without whitespace')
        url = urllib.parse.urlsplit(self.endpoint)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username is not None
                or url.password is not None or url.query or url.fragment):
            raise ValueError('endpoint must be an HTTP(S) URL without credentials, query or fragment')
        url.port
        self.endpoint = self.endpoint.rstrip('/')
        self.query_prefix = options.get('query_prefix', '')
        if not isinstance(self.query_prefix, str):
            raise ValueError('query_prefix must be a string')
        self.batch_size = positive_integer(options, 'batch_size', 32, 256)
        self.max_batch_bytes = positive_integer(options, 'max_batch_bytes', 1_048_576, 67_108_864)
        self.max_response_bytes = positive_integer(options, 'max_response_bytes', 8_388_608, 67_108_864)
        self.timeout = options.get('timeout', 60)
        if type(self.timeout) not in (int, float) or not 0 < self.timeout <= 900:
            raise ValueError('timeout must be finite, greater than zero and at most 900 seconds')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def catalog(self):
        return [Operation('select', 'Rank supplied passages by cosine similarity using a configured '
                          'Ollama embedding model; embed all input text on each call.',
                          Parameters, ('passages',), requires_text=True)]

    def invoke(self, operation, parameters, inputs, context):
        records = inputs['passages']
        if not records:
            yield Outcome(status='success', code='empty_input', message='No passages; the model was not called.')
            return
        deadline = time.monotonic() + self.timeout
        try:
            query = self.query_prefix + parameters['query']
            for text in (query, *(record.text for record in records)):
                self.check(context, deadline)
                self.body([text])
            query_vector = self.embed([query], context, deadline, None)[0]
            ranked = []
            start = 0
            while start < len(records):
                texts = []
                for record in records[start:start + self.batch_size]:
                    try:
                        self.body([*texts, record.text])
                    except Failure:
                        break
                    texts.append(record.text)
                vectors = self.embed(texts, context, deadline, len(query_vector))
                for offset, vector in enumerate(vectors):
                    score = math.fsum(a * b for a, b in zip(query_vector, vector))
                    ranked.append((-score, start + offset))
                start += len(texts)
            ranked.sort()
            selected = [passage(records[index]) for _, index in ranked[:parameters['limit']]]
            self.check(context, deadline)
        except Failure as failure:
            yield failure.outcome
            return
        yield from selected
        yield Outcome(status='success')

    def check(self, context, deadline):
        if context.cancelled.is_set():
            raise Failure('cancelled', 'cancelled_during_model')
        if time.monotonic() >= deadline:
            raise Failure('failed', 'model_timeout', f'Embedding selection exceeded {self.timeout:g} s.')

    def body(self, texts):
        try:
            body = json.dumps({'model': self.model, 'input': texts, 'truncate': False},
                              ensure_ascii=False).encode('utf-8')
        except UnicodeEncodeError:
            raise Failure('failed', 'invalid_input_text', 'Input text must be valid UTF-8.')
        if len(body) > self.max_batch_bytes:
            raise Failure('failed', 'model_input_too_large', 'An embedding input exceeds max_batch_bytes.')
        return body

    def embed(self, texts, context, deadline, dimensions):
        self.check(context, deadline)
        request = urllib.request.Request(f'{self.endpoint}/api/embed', self.body(texts),
                                         {'Content-Type': 'application/json'})
        try:
            try:
                response = self.opener.open(request, timeout=max(0.001, deadline - time.monotonic()))
            except urllib.error.HTTPError as error:
                response = error
            with response:
                chunks, size = [], 0
                while True:
                    self.check(context, deadline)
                    chunk = response.read1(min(65536, self.max_response_bytes + 1 - size))
                    self.check(context, deadline)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise Failure('failed', 'model_response_too_large', 'Response exceeds max_response_bytes.')
                raw = b''.join(chunks)
                status = response.status
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            self.check(context, deadline)
            if isinstance(getattr(error, 'reason', error), (socket.timeout, TimeoutError)):
                raise Failure('failed', 'model_timeout', 'The embedding server timed out.')
            raise Failure('unavailable', 'model_server_unavailable', 'Cannot read from the configured embedding endpoint.')
        if 300 <= status < 400:
            raise Failure('failed', 'model_redirect_refused', 'Configure the destination endpoint explicitly.')
        if status == 404:
            raise Failure('unavailable', 'model_missing', 'Embedding endpoint or configured model was not found.')
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise Failure('failed', 'invalid_embeddings', 'The embedding server returned invalid JSON.')
        if not isinstance(data, dict):
            raise Failure('failed', 'invalid_embeddings', 'The embedding response must be an object.')
        if status != 200 or data.get('error'):
            detail = str(data.get('error', 'Embedding server rejected the request.'))
            code = ('model_input_too_large' if any(term in detail.lower() for term in
                    ('context length', 'context size', 'exceed_context_size', 'input too long')) else 'model_error')
            raise Failure('failed', code, detail[:300])
        vectors = data.get('embeddings')
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise Failure('failed', 'invalid_embeddings', 'Embedding count does not match the input count.')
        result = []
        for vector in vectors:
            normalized = unit_vector(vector, dimensions)
            dimensions = len(normalized)
            result.append(normalized)
        return result
