# Experimental operation boundary

The executable slice is under development. It does not replace the installed MCP API.
The public Python types live in `scripts/recall_operations.py`; plugins import those types,
not runner internals. Version `0.1` is provisional until the independent selector trial.

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

`Passage.context` carries optional source-specific attributes. Evidence identifies a configured
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
```

The demo creates and removes its own synthetic repository. It selects the commit removing a
stale lookup cache, serializes its evidence and reads the patch through a fresh runner. The
selector module is a trusted Python plugin; replacing it does not change the caller or reader.
The default query tests composition, not semantic recall or language-model quality.

`Runner.catalog()` returns descriptors; `Runner.invoke()` yields JSON-compatible `record` events
and one `outcome` event. A consumer stopping early must close the iterator. Trace retention defaults
to the runner's in-memory list. Blocking Git commands finish before cooperative cancellation is
observed. Git history currently follows `HEAD`, not every branch. Source access dependencies are
conservatively accumulated during each call.

The opt-in `git_operations_legacy` source (`repo` setting) routes existing `Recall.recent`,
`search` and `read` through the operation reader. It is a single-repository migration adapter,
not a replacement for Git discovery. Existing configured plugins and MCP tools are unchanged.
The adapter still uses the legacy core's boundary filtering; it does not resolve issue #2.
The operation runner accepts its own explicit policy callback. No policy file format is required.

Structured MCP exposure and a stable external-plugin API remain subsequent work. This slice
does not register a server, alter an installed skill, or start a model.
