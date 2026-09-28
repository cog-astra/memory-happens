import itertools
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import Field, model_validator

import recall_archive
from plugins import git as git_source, memory as memory_source, notes as notes_source, sessions as session_source
from recall_bounds import within
from recall_core import REPO_REV, mentions, modified
from recall_operations import AccessDenied, Evidence, Operation, Outcome, Passage, Value
from recall_time import TimeWindow

FOLDER_PATTERNS = ('*.md', '*.txt', '*.json')
EMPTY_QUERY = Outcome(status='failed', code='empty_query', next_steps=['Give words separated by spaces.'])


class Recent(Value):
    days: int = Field(default=7, ge=1)
    where: str | None = None


class During(Value):
    start: str = Field(description='Inclusive ISO timestamp with a timezone offset.')
    end: str = Field(description='Exclusive ISO timestamp with a timezone offset.')
    where: str | None = None

    @model_validator(mode='after')
    def valid_window(self):
        TimeWindow.parse(self.start, self.end)
        return self


class Around(Value):
    time: str = Field(description='Center ISO timestamp with an explicit timezone offset.')
    seconds: int = Field(ge=1, description='Seconds on EACH side of time; 600 means ten minutes before and after.')
    where: str | None = None

    @model_validator(mode='after')
    def valid_window(self):
        TimeWindow.around(self.time, self.seconds)
        return self


class Search(Value):
    query: str = Field(min_length=1)
    days: int | None = Field(default=None, ge=1)
    where: str | None = None
    limit: int | None = Field(default=None, ge=1)


class FolderSearch(Search):
    root: str = Field(min_length=1)


class Read(Value):
    evidence: Evidence
    start: int | None = Field(default=None, ge=1)
    lines: int = Field(default=80, ge=1)


class Passages(Value):
    lines: int = Field(default=40, ge=1)


class Expand(Value):
    before_lines: int = Field(default=20, ge=0)
    after_lines: int = Field(default=20, ge=0)


def iso(moment):
    return moment.isoformat() if moment else None


def since_of(days):
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


def words_of(query):
    return list(dict.fromkeys(word.casefold() for word in query.split()))


def hides_path(bounds, path):
    return bool(path) and (bounds.hides(path) or bounds.hides(Path(path).resolve()))


def hidden(bounds, bound):
    if 'files' in bound:
        if bounds.owner_of(bound['repo']) is None and bounds.owner_of(Path(bound['repo']).resolve()) is None:
            return False
        return not bound['files'] or any(hides_path(bounds, name) for name in bound['files'])
    if 'project' in bound:
        return bounds.hides_project(bound['project'])
    return hides_path(bounds, bound.get('path'))


def ranked(hits, limit):
    hits.sort(key=lambda hit: (len(hit['matched']), hit['total'], hit['time']), reverse=True)
    return hits[:limit] if limit else hits


def read_text(alias, address, target, start, lines, observed):
    now = modified(target).isoformat()
    with target.open(encoding='utf-8-sig', errors='replace') as stream:
        rows = list(itertools.islice(stream, start - 1, start - 1 + lines + 1))
    yield from window(alias, f'{address} start={start}', rows, start, lines, observed=observed, now=now)


def window(alias, locator, rows, start, lines, revision=None, observed=None, now=None):
    shown = rows[:lines]
    if shown:
        yield Passage(text=''.join(shown),
                      evidence=[Evidence(source=alias, locator=locator, revision=revision, observed_at=now)],
                      context={'first_line': start, 'last_line': start + len(shown) - 1,
                               **({'modified_at': now} if now else {})})
    more = len(rows) > lines
    changed = observed is not None and now is not None and observed != now
    yield Outcome(status='success',
                  code='source_changed' if changed else ('' if shown else 'past_end'),
                  message=('The source changed after this evidence was observed.' if changed
                           else '' if shown else 'The start line is past the end of the source.'),
                  continuation={'start': start + lines} if more else None,
                  next_steps=[f'Read with start={start + lines} to continue.'] if more else [])


