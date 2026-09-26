from datetime import datetime, timezone
from pathlib import Path

from plugins.git_operations import Plugin as Reader
from recall_core import REPO_REV, Source
from recall_operations import Context
from recall_runner import Runner


class Plugin(Source):
    title = 'git'

    def __init__(self, options):
        super().__init__(options)
        self.reader = Reader(options.get('source', 'git'), options['repo'])
        self.runner = Runner({'git': self.reader})

    def records(self, operation, parameters):
        for event in self.runner.invoke('git', operation, parameters):
            if event['type'] == 'record':
                yield event['record']
            elif event['outcome']['status'] != 'success':
                raise RuntimeError(f'Incomplete legacy view: {event["outcome"]["code"]}')

    def recent(self, since):
        repo = self.reader.repo
        for record in self.records('history', {'limit': None}):
            moment = datetime.fromisoformat(record['context']['commit_authored_at'])
            if moment >= since:
                yield {'time': moment, 'where': str(repo), 'group': f'git · {repo.as_posix()}',
                       'bound': {'repo': repo, 'files': [Path(path) for path in record['access'] if path != repo.as_posix()]},
                       'headline': record['text'].splitlines()[0],
                       'locator': f'{repo.as_posix()}@{record["evidence"][0]["locator"]}'}

    def search(self, words, since):
        for trace in self.recent(since or datetime.min.replace(tzinfo=timezone.utc)):
            matched = [word for word in words if word.casefold() in trace['headline'].casefold()]
            if matched:
                yield {**trace, 'excerpt': trace['headline'], 'label': trace['where'],
                       'matched': matched, 'total': len(matched), 'places': []}

    def reference(self, target):
        match = REPO_REV.match(target)
        if match and Path(match[1]).resolve() == self.reader.repo and len(match[2]) in (40, 64):
            return {'source': self.reader.source, 'locator': match[2], 'revision': match[2]}
        return None

    def bound_of(self, target):
        reference = self.reference(target)
        if reference is None:
            return None
        context = Context(lambda resources: True)
        self.reader.require_commit(reference['revision'], context)
        repo = self.reader.repo
        return {'repo': repo, 'files': [Path(path) for path in context.resources if path != repo.as_posix()]}

    def read(self, target, start, lines, characters):
        reference = self.reference(target)
        if reference is None:
            return None
        text = '\n'.join(record['text'] for record in self.records('read', {'evidence': reference}))
        rows = text.splitlines()
        window = '\n'.join(rows[start - 1:start - 1 + lines])
        cut = len(window) > characters or len(rows) >= start + lines
        return window[:characters] + ('\n[partial: increase lines or characters]\n' if cut else '')

    def health(self, now):
        if not (self.reader.repo / '.git').exists():
            return ['Repository unavailable: check the configured repo path.']
        return []
