import argparse
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from codex_transcript import message_blocks


PROJECTION_VERSION = 2


@contextmanager
def exclusive(path):
    with open(path, 'a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def origin(meta):
    source = meta.get('source')
    if isinstance(source, dict) and 'subagent' in source:
        spawn = source['subagent'].get('thread_spawn') if isinstance(source['subagent'], dict) else None
        parent = spawn.get('parent_thread_id') if isinstance(spawn, dict) else None
        return 'subagent' + (f' of {parent}' if parent else '')
    return source if isinstance(source, str) else 'unknown'


def project(data, raw_path):
    complete = data.rfind(b'\n') + 1
    lines = [f'# Codex session {raw_path.stem}', f'raw: {raw_path.as_posix()}', '']
    count = 0
    for number, raw in enumerate(data[:complete].splitlines(), 1):
        try:
            record = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise ValueError(f'Invalid JSONL record {number}') from error
        if record.get('type') == 'session_meta':
            meta = record.get('payload', {})
            lines.extend([f'session: {meta.get("id", "")}', f'project: {meta.get("cwd", "")}',
                          f'origin: {origin(meta)}', ''])
        for message in message_blocks(record, number):
            lines.extend([
                f'## {message["recorded_at"] or ""} [{message["role"]}] '
                f'L{number}:B{message["block"]}', '', message['text'], '',
            ])
            count += 1
    return '\n'.join(lines).encode('utf-8'), count, len(data) - complete


def archive(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Source and archive must be separate directories')
    roots = [source / name for name in ('sessions', 'archived_sessions') if (source / name).is_dir()]
    if not roots:
        raise FileNotFoundError('No Codex session directories found')
    manifest_path = destination / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'copied': 0, 'unchanged': 0,
              'deferred_tail_bytes': 0, 'errors': []}
    for root in roots:
        for path in sorted(root.rglob('*.jsonl')):
            relative = path.relative_to(source)
            key = relative.as_posix()
            target = destination / 'raw' / relative
            corpus = destination / 'sessions-corpus' / relative.with_suffix('.md')
            try:
                stat = path.stat()
                stamp = [stat.st_size, stat.st_mtime_ns]
                prior = manifest.get(key, {})
                if (prior.get('source_stamp') == stamp and target.exists() and corpus.exists()
                        and prior.get('projection_version') == PROJECTION_VERSION):
                    report['unchanged'] += 1
                    report['deferred_tail_bytes'] += prior.get('deferred_tail_bytes', 0)
                    continue
                with path.open('rb') as stream:
                    data = stream.read(stat.st_size)
                if len(data) != stat.st_size:
                    raise OSError('Source shrank during snapshot; retry on next run')
                if target.exists():
                    previous = target.read_bytes()
                    if not data.startswith(previous):
                        version = destination / 'revisions' / relative.parent / (target.stem + '-' + digest(previous) + '.jsonl')
                        if not version.exists():
                            atomic_write(version, previous)
                atomic_write(target, data)
                rendered, count, tail = project(data, target)
                atomic_write(corpus, rendered)
                manifest[key] = {'source_stamp': stamp, 'sha256': digest(data),
                                 'projection_version': PROJECTION_VERSION, 'messages': count, 'deferred_tail_bytes': tail}
                report['copied'] += 1
                report['deferred_tail_bytes'] += tail
            except (OSError, ValueError) as error:
                report['errors'].append({'file': key, 'error': str(error)})
    report['archived_files'] = len(manifest)
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    atomic_write(destination / 'status.json', json.dumps(report, ensure_ascii=False, indent=2).encode('utf-8'))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / '.codex')
    parser.add_argument('--destination', type=Path, default=Path.home() / 'recall-archive' / 'codex')
    args = parser.parse_args()
    args.destination.mkdir(parents=True, exist_ok=True)
    with exclusive(args.destination / '.archive.lock'):
        report = archive(args.source, args.destination)
    print(json.dumps(report, ensure_ascii=False))
    return bool(report['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
