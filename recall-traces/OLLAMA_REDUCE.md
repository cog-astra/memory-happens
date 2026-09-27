# Local-model reduce

`plugins.ollama_reduce` answers a question from supplied passages with a local Ollama model and
cites the passages it used. It is an optional transform ([issue #28](https://github.com/cog-astra/memory-happens/issues/28)):
whether it helps a workflow is a hypothesis under test, not an established result.

## Configure

Model and endpoint come only from trusted configuration, never from passage text:

```json
{"name": "reduce", "module": "plugins.ollama_reduce",
 "options": {"model": "qwen3.8:27b-q8_0", "num_ctx": 32768, "think": false, "timeout": 900}}
```

`model` is required. `endpoint` defaults to `http://127.0.0.1:11434`. `num_ctx`, `num_predict`
(a positive integer), `temperature`, `think` and `keep_alive` are passed to Ollama as given.
`timeout` (seconds) bounds each wait for the server and is checked against the whole answer
between streamed chunks, so one stalled read can outlast the overall deadline by up to one
`timeout`; it is not a strict wall-clock ceiling.

## Use

The operation is `summarize(question)` with input port `passages`; every passage needs text.

```json
[{"name": "found", "plugin": "sessions", "operation": "search", "parameters": {"query": "R9700", "limit": 8}},
 {"name": "answer", "plugin": "reduce", "operation": "summarize",
  "parameters": {"question": "Why was the R9700 chosen?"}, "inputs": {"passages": "found"}}]
```

The result is one passage:
- `text` is the model's answer;
- `evidence` holds the unchanged evidence of the passages it cited, in citation order;
- `context.relation` is `transformed`, and the context also lists `cited`, `inputs`, `input_characters`, `prompt_tokens` and `output_tokens`.

Read the evidence to check the answer: the runner's lineage stays `unknown`, and nothing here
judges whether the interpretation is true.

## Outcomes

| Status / code | Meaning |
| --- | --- |
| `success` | An answer with its cited evidence. |
| `success` / `empty_input` | No passages; the model was not called. |
| `unavailable` / `model_server_unavailable`, `model_missing` | Nothing answered, or the model is not pulled. |
| `failed` / `model_timeout` | No complete answer within `timeout`. |
| `failed` / `model_output_truncated` | The answer hit the output limit. |
| `partial` / `marker_mismatch` | An answer with its cited evidence, but the reply did not echo both prompt markers; coverage unknown, see below. |
| `failed` / `invalid_model_output`, `invalid_citations`, `invalid_model_stream`, `incomplete_model_stream`, `model_error` | The reply cannot be trusted as an answer. |
| `cancelled` | Stopped between streamed chunks. |

## Silent prompt truncation

Ollama cuts a prompt longer than its context without an error. Measured with 0.34.4: a
6453-token prompt at `num_ctx=256` returned HTTP 200 with `prompt_eval_count=131`, and the
only trace was a server-log warning. The beginning was dropped and the tail kept.

The plugin frames the passages with random BEGIN and END markers, and the reply schema makes
the model echo both. `context.markers` records each as `echoed` or `differs`. BEGIN is recorded as
`end_marker` when the reply returned the END marker in its place, which is what the truncation
above looked like. On any mismatch the answer and its cited evidence are still returned, with
`partial/marker_mismatch`. The message says what differed and that coverage of the input is unknown.

A mismatch does not prove truncation either. In one live run a 257-token prompt, far inside its
16384-token context, came back with BEGIN exact and END miscopied by one character. Malformed
answers, invalid citations, server errors and truncated output remain failures and return no
answer.

The markers are a heuristic for the truncation observed above, not a coverage guarantee: a
matching pair means only that the reply echoed both markers that were sent. It says nothing
about attention to the passages between them, and a chat template could drop other parts.
`prompt_eval_count` is reported but does not prove coverage, because Ollama may reuse a cached
prompt prefix. If the prompt may not fit, raise `num_ctx` or pass fewer passages.

Passages are presented to the model as data, and it is told to ignore instructions inside them.
That is an instruction, not a sandbox: treat the answer as a claim to verify against its evidence.
