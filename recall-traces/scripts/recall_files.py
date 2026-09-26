import argparse
import copy
import importlib
import itertools
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recall_options import publish_options
import recall_archive

MEMLAB = Path(os.environ['RECALL_MEMLAB']) if os.environ.get('RECALL_MEMLAB') else None


def read_source(root, source, start_line=1, lines=30):
    if start_line < 1 or lines < 1:
        raise ValueError('Require start-line >= 1 and lines >= 1')
    root = Path(root).resolve()
    logical = (root / source).resolve()
    relative = logical.relative_to(root).as_posix()
    target = recall_archive.resolve(logical)
    with target.open(encoding='utf-8-sig', newline='') as stream:
        selected = list(itertools.islice(stream, start_line - 1, start_line - 1 + lines + 1))
    more = len(selected) > lines
    selected = selected[:lines]
    return {
        'root': str(root), 'source': relative, 'mode': 'read',
        'physical_source': str(target),
        'start_line': start_line, 'requested_lines': lines,
        'next_window_line': start_line + len(selected) if more else None,
        'items': [{'line': start_line + i, 'text': line} for i, line in enumerate(selected)],
    }


def search(root, frame, mode, context, backend=MEMLAB):
    if backend is None:
        raise ImportError('Search needs a memlab backend, which is not part of this repository: '
                          'set RECALL_MEMLAB to its checkout. --source reads files without it.')
    root = Path(root).resolve()
    roots = recall_archive.search_roots(root)
    if not frame.strip():
        raise ValueError('--frame must not be empty')
    sys.path.insert(0, str(backend))
    store = importlib.import_module('lib.store_v0')
    load = store._load_collections
    iter_files = store._iter_files
    config = copy.deepcopy(load()['projects'])
    config['roots'] = [str(path) for path in roots]
    references = {str(path): str(recall_archive.reference_root(path, root)) for path in roots}
    store._load_collections = lambda: {'recall-scope': config}
    store._iter_files = lambda cfg: ((references[scope], path) for scope, path in iter_files(cfg))
    try:
        result = store.recall('recall-scope', frame, budget=4000,
                              mode=mode, context=context).to_dict()
    finally:
        store._load_collections = load
        store._iter_files = iter_files
    if mode == 'map':
        maps = [item for item in result['items'] if item['text'].startswith('НАЙДЕНО:')]
        if len(maps) != 1:
            raise ValueError('Unrecognized memlab map response')
        lines = maps[0]['text'].splitlines()
        items = [{'text': line} for line in lines[1:]]
        candidates = result['run']['items_returned']
    else:
        items = [item for item in result['items'] if item.get('sources')]
        candidates = None
    return {
        'root': str(root), 'frame': frame, 'mode': mode,
        'search_root_count': len(config['roots']),
        'include': config['include'], 'exclude_dirs': config['exclude_dirs'],
        'method': result['run']['method'], 'search_ms': result['run']['ms'],
        'backend_note': result['run'].get('note'),
        'backend_found': result['run'].get('found'), 'backend_files': result['run'].get('files'),
        'backend_candidates': candidates, 'backend_returned': len(items),
        'items': items,
    }


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n'


def encode_text(value, references=False):
    parts = []
    if references and value.get('source'):
        parts.append(f"{value['source']}\n")
    for index, item in enumerate(value['items']):
        if references:
            for source in item.get('sources', []):
                parts.append(f"{source['path']}:{source.get('span', '')}\n")
        prefix = f"{item['line']}: " if references and 'line' in item else ''
        parts.append(prefix + item['text'])
        if item.get('omitted_characters'):
            parts.append(f"\n[recall: omitted_characters={item['omitted_characters']}; "
                         f"retry_offset={value['offset'] + index}; increase --characters]\n")
        if not parts[-1].endswith('\n'):
            parts.append('\n')
        if value.get('mode') != 'read':
            parts.append('\n')
    if not value['items']:
        parts.append('[recall: no items]\n')
    if value['remaining_items']:
        parts.append(f"[recall: remaining_items={value['remaining_items']}; "
                     f"next_offset={value['next_offset']}]\n")
    elif value.get('next_window_line') is not None:
        parts.append(f"[recall: next_window_line={value['next_window_line']}]\n")
    return ''.join(parts)


def page(result, characters, offset=0, render=encode):
    if characters < 1 or offset < 0:
        raise ValueError('Require characters > 0 and offset >= 0')
    remaining = result['items'][offset:]
    output = {**result, 'items': [], 'offset': offset,
              'remaining_items': len(remaining), 'next_offset': offset if remaining else None,
              'character_limit': characters}
    if len(render(output)) > characters:
        raise ValueError('Budget cannot hold response metadata; increase --characters')
    for item in remaining:
        candidate = copy.deepcopy(item)
        output['items'].append(candidate)
        output['remaining_items'] -= 1
        output['next_offset'] = offset + len(output['items']) if output['remaining_items'] else None
        if len(render(output)) <= characters:
            continue
        if len(output['items']) > 1:
            output['items'].pop()
            output['remaining_items'] += 1
            output['next_offset'] = offset + len(output['items'])
            break
        original = candidate['text']
        candidate['text'] = ''
        candidate['omitted_characters'] = len(original)
        if len(render(output)) > characters:
            raise ValueError('Budget cannot hold source references; increase --characters')
        low, high = 0, len(original)
        while low < high:
            middle = (low + high + 1) // 2
            candidate['text'] = original[:middle]
            candidate['omitted_characters'] = len(original) - middle
            if len(render(output)) <= characters:
                low = middle
            else:
                high = middle - 1
        candidate['text'] = original[:low]
        candidate['omitted_characters'] = len(original) - low
        break
    return render(output)


def main():
    parser = argparse.ArgumentParser(description='Bounded read-only access to the neighboring memlab file search')
    publish_options(parser)
    parser.add_argument('--root', required=True, help='One directory; relative source paths refer to this root')
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--frame')
    operation.add_argument('--source', help='Read a file within root, without invoking memlab')
    parser.add_argument('--start-line', type=int, default=1)
    parser.add_argument('--lines', type=int, default=30)
    parser.add_argument('--mode', choices=['map', 'broad', 'precise'], default='map',
                        help='map: file leads; broad: snippets matching any query term; '
                             'precise: narrower windows and fewer snippets matching any query term')
    parser.add_argument('--context', type=int, default=None)
    parser.add_argument('--format', choices=['json', 'text'], default='json',
                        help='Text omits metadata except truncation and continuation markers')
    parser.add_argument('--references', action='store_true',
                        help='Add source paths and line numbers to text output; JSON already includes them')
    parser.add_argument('--characters', type=int, default=4000,
                        help='Entire stdout in Unicode characters, including metadata and newlines; not tokens')
    parser.add_argument('--offset', type=int, default=0,
                        help='Page within backend results; repeats search, so files must remain unchanged')
    args = parser.parse_args()
    if args.references and args.format != 'text':
        parser.error('--references requires --format text')
    try:
        result = (read_source(args.root, args.source, args.start_line, args.lines) if args.source
                  else search(args.root, args.frame, args.mode, args.context))
        render = (lambda value: encode_text(value, args.references)) if args.format == 'text' else encode
        rendered = page(result, args.characters, args.offset, render)
    except (ValueError, OSError, ImportError, KeyError, UnicodeError) as error:
        parser.exit(1, str(error) + '\n')
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    sys.stdout.write(rendered)


if __name__ == '__main__':
    main()