class Coverage:
    def __init__(self, present, missing, warnings=(), recovery=()):
        self.present, self.missing = present, missing
        self.warnings, self.recovery = list(warnings), list(recovery)
        self.hidden = 0
        self.outside_where = 0

    def outcome(self, kind):
        if not self.present:
            return Outcome(status='unavailable', code='corpus_missing' if kind == 'sessions' else 'source_missing',
                           message='; '.join(f'{path} is missing' for path in self.missing) or 'No roots are configured.',
                           next_steps=self.recovery or ['Check this source in the configuration.'])
        reasons = []
        if self.missing:
            reasons.append(('source_partial', f"missing: {', '.join(map(str, self.missing))}"))
        if self.warnings:
            reasons.append(('stale_archive', '; '.join(self.warnings)))
        if self.hidden:
            reasons.append(('policy_filtered', f'{self.hidden} excluded by the configured access policy'))
        outcome = (Outcome(status='partial', code=reasons[0][0], message='; '.join(text for _, text in reasons) + '.',
                           next_steps=self.recovery if self.missing or self.warnings else [])
                   if reasons else Outcome(status='success'))
        if self.outside_where:
            outcome.message = f'{outcome.message} Matching records outside where: {self.outside_where}.'.strip()
            outcome.next_steps.append('Repeat this source search without where to include them.')
        return outcome


class Sessions:
    kind = 'sessions'

    def __init__(self, options):
        self.legacy = session_source.Plugin(options)

    def roots(self):
        return [Path(store['corpus']) for store in self.legacy.stores]

    def coverage(self, now):
        stores = [store for store in self.legacy.stores if Path(store['corpus']).is_dir()]
        warnings = session_source.Plugin({**self.legacy.options, 'stores': stores}).health(now)
        recovery = [f"Refresh the archive: python {session_source.SCRIPTS / store['archiver']}"
                    for store in self.legacy.stores if store.get('archiver')]
        return Coverage([Path(store['corpus']) for store in stores],
                        [root for root in self.roots() if not root.is_dir()], warnings, recovery)

    def during(self, window):
        for trace in self.legacy.during(window):
            path = Path(trace['locator'].split(' start=')[0])
            yield trace, path, '\n'.join([trace['headline'], *trace['quotes']]), {
                'event_time': iso(trace['time']), 'day_start': iso(trace['start']), 'project': trace['where'],
                'automated': trace['automated'], 'untitled': trace['untitled'], 'topics': trace['topics']}

    def search(self, words, since):
        for hit in self.legacy.search(words, since):
            yield hit, Path(hit['locator'].split(' start=')[0]), {
                'event_time' if hit['said'] else 'modified_at': iso(hit['time'])}

    def files(self):
        for path in sorted(set(self.legacy.paths())):
            bound = self.bound(path)
            yield path, bound, {'project': bound['path']}

    def owns(self, path, target):
        return target.suffix == '.md' and any(within(path, root) or within(target, root.resolve()) for root in self.roots())

    def bound(self, target):
        return {'path': session_source.header(target).get('project')}


class Memory:
    kind = 'memory'

    def __init__(self, options):
        self.legacy = memory_source.Plugin(options)

    def roots(self):
        return [Path(root) for root in self.legacy.options.get('roots', [])]

    def coverage(self, now):
        roots = self.roots()
        return Coverage([r for r in roots if r.is_dir()], [r for r in roots if not r.is_dir()])

    def during(self, window):
        for trace in self.legacy.during(window):
            yield trace, Path(trace['locator']), trace['headline'], {
                'modified_at': iso(trace['time']), 'project': trace['where'], 'group': trace['group']}

    def search(self, words, since):
        for hit in self.legacy.search(words, since):
            yield hit, Path(hit['locator'].split(' start=')[0]), {'modified_at': iso(hit['time'])}

    def owns(self, path, target):
        return target.parent.name == 'memory' and any(within(target, root.resolve()) for root in self.roots())

    def bound(self, target):
        return {'project': target.parent.parent.name}


