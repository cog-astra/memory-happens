import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_files
from recall_files import encode_text, page, read_source, search
import recall_archive


needs_memlab = unittest.skipUnless(recall_files.MEMLAB, 'search needs a memlab backend: set RECALL_MEMLAB')


class RecallFilesTests(unittest.TestCase):
    def test_search_without_backend_says_what_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ImportError, 'RECALL_MEMLAB'):
                search(temp, 'needle', 'map', None, backend=None)

    @needs_memlab
    def test_archived_search_references_can_be_read_in_original_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / 'repo' / 'process'
            root.mkdir(parents=True)
            pairs = []
            for name in ('one', 'two'):
                archived = base / 'archive' / 'process' / name
                archived.mkdir(parents=True)
                (archived / 'report.md').write_text(f'needle {name}\n', encoding='utf-8')
                pairs.append((root / name, archived))
            with patch.object(recall_archive, 'entries', return_value=pairs):
                for scope, expected in ((root, {'one/report.md', 'two/report.md'}),
                                        (root / 'one', {'report.md'})):
                    for mode in ('broad', 'precise'):
                        found = search(scope, 'needle', mode, None)
                        sources = [item['sources'][0]['path'] for item in found['items']]
                        self.assertEqual(set(sources), expected)
                        for item, source in zip(found['items'], sources):
                            content = read_source(scope, source)['items'][0]['text'].strip()
                            self.assertEqual(content, item['text'])
                    mapped = search(scope, 'needle', 'map', None)
                    self.assertEqual(mapped['backend_files'], len(expected))
                    for source in expected:
                        self.assertIn(source, '\n'.join(item['text'] for item in mapped['items']))
                (root / 'one').mkdir()
                (root / 'one' / 'report.md').write_text('needle restored\n', encoding='utf-8')
                self.assertEqual(read_source(root, 'one/report.md')['items'][0]['text'].strip(),
                                 'needle restored')
                found = search(root, 'needle', 'broad', None)
                self.assertEqual(found['backend_files'], 2)
                self.assertIn('needle restored', [item['text'] for item in found['items']])
                with self.assertRaises(ValueError):
                    read_source(root / 'two', '../one/report.md')
                with patch.object(recall_archive, 'entries',
                                  return_value=[(root / 'missing', base / 'unavailable')]):
                    with self.assertRaises(FileNotFoundError):
                        search(root, 'needle', 'broad', None)

    def result(self, items):
        return {'root': 'test', 'items': items}

    def test_entire_output_bound_including_escaped_characters(self):
        original = ('Я\n"\\\t🙂' * 500)
        result = self.result([{'text': original, 'sources': [{'path': 'source.md'}]}])
        for budget in [280, 400, 1000]:
            rendered = page(result, budget)
            self.assertLessEqual(len(rendered), budget)
            item = json.loads(rendered)['items'][0]
            self.assertTrue(original.startswith(item['text']))
            self.assertEqual(len(original), len(item['text']) + item['omitted_characters'])
            self.assertEqual(item['sources'], [{'path': 'source.md'}])
        self.assertEqual(result['items'][0]['text'], original)

    def test_pages_do_not_lose_or_repeat_items(self):
        items = [{'text': str(i) * 70} for i in range(20)]
        offset, seen = 0, []
        while offset is not None:
            rendered = page(self.result(items), 450, offset)
            self.assertLessEqual(len(rendered), 450)
            result = json.loads(rendered)
            seen.extend(result['items'])
            offset = result['next_offset']
        self.assertEqual(seen, items)

    def test_empty_and_insufficient_budget(self):
        self.assertIsNone(json.loads(page(self.result([]), 300))['next_offset'])
        with self.assertRaises(ValueError):
            page(self.result([]), 10)

    def test_source_window_and_pages_preserve_coordinates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lines = [f'{i}: строка "\\"\r\n' for i in range(50)]
            (root / 'source.md').write_bytes(('\ufeff' + ''.join(lines)).encode('utf-8'))
            result = read_source(root, 'source.md', 11, 20)
            self.assertEqual(result['next_window_line'], 31)
            offset, seen = 0, []
            while offset is not None:
                rendered = page(result, 700, offset)
                self.assertLessEqual(len(rendered), 700)
                part = json.loads(rendered)
                seen.extend(part['items'])
                offset = part['next_offset']
            self.assertEqual([item['line'] for item in seen], list(range(11, 31)))
            self.assertEqual(''.join(item['text'] for item in seen), ''.join(lines[10:30]))
            self.assertEqual(read_source(root, 'source.md', 100)['items'], [])
            with self.assertRaises(ValueError):
                read_source(root, 'source.md', 0)

    def test_source_cannot_escape_selected_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scope').mkdir()
            (root / 'outside.md').write_text('outside', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_source(root / 'scope', '../outside.md')

    def test_text_read_preserves_content_and_exposes_references_on_demand(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = 'Первая строка\r\n\r\n"Вторая" 🙂\r\n'
            (root / 'source.md').write_bytes(content.encode('utf-8'))
            result = read_source(root, 'source.md')
            self.assertEqual(page(result, 1000, render=encode_text), content)
            referenced = page(result, 1000, render=lambda v: encode_text(v, True))
            self.assertIn('source.md\n1: Первая строка', referenced)
            self.assertIn('3: "Вторая" 🙂', referenced)

    def test_text_pages_keep_continuation_and_window_end_distinct(self):
        result = {'mode': 'read', 'next_window_line': 21,
                  'items': [{'text': f'{i} ' + 'я' * 70 + '\n'} for i in range(20)]}
        offset, seen = 0, []
        while offset is not None:
            text = page(result, 240, offset, encode_text)
            self.assertLessEqual(len(text), 240)
            body = text.split('[recall:')[0]
            seen.append(body)
            if 'next_offset=' in text:
                self.assertNotIn('next_window_line', text)
                offset = int(text.split('next_offset=')[1].split(']')[0])
            else:
                self.assertIn('next_window_line=21', text)
                offset = None
        self.assertEqual(''.join(seen), ''.join(item['text'] for item in result['items']))

    def test_text_truncation_is_visible_and_budgeted_with_unicode(self):
        result = self.result([{'text': '"Я🙂\\\n' * 1000,
                               'sources': [{'path': 'source.md', 'span': '3-9'}]}])
        for references in (False, True):
            for budget in (150, 300, 1000):
                text = page(result, budget, render=lambda v: encode_text(v, references))
                self.assertLessEqual(len(text), budget)
                self.assertIn('omitted_characters=', text)
                self.assertIn('retry_offset=0', text)
                self.assertEqual('source.md:3-9' in text, references)
        self.assertIn('no items', page(self.result([]), 100, render=encode_text))
        with self.assertRaises(ValueError):
            page(result, 10, render=encode_text)

    @needs_memlab
    def test_live_backend_scopes_search_and_bounds_all_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for i in range(30):
                (root / f'{i}.md').write_text('needle ' * 300 + '\n', encoding='utf-8')
            excluded = root / 'node_modules'
            excluded.mkdir()
            (excluded / 'hidden.md').write_text('needle', encoding='utf-8')
            for mode in ['map', 'broad', 'precise']:
                run = subprocess.run([
                    sys.executable, str(Path(__file__).with_name('recall_files.py')),
                    '--root', str(root), '--frame', 'needle', '--mode', mode,
                    '--characters', '1800'], capture_output=True, encoding='utf-8',
                    check=True, timeout=20)
                self.assertLessEqual(len(run.stdout), 1800)
                result = json.loads(run.stdout)
                self.assertTrue(result['items'])
                self.assertNotIn('hidden.md', run.stdout)
                if mode == 'map':
                    self.assertEqual(result['backend_candidates'], 30)
                    self.assertGreater(result['remaining_items'], 0)

    @needs_memlab
    def test_precise_long_intent_keeps_an_isolated_lead(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'lead.md').write_text('needle\n', encoding='utf-8')
            frame = 'needle ' + ' '.join(f'absentword{i}' for i in range(20))
            result = search(root, frame, 'precise', None)
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(result['items'][0]['text'], 'needle')

    @needs_memlab
    def test_backend_diagnostics_are_not_search_hits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'lead.md').write_text('needle\n', encoding='utf-8')
            for mode in ('map', 'broad', 'precise'):
                empty = search(root, 'absentword', mode, None)
                self.assertEqual(empty['items'], [])
                self.assertEqual(empty['backend_found'], 0)
                self.assertTrue(empty['backend_note'])
                found = search(root, 'needle', mode, None)
                self.assertEqual(len(found['items']), 1)
                self.assertEqual(found['backend_found'], 1)
                self.assertEqual(found['backend_files'], 1)
                self.assertNotIn('[склад]', encode_text(json.loads(page(found, 1800))))

    @needs_memlab
    def test_backend_cut_is_reported_and_large_line_still_fits_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = '\n'.join('needle ' + 'я' * 200 for _ in range(40))
            (root / 'window.md').write_text(content, encoding='utf-8')
            result = search(root, 'needle', 'broad', None)
            self.assertLess(len(result['items'][0]['text']), len(content))
            self.assertIn('обрезано', result['backend_note'])
            (root / 'long-line.md').write_text('needle ' * 5000, encoding='utf-8')
            for mode in ('map', 'broad', 'precise'):
                result = search(root, 'needle', mode, None)
                for render in (None, encode_text, lambda v: encode_text(v, True)):
                    output = page(result, 1800, **({'render': render} if render else {}))
                    self.assertLessEqual(len(output), 1800)
                    self.assertTrue(output.strip())


if __name__ == '__main__':
    unittest.main()
