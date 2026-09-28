import importlib
import importlib.util
import itertools
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import recall_archive
from recall_bounds import Bounds

CONFIG = Path(os.environ.get('RECALL_CONFIG') or Path(__file__).with_name('sources.json'))
REPO_REV = re.compile(r'^(.*)@([0-9a-fA-F]{6,40})$')


def expand(value):
    if isinstance(value, str) and value.startswith('~'):
        return os.path.expanduser(value)
    if isinstance(value, list):
        return [expand(item) for item in value]
    if isinstance(value, dict):
        return {key: expand(item) for key, item in value.items()}
    return value


def load_config(path=CONFIG):
    return expand(json.loads(Path(path).read_text(encoding='utf-8')))


def modified(path):
    return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc)


def mentions(text, where):
    return not where or where.casefold() in str(text).casefold()


def scan(path, words, stamp=None):
    groups, said = {}, None
    with Path(path).open(encoding='utf-8', errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            moment = stamp(line) if stamp else None
            if moment:
                said = moment
                continue
            folded = line.casefold()
            present = [word for word in words if word in folded]
            if not present:
                continue
            day = said.astimezone().date() if stamp and said else None
            group = groups.setdefault(day, {'matched': set(), 'total': 0, 'lines': 0, 'places': [], 'best': (0, '', 0, None)})
            group['matched'].update(present)
            group['total'] += sum(folded.count(word) for word in present)
            group['lines'] += 1
            if len(group['places']) < 5:
                group['places'].append(number)
            if len(present) > group['best'][0]:
                group['best'] = (len(present), line.strip(), number, said)
    return [{'matched': [word for word in words if word in group['matched']], 'total': group['total'],
             'lines': group['lines'], 'places': group['places'], 'excerpt': group['best'][1], 'line': group['best'][2],
             'said': group['best'][3]} for group in groups.values()]


class Source:
    title = ''

    def __init__(self, options):
        self.options = options

    def recent(self, since):
        return []

    def search(self, words, since):
        return []

    def health(self, now):
        return []

    def bound_of(self, target):
        return None

    def read(self, target, start, lines, characters):
        return None


def load_plugins(cfg):
    plugins = []
    for entry in cfg.get('sources', []):
        name = entry['plugin']
        if name.endswith('.py'):
            spec = importlib.util.spec_from_file_location(Path(name).stem, name)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        else:
            module = importlib.import_module(f'plugins.{name}')
        plugin = module.Plugin(entry)
        plugin.name = getattr(plugin, 'name', Path(name).stem)
        plugins.append(plugin)
    return plugins


def read_file(path, start, lines, characters):
    target = recall_archive.resolve(path)
    with target.open(encoding='utf-8-sig', errors='replace') as stream:
        window = list(itertools.islice(stream, start - 1, start - 1 + lines + 1))
    output, used = [], 0
    for number, text in enumerate(window[:lines], start):
        entry = f"{number}: {text.rstrip()}\n"
        if used + len(entry) > characters:
            return ''.join(output) + f"[more: start={number}]\n"
        output.append(entry)
        used += len(entry)
    if len(window) > lines:
        output.append(f"[more: start={start + lines}]\n")
    return ''.join(output) or '[past the end of the file]\n'


class Recall:
    def __init__(self, cfg=None, reader=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.plugins = load_plugins(self.cfg)
        self.bounds = Bounds(self.cfg.get('spaces', []), reader)

    def space_of(self, bound):
        if 'files' in bound:
            if not bound['files']:
                return self.bounds.owner_of(bound['repo'])
            return next((space for path in bound['files'] if (space := self.bounds.owner_of(path))), None)
        if 'project' in bound:
            return self.bounds.owner_of_project(bound['project'])
        return self.bounds.owner_of(bound.get('path'))

    def visible(self, bound):
        return self.space_of(bound) is None

    def recent(self, since, where=None):
        found = [{**trace, 'source': plugin.name}
                 for plugin in self.plugins for trace in plugin.recent(since)
                 if trace['time'] >= since and mentions(trace['where'], where) and self.visible(trace['bound'])]
        return sorted(found, key=lambda trace: trace['time'], reverse=True)

    def search(self, words, since=None, where=None):
        found = []
        for plugin in self.plugins:
            hits = [hit for hit in plugin.search(words, since)
                    if (not since or hit['time'] >= since) and mentions(hit['where'], where) and self.visible(hit['bound'])]
            hits.sort(key=lambda hit: (len(hit['matched']), hit['total'], hit['time']), reverse=True)
            found.append((plugin.title, hits))
        return found

    def search_folder(self, root, words, patterns=('*.md', '*.txt', '*.json')):
        from plugins.notes import Plugin as Folder
        folder = Folder({'roots': [str(path) for path in recall_archive.search_roots(root)], 'patterns': list(patterns)})
        folder.title = f'folder {root}'
        hits = [hit for hit in folder.search(words, None) if self.visible(hit['bound'])]
        hits.sort(key=lambda hit: (len(hit['matched']), hit['total'], hit['time']), reverse=True)
        return [(folder.title, hits)]

    def health(self, now=None):
        now = now or datetime.now(timezone.utc)
        return [warning for plugin in self.plugins for warning in plugin.health(now)]

    def read(self, target, start=1, lines=80, characters=6000):
        target, _, given = target.removeprefix('read: ').partition(' start=')
        start = int(given) if given.isdigit() else start
        space = self.bounds.owner_of(target) if Path(target).is_file() else None
        if space:
            return self.bounds.refusal(target, space)
        bound = next((b for plugin in self.plugins if (b := plugin.bound_of(target)) is not None), {'path': target})
        space = self.space_of(bound)
        if space:
            return self.bounds.refusal(target, space)
        for plugin in self.plugins:
            text = plugin.read(target, start, lines, characters)
            if text is not None:
                return text
        if not recall_archive.resolve(target).is_file():
            return (f'No file {target}. Addresses come from the read: lines of recent or search '
                    f'(a file path or repository@revision); for groups, the root from the group header plus the path.\n')
        return read_file(target, start, lines, characters)
