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
observed. Git history currently follows `HEAD`, not every branch.

The Git reader takes an explicit access mode wherever it is connected. With `access='repository'`,
the policy is checked for the repository as a whole, history is read with one `git log`, and every
record depends on the repository only; `--demo` and `--repo` use it. With `access='changed_paths'`,
the policy is also checked for every path each commit changed, for policies that distinguish paths
inside a repository, such as the legacy adapter's boundaries. That mode starts Git processes per
revision and accumulates dependencies during a call
([issue #12](https://github.com/cog-astra/memory-happens/issues/12)).
The lineage, trace and envelope kept for other outputs were not measured separately.

The opt-in `git_operations_legacy` source (`repo` setting) routes existing `Recall.recent`,
`search` and `read` through the operation reader. It is a single-repository migration adapter,
not a replacement for Git discovery. Existing configured plugins and MCP tools are unchanged.
The adapter uses the legacy core's boundary filtering, including the mixed-commit and
junction-alias limitations tracked in [issue #38](https://github.com/cog-astra/memory-happens/issues/38).
The operation runner accepts its own explicit policy callback. No policy file format is required.

## Through MCP

`python recall_mcp.py --demo` serves a temporary synthetic Git history. It exposes only
`operation_catalog` and `operation_run`; no personal source configuration is read.
`--repo /absolute/path/to/repository` connects the same tools to a chosen working tree.
Its access boundary is the whole selected repository. It remains experimental: a patch larger
than the caller's budget can be read only whole.
`--selector trigram_selector` replaces the default selector in either mode.
`--sources /absolute/path/to/sources.json` connects configured sources through operations,
as described below. With no mode flag, the legacy `recent`, `search` and `read` tools remain available.
See [first connection](../BOOTSTRAP.md) for client setup.

`operation_run(steps, characters, view, trace)` runs a finite recipe of catalog operations in one
call with a fresh runner. A step is `{name, plugin, operation, parameters?, inputs?, on_error?}`; an input
port holds the name of an earlier step or a list of complete records. Records move between steps
inside the call, so the caller does not carry intermediate batches. Policy, evidence, lineage and
outcomes apply to every step as they do to a single invocation. A step that ends neither in
`success` nor in `partial` stops the recipe and its outcome becomes the recipe's. Otherwise the
recipe takes the first `partial` step's outcome, or else the last step's, with its next steps
and continuation. Every step that ran is summarized: operation, parameters, record count, its
complete outcome, and a month-by-month breakdown of `context.event_time` that keeps gaps between
periods visible.

An independent source step may set `on_error: "continue"`: failed records from that step are
discarded, subsequent steps run, and the recipe reports partial coverage with
`incomplete_sources`. The default is `"stop"`. Cancellation always stops the recipe, including
when closing the plugin iterator also fails. Caller-supplied recipes allow at most ten steps.

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

## Configured sources through operations

`--sources` uses the existing source configuration for Claude and Codex session archives,
project memory, notes and discovered Git repositories. It exposes `operation_catalog` and
`operation_run` alongside `during`, `recent`, `search` and `read` convenience recipes. These recipes use
the same source operations and collection plugin; they do not invoke the legacy `Recall` core.
Each source may have a unique `name` for its catalog alias. Otherwise its plugin name is used,
with a suffix for repeated source types. Unknown source types report `unsupported`.

Every convenience call requires `characters`. `during(start, end)` reads an absolute time interval:
both boundaries are ISO timestamps with explicit timezone offsets, start is included and end
excluded. Each source exposes the same `during` operation in the catalog. `recent(days)` resolves
`[now - days, now)` and delegates to that operation; an aggregate call shares one pair of boundaries
across sources. `during` also accepts `where`, `limit` and `view`.

`recent` accepts `days`, `where`, `limit` and
`view`; `search` adds `query` and optional `root`. Without `root`, source search results are
ranked by matched words, occurrences and time, with `limit` applied per source. With `root`,
the folder reader searches text files and relocated archives. Empty results are distinct
from missing sources or incomplete coverage. Session archive warnings are retained in outcomes.
The internal source-collection recipe can include more than ten configured sources.

Use a finding's `evidence` in `read`, or pass a legacy `read: path start=N` address as `path`.
These alternatives are mutually exclusive. `start` overrides the address's line offset;
`lines` defaults to 80. Read outcomes carry continuation and identify a changed file when
its observed modification time differs. Evidence can be read by a fresh server using the same
source configuration. Git evidence identifies a repository and revision; the configured Git
adapter reads commit messages and change statistics, matching the legacy source rather than
the full-patch reader used by `--repo`.

Session and commit times use `event_time`; file modification times use `modified_at`.
For `during`/`recent`, sessions select messages within the window before producing daily traces:
`day_start` and `event_time` are the first and last selected messages, and evidence opens a selected
message. Daily topics are retained only when the whole day's messages fit in the window. Notes
and project memory select by modification time; Git selects by author time, not committer time.
Session file modification time cannot exclude matching messages. These plain-file readers still
scan timestamps, and Git traverses history to check author times; absolute bounds do not imply an index.

For example, call `during(start="2026-04-08T09:50:00Z", end="2026-04-08T10:10:00Z", characters=8000)`
to inspect a past event's neighborhood directly. A custom recipe can use a source's `during`
step followed by a selector or reducer; no `recent` step or later date filter is needed.

Session traces retain archive metadata in passage context. Transform
plugins can combine the sources without interpreting their evidence. Configuration is loaded
when the server starts; boundary files are reloaded for each convenience or custom recipe call.
This mode does not install or schedule archive writers, update another MCP registration, or
replace the separately running legacy server.

Additional trusted Python operation plugins can be connected in the same configuration:

```json
{"operations": [{"name": "fuzzy", "module": "trigram_selector"}]}
```

Each entry names an importable module and a unique catalog alias. An optional `options` object
is passed to `Plugin(options)`; without options the loader uses `Plugin()` or the module's own
`catalog` and `invoke`. Names cannot replace a source, `folder`, `selector` or `collect`.
These are executable Python plugins, just like the selector; configure only trusted modules.
They become available to custom `operation_run` recipes. The convenience recipes keep their
existing behavior, and models or other dependencies are not installed by configuration loading.

Notes and session sources also expose `passages(lines=40)`: all accessible file text in
consecutive physical line windows, ordered by path and line. There is no query, age filter
or candidate limit. The source's configured file enumeration and access boundaries still
apply. A session window can cross message boundaries, so it carries `modified_at`, not an
inferred `event_time`. Empty files emit no passages. Each window preserves a line address
and observation time for the existing `read` operation.

With the `fuzzy` configuration above, a custom recipe can select before returning text:

```json
[
  {"name": "candidates", "plugin": "notes", "operation": "passages"},
  {"name": "selected", "plugin": "fuzzy", "operation": "select",
   "parameters": {"query": "gardens", "limit": 5}, "inputs": {"passages": "candidates"}}
]
```

Use a configured session alias in the first step for archive text, or `selector` in the
second step for literal selection. These recipes materialize all candidate records before
selection; `lines` bounds each window's line count, not its characters or total memory use.
The final `characters` budget does not bound intermediate text. `test_source_operations`
checks old and deep text, selector replacement, evidence readback and access filtering on
synthetic notes and session projections.
