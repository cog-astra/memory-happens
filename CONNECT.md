# Recall your own sources

For an agent continuing after [the demo](BOOTSTRAP.md), or asked to connect existing data.
Use the clone and isolated Python environment from that guide. If they do not exist, follow
its prerequisite and installation steps first; a synthetic demo is optional when the user
has already chosen a real source. Current validation is Windows with Python 3.12.

## Choose what to connect

Ask which folder, repository or session archive the user wants available. Start with one
source and a word or episode they expect to find. Do not scan a whole home directory to choose
for them. If the user already supplied a path and authorized setup, use that authorization.

Explain the concrete changes before making them: a local `sources.json` containing the selected
paths, an MCP registration named `recall` in the current client, and, for raw session logs,
a separate archive directory containing copies and readable projections. Recall reads the
selected material; snippets returned to the calling agent become part of that agent's context.
Ordinary search/read does not need Ollama, a model reducer, memlab or an index-building step.

Check `claude mcp get recall` or `codex mcp get recall` first. If a connection already exists,
inspect its command and keep a copy before any approved change. Do not overwrite it or create
another name silently. For a new connection, explain its scope and rollback below, then obtain
approval if setup has not already been authorized. Keep local configurations outside version control.

## Prepare the selected source

`<python>` is the absolute path to the environment's Python; `<scripts>` is
`<clone>/recall-traces/scripts`. Use absolute paths, forward slashes in JSON on Windows,
and quote paths containing spaces. In PowerShell invoke a quoted executable with `&`.

**Markdown notes, Git and existing recall archives** need no conversion. Create a local UTF-8
JSON file at `<config>` with only the chosen entries. This example connects one notes folder:

```json
{"sources": [{"name": "notes", "plugin": "notes", "roots": ["C:/chosen/notes"]}]}
```

Replace that entry with, or add, the applicable entries below. Names must be unique.

| Selected material | Source entry |
| --- | --- |
| Git repository | `{"name":"work","plugin":"git","repos":["C:/chosen/repo"]}` |
| Existing recall session corpus | `{"name":"sessions","plugin":"sessions","stores":[{"corpus":"C:/chosen/archive/sessions-corpus"}]}` |
| Claude project memory | `{"name":"memory","plugin":"memory","roots":["C:/chosen/claude/projects"]}` |

Notes default to Markdown files. Git search covers commit messages; configured Git reads messages
and change statistics, not full patches. A session corpus is the Markdown projection described
below, not the raw JSONL directory. Existing boundary rules can be included using `spaces` from
[the source configuration](recall-traces/scripts/sources.example.json); preserve existing rules
when migrating an installation. They are cooperative filtering, not a sandbox. Connect only
material the user has authorized the calling agent to read.

### Raw Claude or Codex sessions: first export

Skip this section if the selected source is already readable. Otherwise choose an archive
destination separate from the source: neither directory may contain the other. The first
export copies raw logs and writes Markdown into `<archive>/sessions-corpus`; it leaves the
original logs in place. The selected raw directory may contain many projects: explain that
scope before exporting it, and do not include unselected client histories.

For Claude, `<raw-projects>` is the selected projects directory (normally `~/.claude/projects`):

```sh
<python> <scripts>/archive_claude.py --source <raw-projects> --destination <archive>
```

For Codex, `<raw-codex>` is the directory containing `sessions` and/or `archived_sessions`
(normally `~/.codex`, not `~/.codex/sessions`):

```sh
<python> <scripts>/archive_codex.py --source <raw-codex> --destination <archive>
```

Check the exit status, printed report and `<archive>/status.json`. A successful empty export
does not prove there were sessions: confirm `.md` files exist under `sessions-corpus`.
On missing input or errors, report the path and next action; do not call setup complete.
Point the sessions source at the resulting corpus. For freshness warnings, add `live` and
`archiver` to its store, using absolute paths:

```json
{"sources": [{"name":"sessions","plugin":"sessions","stores":[{
  "corpus":"C:/chosen/archive/sessions-corpus",
  "live":"C:/chosen/raw/sessions",
  "archiver":"C:/chosen/clone/recall-traces/scripts/archive_codex.py"
}]}]}
```

For Claude, `live` is `<raw-projects>` and `archiver` is `archive_claude.py`.

### Keep sessions searchable over time

Keep the exact export command and repeat it after new conversations, using the same archive
destination. MCP reads the exported corpus; it does not archive new conversations automatically.
Before cleaning up original session logs, export them and verify a known passage through recall.
Already exported copies and their searchable projections remain when original logs are deleted.
Conversations deleted before the first successful export cannot be recovered by this archive.

Include the entire `<archive>` directory in your regular backup to a separate storage location,
including raw copies, `sessions-corpus`, manifests and any revisions. A copy alongside the live
logs does not protect against losing that disk. Keep the configured corpus path available to recall,
or update it if you restore the archive elsewhere.

Automatic refresh is optional; the Windows `install-*-archive.ps1` scripts create scheduled tasks and
need separate consideration of their configured paths. Do not schedule them during this first
connection.

## Register the configured server

Use the same client profile as the intended working session. Reuse its existing clone and
environment. `<server>` is `<scripts>/recall_mcp.py`; `<config>` is the absolute JSON path.
For a new `recall` connection:

```sh
claude mcp add recall -- <python> <server> --sources <config>
claude mcp get recall
```

Run Claude's commands from the intended project directory; its default registration is local
to that project. For Codex, the registration is in that profile's global `config.toml`:

```sh
codex mcp add recall -- <python> <server> --sources <config>
codex mcp get recall
```

For an approved replacement, remove the old registration in its original scope before adding
the new command. The `--sources` flag selects the current operation-based mode. Starting without
it selects legacy mode. After the new connection is verified, the unused `recall-demo`
registration can be removed with the user's setup authorization; no new server name is needed
for each source. Edit the same configuration to add sources, then restart its MCP server/session.

## Verify through the client

Start a new session in the same profile (and Claude project directory) if the tools are not
loaded. Registration output alone does not verify a recall. Do not substitute an SDK call
for the native-client check or report a result you could not obtain.

1. Ask for a known episode from the selected material. Call `search` with a distinctive source
   word and an explicit `characters` budget, for example `query="cache", characters=8000`.
   Word matching is literal; do not require an exact question to match its answer.
2. Inspect the outcome and source coverage. Open a returned `evidence` with `read`, for example
   `characters=12000, lines=40`. State what you found and which source you actually read.
3. If nothing matches, try a known word or inspect `recent`. If the corpus is missing or stale,
   run the chosen export command and retry. Do not treat incomplete coverage as absence.
   If output is over budget, follow its next steps or narrow the query.

The connection is verified only after the intended client's native tools return a finding
and its source text. A blocked step should name the actual error and next step, not claim
successful setup. Feedback can use a synthetic example without posting private text or paths.

## Undo

Remove only the registration created here:

```sh
claude mcp remove recall -s local
codex mcp remove recall
```

Use the command for the client and the scope actually used. If this replaced a registration,
restore its saved command/configuration. Restart the client to unload the server. Delete only
the configuration and archive copies created for this setup if no longer wanted; original notes,
repositories and logs stay in place. Keep a shared clone/environment while another registration
still uses it. This procedure created no scheduled task.
