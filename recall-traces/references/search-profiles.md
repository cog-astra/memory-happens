# Recall profiles

Choose a workflow by the question and available tools. These examples assume the catalog
contains a notes source named `notes`; substitute an actual source alias. Optional aliases
`fuzzy` and `semantic` below are configuration examples, not built-in names.
Inspect `operation_catalog` first. Profiles do not change installation or download models.

## Words: a precise clue

Use the configured convenience `search(query="invoice", characters=6000)`, then pass a returned
`evidence` to `read(evidence=..., lines=80, characters=12000)`. A rare identifier is often a
better starting clue than a whole question. Search is case-insensitive substring matching,
not a semantic query. In legacy mode, use the returned `read:` address and the tool's schema.

For project narrowing use `where`; for a known folder use `root`. Inspect coverage hints if
nothing appears. A matching word may occur in a quoted old conversation or a task description;
opening the source is what tells you what happened.

## Word forms: a lightweight selector

Requires the optional `trigram_selector` plugin, for example configured as `fuzzy`.
It compares character trigrams within words; it is useful for some word forms and approximate
spellings, not translation or synonyms. On a small configured notes collection:

```json
{
  "steps": [
    {"name": "candidates", "plugin": "notes", "operation": "passages",
     "parameters": {"lines": 20}},
    {"name": "selected", "plugin": "fuzzy", "operation": "select",
     "parameters": {"query": "gardens", "limit": 5},
     "inputs": {"passages": "candidates"}}
  ],
  "characters": 10000,
  "view": "passages"
}
```

`notes.passages` and `sessions.passages` read all accessible text in their configured source.
They have no query, date filter or candidate limit. `lines` bounds physical lines per window,
not total input or characters per window. Use this recipe on a suitably small source.
For a large corpus, a source `search` or `during` step can supply a narrower candidate set;
that choice also limits what the selector can discover.

## Meaning: describe the answer

Requires `plugins.ollama_embed` with an explicitly configured embedding model and endpoint,
for example under alias `semantic`. On the same small source, replace `fuzzy` with
`semantic` and ask something like `"Why did repeated invoices charge the customer twice?"`.
Selected passages keep their original text and evidence. Read them to decide whether they
answer the question: the selector returns nearest candidates even if none is relevant.

On a larger source, this recipe deliberately searches for a topic first:

```json
{
  "steps": [
    {"name": "candidates", "plugin": "notes", "operation": "search",
     "parameters": {"query": "invoice", "limit": 20}},
    {"name": "selected", "plugin": "semantic", "operation": "select",
     "parameters": {"query": "Why did repeated invoices charge the customer twice?", "limit": 3},
     "inputs": {"passages": "candidates"}}
  ],
  "characters": 10000,
  "view": "passages"
}
```

This will miss a relevant passage excluded by the word search. If topic words are unknown,
use a small connected corpus or an appropriate time interval rather than treating lexical
prefiltering as full semantic recall. A source's `during` result is a time-selected trace,
not every line of every matching file.

Every embedding call processes all supplied candidate text again; there is no persistent
index or cache. Reducing the selector's `limit` only reduces returned records. Oversized
individual text can fail with `model_input_too_large`; choose smaller source windows or
read a smaller passage, or use another profile. Reducing `characters` does not solve model
input limits. Text goes to the configured endpoint, which may be local or remote; use only
an endpoint authorized for that data. Configuration is described in
[optional embedding selection](https://github.com/cog-astra/memory-happens/blob/main/recall-traces/OPERATIONS.md#optional-ollama-embedding-selection).

## Context: unfold lines or time

Notes, sessions and memory sources expose `expand`. Each input anchor must have one evidence
from that source. Append this step after a selection named `selected` from notes:

```json
{"name": "context", "plugin": "notes", "operation": "expand",
 "parameters": {"before_lines": 15, "after_lines": 25},
 "inputs": {"anchors": "selected"}}
```

The recipe returns only its last step. Expansion centers on the locator's starting line;
it may omit the tail of a long original passage. Keep the original finding or read a window
covering both it and its neighbors. Overlapping windows remain separate.

For an event's time neighborhood, the configured convenience call
`around(time="2026-04-08T10:00:00Z", seconds=600, characters=10000)` reads ten minutes on
each side. `during(start="2026-04-08T09:50:00Z", end="2026-04-08T10:10:00Z", characters=10000)`
expresses the same half-open interval. Both timestamps need timezone offsets.
These calls can gather different connected sources; their times mean different things:
session message time, Git author time, or file modification time. Temporal proximity suggests
a lead, not a causal relationship. Line expansion and time expansion offer different views
of context; they are not interchangeable evidence.

## Explore: follow something interesting

Start with a loose topic, question or fragment. Word or semantic selection can offer leads;
read the surrounding conversation when one catches your attention. It is fine to leave the
initial question behind and surface a useful analogy or a new question instead.

Describe the connection as your interpretation and retain its source. A surprising near
miss can be useful feedback. This profile has no special operation, required model, relevance
score to achieve or minimum number of findings. Stop when the exploration has served the
conversation; it need not turn into a benchmark.
