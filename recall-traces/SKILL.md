---
name: recall-traces
description: "Beta recall from existing sessions, notes, project memory and Git. Try it for past decisions, forgotten context, related examples or inspiration, even without an exact question. Choose word, word-form, semantic or context-expansion workflows according to the connected tools. Real-task use and feedback on useful discoveries, misses and friction are welcome."
---

Try recall on a real task where past traces could help. This is a beta: other agent sessions
are welcome to use it, explore different workflows and share what helped or got in the way.
A useful result may be a source, an unexpected connection, a better question or a miss worth
reporting. There is no need to manufacture a problem or finish an exhaustive search.

## Choose a recall profile

These profiles are ways to compose a workflow, not saved server settings or model presets.
Use the one that fits the present intent; combine or switch them when a finding suggests it.

| What you have or want | Starting profile |
| --- | --- |
| A rare word, symbol, filename or remembered phrase | **Words:** search, then read a finding. |
| Approximate spelling or a different word form | **Word forms:** candidates → trigram selector → read. No model needed. |
| A description of the answer, with different vocabulary | **Meaning:** bounded candidates → optional embedding selector → read. Requires a configured embedding model. |
| A fragment whose circumstances matter | **Context:** read or expand nearby lines; during/around explores a time neighborhood. |
| Curiosity, an analogy or inspiration | **Explore:** start with a loose question, follow a promising fragment into its neighbors, and say what connection you see. |

For copyable recipes, prerequisites and limits, read
[search profiles](references/search-profiles.md). Start with an ordinary word search when that
is enough; these are alternatives, not a mandatory ladder. A selector can only choose among
its supplied candidates. An empty lexical search cannot be repaired by ranking that empty set.

## Use the connected tools

If `operation_catalog` is available, inspect it for source aliases, operations and parameter
schemas. In configured-source mode, `search`, `read`, `recent`, `during` and `around` are
convenience recipes; `operation_run` composes steps inside one call. State `characters` explicitly.
Start with `view="first_look"` for orientation or `"passages"` to read text with evidence.
Intermediate records stay inside the recipe; the output budget does not limit their size.

With only legacy `recent`, `search` and `read`, use those directly and their exposed schemas.
Legacy `search` matches words across connected sources; `root` targets a folder.
Open the returned `read:` address with `read`. Custom selectors and expansion profiles require
the operation API. Do not assume a particular MCP server name or optional plugin is installed.

Read outcomes and coverage as well as findings: an unavailable or stale archive is different
from no match. On an unhelpful result, try source vocabulary, another source or a different
scope. `during` uses an explicit past interval; `recent` is relative to now. For conversation
corpora and long-term retention, see [archive notes](references/conversation-traces.md).

Keep the evidence or path that lets a finding be reopened. A match or high similarity is a
lead; read enough to distinguish the original words from your interpretation. If a neighboring
fragment changes the question, follow it when useful. Say what caught you in an indirect
connection, and leave uncertainty when nothing settles it.

## Access and setup

A folder containing `humans.txt` is a personal space. Read its owner's boundary before
searching or quoting it. Its `[recall]` section uses relative paths: `open` exposes paths,
`private` stays closed even within an open part, and `guests` treats residents of those
subfolders as neighbors. Do not use another reader or a shell path to bypass a closed source.

For a new connection, use the repository's
[connection guide](https://github.com/cog-astra/memory-happens/blob/main/CONNECT.md).
Detailed operation contracts and optional plugin setup are in
[OPERATIONS.md](https://github.com/cog-astra/memory-happens/blob/main/recall-traces/OPERATIONS.md).
A missing tool is a setup limitation, not evidence that the past event did not happen.

## Feedback makes this beta useful

Helpful discoveries matter as much as failures. A short report is enough:

- What were you trying to remember or explore?
- Which profile, connected source types and version did you use, if known?
- What helped, surprised, missed or cost too much? What would you try next?

Feedback is optional and need not interrupt the user's task. With existing authorization to
post, check for a related issue and report directly in the
[issue tracker](https://github.com/cog-astra/memory-happens/issues). Otherwise leave the
observation for the user. Use general task descriptions and minimal synthetic examples;
do not publish private excerpts, personal paths, project details or credentials.

For a patch, work in a repository checkout and follow
[CONTRIBUTING.md](https://github.com/cog-astra/memory-happens/blob/main/CONTRIBUTING.md);
the installed skill is a consumer. No automatic telemetry or feedback submission is implied.
