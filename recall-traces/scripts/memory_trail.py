import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_options import publish_options

def git(root, *args, input=None):
    result = subprocess.run(
        ['git', '-C', str(root), *args], capture_output=True,
        encoding='utf-8', errors='strict', check=True, input=input,
    )
    return result.stdout


def excerpt(text, budget):
    return {'text': text[:budget], 'omitted_characters': max(0, len(text) - budget)}


def query_terms(cue, literal_terms):
    if literal_terms is not None:
        if cue.strip():
            raise ValueError('Use either --cue or repeated --term arguments')
        values = [term.strip() for term in literal_terms]
        if any(not term for term in values):
            raise ValueError('--term must not be empty')
    else:
        values = cue.split()
        if any(term in ('OR', 'AND', 'NOT') for term in values):
            raise ValueError('Boolean syntax is not supported; use --term memory --term память for alternatives')
    return list(dict.fromkeys(term.casefold() for term in values))


def render_overview(result, characters, items='episodes'):
    result = {**result, items: list(result[items]),
              'output_budget': {'characters': characters, 'unit': 'Unicode characters, including JSON formatting'}}
    while True:
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if len(rendered) + 1 <= characters:
            return rendered
        if not result[items]:
            raise ValueError('Character budget cannot hold search scope and coverage; increase --characters')
        result[items].pop()
        result['omitted_candidates'] += 1


def render_trail(result, characters):
    result = copy.deepcopy(result)
    result['output_budget'] = {'characters': characters,
                               'unit': 'Unicode characters, including JSON formatting'}
    excerpts = [result['current']['content']] + [episode['patch'] for episode in result['episodes']]
    while True:
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        excess = len(rendered) + 1 - characters
        if excess <= 0:
            return rendered
        longest = max(excerpts, key=lambda item: len(item['text']))
        removed = min(excess, len(longest['text']))
        if not removed:
            raise ValueError('Character budget cannot hold source references and coverage; increase --characters or reduce --limit')
        longest['text'] = longest['text'][:-removed]
        longest['omitted_characters'] += removed


def history_args(scan, since, until):
    start, end = boundary(since), boundary(until)
    if start and end and start > end:
        raise ValueError('--since must not be later than --until')
    return ['log', f'-{scan}', '--format=%H%x00%cI%x00%s']


