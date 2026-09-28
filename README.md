# memory-happens

Memory assembled from traces for the task at hand.

An experimental recall tool for AI-assisted work: find a past conversation, decision,
change or unresolved question without asking the human to reconstruct it each time.
The implementation provides MCP tools for recent activity, search and reading sources.
Finding a matching passage is a lead; it does not establish the meaning of a decision.

**See it first.** [Walk through a recorded synthetic recall](https://cog-astra.github.io/memory-happens/) in your browser; no installation required.
Or [reopen a past conversation and handover note](https://cog-astra.github.io/memory-happens/sessions.html), including a search that misses both.

**Try a first recall.** Give an agent (Claude Code or Codex) this repository's URL.
[BOOTSTRAP.md](BOOTSTRAP.md) guides the first connection over a synthetic Git history.
Already have material to recall? [CONNECT.md](CONNECT.md) guides connecting your chosen sources.
For long-term session search, [refresh and back up the session archive](CONNECT.md#keep-sessions-searchable-over-time); connecting MCP does not preserve future conversations automatically.

**Compare workflows.** [Run literal and trigram recall on the same notes](examples/workflows/README.md),
including an exact match, a word-form difference and a miss. Both recipes are editable JSON; no model is required.

**For an agent receiving this link:** briefly explain the project, then use BOOTSTRAP's
read-only checks to offer a concrete demo setup for approval. Do not require the user to know
the setup steps or ask a second question to discover them. Install only after approval;
if the user requested only a review or discussion, stay with that request.

Our [vision and design principles](VISION.md) explain why we build recall from traces,
how we treat evidence and attention, and what would count as useful memory.
The [FAQ](FAQ.md) explores plugins, recall workflows, model-assisted understanding
and the limits of what a trace can tell us.
The [operation design](ARCHITECTURE.md) records the proposal and its acceptance checks.
The [implemented operations](recall-traces/OPERATIONS.md) document the experimental API,
configured sources and optional model-assisted processing.

## Work together

Found a problem or have a proposal? [Open an issue](https://github.com/cog-astra/memory-happens/issues/new/choose).
Describe what you tried, what happened and what would help. A patch is optional.
For an implementation, open a branch and a pull request; see [CONTRIBUTING.md](CONTRIBUTING.md).
Human and agent sessions use the same process. The human does not have to relay reports.

## Status

The recall implementation lives in `recall-traces/`: the skill, the MCP server, source plugins,
session archivers and their tests. It was imported from a working installation; the import PR
records the source revision. Cloning or changing this repository does not change a running
installation.

Known limitations are tracked in issues. The current
`humans.txt` filtering is an experimental cooperation mechanism, not an OS security boundary.
Python plugins run trusted code in the server process.

## Install and test

For the demo, use [BOOTSTRAP.md](BOOTSTRAP.md). For selected existing sources, use
[CONNECT.md](CONNECT.md): configuration, first archive export where needed, client registration,
search/read verification and removal. It uses `recall_mcp.py --sources /absolute/path/to/sources.json`.
The [API reference](recall-traces/OPERATIONS.md#configured-sources-through-operations) describes
the operations behind `recent`, `search` and `read`.

Validated in an isolated Python 3.12 environment on Windows; other versions and platforms
are untested. Embedded Python builds that ignore `PYTHONPATH` have a known test limitation
([issue #33](https://github.com/cog-astra/memory-happens/issues/33)).

```sh
<python> -m pip install -r recall-traces/requirements.txt
cd recall-traces/scripts
<python> -m unittest
```

Here `<python>` is the isolated environment from BOOTSTRAP; tests need Git on PATH.
Running a stdio server in a terminal does not connect it to a client.
The legacy mode (no mode flag) remains available for existing installations. Its known
mixed-commit and junction-alias filtering gaps are tracked in
[issue #38](https://github.com/cog-astra/memory-happens/issues/38); do not rely on it to separate
closed spaces from guests. New setups should follow CONNECT.

Optional parts:

- `recall_files.py` search needs a memlab backend, which is not included; set `RECALL_MEMLAB`
  to its checkout. Without it five tests are skipped and `--source` reading still works.
- `topics.py` needs a local model served by Ollama.
- `install-claude-archive.ps1` and `install-codex-archive.ps1` register Windows scheduled tasks.
  The archivers write to `~/recall-archive/claude` and `~/recall-archive/codex` unless given
  `--destination`.
- Output limits such as `characters` count Unicode characters, not tokens.

## Origins

Developed with Pavel Tsiber (Terra), Astra (OpenAI Codex) and Claude.
The work combines session archiving and trace-based recall with source adapters and MCP access.
The import PR records implementation provenance; git authorship alone does not distinguish
human and agent work. Publication dates this implementation, not the invention of the idea.

Code and project documentation use the [MIT license](LICENSE). Private source material is
not included or licensed by this repository. Public release is a separate decision after
review of the imported contents, dependencies and remaining limitations.
