from pathlib import Path

from recall_core import Source, modified, scan


def title(path):
    with path.open(encoding='utf-8', errors='replace') as stream:
        for line in stream:
            if line.startswith('# '):
                return line[2:].strip()
    return path.stem


class Plugin(Source):
    title = 'notes'

    def paths(self, since=None):
        for root in map(Path, self.options.get('roots', [])):
            for pattern in self.options.get('patterns', ['*.md']):
                for path in root.rglob(pattern):
                    if not any(part.startswith('.') for part in path.relative_to(root).parts) \
                            and not (since and modified(path) < since):
                        yield root, path

    def recent(self, since):
        for root, path in self.paths(since):
            named = title(path)
            yield {'time': modified(path), 'where': str(path), 'bound': {'path': path},
                   'group': f"notes in {root}",
                   'headline': path.relative_to(root).as_posix() + ('' if named == path.stem else f" — {named}"),
                   'locator': str(path)}

    def search(self, words, since):
        for root, path in self.paths(since):
            for hit in scan(path, words):
                yield {**hit, 'time': modified(path), 'where': str(path), 'bound': {'path': path},
                       'label': path.relative_to(root).as_posix(), 'locator': f"{path} start={hit['line']}"}

    def health(self, now):
        return [f"notes unavailable: {root} — searching without them; set in sources.json"
                for root in map(Path, self.options.get('roots', [])) if not root.is_dir()]