def boundary(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if len(value) == 10:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        raise ValueError('Use an ISO date (UTC midnight) or a timestamp with an explicit timezone')
    return parsed


def in_period(date, since, until):
    observed, start, end = boundary(date), boundary(since), boundary(until)
    return (start is None or observed >= start) and (end is None or observed <= end)


def backlinks(root, source, scope='process', limit=4):
    if limit < 1:
        raise ValueError('Require limit >= 1')
    root = Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve()
    relative = (root / source).resolve().relative_to(root).as_posix()
    search_scope = (root / scope).resolve().relative_to(root).as_posix()
    revision = git(root, 'rev-parse', 'HEAD').strip()
    terms = list(dict.fromkeys([relative, Path(relative).name]))
    args = ['grep', '-I', '-l', '-z', '-F', '--full-name']
    for term in terms:
        args.extend(['-e', term])
    try:
        matches = git(root, *args, revision, '--', ':(literal)' + search_scope)
    except subprocess.CalledProcessError as error:
        if error.returncode != 1:
            raise
        matches = ''
    paths = [ref.split(':', 1)[1] for ref in matches.split('\0') if ref]
    paths = [path for path in paths if path != relative]
    return {
        'mode': 'filename_mentions', 'source': relative, 'repository_head': revision,
        'scope': {'path': search_scope, 'time_basis': 'Committed HEAD snapshot, not activity time'},
        'query': {'match': 'any_literal_substring', 'terms': terms},
        'limits': ['These are textual filename mentions, not verified semantic links or supersession.',
                   'Basename matches may refer to another file with the same name.',
                   'Uncommitted files, binary files and other history versions were not searched.'],
        'candidate_count': len(paths), 'omitted_candidates': max(0, len(paths) - limit),
        'links': [{'source': path, 'ref': revision + ':' + path} for path in paths[:limit]],
    }


def changed_paths(root, revisions, pathspec):
    if not revisions:
        return {}
    output = git(root, 'diff-tree', '--stdin', '--root', '--name-only', '--no-renames',
                 '-r', '-z', '--format=%x00%H', '--', pathspec,
                 input='\n'.join(revisions) + '\n')
    changes = {}
    for record in output.removeprefix('\0').split('\0\0'):
        revision, separator, paths = record.partition('\0\n')
        if separator:
            changes[revision] = paths.removesuffix('\0').split('\0') if paths else []
    return changes


def discover(root, scope='process', cue='', limit=4, scan=80, since=None, until=None, literal_terms=None):
    if limit < 1 or scan < 1:
        raise ValueError('Require limit >= 1 and scan >= 1')
    terms = query_terms(cue, literal_terms)
    root = Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve()
    relative = (root / scope).resolve().relative_to(root).as_posix()
    pathspec = ':(literal)' + relative
    history = git(root, *history_args(scan, since, until), '--', pathspec)
    records = [record.split('\0', 2) for record in history.splitlines()]
    selected = [record for record in records if in_period(record[1], since, until)]
    paths_by_revision = changed_paths(root, [record[0] for record in selected], pathspec)
    candidates = []
    inspected = len(records)
    for revision, date, subject in selected:
        paths = paths_by_revision.get(revision, [])
        sources = []
        title_match = any(term in subject.casefold() for term in terms)
        for path in filter(None, paths):
            path_match = any(term in path.casefold() for term in terms)
            if terms and not (title_match or path_match):
                continue
            sources.append({
                'source': path,
                'match_basis': 'path' if path_match else 'commit_subject' if terms else 'period',
            })
        if sources:
            candidates.append({'revision': revision, 'committed_at': date,
                               'commit_subject': subject, 'sources': sources})
    drilldown = [sys.executable, str(Path(__file__).resolve()), '{source}', '--repo', str(root)]
    if since:
        drilldown.extend(['--since', since])
    if until:
        drilldown.extend(['--until', until])
    return {
        'mode': 'commit_overview', 'query': {'match': 'any_literal_substring', 'terms': terms},
        'scope': {'path': relative, 'since': since, 'until': until,
                  'time_basis': 'Git commit time, not time an activity occurred',
                  'scan_limit': scan, 'commits_inspected': inspected},
        'selection': 'Any normalized term in commit subjects or changed paths; newest matching commit first.',
        'limits': ['File bodies, uncommitted work and non-Git sources were not searched.',
                   'An episode here is one Git commit, not an inferred activity or domain.',
                   'The scan limit applies before the period filter; older matching commits can remain unexamined.',
                   'Merge-only changes are not enumerated by this source adapter.',
                   'A commit-subject match can nominate unrelated files changed in the same commit.',
                   'No match means no candidate in this search, not no personal experience.'],
        'candidate_count': len(candidates),
        'omitted_candidates': max(0, len(candidates) - limit),
        'drilldown_argv_template': drilldown,
        'episodes': candidates[:limit],
    }


def recall(root, source, cue='', limit=4, scan=80, characters=16000, since=None, until=None, literal_terms=None):
    if limit < 1 or scan < limit or characters < 1:
        raise ValueError('Require limit >= 1, scan >= limit, characters >= 1')
    terms = query_terms(cue, literal_terms)
    root = Path(git(root, 'rev-parse', '--show-toplevel').strip()).resolve()
    target = (root / source).resolve()
    relative = target.relative_to(root).as_posix()
    pathspec = ':(literal)' + relative
    history = git(root, *history_args(scan, since, until), '--', pathspec)
    episodes = []
    inspected = 0
    for record in history.splitlines():
        revision, date, subject = record.split('\0', 2)
        inspected += 1
        if not in_period(date, since, until):
            continue
        patch = git(root, 'show', '--format=', '--no-ext-diff', '--no-textconv',
                    '--no-renames', '--unified=1', revision, '--', pathspec)
        searchable = (subject + '\n' + patch).casefold()
        if terms and not any(term in searchable for term in terms):
            continue
        parents = git(root, 'rev-list', '--parents', '-n', '1', revision).strip().split()[1:]
        episodes.append({
            'revision': revision, 'committed_at': date, 'commit_subject': subject,
            'before_refs': [parent + ':' + relative for parent in parents],
            'after_ref': revision + ':' + relative, 'patch': patch,
        })
        if len(episodes) == limit:
            break
    head = git(root, 'rev-parse', 'HEAD').strip()
    if target.is_file():
        raw = target.read_bytes()
        current = {'exists': True, 'sha256': hashlib.sha256(raw).hexdigest(),
                   'content': raw.decode('utf-8-sig')}
    else:
        current = {'exists': False, 'content': ''}
    budget = characters // (len(episodes) + 1)
    current['content'] = excerpt(current['content'], budget)
    for episode in episodes:
        episode['patch'] = excerpt(episode['patch'], budget)
    return {
        'source': relative, 'repository_head': head,
        'query': {'match': 'any_literal_substring', 'terms': terms},
        'selection': 'Newest matching commits; any normalized term in subject or patch.',
        'scope': {'history_scan_limit': scan, 'commits_inspected': inspected,
                  'episode_limit': limit,
                  'since': since, 'until': until, 'time_basis': 'Git commit time'},
        'limits': ['One path only; history before renames is not followed.',
                   'Content is clipped from the beginning; omitted-character counts mark incomplete excerpts.',
                   'Version references can name an absent file before creation or after deletion.',
                   'Commit subjects are author statements; patches establish edits, not execution or correctness.',
                   'Current content is the working file, possibly uncommitted. No semantic supersession is inferred.',
                   'Date filters apply to history; the current working file is outside that historical interval.',
                   'The scan limit applies before the period filter; date-only boundaries are UTC midnight, inclusive.',
                   'Empty results do not establish absence outside the scanned history.'],
        'current': current, 'episodes': episodes,
    }


def main():
    parser = argparse.ArgumentParser(
        description='Find Git source candidates, file history or filename mentions within an output budget.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Choosing an operation:
  Known file, current contents needed: ordinary file reading may suffice.
  Unknown source: omit source; use --scope and literal --term alternatives.
  Changes over time: supply source; optionally narrow by --since / --until.
  Other records mentioning a file: supply source with --backlinks.

Recall planning (caller judgment, not implemented by this CLI):
  What do you want to try, and what missing experience could help?
  Similarity may concern an obstacle or method; matching here is only literal.
  A useful episode can suggest a connection while differing in crucial ways.
  Stop when the current need is met or the search effort budget is exhausted.
  Preserve unresolved uncertainty and the scope searched in either case.''')
    publish_options(parser)
    parser.add_argument('source', nargs='?', help='Path relative to repository root; omit for source overview')
    parser.add_argument('--scope', default='process', help='Repository-relative search scope for overview')
    parser.add_argument('--backlinks', action='store_true',
                        help='Find committed filename mentions of source within --scope; snapshot search, no date filters')
    parser.add_argument('--since')
    parser.add_argument('--until')
    query = parser.add_mutually_exclusive_group()
    query.add_argument('--term', action='append', help='One literal substring; repeat for alternatives, e.g. --term memory --term память')
    query.add_argument('--cue', default='', help='Legacy whitespace-separated words; Boolean operators rejected')
    parser.add_argument('--repo', default='.')
    parser.add_argument('--limit', type=int, default=4)
    parser.add_argument('--scan', type=int, default=80)
    parser.add_argument('--characters', type=int, default=16000,
                        help='Total output Unicode characters, including JSON and final newline (not tokens)')
    args = parser.parse_args()
    try:
        if args.backlinks:
            if not args.source or args.since or args.until or args.cue or args.term:
                raise ValueError('--backlinks requires a source and does not accept dates or query terms')
            result = backlinks(args.repo, args.source, args.scope, args.limit)
        elif args.source:
            result = recall(args.repo, args.source, args.cue, args.limit, args.scan,
                            args.characters, args.since, args.until, args.term)
        else:
            result = discover(args.repo, args.scope, args.cue, args.limit, args.scan,
                              args.since, args.until, args.term)
        if args.backlinks:
            rendered = render_overview(result, args.characters, 'links')
        else:
            rendered = (render_trail(result, args.characters) if args.source
                        else render_overview(result, args.characters))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')
    sys.stdout.reconfigure(newline='\n')
    print(rendered)


if __name__ == '__main__':
    main()
