import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_transcript import TOOL_PREFIX
from recall_core import Source, modified, scan

MESSAGE = re.compile(r'^## (\d{4}-\d{2}-\d{2}T[\d:.]+Z) \[(user|assistant)\] L\d+:B\d+$')
SERVICE_PREFIXES = ('<', '# AGENTS.md', '[Request interrupted')
AUTOMATED_ORIGINS = ('subagent', 'sdk-cli')
STALE = timedelta(hours=1)
SILENT = timedelta(minutes=45)
SCRIPTS = Path(__file__).resolve().parents[1]


def stamp(line):
    match = MESSAGE.match(line.rstrip('\r\n'))
    return datetime.fromisoformat(match[1].replace('Z', '+00:00')) if match else None


def header(path):
    fields = {'agent': None}
    with Path(path).open(encoding='utf-8', errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            if MESSAGE.match(line.rstrip('\r\n')) or number > 12:
                break
            if number == 1 and line.startswith('# '):
                fields['agent'] = line.split()[1].lower()
            elif ': ' in line:
                key, _, value = line.partition(': ')
                fields[key.strip()] = value.strip()
    return fields


def parse(path):
    messages, current = [], None
    with path.open(encoding='utf-8', errors='replace') as stream:
        for number, line in enumerate(stream, 1):
            match = MESSAGE.match(line.rstrip('\r\n'))
            if match:
                current = {'time': datetime.fromisoformat(match[1].replace('Z', '+00:00')),
                           'role': match[2], 'line': number, 'lines': []}
                messages.append(current)
            elif current is not None:
                current['lines'].append(line)
    for message in messages:
        message['text'] = ''.join(message.pop('lines')).strip()
    return messages


def newest(root, pattern):
    return max((modified(path) for path in Path(root).rglob(pattern)), default=None)


def acknowledged_source_change(corpus):
    manifest = corpus.parent / 'manifest.json'
    if not manifest.is_file():
        return None
    entries = json.loads(manifest.read_text(encoding='utf-8'))
    stamps = [entry['source_stamp'][1] for entry in entries.values() if entry.get('source_stamp')]
    return datetime.fromtimestamp(max(stamps) / 1_000_000_000, timezone.utc) if stamps else None


def clip(text, limit=220):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


class Plugin(Source):
    title = 'sessions'

    def __init__(self, options):
        super().__init__(options)
        self.stores = options.get('stores', [])
        self.service = tuple(options.get('service_prefixes', SERVICE_PREFIXES))

    def paths(self, since=None):
        for store in self.stores:
            corpus = Path(store['corpus'])
            if corpus.is_dir():
                for path in corpus.rglob('*.md'):
                    if 'subagents' not in path.parts and not (since and modified(path) < since):
                        yield path

    def human(self, message):
        text = message['text'].lstrip()
        return message['role'] == 'user' and bool(text) and not text.startswith(self.service)

    def recent(self, since):
        for path in self.paths(since):
            fields, messages = header(path), parse(path)
            store = path.with_suffix('.topics.json')
            topics = (json.loads(store.read_text(encoding='utf-8'))
                      if store.is_file() and self.options.get('topics', True) else {})
            days = {}
            for message in messages:
                days.setdefault(message['time'].astimezone().date(), []).append(message)
            for date, day in days.items():
                if day[-1]['time'] >= since:
                    yield self.trace(path, fields, messages[0]['time'], day, topics.get(date.isoformat()))

    def during(self, window):
        for path in self.paths():
            fields, messages = header(path), parse(path)
            store = path.with_suffix('.topics.json')
            topics = (json.loads(store.read_text(encoding='utf-8'))
                      if store.is_file() and self.options.get('topics', True) else {})
            days = {}
            for message in sorted(messages, key=lambda message: message['time']):
                days.setdefault(message['time'].astimezone().date(), []).append(message)
            for date, day in days.items():
                selected = [message for message in day if window.contains(message['time'])]
                if not selected:
                    continue
                topic = topics.get(date.isoformat()) if len(selected) == len(day) else None
                trace = self.trace(path, fields, min(message['time'] for message in messages), selected, topic)
                yield {**trace, 'topics': topic}

    def trace(self, path, fields, opened, day, topics=None):
        humans = [m for m in day if self.human(m)]
        replies = [m for m in day if m['role'] == 'assistant' and m['text'] and not m['text'].startswith(TOOL_PREFIX)]
        project = fields.get('project', '')
        since = f" · open since {opened.astimezone():%Y-%m-%d}" if opened.astimezone().date() < day[0]['time'].astimezone().date() else ''
        quotes = [f"> {clip(humans[0]['text'])}"] if humans else []
        if len(humans) > 1:
            quotes.append(f"> {clip(humans[-1]['text'])}")
        if replies:
            quotes.append(f"< {clip(replies[-1]['text'])}")
        if topics and topics.get('topics'):
            listed = '; '.join(f"{topic['text']} L{topic['lines'][0]}" for topic in topics['topics'])
            quotes.insert(0, f"topics ({topics['model']}, {topics['made'][:10]}): {clip(listed, 600)}")
        automated = len(humans) < 2 or fields.get('origin', '').startswith(AUTOMATED_ORIGINS)
        return {'time': day[-1]['time'], 'start': day[0]['time'], 'where': project, 'bound': {'path': project},
                'automated': automated, 'untitled': not automated and not topics,
                'headline': f"{fields['agent']} · {project} · human turns: {len(humans)}{since}",
                'quotes': quotes,
                'locator': f"{path} start={humans[0]['line'] if humans else day[0]['line']}"}

    def search(self, words, since):
        for path in self.paths(since):
            fields = header(path)
            project = fields.get('project', '')
            for hit in scan(path, words, stamp):
                yield {**hit, 'time': hit['said'] or modified(path), 'where': project, 'bound': {'path': project},
                       'label': f"{fields['agent']} · {project}", 'locator': f"{path} start={hit['line']}"}

    def health(self, now):
        for store in self.stores:
            corpus = Path(store['corpus'])
            fix = f"; refresh: python {SCRIPTS / store['archiver']}" if store.get('archiver') else ''
            if not corpus.is_dir():
                yield f"session corpus unavailable: {corpus} — searching without it; set in sources.json"
                continue
            status = corpus.parent / 'status.json'
            if status.is_file():
                state = json.loads(status.read_text(encoding='utf-8'))
                checked = datetime.fromisoformat(state['checked_at'])
                if now - checked > STALE:
                    yield f"archive {corpus.parent} not updated since {checked.astimezone():%Y-%m-%d %H:%M} — fresh sessions are missing{fix}"
                if state.get('errors'):
                    yield f"archive {corpus.parent}: {len(state['errors'])} errors on the last pass — listed in {status}"
            live = newest(store['live'], '*.jsonl') if store.get('live') and Path(store['live']).is_dir() else None
            archived = acknowledged_source_change(corpus)
            reference = 'last archived source change'
            if archived is None:
                archived = newest(corpus, '*.md')
                reference = 'corpus'
            if live and archived and live - archived > SILENT:
                yield (f"archive {corpus.parent} is silent: a live session changed at {live.astimezone():%H:%M}, "
                       f"the {reference} at {archived.astimezone():%H:%M}{fix}")

    def bound_of(self, target):
        path = Path(target.split(' start=')[0])
        for store in self.stores:
            corpus = Path(store['corpus'])
            if path.suffix == '.md' and path.is_file() and path.resolve().is_relative_to(corpus.resolve()):
                return {'path': header(path).get('project')}
        return None
