import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PERIODS = (('2024-01', 3), ('2024-04', 24), ('2024-07', 6), ('2024-08', 5))
AREAS = ('inventory', 'pricing', 'orders', 'reports', 'sync')
FILES = tuple(f'services/{area}/handlers/{area}_{kind}_handler.py'
              for area in AREAS for kind in ('lookup', 'batch', 'audit', 'export', 'retry', 'merge'))
SUBJECTS = ('Tune batch size for {area} sync', 'Log slow {area} requests', 'Retry {area} export on timeout',
            'Rename {area} audit fields', 'Split {area} merge into two passes', 'Document {area} handler limits')
SPECIAL = {
    ('2024-04', 5): 'Cache row lookups to avoid repeated reads',
    ('2024-07', 2): 'Vendor the pricing tables',
    ('2024-08', 3): 'Remove lookup cache: edits returned stale values\n\n'
                    'The cache key omitted the row revision. Prefer a fresh read until invalidation is reliable.',
}


def data(text):
    raw = text.encode('utf-8')
    return b'data %d\n' % len(raw) + raw + b'\n'


def build(repo, periods=PERIODS):
    """Commits over separated months, with repeated and distinct changed paths and one very large patch.

    One git fast-import stream keeps histories of hundreds of commits quick to create."""
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'init', '-q', '--initial-branch=main', str(repo)], check=True)
    stream, months, names, number = [], {}, {}, 0
    for month, count in periods:
        for index in range(count):
            number += 1
            when = int(datetime(int(month[:4]), int(month[5:]), 2 + index * 26 // count, 10,
                                tzinfo=timezone.utc).timestamp())
            message = SPECIAL.get((month, index)) or SUBJECTS[number % len(SUBJECTS)].format(area=AREAS[number % len(AREAS)])
            if message.startswith('Vendor'):
                files = {'vendor/pricing/tables.csv': '\n'.join(
                    f'{row},sku-{row:05d},{row * 37 % 1000}.{row % 100:02d},EUR' for row in range(6000)) + '\n'}
            else:
                touched = [FILES[(number * step) % len(FILES)] for step in (1, 7, 13, 19)] + [f'changes/{number:04d}.md']
                files = {path: f'# revision {number}\nVALUE = {number}\n' for path in touched}
            stream += [b'commit refs/heads/main\n', b'mark :%d\n' % number,
                       b'author Demo <demo@example.invalid> %d +0000\n' % when,
                       b'committer Demo <demo@example.invalid> %d +0000\n' % when, data(message)]
            if number > 1:
                stream.append(b'from :%d\n' % (number - 1))
            for path, content in files.items():
                stream += [b'M 100644 inline %s\n' % path.encode(), data(content)]
            months[month] = months.get(month, 0) + 1
            for key, name in (('Cache row', 'cache'), ('Vendor', 'vendor'), ('Remove lookup cache', 'rollback')):
                if message.startswith(key):
                    names[number] = name
    with tempfile.TemporaryDirectory() as folder:
        marks = Path(folder) / 'marks'
        subprocess.run(['git', '-C', str(repo), 'fast-import', '--quiet', f'--export-marks={marks}'],
                       input=b''.join(stream), check=True)
        revisions = {names[int(mark[1:])]: sha for mark, sha in
                     (line.split() for line in marks.read_text().splitlines()) if int(mark[1:]) in names}
    return {'revisions': revisions, 'months': months, 'commits': number}


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(build(sys.argv[1]), indent=2))
