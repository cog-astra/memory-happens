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
| `failed` / `model_input_too_large` | The backend explicitly refused an input exceeding its context; raise `num_ctx` or pass fewer passages. |
| `failed` / `invalid_model_output`, `invalid_citations`, `invalid_model_stream`, `incomplete_model_stream`, `model_error` | The reply cannot be trusted as an answer. |
| `cancelled` | Stopped between streamed chunks. |

## Input size

Every request sends top-level `truncate=false`; the model no longer has to echo boundary markers.
On 2026-09-27, Ollama 0.34.4 with `qwen3.8:27b-q8_0` accepted a synthetic oversized input by
default (`prompt_eval_count=1026`), but rejected the same input twice with `truncate=false`:
HTTP 400, `exceed_context_size_error`, 30011 tokens against 2048 available. Two short controls
passed. Streaming with the answer/cited JSON schema also passed a short control and refused
both oversized inputs (30036 tokens). Requested `num_ctx=512` differed from the reported 2048.

This is the tested server/model combination, not a guarantee for other Ollama versions or
backends: an implementation ignoring the flag may still truncate silently. The plugin reports
the backend's token counts and explicit errors; it does not independently tokenize the prompt
or judge whether the model understood it. Unknown server errors remain `model_error`.

Passages are presented to the model as data, and it is told to ignore instructions inside them.
That is an instruction, not a sandbox: treat the answer as a claim to verify against its evidence.
