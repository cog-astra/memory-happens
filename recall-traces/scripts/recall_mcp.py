import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_core import Recall

INSTRUCTIONS = """\
Memory here is not a store but an assembly of traces for the current intent: Claude and Codex session transcripts across all projects, project memory, notes, git.
Before reconstructing the past by hand (git log, reading jsonl, grepping files), assemble it here:
- "let's continue X", "where did we stop", a session starting without context → recent;
- "where did we discuss", "what did we decide about", a familiar word without a place → search;
- a found place → read.
A word match is a lead, not proof. The freshest trace is not necessarily the main thread: look a few days back before choosing.
When answering from findings, say what you read and what stayed uncovered.
Development: https://github.com/cog-astra/memory-happens (currently private). With repository access and authorization to collaborate, report observations or proposals directly in issues, using synthetic examples rather than private traces. Changes go through PRs; see CONTRIBUTING.md in the repository."""

GROUP_SHOWN = 8


def local(time):
    return time.astimezone()


def line(text, limit=220):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def around(text, words, limit=220):
    folded = text.casefold()
    first = min((folded.find(word) for word in words if word in folded), default=0)
    start = max(0, first - limit // 3)
    return ('…' if start else '') + line(text[start:], limit)


def fit(blocks, characters, tail):
    output, used = [], 0
    for index, block in enumerate(blocks):
        if used + len(block) > characters:
            output.append(tail(len(blocks) - index))
            break
        output.append(block)
        used += len(block)
    return ''.join(output)


def trace_block(trace, full):
    moment = (f"{local(trace['start']):%H:%M}–{local(trace['time']):%H:%M}" if trace.get('start')
              else f"{local(trace['time']):%H:%M}")
    head = f"{moment} · {trace['headline']}\n"
    if not full:
        return head
    quotes = ''.join(f"  {quote}\n" for quote in trace.get('quotes', []))
    return head + quotes + (f"  read: {trace['locator']}\n" if trace.get('locator') else '')


def day_block(day, traces, full):
    parts = [f"## {day:%Y-%m-%d}{'' if full else ' (compact)'}\n"]
    automated, groups = defaultdict(int), defaultdict(list)
    for trace in traces:
        if trace.get('automated'):
            automated[trace['where']] += 1
        elif trace.get('group'):
            groups[trace['group']].append(trace)
        else:
            parts.append(trace_block(trace, full))
    for group, members in groups.items():
        if full:
            shown = ''.join(f"  {line(member['headline'], 160)}\n" for member in members[:GROUP_SHOWN])
            more = f"  and {len(members) - GROUP_SHOWN} more\n" if len(members) > GROUP_SHOWN else ''
            parts.append(f"{group}:\n{shown}{more}")
        else:
            parts.append(f"{group}: {len(members)}\n")
    if automated:
        parts.append('automated runs: ' + ', '.join(f"{where} ×{count}" for where, count in automated.items()) + '\n')
    return ''.join(parts) + '\n'


def render_recent(traces, characters):
    days = defaultdict(list)
    for trace in traces:
        days[local(trace['time']).date()].append(trace)
    if not days:
        return 'No traces in this period. Increase days or drop where.\n'
    ordered = sorted(days, reverse=True)
    compact = [day_block(day, days[day], False) for day in ordered]
    output, used, shrunk = [], 0, False
    for index, day in enumerate(ordered):
        block = day_block(day, days[day], True)
        if used + len(block) + sum(map(len, compact[index + 1:])) > characters:
            block, shrunk = compact[index], True
        if used + len(block) > characters:
            output.append(f"[earlier days that did not fit: {len(ordered) - index}; raise characters or narrow where]\n")
            break
        output.append(block)
        used += len(block)
    if shrunk:
        output.append('[compact days in full: recent with where or a larger characters]\n')
    untitled = sum(1 for trace in traces if trace.get('untitled'))
    if untitled:
        output.append(f"[session days without topics: {untitled} — the middle of such a day shows only through search and read; "
                      f"write topics: python {Path(__file__).with_name('topics.py')}]\n")
    return ''.join(output)


def hit_block(hit, words):
    head = f"{local(hit['time']):%Y-%m-%d %H:%M} · {hit['label']} · [{', '.join(hit['matched'])}] ×{hit['total']}\n"
    read = f"  read: {hit['locator']}\n"
    if not hit['places']:
        return head + f"  {line(hit['excerpt'])}\n" + read
    if 'line' not in hit:
        return head + f"  lines {', '.join(map(str, hit['places']))} | {around(hit['excerpt'], words)}\n" + read
    also = [place for place in hit['places'] if place != hit['line']]
    more = hit['lines'] - 1 - len(also) if 'lines' in hit else 0
    tail = (f" · also {', '.join(map(str, also))}" if also else '') + (f" +{more} more" if more else '')
    return head + f"  line {hit['line']} | {around(hit['excerpt'], words)}{tail}\n" + read


def render_search(found, words, limit, characters):
    blocks = [f"### {title}: {len(hits)}\n" + ''.join(hit_block(hit, words) for hit in hits[:limit]) + '\n'
              for title, hits in found if hits]
    if not blocks:
        return 'Nothing found. Try other words, synonyms or word stems; no finding does not mean it never happened.\n'
    return fit(blocks, characters, lambda rest: f"[sources beyond characters: {rest}; raise characters or lower limit]\n")


def preface(recall):
    warnings = recall.health()
    return ''.join(f'⚠ {warning}\n' for warning in warnings) + ('\n' if warnings else '') + recall.bounds.notice()


def create_server():
    from mcp.server.mcpserver import MCPServer
    server = MCPServer('recall', instructions=INSTRUCTIONS)

    @server.tool(structured_output=False, description='What happened in recent days: Claude and Codex sessions (time, project, first and last human turn, last reply, topics), commits, changed project memory and notes. The first step for "let\'s continue X" and "where did we stop". A session shows only the edges of its day; open the middle with read or find it with search using words from the ribbon.')
    def recent(
        days: Annotated[int, Field(description='How many days back to look', ge=1)] = 7,
        where: Annotated[str | None, Field(description='Part of a project, repository or note path')] = None,
        characters: Annotated[int, Field(description='Answer length limit in Unicode characters, not tokens', ge=500)] = 8000,
    ) -> str:
        recall = Recall()
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return preface(recall) + render_recent(recall.recent(since, where), characters)

    @server.tool(structured_output=False, description='Search words across all sources at once: Claude and Codex sessions, project memory, notes, commit messages. Words match as case-insensitive substrings, so a stem catches every form. With root, search only that folder (including archived process folders).')
    def search(
        query: Annotated[str, Field(description='Words separated by spaces; a stem catches every form')],
        days: Annotated[int | None, Field(description='Only traces from the last N days', ge=1)] = None,
        where: Annotated[str | None, Field(description='Part of a project, repository or note path')] = None,
        root: Annotated[str | None, Field(description='Search only this folder instead of the configured sources')] = None,
        limit: Annotated[int, Field(description='Findings per source', ge=1)] = 8,
        characters: Annotated[int, Field(description='Answer length limit in Unicode characters, not tokens', ge=500)] = 8000,
    ) -> str:
        recall = Recall()
        words = list(dict.fromkeys(word.casefold() for word in query.split()))
        if not words:
            return 'Empty query: give words separated by spaces.\n'
        if root:
            if not Path(root).is_dir():
                return f'No folder {root}. root must be an existing folder; without root the search covers all sources.\n'
            space = recall.bounds.owner_of(root)
            if space:
                return recall.bounds.refusal(root, space)
            return recall.bounds.notice() + render_search(recall.search_folder(root, words), words, limit, characters)
        since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
        return preface(recall) + render_search(recall.search(words, since, where), words, limit, characters)

    @server.tool(structured_output=False, description='Read a found place: a file path (session, note, memory) with a line number, or repository@revision for a commit.')
    def read(
        path: Annotated[str, Field(description='The path from a read: line, or repository@revision')],
        start: Annotated[int, Field(description='First line', ge=1)] = 1,
        lines: Annotated[int, Field(description='How many lines', ge=1)] = 80,
        characters: Annotated[int, Field(description='Answer length limit in Unicode characters, not tokens', ge=500)] = 6000,
    ) -> str:
        return Recall().read(path, start, lines, characters)

    return server


def main():
    import argparse
    import shutil
    import tempfile

    parser = argparse.ArgumentParser(description='Recall MCP server over stdio. Connect it from an MCP client; --demo needs no source configuration.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='Use a temporary synthetic Git history; no personal sources')
    mode.add_argument('--repo', type=Path, help='Connect operations to this Git repository only')
    parser.add_argument('--selector', default='plugins.select_literal', help='Trusted selector module for --demo or --repo')
    args = parser.parse_args()
    if (args.demo or args.repo is not None) and shutil.which('git') is None:
        parser.error('Git is required for --demo and --repo. Install Git and make it available on PATH.')
    if sys.stdin.isatty():
        print('This is an MCP stdio server. Register this command in your MCP client; see BOOTSTRAP.md. Waiting for client input.', file=sys.stderr)
    if args.demo or args.repo is not None:
        from operation_mcp import create_server as operations
        if args.demo:
            from demo_operations import fixture
            with tempfile.TemporaryDirectory(prefix='recall-demo-') as folder:
                fixture(folder)
                operations(folder, args.selector).run()
        else:
            if not (args.repo.resolve() / '.git').exists():
                parser.error('--repo must name a Git working tree (with .git). Try --demo for a synthetic example.')
            operations(args.repo, args.selector).run()
    else:
        create_server().run()


if __name__ == '__main__':
    main()
