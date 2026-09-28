import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from recall_core import REPO_REV, Source, modified

SKIP = {'node_modules', '.git', 'Library', 'Temp', 'venv', '.venv', '__pycache__', 'build', 'dist'}
FOUND = {}


def git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    return result.stdout if result.returncode == 0 else ''


def discover(root, depth=3):
    found = []
    for folder, children, _ in os.walk(root):
        level = len(Path(folder).relative_to(root).parts)
        if (Path(folder) / '.git').exists():
            found.append(Path(folder))
        children[:] = [] if level >= depth else [c for c in children if c not in SKIP and not c.startswith('.')]
    return found


def repos(options, ttl=600):
    key = tuple(options.get('discover', []))
    if key not in FOUND or time.time() - FOUND[key][0] > ttl:
        FOUND[key] = (time.time(), [repo for root in key if Path(root).is_dir() for repo in discover(root)])
    explicit = [Path(repo) for repo in options.get('repos', []) if (Path(repo) / '.git').exists()]
    return sorted(set(FOUND[key][1]) | set(explicit))


def commits(repo, since=None, words=(), full=False, window=None):
    args = ['log', '--branches', '-m', '--name-only', '-z',
            f"--format=%x1e{'%H' if full else '%h'}%x1f%aI%x1f%s%x1f%(trailers:key=Co-Authored-By,valueonly,separator=%x2C )"]
    if since and window is None:
        args.append(f'--since={since.isoformat()}')
    if words:
        args += ['-i', *[f'--grep={word}' for word in words]]
    found = {}
    for record in git(repo, *args).split('\x1e')[1:]:
        head, _, names = record.partition('\x00')
        files = names.removeprefix('\n').split('\x00')
        rev, when, subject, partners = head.split('\x1f', 3)
        moment = datetime.fromisoformat(when)
        # Git's date filters use committer time; this stream exposes author time.
        if window is not None and not window.contains(moment):
            continue
        voices = ', '.join(name.split(' <')[0] for name in partners.split(', ') if name.strip())
        entry = found.setdefault(rev, {'rev': rev, 'time': moment,
                                 'subject': subject + (f" [co-author: {voices}]" if voices else ''),
                                 'bound': {'repo': repo, 'files': []}})
        entry['bound']['files'].extend(repo / name for name in files if name)
    yield from found.values()


def active(repo, since):
    log = repo / '.git' / 'logs' / 'HEAD'
    return not since or not log.is_file() or modified(log) >= since


def across(found, work):
    with ThreadPoolExecutor(8) as pool:
        for repo, results in zip(found, pool.map(lambda repo: list(work(repo)), found)):
            for result in results:
                yield repo, result


class Plugin(Source):
    title = 'git'

    def recent(self, since):
        found = [repo for repo in repos(self.options) if active(repo, since)]
        for repo, commit in across(found, lambda repo: commits(repo, since)):
            yield {'time': commit['time'], 'where': str(repo), 'bound': commit['bound'],
                   'group': f"git · {repo.as_posix()}", 'headline': f"{commit['rev']} {commit['subject']}",
                   'locator': f"{repo.as_posix()}@{commit['rev']}"}

    def search(self, words, since):
        found = [repo for repo in repos(self.options) if active(repo, since)]
        for repo, commit in across(found, lambda repo: commits(repo, since, words)):
            folded = commit['subject'].casefold()
            yield {'time': commit['time'], 'where': str(repo), 'bound': commit['bound'],
                   'matched': [word for word in words if word in folded], 'total': 1, 'places': [],
                   'excerpt': f"{commit['rev']} {commit['subject']}", 'label': repo.as_posix(),
                   'locator': f"{repo.as_posix()}@{commit['rev']}"}

    def health(self, now):
        return [f"repository unavailable: {repo} — searching without it; set in sources.json"
                for repo in self.options.get('repos', []) if not (Path(repo) / '.git').exists()]

    def bound_of(self, target):
        match = REPO_REV.match(target)
        if not match or not Path(match[1]).is_dir():
            return None
        repo = Path(match[1])
        files = git(repo, 'diff-tree', '--root', '-m', '-r', '--no-commit-id', '--name-only', '-z', match[2]).split('\x00')
        return {'repo': repo, 'files': [repo / name for name in files if name]}

    def read(self, target, start, lines, characters):
        match = REPO_REV.match(target)
        if not match or not Path(match[1]).is_dir():
            return None
        text = git(match[1], 'show', '--stat', '--format=%H%n%aI · %an%n%n%B', match[2])
        if not text:
            return f'No revision {match[2]} in {match[1]}.\n'
        return text[:characters] + ('' if len(text) <= characters else '\n[cut at characters]\n')
