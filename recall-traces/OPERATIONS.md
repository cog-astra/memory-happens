# Experimental operation boundary

The executable slice is under development. It does not replace the installed MCP API.
The public Python types live in `scripts/recall_operations.py`; plugins import those types,
not runner internals. Version `0.1` is provisional until the independent selector trial.

A plugin supplies `catalog() -> iterable[Operation]` and
`invoke(operation, parameters, inputs, context) -> iterator[Passage | Outcome]`.
The runner validates parameters against the descriptor's Pydantic model, then passes their
plain dictionary with defaults applied. Inputs map the declared port names to finite lists
of `Record`. Operations needing text set `requires_text=True`.

For a replaceable selector, expose `select`, input port `passages`, and parameters
`query: str` (nonempty) and `limit: int` (positive, default 5). Yield selected passages and
then exactly one `Outcome(status='success')`, including when nothing matched. Ranking may
differ between implementations. Preserve evidence without interpreting its source or locator.
`passage(record)` copies the passage fields without copying the runner-owned envelope.

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
