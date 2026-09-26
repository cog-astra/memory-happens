import os
import subprocess
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


def build(repo):
    """Commits spread over separated months, overlapping changed paths and one very large patch."""
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)

    def git(*args, when=None):
        env = {**os.environ, 'GIT_AUTHOR_NAME': 'Demo', 'GIT_AUTHOR_EMAIL': 'demo@example.invalid',
               'GIT_COMMITTER_NAME': 'Demo', 'GIT_COMMITTER_EMAIL': 'demo@example.invalid'}
        if when:
            env.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        return subprocess.check_output(['git', '-c', 'commit.gpgsign=false', '-c', f'core.hooksPath={repo / "no-hooks"}',
                                        '-C', str(repo), *args], env=env, stderr=subprocess.PIPE).decode('utf-8').strip()

    git('init', '-q')
    revisions, months, number = {}, {}, 0
    for month, count in PERIODS:
        for index in range(count):
            number += 1
            when = f'{month}-{2 + index * 26 // count:02d}T10:00:00+00:00'
            message = SPECIAL.get((month, index)) or SUBJECTS[number % len(SUBJECTS)].format(area=AREAS[number % len(AREAS)])
            touched = [FILES[(number * step) % len(FILES)] for step in (1, 7, 13, 19)]
            if message.startswith('Vendor'):
                touched = ['vendor/pricing/tables.csv']
                rows = '\n'.join(f'{row},sku-{row:05d},{row * 37 % 1000}.{row % 100:02d},EUR' for row in range(6000))
                (repo / touched[0]).parent.mkdir(parents=True, exist_ok=True)
                (repo / touched[0]).write_text(rows + '\n', encoding='utf-8')
            else:
                for path in touched:
                    (repo / path).parent.mkdir(parents=True, exist_ok=True)
                    (repo / path).write_text(f'# revision {number}\nVALUE = {number}\n', encoding='utf-8')
            git('add', '--force', *touched)
            git('commit', '-q', '-m', message, when=when)
            revision = git('rev-parse', 'HEAD')
            months[month] = months.get(month, 0) + 1
            for key, name in (('Cache row', 'cache'), ('Vendor', 'vendor'), ('Remove lookup cache', 'rollback')):
                if message.startswith(key):
                    revisions[name] = revision
    return {'revisions': revisions, 'months': months, 'commits': number}


if __name__ == '__main__':
    import json
    import sys
    print(json.dumps(build(sys.argv[1]), indent=2))
