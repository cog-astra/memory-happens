import json
from pathlib import Path


MANIFEST = 'process-archive.json'


def entries(near):
    for repository in [near, *near.parents]:
        manifest = repository / MANIFEST
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            return [(repository / item['source'], Path(data['location']) / item['source'])
                    for item in data['folders']]
    return []


def resolve(path):
    path = Path(path).resolve()
    if path.exists():
        return path
    for original, archived in entries(path):
        if path.is_relative_to(original):
            return archived / path.relative_to(original)
    return path


def search_roots(root):
    root = Path(root).resolve()
    roots = [root] if root.is_dir() else []
    for original, archived in entries(root):
        if original.exists():
            continue
        if original.is_relative_to(root):
            roots.append(archived)
        elif root.is_relative_to(original):
            roots.append(archived / root.relative_to(original))
    for path in roots:
        if not path.is_dir():
            raise FileNotFoundError(f'Recall archive is unavailable: {path}')
    if not roots:
        raise FileNotFoundError(root)
    return list(dict.fromkeys(roots))


def reference_root(scope, logical_root):
    for original, archived in entries(Path(logical_root)):
        if scope == archived and original.is_relative_to(logical_root):
            depth = len(original.relative_to(logical_root).parts)
            return scope.parents[depth - 1] if depth else scope
    return scope
