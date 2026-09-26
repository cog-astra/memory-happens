# memory-happens

Memory assembled from traces for the task at hand.

An experimental recall tool for AI-assisted work: find a past conversation, decision,
change or unresolved question without asking the human to reconstruct it each time.
The implementation provides MCP tools for recent activity, search and reading sources.
Finding a matching passage is a lead; it does not establish the meaning of a decision.

**First recall in a few minutes.** Give an agent (Claude Code or Codex) this repository's URL
and ask it to set up recall. [BOOTSTRAP.md](BOOTSTRAP.md) tells it what to check and what to ask
you once before changing anything. It then makes a first recall over a synthetic Git history and
can connect a repository of your choice.

Our [vision and design principles](VISION.md) explain why we build recall from traces,
how we treat evidence and attention, and what would count as useful memory.
The [FAQ](FAQ.md) explores plugins, recall workflows, model-assisted understanding
and the limits of what a trace can tell us.
The [proposed operation contract](ARCHITECTURE.md) describes the next architecture slice
and its acceptance checks; it is not the API of the imported implementation.

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

Known access-filter failures and portability gaps are tracked in issues. The current
`humans.txt` filtering is an experimental cooperation mechanism, not an OS security boundary.
Python plugins run trusted code in the server process.

## Install and test

Tested with Python 3.12 on Windows; other versions and platforms are untested.

```sh
cd recall-traces/scripts
python -m pip install -r ../requirements.txt
python -m unittest                      # needs git on PATH
cp sources.example.json sources.json    # edit the paths, or set RECALL_CONFIG to a config file
python recall_mcp.py                    # MCP server over stdio
```

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