class Notes:
    kind = 'notes'

    def __init__(self, options):
        self.legacy = notes_source.Plugin(options)

    def roots(self):
        return [Path(root) for root in self.legacy.options.get('roots', [])]

    def coverage(self, now):
        roots = self.roots()
        return Coverage([r for r in roots if r.is_dir()], [r for r in roots if not r.is_dir()])

    def during(self, window):
        for trace in self.legacy.during(window):
            yield trace, Path(trace['locator']), trace['headline'], {
                'modified_at': iso(trace['time']), 'group': trace['group']}

    def search(self, words, since):
        for hit in self.legacy.search(words, since):
            yield hit, Path(hit['locator'].split(' start=')[0]), {'modified_at': iso(hit['time'])}

    def files(self):
        for path in sorted({path for _, path in self.legacy.paths()}):
            yield path, self.bound(path), {}

    def owns(self, path, target):
        for root in self.roots():
            if within(target, root.resolve()):
                relative = target.relative_to(root.resolve())
                return not any(part.startswith('.') for part in relative.parts) and any(
                    target.match(pattern) for pattern in self.legacy.options.get('patterns', ['*.md']))
        return False

    def bound(self, target):
        return {'path': target}


class Git:
    kind = 'git'

    def __init__(self, options):
        self.options = options

    def roots(self):
        return [Path(root) for root in [*self.options.get('discover', []), *self.options.get('repos', [])]]

    def coverage(self, now):
        discover = [Path(root) for root in self.options.get('discover', [])]
        repos = [Path(repo) for repo in self.options.get('repos', [])]
        present = [r for r in discover if r.is_dir()] + [r for r in repos if (r / '.git').exists()]
        missing = [r for r in discover if not r.is_dir()] + [r for r in repos if not (r / '.git').exists()]
        return Coverage(present, missing)

    def commits(self, since, words=()):
        found = [repo for repo in git_source.repos(self.options) if git_source.active(repo, since)]
        yield from git_source.across(found, lambda repo: git_source.commits(repo, since, words, full=True))

    def during(self, window):
        found = git_source.repos(self.options)
        for repo, commit in git_source.across(found, lambda repo: git_source.commits(repo, full=True, window=window)):
            trace = {'time': commit['time'], 'where': str(repo), 'bound': commit['bound'],
                     'locator': f"{repo.as_posix()}@{commit['rev']}"}
            yield trace, None, commit['subject'], {
                'event_time': iso(commit['time']), 'repository': repo.as_posix(), 'revision': commit['rev']}

    def search(self, words, since):
        for repo, commit in self.commits(since, words):
            folded = commit['subject'].casefold()
            hit = {'time': commit['time'], 'where': str(repo), 'bound': commit['bound'],
                   'matched': [word for word in words if word in folded], 'total': 1, 'places': [],
                   'excerpt': commit['subject'], 'label': repo.as_posix(),
                   'locator': f"{repo.as_posix()}@{commit['rev']}"}
            yield hit, None, {'event_time': iso(commit['time']), 'repository': repo.as_posix(), 'revision': commit['rev']}

    def repository(self, locator):
        match = REPO_REV.match(locator)
        if not match:
            return None, None
        repo = Path(match[1]).resolve()
        known = {Path(found).resolve() for found in git_source.repos(self.options)}
        return (repo, match[2]) if repo in known else (None, None)


KINDS = {kind.kind: kind for kind in (Sessions, Memory, Notes, Git)}


class Places:
    def __init__(self, bounds, entries):
        """entries are all configured sources: a file one of them owns is judged by that owner's bound too."""
        self.bounds = bounds
        self.owners = [KINDS[entry['plugin']](entry) for entry in entries
                       if entry.get('plugin') in ('sessions', 'memory', 'notes')]

    def hidden(self, bound=None, path=None):
        if bound and hidden(self.bounds, bound):
            return True
        if path is None:
            return False
        target = recall_archive.resolve(path)
        return hides_path(self.bounds, path) or hides_path(self.bounds, target) or any(
            owner.owns(Path(path), target) and target.is_file() and hidden(self.bounds, owner.bound(target))
            for owner in self.owners)


