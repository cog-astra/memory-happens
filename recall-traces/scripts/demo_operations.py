import argparse
import importlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from plugins.git_operations import Plugin as GitReader
from recall_runner import Runner


def fixture(repo):
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'GIT_AUTHOR_NAME': 'Demo', 'GIT_AUTHOR_EMAIL': 'demo@example.invalid',
           'GIT_COMMITTER_NAME': 'Demo', 'GIT_COMMITTER_EMAIL': 'demo@example.invalid',
           'GIT_AUTHOR_DATE': '2026-01-01T00:00:00+0000', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00+0000'}

    def git(*args):
        return subprocess.check_output(
            ['git', '-c', 'commit.gpgsign=false', '-c', f'core.hooksPath={repo / "no-hooks"}',
             '-C', str(repo), *args], env=env, stderr=subprocess.PIPE).decode('utf-8').strip()

    git('init', '-q')
    revisions = {}
    changes = [
        ('base', 'lookup.py', 'def lookup(rows, key):\n    return rows.get(key)\n', 'Add row lookup'),
        ('cache', 'lookup.py', 'cache = {}\ndef lookup(rows, key):\n    if key not in cache:\n        cache[key] = rows.get(key)\n    return cache[key]\n', 'Cache row lookups to avoid repeated reads'),
        ('guide', 'GUIDE.md', 'Lookups return the current row value.\n', 'Document row lookup behavior'),
        ('rollback', 'lookup.py', 'def lookup(rows, key):\n    return rows.get(key)\n',
         'Remove lookup cache: edits returned stale values\n\nThe cache key omitted the row revision. Prefer a fresh read until invalidation is reliable.'),
    ]
    for name, filename, content, message in changes:
        (repo / filename).write_text(content, encoding='utf-8')
        git('add', '--force', filename)
        git('commit', '-q', '-m', message)
        revisions[name] = git('rev-parse', 'HEAD')
    return revisions


def call(runner, plugin, operation, parameters=None, inputs=None):
    events = list(runner.invoke(plugin, operation, parameters, inputs))
    outcome = events[-1]['outcome']
    if outcome['status'] != 'success':
        raise RuntimeError(f'{plugin}.{operation}: {outcome["status"]} ({outcome["code"]})')
    return [event['record'] for event in events if event['type'] == 'record']


def recall_change(repo, selector):
    runner = Runner({'git': GitReader('demo', repo), 'selector': selector})
    candidates = call(runner, 'git', 'history')
    selected = call(runner, 'selector', 'select', {'query': 'cache stale', 'limit': 1},
                    {'passages': candidates})
    if not selected:
        return {'selection': [], 'patches': [], 'trace': runner.trace}
    evidence = json.loads(json.dumps(selected[0]['evidence'][0]))
    fresh = Runner({'git': GitReader('demo', repo)})
    patches = call(fresh, 'git', 'read', {'evidence': evidence})
    return {'selection': selected, 'patches': patches, 'trace': runner.trace + fresh.trace}


def main():
    parser = argparse.ArgumentParser(description='Recall why a synthetic optimization was removed.')
    parser.add_argument('--selector', default='plugins.select_literal', help='Trusted Python module exporting Plugin()')
    args = parser.parse_args()
    selector = importlib.import_module(args.selector).Plugin()
    with tempfile.TemporaryDirectory() as folder:
        fixture(folder)
        print(json.dumps(recall_change(folder, selector), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
