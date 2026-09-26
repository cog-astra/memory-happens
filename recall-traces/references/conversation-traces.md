# Conversations in the local archive

Codex and Claude Code sessions are copied into archives and projected into Markdown for search.
The recall MCP tools (`recent`, `search`, `read`) read these projections; this page explains how
they are built and what they leave out.

## How it is built

`raw/` (Codex) and `projects/` (Claude) hold exact JSONL copies, including Claude subagents
(`<session>/subagents/agent-*.jsonl`). Claude Code deletes sources older than 30 days; the
archive does not. A vanished source does not delete the archive; when a source is rewritten, the
previous bytes stay in `revisions`, and an unfinished tail is kept in raw but deferred in the
projection. The archive is local and does not strip secrets from the turns; it is not for
publication.

`sessions-corpus` next to each archive is the Markdown projection. The file header holds the raw
path, `session`, `project` (cwd) and `origin`: for Codex `cli`, `exec` or `subagent of <parent>`,
for Claude `cli` or `sdk-cli` (a `-p` run). Turns are `## <time> [role] L<JSONL line>:B<block>`.
The projection keeps the text of user turns and public assistant replies. A Claude tool call
leaves a line `[tool:Name] intent — path`: its `description` and the edited path, never the
command text. Thinking, tool results and meta records are left out.

Scheduled tasks run `scripts/archive_claude.py` and `scripts/archive_codex.py` at logon and
every 15 minutes; the state is `status.json` at the archive root, the installers are
`scripts/install-*-archive.ps1`. When an archive has not been updated for a while, failed on its
last pass, or stays silent while live sessions keep changing, `recent` and `search` say so on
their first line.

## Whose traces these are

`user` is a message role, not proof of human authorship: it may be a parent's task for a
subagent, an inherited conversation, a timer or a message delivery. Known service openings are
listed in `service_prefixes` of the sessions plugin config; the ribbon does not present them as
the human. A new service opening belongs there.

Several hits may be copies of one answer: compare the text and `origin` before counting them as
independent confirmations. The time of a copied turn does not establish when it was first said.

An anchor note needs only a reason to return and a place: the file path, the `L` line and `B`
block, and, if useful, a short recognisable quote. When the file changes, check the quote; an
earlier version may be in `revisions`.
