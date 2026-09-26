---
name: recall-traces
description: "Recall what happened and where: \"let's continue X\", \"where did we stop\", \"where did we discuss\", \"what did we decide about\". Your past Claude and Codex sessions across all projects, project memory, notes, git. The main path is the recall MCP tools (recent → search → read); this file covers digging deeper and handling findings."
---

Help see what from the past may relate to the current intent. There may be no exact question
yet. The result can be a pointer, a useful fragment, a new question or a few possible
directions; choose the scope and depth the conversation needs.

You choose how to search: the source's own words, file names, links, change history, an
analogy of an obstacle or a way of acting. A word match is a lead, not proof of a connection in
meaning. If you offer an indirect link, say what caught you.

If something you read surprises, pleases or worries you, you may bring that reaction along with
its source. This is an invitation, not an extra task.

## The recall tools (MCP)

`recent` is a ribbon by day: Claude and Codex sessions split into days of activity (first and
last human turn, last reply, topics if written), commits of the repositories found, changed
project memory and notes. `search` looks for words across all these sources at once; findings
where more distinct words matched come first. With `root` it searches one folder, including
archived process folders. `read` opens a place by the address from a `read:` line or
`repository@revision`.

Sources are plugins listed in `scripts/sources.json` (or the file named by `RECALL_CONFIG`):
`sessions` (transcript corpora), `memory` (Claude project memory), `notes` (Markdown folders),
`git` (discovered and explicitly listed repositories). A plugin is a `Plugin(Source)` class from
`recall_core.py`, placed in `scripts/plugins/` or given as a path to any `.py`; it yields findings
with time, address and a place for bounds, while time windows, the answer budget, bounds and
loud failures stay in the core. `test_recall_core.py` shows a third-party source.

`topics.py` writes topics for session days with a local model through Ollama: only topics and
line numbers, each topic grounded in the lines it cites, stored next to the corpus and marked
with the model and date. A day is cut into stretches so its middle gets a voice. Treat topics as
leads for search and read, never as decisions.

## Bounds

A folder containing `humans.txt` is a personal space. For sessions outside it everything inside
is hidden: sessions opened there, those projects' memory, commits, files. The owner opens parts
with a section in the same file; paths are relative to the folder:

```
[recall]
open = play/, notes/
private = private/
guests = agents/
```

`open` is what neighbours may see (`.` is the whole folder), `private` stays closed even inside
an open part, `guests` makes residents of those subfolders read as neighbours. The reader is the
session's working folder (`RECALL_READER` overrides it). The rules file itself is always
readable. Hidden things do not go silent: the first line of an answer names the space and its
rules file. Spaces are searched under `spaces` in the config.

## By hand

For a path that disappeared: `git -C FOLDER log --all -- PATH`, then `git show REVISION:PATH`;
for a known file there is `scripts/memory_trail.py --help`. `scripts/recall_files.py --source`
reads a window of a file under a root; its windowed search needs a memlab backend, which is not
part of this repository (set `RECALL_MEMLAB`). `--describe` on either script prints its options
as JSON.

Earlier conversations live in local Codex and Claude Code corpora:
[how the archives are built and whose traces they hold](references/conversation-traces.md).
Choosing the archive is part of the search; not finding an episode in a project folder says
nothing about the conversation.

Keep the path and place that let a finding be unfolded again. Someone else's text stays their
testimony: separate the quote from your interpretation, and not finding from not having
happened. When the budget runs out, name the remaining uncertainty; a search does not have to
become a full review.

## Improve recall

Development and issue tracking: https://github.com/cog-astra/memory-happens (currently private).
With repository access and authorization to collaborate, report an observation or proposal there
directly; a patch is optional. Check existing issues and use synthetic examples instead of private
traces. For changes, work in a repository checkout and follow CONTRIBUTING.md; the installed skill
is a consumer. Do not require the human to relay a report between sessions.

When results are empty or useless, you may ask the human you work with about a similar
episode, briefly saying what you searched and where. A hint helps check where the thing got
lost; "I don't remember either" leaves the uncertainty. The answer is not required to finish
the current pass: keep the question and carry on.
