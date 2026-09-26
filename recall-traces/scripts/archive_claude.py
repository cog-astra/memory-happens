import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_codex import atomic_write, digest, exclusive
from claude_transcript import message_blocks

PROJECTION_VERSION = 3


def project(data, raw_path, relative):
    complete = data.rfind(b'\n') + 1
    head = [f'# Claude session {relative.as_posix()}', f'raw: {raw_path.as_posix()}']
    body, count, meta = [], 0, {}
    for number, raw in enumerate(data[:complete].splitlines(), 1):
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise ValueError(f'Invalid JSONL record {number}') from error
        for key, field in (('session', 'sessionId'), ('project', 'cwd'), ('origin', 'entrypoint')):
            if key not in meta and record.get(field):
                meta[key] = record[field]
        for message in message_blocks(record, number):
            body.extend([
                f'## {message["recorded_at"] or ""} [{message["role"]}] '
                f'L{number}:B{message["block"]}', '', message['text'], '',
            ])
            count += 1
    head.extend(f'{key}: {value}' for key, value in meta.items())
    return '\n'.join(head + [''] + body).encode('utf-8'), count, len(data) - complete


def snapshot(path):
    stat = path.stat()
    with path.open('rb') as stream:
        data = stream.read(stat.st_size)
    if len(data) != stat.st_size:
        raise OSError('Source shrank during snapshot; retry on next run')
    return data, [stat.st_size, stat.st_mtime_ns]


def copy(source, raw_root, destination, manifest, report):
    for path in sorted(source.rglob('*.jsonl')):
        key = path.relative_to(source).as_posix()
        target = raw_root / key
        try:
            stat = path.stat()
            if manifest.get(key, {}).get('source_stamp') == [stat.st_size, stat.st_mtime_ns] and target.exists():
                continue
            data, stamp = snapshot(path)
            if target.exists():
                previous = target.read_bytes()
                if data == previous:
                    manifest.setdefault(key, {})['source_stamp'] = stamp
                    continue
                if not data.startswith(previous):
                    version = destination / 'revisions' / Path(key).parent / (target.stem + '-' + digest(previous) + '.jsonl')
                    if not version.exists():
                        atomic_write(version, previous)
            atomic_write(target, data)
            manifest.setdefault(key, {})['source_stamp'] = stamp
            report['copied'] += 1
        except (OSError, ValueError) as error:
            report['errors'].append({'file': key, 'error': str(error)})


def render(raw_root, corpus_root, manifest, report):
    for target in sorted(raw_root.rglob('*.jsonl')):
        relative = target.relative_to(raw_root)
        key = relative.as_posix()
        corpus = corpus_root / relative.with_suffix('.md')
        entry = manifest.setdefault(key, {})
        try:
            stat = target.stat()
            stamp = [stat.st_size, stat.st_mtime_ns]
            if (entry.get('raw_stamp') == stamp and corpus.exists()
                    and entry.get('projection_version') == PROJECTION_VERSION):
                report['unchanged'] += 1
                report['deferred_tail_bytes'] += entry.get('deferred_tail_bytes', 0)
                continue
            data, stamp = snapshot(target)
            rendered, count, tail = project(data, target, relative)
            atomic_write(corpus, rendered)
            entry.update({'raw_stamp': stamp, 'projection_version': PROJECTION_VERSION,
                          'messages': count, 'deferred_tail_bytes': tail})
            report['projected'] += 1
            report['deferred_tail_bytes'] += tail
        except (OSError, ValueError) as error:
            report['errors'].append({'file': key, 'error': str(error)})


def archive(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and archive must be separate directories')
    if not source.is_dir():
        raise FileNotFoundError(f'No Claude projects directory: {source}')
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'copied': 0, 'projected': 0,
              'unchanged': 0, 'deferred_tail_bytes': 0, 'errors': []}
    raw_root = destination / 'projects'
    copy(source, raw_root, destination, manifest, report)
    render(raw_root, destination / 'sessions-corpus', manifest, report)
    report['archived_files'] = len(manifest)
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    atomic_write(destination / 'status.json', json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / '.claude' / 'projects')
    parser.add_argument('--destination', type=Path, default=Path.home() / 'recall-archive' / 'claude')
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    with exclusive(args.destination / '.archive.lock'):
        report = archive(args.source, args.destination)
    print(json.dumps({key: value for key, value in report.items() if key != 'errors'}
                     | {'errors': len(report['errors'])}, ensure_ascii=False))
    return bool(report['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
