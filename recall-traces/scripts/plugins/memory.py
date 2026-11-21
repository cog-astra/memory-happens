from pathlib import Path

from recall_core import Source, excluded_project, modified, scan


def frontmatter(text):
    if not text.startswith('---'):
        return {}
    fields = {}
    for line in text[3:].split('\n---', 1)[0].splitlines():
        if ':' in line and not line.startswith(' '):
            key, _, value = line.partition(':')
            fields[key.strip()] = value.strip().strip('"').replace('\\\\', '\\')
    return fields


class Plugin(Source):
    title = 'project memory'
    cost = 2

    def paths(self, since=None):
        skipped = self.options.get('exclude', [])
        for root in map(Path, self.options.get('roots', [])):
            for path in root.glob('*/memory/*.md'):
                if path.name != 'MEMORY.md' and not excluded_project(path.parent.parent.name, skipped) \
                        and not (since and modified(path) < since):
                    yield root, path

    def recent(self, since):
        yield from self.activity(since)

    def during(self, window):
        yield from self.activity(window.start, window)

    def activity(self, since, window=None):
        for root, path in self.paths(since):
            when = modified(path)
            if window is not None and not window.contains(when):
                continue
            fields = frontmatter(path.read_text(encoding='utf-8', errors='replace'))
            project = path.parent.parent.name
            yield {'time': when, 'where': project,
                   'group': f"memory in {root}",
                   'headline': f"{path.relative_to(root).as_posix()} — {' '.join(fields.get('description', '').split())[:140]}",
                   'locator': str(path)}

    def search(self, words, since):
        for root, path in self.newest(self.paths(since), lambda pair: pair[1]):
            project = path.parent.parent.name
            for hit in scan(path, words):
                yield {**hit, 'time': modified(path), 'where': project,
                       'label': f"{project} · {path.stem}", 'locator': f"{path} start={hit['line']}"}

    def health(self, now):
        return [f"project memory unavailable: {root} — searching without it; set in sources.json"
                for root in map(Path, self.options.get('roots', [])) if not root.is_dir()]
