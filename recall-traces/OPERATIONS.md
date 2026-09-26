# Experimental operation boundary

The executable slice is experimental. It does not replace the default MCP API.
The public Python types live in `scripts/recall_operations.py`; plugins import those types,
not runner internals. Version `0.1` is provisional; two selectors are exercised by the tests.

A plugin object (including a Python module) supplies `catalog() -> iterable[Operation]` and
`invoke(operation, parameters, inputs, context) -> iterator[Passage | Outcome]`.
The runner validates parameters against the descriptor's Pydantic model, then passes their
plain dictionary with defaults applied. Inputs map the declared port names to finite lists
of `Record`. The `operation` argument is the descriptor's name, a string. Operations needing
text set `requires_text=True`; the runner checks every record on every declared input port.

For a replaceable selector, expose `select`, input port `passages`, and parameters
`query: str` (nonempty) and `limit: int` (positive, default 5). Yield selected passages and
then exactly one `Outcome(status='success')`, including when nothing matched. Ranking may
differ between implementations. Preserve evidence without interpreting its source or locator.
`passage(record)` deeply copies passage fields without copying the runner-owned envelope.
This prevents edits to its result from mutating the supplied record; it does not make values
immutable or enforce semantic fidelity. The slice always uses conservative lineage; plugins
cannot yet refine it, although the architecture leaves that extension open.

Readers call `context.require(*resolved_resources)` before accessing a resource. Transforms
receive the conservative union of input access dependencies. These checks constrain trusted
plugins; they do not sandbox Python. Cancellation is cooperative via `context.cancelled`.
Policy refusals raise `AccessDenied`, distinct from OS permission failures. A source may skip
a refused item and report a partial result. Git history does so with `policy_filtered`; a
direct read of denied evidence fails with `access_denied`.

`Passage.context` carries optional source-specific attributes; `event_time` (ISO 8601) is when
the traced event happened. Evidence identifies a configured
source and an opaque locator, optionally its revision or observation time. Records returned by
a caller have unverified provenance. Read operations resolve their evidence and check policy
again; record IDs cannot retrieve content in a later invocation.

Parameters, passage text and evidence locators are not automatically included in the runner's
trace. Trace events contain invocation identity, operation/version, record links and outcome.
Persistent trace retention is the caller's choice.

## Run the slice

From `recall-traces/scripts`, with the repository's requirements installed:

```sh
python -m unittest test_operations
python demo_operations.py
python demo_operations.py --selector plugins.select_literal
python demo_operations.py --selector trigram_selector
```

The demo creates and removes its own synthetic repository. It selects the commit removing a
stale lookup cache, serializes its evidence and reads the patch through a fresh runner. The
selector module is a trusted Python plugin; replacing it does not change the caller or reader.
The default query tests composition, not semantic recall or language-model quality.

`Runner.catalog()` returns descriptors; `Runner.invoke()` yields JSON-compatible `record` events
and one `outcome` event. A consumer stopping early must close the iterator. Invalid calls fail
before invocation, invalid plugin output is
`invalid_output`, and unexpected plugin exceptions are `operation_failed`. Input record IDs
must be distinct across ports. Exceptions are not inferred to be user mistakes or policy refusals.
Trace retention defaults to the runner's in-memory list. Blocking Git commands finish before cooperative cancellation is
observed. Git history currently follows `HEAD`, not every branch. Source access dependencies are
conservatively accumulated during each call.
The reader starts separate Git processes per revision; large-history performance is tracked in
[issue #12](https://github.com/cog-astra/memory-happens/issues/12).

The opt-in `git_operations_legacy` source (`repo` setting) routes existing `Recall.recent`,
`search` and `read` through the operation reader. It is a single-repository migration adapter,
not a replacement for Git discovery. Existing configured plugins and MCP tools are unchanged.
The adapter still uses the legacy core's boundary filtering; it does not resolve issue #2.
The operation runner accepts its own explicit policy callback. No policy file format is required.

## Through MCP

`python recall_mcp.py --demo` serves a temporary synthetic Git history. It exposes only
`operation_catalog` and `operation_run`; no personal source configuration is read.
`--repo /absolute/path/to/repository` connects the same tools to a chosen working tree.
It remains experimental: a patch larger than the caller's budget can be read only whole, and
history starts separate Git processes per commit ([issue #12](https://github.com/cog-astra/memory-happens/issues/12)).
`--selector trigram_selector` replaces the default selector in either mode.
Without either mode flag, the existing `recent`, `search` and `read` tools remain available.
See [first connection](../BOOTSTRAP.md) for client setup.

`operation_run(steps, characters, view, trace)` runs a finite recipe of catalog operations in one
call with a fresh runner. A step is `{name, plugin, operation, parameters?, inputs?}`; an input
port holds the name of an earlier step or a list of complete records. Records move between steps
inside the call, so the caller does not carry intermediate batches. Policy, evidence, lineage and
outcomes apply to every step as they do to a single invocation. A step that ends neither in
`success` nor in `partial` stops the recipe and its outcome becomes the recipe's. Otherwise the
recipe takes the first `partial` step's outcome, or else the last step's, with its next steps
and continuation. Every step that ran is summarized: operation, parameters, record count, its
complete outcome, and a month-by-month breakdown of `context.event_time` that keeps gaps between
periods visible.

Only the last step's records are returned, projected by `view`: `first_look` (default) gives
headline, event time and evidence; `passages` gives text, evidence and context; `records` gives
complete records with the runner envelope. Projection happens only at this boundary; inside the
recipe every record keeps its access dependencies.

`characters` is required and has no default. It bounds the reply's JSON text in Unicode code
points and counts everything returned, including `trace` and the `size` field itself; structured
content carries the same object. If the reply would exceed it, a fixed-shape summary replaces
it: outcome `partial` with code `over_budget` and next steps, the recipe's status and code, each
step's name, operation, record count, status and code, and the would-be size with the record
count and largest record. It never repeats parameters, messages or records. This summary is
returned even when it alone exceeds a very small `characters`.

The MCP mode collects finite results before returning; it does not stream records to the
client or propagate MCP cancellation to the synchronous runner. Git history defaults to
50 commits and names its coverage in its outcome message, such as
`50 most recent of 626 commits on HEAD`. Git reading is restricted to the explicitly configured
repository. Selector modules are trusted Python code, not a sandbox. The demo repository lasts
for the server process; its paths are not durable references.

The stdio integration tests exercise both selectors, a first look followed by a detail read,
the character budget and distinct outcomes over a synthetic history with separated periods,
overlapping paths and a large patch (`synthetic_history.py`). They do not establish the quality
of a language model's interpretation.
