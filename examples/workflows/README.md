# Compare two starter workflows

Run both workflows over the same three invented notes, using the environment installed by [BOOTSTRAP](../../BOOTSTRAP.md):

```sh
<python> examples/workflows/compare.py
```

The script opens a temporary SDK MCP connection to this checkout, reads only the supplied notes, and removes its temporary source configuration when finished. It does not register a server in your client or load your personal source configuration. No model, API key or vector database is needed. This is a separate comparison command; it does not change the Git-based `--demo` server.

| Query | Literal workflow | Trigram workflow |
|---|---|---|
| `invoice` | Billing note | Billing note |
| `gardens` | No finding | Orchard note, which says `garden` |
| `duplicate` | No finding | No finding, although the billing note describes sending twice |

The command prints the observed table and reopens each finding through the source's `read` operation. Failures and over-budget results end the comparison with an error instead of appearing as empty searches. These hand-written cases illustrate behavior; they are not a quality benchmark or a claim that trigrams always help.

## The recipes

Both workflows have the same source, passage windows, limit and output budget:

```text
notes.passages → selector.select → read returned evidence
notes.passages → fuzzy.select    → read returned evidence
```

[literal.json](literal.json) and [trigram.json](trigram.json) are ready `operation_run` arguments. They differ only in the selector plugin name. The source and selector run inside one call; `read` is a subsequent call using the returned evidence. Literal selection accepts any query term as a substring; trigram selection ranks words by shared character trigrams. Neither is semantic search or translation.

Try your own wording or inspect every request and response:

```sh
<python> examples/workflows/compare.py --query garden --query gardens
<python> examples/workflows/compare.py --json
<python> examples/workflows/compare.py --characters 1
```

The last command deliberately reports `over_budget` and exits unsuccessfully. It demonstrates the output boundary; it does not change what either selector searched. Current recipes materialize finite batches in memory, so this small example says nothing about large-corpus resource use.

## Use the same recipes with your source

Follow [CONNECT](../../CONNECT.md) to choose your source. For a source named `notes`, add this optional operation entry to that configuration:

```json
"operations": [{"name": "fuzzy", "module": "trigram_selector"}]
```

Preserve any operations already present. Restart the server after configuration changes and check `operation_catalog`. Set the query in either recipe and call `operation_run`. For an exported session source named `sessions`, change the source step's plugin from `notes` to `sessions`; both provide `passages`. For other aliases use the name in your configuration. Read findings with the returned evidence, for example `read(evidence=<returned evidence>, lines=40, characters=6000)`.

Optional model reduction is a further workflow described in [Local-model reduce](../../recall-traces/OLLAMA_REDUCE.md). It needs explicit model configuration and has its own costs; it is not silently enabled by these examples.
