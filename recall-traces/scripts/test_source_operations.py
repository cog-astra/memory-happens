import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_support import slug
import source_operations
import trigram_selector
from plugins import select_literal
from recall_core import Recall
from recall_recipe import run as run_recipe
from recall_runner import Runner

NOW = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)
DAY1, DAY2 = NOW - timedelta(days=2), NOW - timedelta(days=1)


def stamp(moment, minutes=0):
    return (moment + timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def turns(*messages):
    return ''.join(f'## {stamp(moment, minutes)} [{role}] L{n}:B0\n\n{text}\n\n'
                   for n, (moment, minutes, role, text) in enumerate(messages, 1))


def claude(name, project, *messages):
    return f'# Claude session {name}.jsonl\nraw: {name}.jsonl\nsession: {name}\nproject: {project}\norigin: cli\n\n' + turns(*messages)


def codex(name, project, *messages):
    return f'# Codex session {name}\nraw: {name}.jsonl\n\nsession: {name}\nproject: {project}\norigin: cli\n\n' + turns(*messages)


def line_of(path, fragment):
    return next(n for n, text in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1) if fragment in text)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, files, message):
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding='utf-8')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


class SourceOperationsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = self.base = Path(folder.name).resolve()
        self.work = base / 'work'
        self.friend = base / 'spaces' / 'friend'
        (self.friend / 'open').mkdir(parents=True)

        self.corpus = base / 'archive' / 'corpus'
        sessions = self.corpus / 'C--Work'
        sessions.mkdir(parents=True)
        self.claude = sessions / 'claude.md'
        self.claude.write_text(claude('claude', self.work,
                                      (DAY1, 0, 'user', "Let's paint the lighthouse blue"),
                                      (DAY1, 5, 'assistant', 'Blue it is, two coats.'),
                                      (DAY1, 9, 'user', 'And the railing too'),
                                      (DAY2, 0, 'user', 'Where did we stop with the lighthouse?'),
                                      (DAY2, 3, 'assistant', 'At the railing.')), encoding='utf-8')
        self.claude.with_suffix('.topics.json').write_text(json.dumps({DAY1.astimezone().date().isoformat(): {
            'model': 'test', 'made': NOW.isoformat(), 'topics': [{'text': 'lighthouse colour', 'lines': [8]}]}}),
            encoding='utf-8')
        self.codex = sessions / 'codex.md'
        self.codex.write_text(codex('codex', self.work,
                                    (DAY2, 30, 'user', 'Check the harbour crane near the lighthouse'),
                                    (DAY2, 31, 'assistant', 'The crane is fine.'),
                                    (DAY2, 32, 'user', 'Good, close it')), encoding='utf-8')
        self.shared = sessions / 'shared.md'
        self.shared.write_text(claude('shared', self.friend / 'open',
                                      (DAY2, 50, 'user', 'An open lighthouse sketch'),
                                      (DAY2, 51, 'user', 'Share it')), encoding='utf-8')

        projects = base / 'projects'
        for project, name, text in ((self.work, 'lighthouse', 'The lighthouse is blue.'),):
            memory = projects / slug(project) / 'memory'
            memory.mkdir(parents=True)
            (memory / 'MEMORY.md').write_text('- index\n', encoding='utf-8')
            (memory / f'{name}.md').write_text(f'---\nname: {name}\ndescription: "About {name}"\n---\n\n{text}\n',
                                               encoding='utf-8')
        self.memory_note = projects / slug(self.work) / 'memory' / 'lighthouse.md'

        vault = base / 'vault'
        (vault / 'Places').mkdir(parents=True)
        (vault / '.obsidian').mkdir()
        (vault / '.obsidian' / 'x.md').write_text('# service lighthouse\n', encoding='utf-8')
        self.cape = vault / 'Places' / 'Cape.md'
        self.cape.write_text('# Cape\n\nA lighthouse on the northern cape.\nIts keeper writes a log.\n', encoding='utf-8')

        for repo in (self.work, self.friend):
            repo.mkdir(parents=True, exist_ok=True)
            git(repo, 'init', '-q')
        self.painted = commit(self.work, {'paint.txt': 'blue'}, 'Paint the lighthouse blue')
        commit(self.work, {'crane.txt': 'ok'}, 'Inspect the harbour crane')
        self.opened = commit(self.friend, {'open/a.txt': '1'}, 'Open lighthouse sketch')

        self.options = {
            'sessions': {'plugin': 'sessions', 'stores': [{'corpus': str(self.corpus), 'archiver': 'archive_claude.py'}]},
            'memory': {'plugin': 'memory', 'roots': [str(projects)]},
            'notes': {'plugin': 'notes', 'roots': [str(vault)]},
            'git': {'plugin': 'git', 'repos': [str(self.work)], 'discover': [str(base / 'spaces')]}}

    def runner(self, **replaced):
        options = {**self.options, **replaced}
        plugins = {alias: source_operations.Plugin(alias, entry) for alias, entry in options.items()}
        plugins['folder'] = source_operations.FolderPlugin('folder')
        plugins['select'] = select_literal.Plugin()
        return Runner(plugins)

    def run_op(self, runner, alias, operation, parameters=None, inputs=None):
        events = list(runner.invoke(alias, operation, parameters, inputs))
        return [event['record'] for event in events if event['type'] == 'record'], events[-1]['outcome']

    def legacy(self, words):
        cfg = {'spaces': [str(self.base / 'spaces')], 'sources': list(self.options.values())}
        return dict(Recall(cfg).search(words))

    def test_session_scope_accepts_either_path_separator(self):
        cfg = {'spaces': [str(self.base / 'spaces')], 'sources': [self.options['sessions']]}
        for project, scope in ((r'X:\Demo\harbour', 'x:/demo/harbour'),
                               ('X:/Demo/harbour', r'x:\demo\harbour')):
            with self.subTest(project=project, scope=scope):
                self.claude.write_text(claude('claude', project,
                    (DAY1, 0, 'user', 'The lighthouse keeper has the answer.')), encoding='utf-8')
                legacy = Recall(cfg)
                hits = dict(legacy.search(['lighthouse'], where=scope))['sessions']
                self.assertEqual([hit['where'] for hit in hits], [project])
                recent = legacy.recent(DAY1 - timedelta(days=1), where=scope)
                self.assertEqual([hit['where'] for hit in recent], [project])
                runner = self.runner()
                for operation, parameters in (
                    ('search', {'query': 'lighthouse', 'where': scope}),
                    ('during', {'start': (DAY1 - timedelta(days=1)).isoformat(),
                                'end': NOW.isoformat(), 'where': scope}),
                ):
                    records, outcome = self.run_op(runner, 'sessions', operation, parameters)
                    self.assertEqual(outcome['status'], 'success')
                    self.assertEqual(len(records), 1)
                    self.assertIn(str(self.claude), records[0]['evidence'][0]['locator'])

    def test_search_finds_the_known_places_and_the_same_places_as_legacy(self):
        runner = self.runner()
        expected = {'sessions': {f'{self.claude} start={line_of(self.claude, "paint the lighthouse")}',
                                 f'{self.claude} start={line_of(self.claude, "stop with the lighthouse")}',
                                 f'{self.codex} start={line_of(self.codex, "harbour crane")}',
                                 f'{self.shared} start={line_of(self.shared, "open lighthouse")}'},
                    'memory': {f'{self.memory_note} start={line_of(self.memory_note, "name: lighthouse")}'},
                    'notes': {f'{self.cape} start=3'},
                    'git': {f'{self.work.as_posix()}@{self.painted}', f'{self.friend.as_posix()}@{self.opened}'}}
        legacy = self.legacy(['lighthouse'])
        for alias, places in expected.items():
            records, outcome = self.run_op(runner, alias, 'search', {'query': 'Lighthouse'})
            found = {record['evidence'][0]['locator'] for record in records}
            self.assertEqual(found, places, alias)
            before = {hit['locator'] for hit in legacy[{'memory': 'project memory'}.get(alias, alias)]}
            self.assertEqual({place.split('@')[0] + '@' + place.split('@')[1][:7] for place in found}
                             if alias == 'git' else found, before, alias)
            for record in records:
                self.assertIn('lighthouse', record['text'].casefold())
                self.assertEqual(record['evidence'][0]['source'], alias)
                self.assertIn('matched', record['context'])
                self.assertIn('total', record['context'])
                self.assertTrue(('event_time' in record['context']) != ('modified_at' in record['context']), alias)
        best = self.run_op(runner, 'sessions', 'search', {'query': 'lighthouse'})[0]
        limited = self.run_op(runner, 'sessions', 'search', {'query': 'lighthouse', 'limit': 1})[0]
        self.assertEqual([r['evidence'] for r in limited], [best[0]['evidence']])

    def test_search_reports_visible_records_outside_where_in_one_scan(self):
        runner = self.runner()
        for alias, count in {'sessions': 4, 'memory': 1, 'notes': 1, 'git': 2}.items():
            with self.subTest(source=alias):
                source = runner.plugins[alias].source
                with patch.object(source, 'search', wraps=source.search) as scan:
                    records, outcome = self.run_op(runner, alias, 'search',
                                                  {'query': 'lighthouse', 'where': 'no-such-project'})
                self.assertEqual(scan.call_count, 1)
                self.assertEqual(records, [])
                self.assertEqual(outcome['status'], 'success')
                self.assertEqual(outcome['message'], f'Matching records outside where: {count}.')
                self.assertEqual(outcome['next_steps'], ['Search this source without where for a broader scope.'])

    def test_search_scope_preserves_matches_order_and_omits_empty_hints(self):
        runner = self.runner()
        broad, _ = self.run_op(runner, 'sessions', 'search', {'query': 'lighthouse'})
        expected = [record for record in broad if record['context']['where'] == str(self.work)]
        scoped, outcome = self.run_op(runner, 'sessions', 'search',
                                     {'query': 'lighthouse', 'where': 'work', 'limit': 2})
        self.assertEqual([{key: record[key] for key in ('text', 'evidence', 'access')} for record in scoped],
                         [{key: record[key] for key in ('text', 'evidence', 'access')} for record in expected[:2]])
        self.assertEqual(outcome['message'], 'Matching records outside where: 1.')
        for parameters in ({'query': 'lighthouse'}, {'query': 'lighthouse', 'where': 'Places'},
                           {'query': 'no-such-word', 'where': 'elsewhere'}):
            _, outcome = self.run_op(runner, 'notes', 'search', parameters)
            self.assertEqual(outcome['message'], '')
            self.assertEqual(outcome['next_steps'], [])

    def test_folder_reports_only_visible_matches_inside_its_root(self):
        runner = self.runner()
        broad, _ = self.run_op(runner, 'folder', 'search', {'query': 'lighthouse', 'root': str(self.corpus)})
        self.assertEqual({record['evidence'][0]['locator'].split(' start=')[0] for record in broad},
                         {str(path) for path in (self.claude, self.codex, self.shared, self.claude.with_suffix('.topics.json'))})
        records, outcome = self.run_op(runner, 'folder', 'search',
                                     {'query': 'lighthouse', 'root': str(self.corpus), 'where': 'no-such-folder'})
        self.assertEqual(records, [])
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual(outcome['message'], 'Matching records outside where: 4.')
        _, outcome = self.run_op(runner, 'folder', 'search',
                                {'query': 'lighthouse', 'root': str(self.cape.parent), 'where': 'Places'})
        self.assertEqual(outcome['message'], '')

    def test_configured_exclusions_still_apply(self):
        excluded = {**self.options['memory'], 'exclude': [slug(self.work)]}
        records, outcome = self.run_op(self.runner(memory=excluded), 'memory', 'search', {'query': 'blue'})
        self.assertEqual((records, outcome['status']), ([], 'success'))

    def test_passages_cover_old_and_deep_text_with_replaceable_selectors(self):
        for path in (self.cape, self.claude):
            with path.open('a', encoding='utf-8') as stream:
                stream.write('\n' * 90 + 'The garden contains a barometer.\n')
            old = (NOW - timedelta(days=540)).timestamp()
            os.utime(path, (old, old))
        for alias, path in (('notes', self.cape), ('sessions', self.claude)):
            runner = self.runner()
            candidates, outcome = self.run_op(runner, alias, 'passages')
            windows = [r for r in candidates if r['evidence'][0]['locator'].startswith(f'{path} start=')]
            self.assertEqual(''.join(r['text'] for r in windows), path.read_text(encoding='utf-8'))
            self.assertTrue(all(r['context']['last_line'] - r['context']['first_line'] < 40 for r in windows))
            self.assertEqual(windows[-1]['context']['last_line'], len(path.read_text(encoding='utf-8').splitlines()))
            self.assertTrue(all(r['access'] and r['evidence'][0]['observed_at'] for r in windows))
            for selector, expected in ((select_literal.Plugin(), 0), (trigram_selector, 1)):
                runner.plugins['select'] = selector
                recipe = [{'name': 'all', 'plugin': alias, 'operation': 'passages'},
                          {'name': 'found', 'plugin': 'select', 'operation': 'select',
                           'parameters': {'query': 'gardens', 'limit': 5}, 'inputs': {'passages': 'all'}}]
                records, steps, result = run_recipe(runner, recipe)
                self.assertEqual(steps[0]['records'], len(candidates))
                self.assertEqual(len(records), expected)
                self.assertIn(result.status, ('success', 'partial'))
                for record in records:
                    self.assertGreater(record['context']['first_line'], 80)
                    evidence = json.loads(json.dumps(record['evidence'][0]))
                    read, outcome = self.run_op(self.runner(), alias, 'read', {'evidence': evidence, 'lines': 40})
                    self.assertEqual(read[0]['text'], record['text'])
                    self.assertEqual(outcome['status'], 'success')
                    self.assertTrue(record['lineage']['inputs'])

    def test_passages_catalog_scope_validation_and_missing_source(self):
        runner = self.runner()
        self.assertEqual({op['plugin'] for op in runner.catalog() if op['name'] == 'passages'}, {'notes', 'sessions'})
        for invalid in ({'query': 'garden'}, {'days': 7}, {'lines': 0}):
            self.assertEqual(self.run_op(runner, 'notes', 'passages', invalid)[1]['code'], 'invalid_call')
        gone = {'plugin': 'notes', 'roots': [str(self.base / 'gone')]}
        records, outcome = self.run_op(self.runner(notes=gone), 'notes', 'passages')
        self.assertEqual((records, outcome['status'], outcome['code']), ([], 'unavailable', 'source_missing'))

    def test_passages_keep_file_enumeration_and_do_not_duplicate_overlapping_patterns(self):
        (self.corpus / 'subagents').mkdir()
        (self.corpus / 'subagents' / 'hidden.md').write_text('A hidden garden\n', encoding='utf-8')
        (self.cape.parent / 'empty.md').touch()
        options = {**self.options['notes'], 'patterns': ['*.md', 'C*.md']}
        runner = self.runner(notes=options)
        notes, outcome = self.run_op(runner, 'notes', 'passages')
        self.assertEqual([r['evidence'][0]['locator'] for r in notes], [f'{self.cape} start=1'])
        self.assertEqual(outcome['status'], 'success')
        sessions, _ = self.run_op(runner, 'sessions', 'passages')
        self.assertFalse(any('subagents' in r['evidence'][0]['locator'] for r in sessions))

    def test_times_keep_their_meaning_per_source(self):
        runner = self.runner()
        sessions = self.run_op(runner, 'sessions', 'search', {'query': 'lighthouse'})[0]
        self.assertTrue(all('event_time' in record['context'] for record in sessions))
        for alias in ('memory', 'notes'):
            records = self.run_op(runner, alias, 'search', {'query': 'lighthouse'})[0]
            self.assertTrue(records and all('modified_at' in r['context'] and 'event_time' not in r['context'] for r in records))
        commits = self.run_op(runner, 'git', 'recent', {'days': 3})[0]
        self.assertTrue(all(record['evidence'][0]['revision'] and 'event_time' in record['context'] for record in commits))

    def test_recent_keeps_day_edges_topics_and_where(self):
        records, outcome = self.run_op(self.runner(), 'sessions', 'recent', {'days': 7})
        claude_days = [r for r in records if r['evidence'][0]['locator'].startswith(str(self.claude))]
        self.assertEqual(len(claude_days), 2)
        first = min(claude_days, key=lambda r: r['context']['event_time'])
        self.assertEqual(first['context']['day_start'][:16], DAY1.isoformat()[:16])
        self.assertEqual(first['context']['topics']['topics'][0]['text'], 'lighthouse colour')
        self.assertIn("paint the lighthouse blue", first['text'])
        self.assertIn('And the railing too', first['text'])
        self.assertEqual(outcome['status'], 'success')
        narrowed = self.run_op(self.runner(), 'sessions', 'recent', {'days': 7, 'where': 'friend'})[0]
        self.assertEqual({r['evidence'][0]['locator'].split(' start=')[0] for r in narrowed}, {str(self.shared)})
        ordered = [r['context']['event_time'] for r in records]
        self.assertEqual(ordered, sorted(ordered, reverse=True))

    def test_evidence_survives_serialization_and_reads_in_windows_through_a_fresh_runner(self):
        records = self.run_op(self.runner(), 'notes', 'search', {'query': 'lighthouse'})[0]
        carried = json.loads(json.dumps(records[0]['evidence'][0]))
        runner = self.runner()
        first, outcome = self.run_op(runner, 'notes', 'read', {'evidence': carried, 'lines': 1})
        self.assertEqual(first[0]['text'], 'A lighthouse on the northern cape.\n')
        self.assertEqual(outcome['continuation'], {'start': 4})
        second, outcome = self.run_op(runner, 'notes', 'read', {'evidence': carried, 'start': 4, 'lines': 5})
        self.assertEqual(second[0]['text'], 'Its keeper writes a log.\n')
        self.assertEqual((outcome['status'], outcome['continuation']), ('success', None))
        commits = self.run_op(runner, 'git', 'search', {'query': 'paint'})[0]
        patch = self.run_op(self.runner(), 'git', 'read', {'evidence': json.loads(json.dumps(commits[0]['evidence'][0]))})[0]
        self.assertIn(self.painted, patch[0]['text'])
        self.assertIn('paint.txt', patch[0]['text'])

    def test_a_changed_source_is_reported_on_read(self):
        carried = self.run_op(self.runner(), 'notes', 'search', {'query': 'keeper'})[0][0]['evidence'][0]
        self.cape.write_text('# Cape\n\nRewritten.\nIts keeper left.\n', encoding='utf-8')
        later = datetime.now().timestamp() + 5
        os.utime(self.cape, (later, later))
        records, outcome = self.run_op(self.runner(), 'notes', 'read', {'evidence': carried})
        self.assertEqual((outcome['status'], outcome['code']), ('success', 'source_changed'))
        self.assertIn('Its keeper left.', records[0]['text'])

    def test_missing_and_partial_corpora_stay_visible_and_differ_from_empty(self):
        gone = str(self.base / 'gone')
        missing = {'plugin': 'sessions', 'stores': [{'corpus': gone, 'archiver': 'archive_claude.py'}]}
        records, outcome = self.run_op(self.runner(sessions=missing), 'sessions', 'search', {'query': 'lighthouse'})
        self.assertEqual((records, outcome['status'], outcome['code']), ([], 'unavailable', 'corpus_missing'))
        self.assertTrue(any('archive_claude.py' in step for step in outcome['next_steps']))
        half = {'plugin': 'sessions', 'stores': [{'corpus': str(self.corpus)}, {'corpus': gone}]}
        records, outcome = self.run_op(self.runner(sessions=half), 'sessions', 'search', {'query': 'crane'})
        self.assertEqual(len(records), 1)
        self.assertEqual((outcome['status'], outcome['code']), ('partial', 'source_partial'))
        records, outcome = self.run_op(self.runner(), 'notes', 'search', {'query': 'zeppelin'})
        self.assertEqual((records, outcome['status']), ([], 'success'))
        health = self.run_op(self.runner(sessions=half), 'sessions', 'health')
        self.assertIn(gone, health[0][0]['text'])
        self.assertEqual(self.run_op(self.runner(), 'notes', 'search', {'query': '   '})[1]['code'], 'empty_query')

    def test_stale_archive_shows_in_ordinary_calls(self):
        (self.corpus.parent / 'status.json').write_text(json.dumps({'checked_at': (NOW - timedelta(days=3)).isoformat()}),
                                                         encoding='utf-8')
        outcome = self.run_op(self.runner(), 'sessions', 'search', {'query': 'crane'})[1]
        self.assertEqual((outcome['status'], outcome['code']), ('partial', 'stale_archive'))
        self.assertTrue(any('archive_claude.py' in step for step in outcome['next_steps']))

    def test_records_from_different_sources_pass_one_selector_with_evidence_intact(self):
        runner = self.runner()
        passages = []
        for alias in ('sessions', 'notes', 'git'):
            passages += self.run_op(runner, alias, 'search', {'query': 'lighthouse'})[0]
        selected, outcome = self.run_op(runner, 'select', 'select', {'query': 'northern paint', 'limit': 10},
                                        {'passages': passages})
        self.assertEqual(outcome['status'], 'success')
        self.assertEqual({json.dumps(r['evidence'], sort_keys=True) for r in selected},
                         {json.dumps(p['evidence'], sort_keys=True) for p in passages
                          if 'northern' in p['text'].casefold() or 'paint' in p['text'].casefold()})
        self.assertEqual(len(selected), 3)

    def test_folder_search_follows_a_relocated_archive_and_reads_it(self):
        project, moved = self.base / 'proj', self.base / 'moved'
        project.mkdir()
        (moved / 'old').mkdir(parents=True)
        (moved / 'old' / 'log.md').write_text('keeper notes\nthe lighthouse keeper returned\n', encoding='utf-8')
        (project / 'process-archive.json').write_text(json.dumps({'location': str(moved), 'folders': [{'source': 'old'}]}),
                                                     encoding='utf-8')
        runner = self.runner()
        for root in (project, project / 'old'):
            records, outcome = self.run_op(runner, 'folder', 'search', {'query': 'lighthouse keeper', 'root': str(root)})
            self.assertEqual(outcome['status'], 'success', root)
            self.assertEqual(records[0]['evidence'][0]['locator'], f"{(moved / 'old' / 'log.md')} start=2")
        read, outcome = self.run_op(runner, 'folder', 'read', {'evidence': records[0]['evidence'][0], 'lines': 1})
        self.assertEqual(read[0]['text'], 'the lighthouse keeper returned\n')
        missing = self.run_op(runner, 'folder', 'search', {'query': 'x', 'root': str(self.base / 'nowhere')})[1]
        self.assertEqual((missing['status'], missing['code']), ('unavailable', 'root_missing'))

    def test_unknown_types_and_foreign_evidence_are_unsupported(self):
        runner = self.runner(odd={'plugin': 'audio'})
        self.assertEqual(self.run_op(runner, 'odd', 'search', {'query': 'x'})[1]['code'], 'unknown_source_type')
        foreign = {'source': 'notes', 'locator': f'{self.claude} start=1'}
        self.assertEqual(self.run_op(runner, 'notes', 'read', {'evidence': foreign})[1]['code'], 'incompatible_evidence')
        wrong_alias = {'source': 'sessions', 'locator': f'{self.cape} start=1'}
        self.assertEqual(self.run_op(runner, 'notes', 'read', {'evidence': wrong_alias})[1]['code'], 'incompatible_evidence')


if __name__ == '__main__':
    unittest.main()
