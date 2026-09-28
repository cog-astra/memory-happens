import os
import re
from pathlib import Path

RULES = 'humans.txt'
SECTION = re.compile(r'^\[recall\]\s*$')


def norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


def within(path, folder):
    path, folder = norm(path), norm(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def resolved_within(path, folder):
    return within(Path(path).resolve(), Path(folder).resolve())


def slug(path):
    return re.sub(r'[^A-Za-z0-9]', '-', os.path.abspath(str(path))).casefold()


def parse(rules):
    root = rules.parent
    fields, inside = {}, False
    for line in rules.read_text(encoding='utf-8', errors='replace').splitlines():
        if SECTION.match(line):
            inside = True
        elif inside and line.startswith('['):
            break
        elif inside and '=' in line:
            key, _, value = line.partition('=')
            fields[key.strip()] = [root / part.strip() for part in value.split(',') if part.strip()]
    return {'root': root, 'rules': rules, 'open': fields.get('open', []),
            'private': fields.get('private', []), 'guests': fields.get('guests', [])}


def closes(space, path, inside):
    return inside(path, space['root']) and not inside(path, space['rules']) and (
        any(inside(path, p) for p in space['private']) or not any(inside(path, o) for o in space['open']))


def spaces(bases):
    found = {}
    for base in map(Path, bases):
        for pattern in (RULES, f'*/{RULES}', f'*/*/{RULES}'):
            for rules in base.glob(pattern):
                found[norm(rules)] = parse(rules)
    return list(found.values())


def owns(space, reader):
    return within(reader, space['root']) and not any(within(reader, guest) for guest in space['guests'])


class Bounds:
    def __init__(self, bases, reader=None):
        self.reader = reader or os.environ.get('RECALL_READER') or os.getcwd()
        self.closed = [space for space in spaces(bases) if not owns(space, self.reader)
                       and not (any(within(space['root'], o) for o in space['open'])
                                and not any(Path(p).exists() for p in space['private']))]

    def owner_of(self, path):
        return next((space for space in self.closed if path and
                     (closes(space, path, within) or closes(space, path, resolved_within))), None)

    def owner_of_project(self, key):
        prefix = lambda project, folder: project.casefold().startswith(slug(folder))
        return next((space for space in self.closed if closes(space, key, prefix)), None)

    def hides(self, path):
        return self.owner_of(path) is not None

    def hides_project(self, key):
        return self.owner_of_project(key) is not None

    def open_paths(self, repo):
        for space in self.closed:
            if within(repo, space['root']):
                opened = [os.path.relpath(o, repo) for o in space['open'] if within(o, repo)]
                return opened and opened + [f":(exclude){os.path.relpath(p, repo)}"
                                            for p in space['private'] if within(p, repo)]
        return None

    def opened(self, space):
        listed = ', '.join(os.path.relpath(o, space['root']) for o in space['open']) or 'nothing'
        private = ', '.join(os.path.relpath(p, space['root']) for p in space['private'])
        return listed + (f', except private {private}' if private else '')

    def refusal(self, what, space):
        if not space:
            return ''
        return (f"Closed: {what} lies in the personal space {space['root']} under its {space['rules']}; "
                f"open to neighbours: {self.opened(space)}. Only the owner can open parts of it, "
                f"with a [recall] open = … section in {RULES}.\n")

    def notice(self):
        if not self.closed:
            return ''
        listed = '; '.join(f"{space['root']} (open: {self.opened(space)})" for space in self.closed)
        return (f"bounds: personal spaces are hidden under their {RULES} — {listed}; reading from {self.reader}. "
                f"Only the owner can open parts of it, with a [recall] open = … section in {RULES}.\n\n")