class Plugin:
    def __init__(self, alias, options, places):
        self.alias, self.options, self.places = alias, options, places
        self.bounds = places.bounds
        self.kind = options.get('plugin')
        self.source = KINDS[self.kind](options) if self.kind in KINDS else None

    def catalog(self):
        operations = [Operation('during', 'Traces in [start, end), newest first. Sessions use message time, Git author time, notes/memory modification time.', During),
                      Operation('around', 'Same as during(time - seconds, time + seconds); lower bound included, upper excluded.', Around),
                      Operation('recent', 'A time window ending now, starting days ago.', Recent),
                      Operation('search', 'Places where the query words occur, best matches first.', Search),
                      Operation('read', 'Read the place identified by evidence, with a continuation.', Read),
                      Operation('health', 'Warnings about missing or stale parts of this source.')]
        if self.kind in ('notes', 'sessions'):
            operations.append(Operation('passages', 'Read all accessible text in line windows before selection.', Passages))
        if self.kind in ('notes', 'sessions', 'memory'):
            operations.append(Operation('expand', 'Read a line neighborhood around each anchor locator; keep anchors separate.',
                                        Expand, inputs=('anchors',)))
        return operations

    def evidence(self, locator, path, revision=None):
        return Evidence(source=self.alias, locator=locator, revision=revision,
                        observed_at=iso(modified(path)) if path is not None else None)

    def invoke(self, operation, parameters, inputs, context):
        if self.source is None:
            yield Outcome(status='unsupported', code='unknown_source_type',
                          message=f"No operation adapter for source type {self.kind!r}.")
            return
        coverage = self.source.coverage(datetime.now(timezone.utc))
        if operation == 'health':
            for warning in [*[f'{path} is missing' for path in coverage.missing], *coverage.warnings]:
                yield Passage(text=warning, context={'source_type': self.kind})
            yield Outcome(status='success' if coverage.present else 'unavailable',
                          code='' if coverage.present else 'source_missing', next_steps=coverage.recovery)
            return
        if operation == 'read':
            yield from self.read(parameters, context)
            return
        if operation == 'expand':
            yield from self.expand(parameters, inputs['anchors'], context)
            return
        if not coverage.present:
            yield coverage.outcome(self.kind)
            return
        closed = [root.resolve() for root in coverage.present if hides_path(self.bounds, root)]
        context.require(*sorted({root.resolve().as_posix() for root in coverage.present if root.resolve() not in closed}))

        def resources_for(bound, path):
            if self.places.hidden(bound, path):
                return None
            place = Path(bound['repo']) if 'files' in bound else path
            if place is not None and any(within(place, root) for root in closed):
                return ([Path(name).resolve().as_posix() for name in bound['files']] if 'files' in bound
                        else [Path(path).resolve().as_posix()])
            return []

        def admit(bound, path):
            resources = resources_for(bound, path)
            if resources is None:
                coverage.hidden += 1
                return False
            if resources:
                context.require(*resources)
            return True

        if operation == 'passages':
            for path, bound, extra in self.source.files():
                if not admit(bound, path):
                    continue
                observed = iso(modified(path))
                with path.open(encoding='utf-8-sig', errors='replace') as stream:
                    start = 1
                    while rows := list(itertools.islice(stream, parameters['lines'])):
                        yield Passage(text=''.join(rows),
                                      evidence=[Evidence(source=self.alias, locator=f'{path} start={start}',
                                                         observed_at=observed)],
                                      context={'first_line': start, 'last_line': start + len(rows) - 1,
                                               'modified_at': observed, **extra})
                        start += len(rows)
        elif operation in ('recent', 'during', 'around'):
            interval = (TimeWindow.past(parameters['days']) if operation == 'recent' else
                        TimeWindow.around(parameters['time'], parameters['seconds']) if operation == 'around' else
                        TimeWindow.parse(parameters['start'], parameters['end']))
            found = []
            for trace, path, text, extra in self.source.during(interval):
                if not mentions(trace['where'], parameters['where']):
                    continue
                if not admit(trace['bound'], path):
                    continue
                found.append((trace['time'], Passage(
                    text=text, evidence=[self.evidence(trace['locator'], path, extra.get('revision'))],
                    context={'matched': [], 'total': 0, **extra})))
            for _, item in sorted(found, key=lambda pair: pair[0], reverse=True):
                yield item
        else:
            words = words_of(parameters['query'])
            if not words:
                yield EMPTY_QUERY
                return
            since = since_of(parameters['days'])
            hits = []
            for hit, path, extra in self.source.search(words, since):
                if since and hit['time'] < since:
                    continue
                if not mentions(hit['where'], parameters['where']):
                    resources = resources_for(hit['bound'], path)
                    if resources is not None and context.policy(tuple(sorted(context.resources.union(resources)))):
                        coverage.outside_where += 1
                    continue
                if not admit(hit['bound'], path):
                    continue
                hits.append({**hit, 'path': path, 'extra': extra})
            for hit in ranked(hits, parameters['limit']):
                yield hit_passage(self.evidence(hit['locator'], hit['path'], hit['extra'].get('revision')), hit)
        yield coverage.outcome(self.kind)

    def expand(self, parameters, anchors, context):
        windows = []
        for anchor in anchors:
            if len(anchor.evidence) != 1 or anchor.evidence[0].source != self.alias:
                yield Outcome(status='unsupported', code='incompatible_anchor', message=f'Anchor {anchor.id} needs one evidence from {self.alias}.')
                return
            evidence = anchor.evidence[0]
            _, separator, line = evidence.locator.partition(' start=')
            if not separator or re.fullmatch(r'[1-9][0-9]*', line) is None or self.kind == 'git':
                yield Outcome(status='unsupported', code='line_anchor_required', message=f'Anchor {anchor.id} needs a positive start= line.')
                return
            center = int(line)
            start = max(1, center - parameters['before_lines'])
            windows.append((anchor, evidence, center, start))
        changed, empty, continuation = [], [], []
        for anchor, evidence, center, start in windows:
            if context.cancelled.is_set():
                yield Outcome(status='cancelled')
                return
            events = list(self.read({'evidence': evidence.model_dump(), 'start': start,
                                     'lines': center + parameters['after_lines'] - start + 1}, context))
            outcome = events[-1]
            if outcome.status not in ('success', 'partial'):
                yield outcome.model_copy(update={'message': f'Anchor {anchor.id}: {outcome.message or outcome.code}'})
                return
            if len(events) == 1:
                empty.append(anchor.id)
            if outcome.code == 'source_changed':
                changed.append(anchor.id)
            if outcome.continuation:
                continuation.append({'anchor_id': anchor.id, 'evidence': evidence.model_dump(), **outcome.continuation})
            for item in events[:-1]:
                item.context['expansion'] = {'anchor_id': anchor.id, 'anchor': evidence.model_dump(),
                                             'line': center, 'read_outcome': outcome.model_dump()}
                yield item
        messages = []
        if empty:
            messages.append(f'No lines for anchors: {", ".join(empty)}.')
        if changed:
            messages.append(f'source_changed for anchors: {", ".join(changed)}.')
        yield Outcome(status='partial' if empty else 'success',
                      code='empty_expansions' if empty else 'source_changed' if changed else '',
                      message=' '.join(messages),
                      continuation={'anchors': continuation} if continuation else None,
                      next_steps=['Continue individual windows with read using continuation.anchors.'] if continuation else [])

    def read(self, parameters, context):
        evidence = Evidence.model_validate(parameters['evidence'])
        if evidence.source != self.alias:
            yield Outcome(status='unsupported', code='incompatible_evidence')
            return
        if self.kind == 'git':
            yield from self.read_commit(evidence, parameters, context)
            return
        address, _, given = evidence.locator.partition(' start=')
        start = parameters['start'] or (int(given) if given.isdigit() else 1)
        path = Path(address)
        target = recall_archive.resolve(path)
        if not self.source.owns(path, target):
            yield Outcome(status='unsupported', code='incompatible_evidence')
            return
        if self.places.hidden(path=path):
            raise AccessDenied('The evidence lies in a closed personal space.')
        if not target.is_file():
            yield Outcome(status='unavailable', code='source_missing', message=f'{address} is missing.')
            return
        if self.places.hidden(self.source.bound(target), path):
            raise AccessDenied('The evidence lies in a closed personal space.')
        context.require(target.as_posix())
        yield from read_text(self.alias, address, target, start, parameters['lines'], evidence.observed_at)

    def read_commit(self, evidence, parameters, context):
        repo, revision = self.source.repository(evidence.locator)
        if repo is None or evidence.revision not in (None, revision):
            yield Outcome(status='unsupported', code='incompatible_evidence')
            return
        files = [repo / name for name in git_source.git(repo, 'show', '--name-only', '--format=', revision).split('\n') if name]
        if self.places.hidden({'repo': repo, 'files': files}):
            raise AccessDenied('The commit lies in a closed personal space.')
        context.require(*([name.resolve().as_posix() for name in files] if hides_path(self.bounds, repo) else [repo.as_posix()]))
        text = git_source.git(repo, 'show', '--stat', '--format=%H%n%aI · %an%n%n%B', revision)
        if not text:
            yield Outcome(status='unavailable', code='revision_missing', message=f'No revision {revision} in {repo}.')
            return
        start = parameters['start'] or 1
        rows = text.splitlines(keepends=True)[start - 1:start - 1 + parameters['lines'] + 1]
        yield from window(self.alias, evidence.locator, rows, start, parameters['lines'], revision=revision)


