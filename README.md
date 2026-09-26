# memory-happens

Memory assembled from traces for the task at hand.

An experimental recall tool for AI-assisted work: find a past conversation, decision,
change or unresolved question without asking the human to reconstruct it each time.
The implementation provides MCP tools for recent activity, search and reading sources.
Finding a matching passage is a lead; it does not establish the meaning of a decision.

Our [vision and design principles](VISION.md) explain why we build recall from traces,
how we treat evidence and attention, and what would count as useful memory.
The [FAQ](FAQ.md) discusses vector databases, ordinary workflows and model-assisted reading.

## Work together

Found a problem or have a proposal? [Open an issue](https://github.com/cog-astra/memory-happens/issues/new/choose).
Describe what you tried, what happened and what would help. A patch is optional.
For an implementation, open a branch and a pull request; see [CONTRIBUTING.md](CONTRIBUTING.md).
Human and agent sessions use the same process. The human does not have to relay reports.

## Status

This private repository starts with the collaboration workflow. The existing local
implementation is being imported through a reviewed PR; this branch is not yet an installable
package. No running installation is changed by cloning it.

The planned import includes session archivers and projections, source adapters, the recall
MCP server, tests and a skill. It excludes conversation corpora, personal configuration,
working handoffs and the source repository's private history.

Known access-filter failures and portability gaps are tracked in issues. The current
`humans.txt` filtering is an experimental cooperation mechanism, not an OS security boundary.
Python plugins run trusted code in the server process.

## Origins

Developed with Pavel Tsiber (Terra), Astra (OpenAI Codex) and Claude.
The work combines session archiving and trace-based recall with source adapters and MCP access.
The import PR records implementation provenance; git authorship alone does not distinguish
human and agent work. Publication dates this implementation, not the invention of the idea.

Code and project documentation use the [MIT license](LICENSE). Private source material is
not included or licensed by this repository. Public release is a separate decision after
review of the imported contents, dependencies and remaining limitations.
