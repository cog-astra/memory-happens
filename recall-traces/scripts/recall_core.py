import importlib
import importlib.util
import itertools
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import recall_archive
from recall_ranking import relevance

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


def excluded(path, roots):
    path = os.path.normcase(os.path.abspath(str(path)))
    return any(path == root or path.startswith(root.rstrip(os.sep) + os.sep)
               for root in (os.path.normcase(os.path.abspath(str(root))) for root in roots))


def mentions(text, where):
    return not where or where.replace('\\', '/').casefold() in str(text).replace('\\', '/').casefold()


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
    opt_in = False
    cost = 5
    deadline = None
    stopped = None

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def newest(self, items, path_of=lambda item: item):
        stamped = sorted(((modified(path_of(item)), item) for item in items), key=lambda pair: pair[0], reverse=True)
        for when, item in stamped:
            if self.expired():
                self.stopped = f'files last changed on or before {when.astimezone():%Y-%m-%d}'
                return
            yield item

    def covers(self, where):
        return False

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
    def __init__(self, cfg=None):
        self.cfg = cfg if cfg is not None else load_config()
        self.plugins = load_plugins(self.cfg)
        self.skipped = []
        self.unfinished = []

    def recent(self, since, where=None):
        found = [{**trace, 'source': plugin.name}
                 for plugin in self.plugins for trace in plugin.recent(since)
                 if trace['time'] >= since and mentions(trace['where'], where)]
        return sorted(found, key=lambda trace: trace['time'], reverse=True)

    def search(self, words, since=None, where=None):
        return self.search_with_scope(words, since, where)[0]

    def search_with_scope(self, words, since=None, where=None, opt_in=True, budget=None):
        found, outside_where = {}, []
        self.skipped, self.unfinished = [], []
        deadline = None if budget is None else time.monotonic() + budget
        order = self.plugins if budget is None else sorted(self.plugins, key=lambda plugin: getattr(plugin, 'cost', 5))
        for plugin in order:
            hits, outside = [], 0
            if plugin.opt_in and not (opt_in or plugin.covers(where)):
                self.skipped.append(plugin.title)
                continue
            if deadline is not None and time.monotonic() >= deadline:
                self.unfinished.append((plugin.title, 'not started'))
                found[plugin.title] = []
                continue
            plugin.deadline, plugin.stopped = deadline, None
            if plugin.opt_in:
                stream = plugin.search(words, since, where)
            else:
                stream = plugin.search(words, since)
            for hit in stream:
                if since and hit['time'] < since:
                    continue
                if mentions(hit['where'], where):
                    hits.append(hit)
                else:
                    outside += 1
            hits.sort(key=lambda hit: relevance(hit['matched'], hit['total'], hit['time'], hit.get('excerpt', '')), reverse=True)
            found[plugin.title] = hits
            if getattr(plugin, 'stopped', None):
                self.unfinished.append((plugin.title, plugin.stopped))
            if outside:
                outside_where.append((plugin.title, outside))
        return [(plugin.title, found[plugin.title]) for plugin in self.plugins if plugin.title in found], outside_where

    def search_folder(self, root, words, patterns=('*.md', '*.txt', '*.json')):
        from plugins.notes import Plugin as Folder
        folder = Folder({'roots': [str(path) for path in recall_archive.search_roots(root)], 'patterns': list(patterns)})
        folder.title = f'folder {root}'
        hits = list(folder.search(words, None))
        hits.sort(key=lambda hit: relevance(hit['matched'], hit['total'], hit['time'], hit.get('excerpt', '')), reverse=True)
        return [(folder.title, hits)]

    def health(self, now=None):
        now = now or datetime.now(timezone.utc)
        return [warning for plugin in self.plugins for warning in plugin.health(now)]

    def read(self, target, start=1, lines=80, characters=6000):
        target, _, given = target.removeprefix('read: ').partition(' start=')
        start = int(given) if given.isdigit() else start
        for plugin in self.plugins:
            text = plugin.read(target, start, lines, characters)
            if text is not None:
                return text
        if not recall_archive.resolve(target).is_file():
            return (f'No file {target}. Addresses come from the read: lines of recent or search '
                    f'(a file path or repository@revision); for groups, the root from the group header plus the path.\n')
        return read_file(target, start, lines, characters)