def hit_passage(evidence, hit):
    return Passage(text=hit['excerpt'], evidence=[evidence], context={
        'matched': hit['matched'], 'total': hit['total'], 'label': hit['label'], 'where': hit['where'],
        'line': hit.get('line'), 'places': hit['places'], **hit['extra']})


class FolderPlugin:
    def __init__(self, alias, places):
        self.alias, self.places = alias, places

    def catalog(self):
        return [Operation('search', 'Places where the query words occur under one folder, including its relocated archives.',
                          FolderSearch),
                Operation('read', 'Read a file place identified by evidence, with a continuation.', Read)]

    def invoke(self, operation, parameters, inputs, context):
        if operation == 'read':
            yield from self.read(parameters, context)
            return
        words, since = words_of(parameters['query']), since_of(parameters['days'])
        if not words:
            yield EMPTY_QUERY
            return
        root = Path(parameters['root'])
        if self.places.hidden(path=root):
            raise AccessDenied('The folder lies in a closed personal space.')
        try:
            roots = recall_archive.search_roots(root)
        except FileNotFoundError as error:
            yield Outcome(status='unavailable', code='root_missing', message=str(error),
                          next_steps=['Give an existing folder, or search the configured sources without root.'])
            return
        context.require(*sorted({path.as_posix() for path in roots}))
        folder = notes_source.Plugin({'roots': [str(path) for path in roots], 'patterns': list(FOLDER_PATTERNS)})
        coverage, hits = Coverage(roots, []), []
        for hit in folder.search(words, since):
            if not mentions(hit['where'], parameters['where']):
                path = Path(hit['locator'].split(' start=')[0])
                if not self.places.hidden(hit['bound'], path):
                    coverage.outside_where += 1
                continue
            path = Path(hit['locator'].split(' start=')[0])
            if self.places.hidden(hit['bound'], path):
                coverage.hidden += 1
                continue
            hits.append({**hit, 'path': path, 'extra': {'modified_at': iso(hit['time'])}})
        for hit in ranked(hits, parameters['limit']):
            yield hit_passage(Evidence(source=self.alias, locator=hit['locator'], observed_at=iso(modified(hit['path']))), hit)
        yield coverage.outcome('folder')

    def read(self, parameters, context):
        evidence = Evidence.model_validate(parameters['evidence'])
        if evidence.source != self.alias:
            yield Outcome(status='unsupported', code='incompatible_evidence')
            return
        address, _, given = evidence.locator.partition(' start=')
        path = Path(address)
        target = recall_archive.resolve(path)
        if self.places.hidden(path=path):
            raise AccessDenied('The evidence lies in a closed personal space.')
        if not target.is_file():
            yield Outcome(status='unavailable', code='source_missing', message=f'{address} is missing.')
            return
        context.require(target.as_posix())
        start = parameters['start'] or (int(given) if given.isdigit() else 1)
        yield from read_text(self.alias, address, target, start, parameters['lines'], evidence.observed_at)
