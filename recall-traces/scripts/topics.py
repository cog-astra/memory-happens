import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import zip_longest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_transcript import TOOL_PREFIX
from plugins.sessions import AUTOMATED_ORIGINS, header, parse
from recall_core import Recall

OLLAMA = 'http://localhost:11434/api/chat'
LIMIT = 3000
SCHEMA = {'type': 'object', 'required': ['topics'], 'properties': {'topics': {'type': 'array', 'items': {
    'type': 'object', 'required': ['text', 'lines'],
    'properties': {'text': {'type': 'string'}, 'lines': {'type': 'array', 'items': {'type': 'integer'}}}}}}}

PROMPT = """You are given a stretch of a working day: human turns and the agent's action intents, each line numbered L.
Write 1–2 topics of the stretch — what was talked about, not what was decided. A topic is 2–6 words taken from the lines themselves, in the language of the lines.
Give each topic 1–3 line numbers where it appears. Add nothing of your own: what is not in the lines is not a topic.
Be concrete — objects, names, files, terms from the lines. Do not generalise: not "report discussion" but "report export: crash on empty dates".
Topics from the middle of the day matter most: its start and end are visible anyway. [tool:…] lines are what the agent did; they are topics too.

Example. Lines:
L12: давай починим экспорт отчёта, падает на пустых датах
L20: [tool:Bash] убедиться, что пустая дата воспроизводит падение
L41: кстати, а логотип в шапке можно заменить на новый?
L44: [tool:Write] C:/site/assets/logo-2026.svg
L58: ок, экспорт работает, на сегодня всё
Answer: {"topics": [{"text": "падение экспорта на пустых датах", "lines": [12, 20]}, {"text": "новый логотип logo-2026 в шапке", "lines": [41, 44]}]}"""


def stems(text):
    return {word[:5] for word in text.casefold().replace('«', ' ').replace('»', ' ').split() if len(word) >= 4}


def day_lines(messages, service):
    lines = []
    for message in messages:
        text = message['text'].strip()
        if message['role'] == 'user' and text and not text.startswith(service):
            lines += [(message['line'] + 2 + offset, ' '.join(paragraph.split())[:300])
                      for offset, paragraph in enumerate(text.split('\n')) if paragraph.strip()]
        elif message['role'] == 'assistant' and text.startswith(TOOL_PREFIX):
            lines.append((message['line'], text[:160]))
    return lines


def stretches(lines):
    stretch, size = [], 0
    for number, text in lines:
        if stretch and size + len(text) > LIMIT:
            yield stretch
            stretch, size = [], 0
        stretch.append((number, text))
        size += len(text)
    if stretch:
        yield stretch


def ask(model, lines):
    body = {'model': model, 'stream': False, 'format': SCHEMA, 'think': False,
            'options': {'temperature': 0.2, 'num_ctx': 8192},
            'messages': [{'role': 'system', 'content': PROMPT},
                         {'role': 'user', 'content': '\n'.join(f"L{number}: {text}" for number, text in lines)}]}
    request = urllib.request.Request(OLLAMA, json.dumps(body).encode('utf-8'), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(json.loads(response.read())['message']['content'])['topics']


def grounded(topics, lines):
    texts = dict(lines)
    kept = []
    for topic in topics:
        cited = [number for number in topic.get('lines', []) if number in texts]
        words = stems(topic.get('text', ''))
        if cited and words and any(words & stems(texts[number]) for number in cited):
            kept.append({'text': topic['text'].strip(), 'lines': cited[:3]})
    return kept


def distinct(parts, limit=10):
    chosen = []
    for round_ in zip_longest(*parts):
        for topic in filter(None, round_):
            words = stems(topic['text'])
            if len(chosen) < limit and all(len(words & stems(c['text'])) / len(words | stems(c['text'])) < 0.34
                                           for c in chosen):
                chosen.append(topic)
    return sorted(chosen, key=lambda topic: topic['lines'][0])


def store(path):
    return path.with_suffix('.topics.json')


def main():
    parser = argparse.ArgumentParser(description='Write topics of session days with a local model: topics and line numbers only, for sessions visible to the reader')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--model', default='qwen3:14b')
    parser.add_argument('--only', help='part of a corpus path: write topics only for these sessions')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    recall = Recall()
    sessions = next(plugin for plugin in recall.plugins if plugin.name == 'sessions')
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    for path in sessions.paths(since):
        fields = header(path)
        if (args.only and args.only not in str(path)) or not recall.visible({'path': fields.get('project')}) \
                or fields.get('origin', '').startswith(AUTOMATED_ORIGINS):
            continue
        known = json.loads(store(path).read_text(encoding='utf-8')) if store(path).is_file() else {}
        days = {}
        for message in parse(path):
            days.setdefault(message['time'].astimezone().date().isoformat(), []).append(message)
        for day, messages in days.items():
            upto = messages[-1]['time'].isoformat()
            if messages[-1]['time'] < since or (not args.force and known.get(day, {}).get('upto') == upto):
                continue
            lines = day_lines(messages, sessions.service)
            if sum(1 for number, text in lines if not text.startswith(TOOL_PREFIX)) < 2:
                continue
            topics = distinct([grounded(ask(args.model, stretch), stretch) for stretch in stretches(lines)])
            known[day] = {'model': args.model, 'made': datetime.now(timezone.utc).isoformat(), 'upto': upto, 'topics': topics}
            store(path).write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding='utf-8')
            print(f"{day} {path.name[:40]}: " + '; '.join(topic['text'] for topic in topics))


if __name__ == '__main__':
    main()
