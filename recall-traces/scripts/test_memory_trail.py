import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_trail import backlinks, changed_paths, discover, git, recall, render_overview, render_trail


class MemoryTrailTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        git(self.root, 'init', '-q')
        self.source = self.root / 'state.md'
        self.commit('Нужно установить канал.\n', 'Plan installation')
        self.first = git(self.root, 'rev-parse', 'HEAD').strip()
        self.commit('Канал установлен.\nГрупповой повтор не готов.\n', 'Install channel')
        self.second = git(self.root, 'rev-parse', 'HEAD').strip()

    def commit(self, body, subject):
        self.source.write_text(body, encoding='utf-8')
        git(self.root, 'add', '--', self.source.name)
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', subject)

    def test_transition_retains_removed_instruction_and_source_versions(self):
        result = recall(self.root, 'state.md', 'установить')
        episode = result['episodes'][0]
        self.assertEqual(episode['revision'], self.second)
        self.assertEqual(episode['before_refs'], [self.first + ':state.md'])
        self.assertIn('-Нужно установить канал.', episode['patch']['text'])
        self.assertIn('+Канал установлен.', episode['patch']['text'])
        self.assertIn('Групповой повтор не готов.', result['current']['content']['text'])

    def test_working_copy_is_distinct_from_committed_history(self):
        self.source.write_text('Новое неподтверждённое наблюдение', encoding='utf-8')
        result = recall(self.root, 'state.md')
        self.assertEqual(result['repository_head'], self.second)
        self.assertEqual(result['current']['content']['text'], 'Новое неподтверждённое наблюдение')
        self.assertNotIn('Новое неподтверждённое наблюдение', result['episodes'][0]['patch']['text'])

    def test_deleted_file_still_has_history(self):
        self.source.unlink()
        git(self.root, 'add', '-u')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', 'Remove state')
        result = recall(self.root, 'state.md', 'установлен')
        self.assertFalse(result['current']['exists'])
        self.assertIn('-Канал установлен.', result['episodes'][0]['patch']['text'])

    def test_budget_is_explicit_and_bounded(self):
        result = recall(self.root, 'state.md', characters=30)
        fragments = [result['current']['content']] + [e['patch'] for e in result['episodes']]
        self.assertLessEqual(sum(len(item['text']) for item in fragments), 30)
        self.assertTrue(any(item['omitted_characters'] > 0 for item in fragments))

    def test_scan_limit_and_miss_are_visible(self):
        result = recall(self.root, 'state.md', cue='missing', limit=1, scan=1)
        self.assertEqual(result['episodes'], [])
        self.assertEqual(result['scope']['commits_inspected'], 1)

    def test_outside_repository_is_rejected(self):
        with self.assertRaises(ValueError):
            recall(self.root, '../outside.md')

    def test_cli_outputs_parseable_unicode(self):
        script = Path(__file__).with_name('memory_trail.py')
        result = subprocess.run([sys.executable, str(script), 'state.md', '--repo', str(self.root)],
                                capture_output=True, encoding='utf-8', check=True)
        self.assertIn('Канал установлен.', json.loads(result.stdout)['current']['content']['text'])

    def test_discovery_finds_source_without_body_search(self):
        result = discover(self.root, '.', 'installation')
        self.assertEqual(result['episodes'][0]['sources'][0]['source'], 'state.md')
        self.assertEqual(result['episodes'][0]['sources'][0]['match_basis'], 'commit_subject')
        self.assertEqual(result['episodes'][0]['revision'], self.first)
        self.assertEqual(discover(self.root, '.', 'Групповой')['episodes'], [])

    def test_discovery_preserves_period_in_drilldown(self):
        result = discover(self.root, '.', 'state', since='2000-01-01', until='2100-01-01')
        args = result['drilldown_argv_template']
        self.assertEqual(args[-4:], ['--since', '2000-01-01', '--until', '2100-01-01'])
        self.assertEqual(discover(self.root, '.', since='2100-01-01')['episodes'], [])
        self.assertEqual(recall(self.root, 'state.md', since='2100-01-01')['episodes'], [])

    def test_overview_budget_retains_scope_and_reports_omission(self):
        result = discover(self.root, '.', 'installation')
        full = render_overview(result, 10000)
        short = render_overview(result, len(full) - 100)
        decoded = json.loads(short)
        self.assertLessEqual(len(short) + 1, len(full) - 100)
        self.assertEqual(decoded['episodes'], [])
        self.assertEqual(decoded['omitted_candidates'], 1)
        self.assertEqual(decoded['scope']['path'], '.')
        with self.assertRaises(ValueError):
            render_overview(result, 10)

    def test_invalid_period_is_rejected_instead_of_reported_as_no_memory(self):
        with self.assertRaises(ValueError):
            discover(self.root, '.', since='2030-01-01', until='2000-01-01')
        with self.assertRaises(ValueError):
            discover(self.root, '.', since='2026-09-08T12:00:00')

    def test_one_commit_uses_one_overview_slot_and_keeps_all_matching_sources(self):
        (self.root / 'reader-a.json').write_text('{}', encoding='utf-8')
        (self.root / 'reader-b.json').write_text('{}', encoding='utf-8')
        git(self.root, 'add', '--', 'reader-a.json', 'reader-b.json')
        self.commit('Завершено.\n', 'Run memory readers')
        result = discover(self.root, '.', 'memory', limit=1)
        self.assertEqual(result['candidate_count'], 1)
        self.assertEqual(len(result['episodes']), 1)
        self.assertEqual({s['source'] for s in result['episodes'][0]['sources']},
                         {'state.md', 'reader-a.json', 'reader-b.json'})

    def test_cli_alternatives_do_not_search_the_boolean_connector(self):
        self.commit('Память.\n', 'Memory work')
        memory_revision = git(self.root, 'rev-parse', 'HEAD').strip()
        self.commit('Другая работа.\n', 'Record transport status')
        script = str(Path(__file__).with_name('memory_trail.py'))
        base = [sys.executable, script, '--repo', str(self.root), '--scope', '.']
        rejected = subprocess.run(base + ['--cue', 'memory OR память'],
                                  capture_output=True, encoding='utf-8')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(rejected.stdout, '')
        self.assertIn('--term memory --term память', rejected.stderr)
        accepted = subprocess.run(base + ['--term', 'memory', '--term', 'память'],
                                  capture_output=True, encoding='utf-8', check=True)
        result = json.loads(accepted.stdout)
        self.assertEqual(result['query']['terms'], ['memory', 'память'])
        self.assertEqual([e['revision'] for e in result['episodes']], [memory_revision])

    def test_literal_phrase_stays_whole_and_empty_term_is_rejected(self):
        result = discover(self.root, '.', literal_terms=['PLAN INSTALLATION', 'plan installation'])
        self.assertEqual(result['query']['terms'], ['plan installation'])
        self.assertEqual([e['revision'] for e in result['episodes']], [self.first])
        with self.assertRaises(ValueError):
            discover(self.root, '.', literal_terms=[' '])
        with self.assertRaises(ValueError):
            recall(self.root, 'state.md', cue='memory OR память')

    def test_backlinks_find_committed_mentions_even_if_target_is_deleted(self):
        folder = self.root / 'notes'
        folder.mkdir()
        (folder / 'decision.md').write_text('Revises state.md after review.\n', encoding='utf-8')
        git(self.root, 'add', '--', 'notes/decision.md')
        self.commit('Closed.\n', 'Record decision')
        (folder / 'uncommitted.md').write_text('state.md', encoding='utf-8')
        self.source.unlink()
        git(self.root, 'add', '-u')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', 'Remove target')
        result = backlinks(self.root, 'state.md', 'notes')
        self.assertEqual([item['source'] for item in result['links']], ['notes/decision.md'])
        self.assertEqual(git(self.root, 'show', result['links'][0]['ref']).strip(),
                         'Revises state.md after review.')
        self.assertEqual(backlinks(self.root, 'unknown.md', 'notes')['links'], [])

    def test_backlink_scope_and_dates_are_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            backlinks(self.root, 'state.md', '..')
        script = str(Path(__file__).with_name('memory_trail.py'))
        result = subprocess.run([sys.executable, script, 'state.md', '--repo', str(self.root),
                                 '--backlinks', '--since', '2026-09-08'],
                                capture_output=True, encoding='utf-8')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not accept dates', result.stderr)

    def test_trail_budget_includes_json_escaping_and_references(self):
        self.source.write_text(('"Память" \\ история\n' * 800), encoding='utf-8')
        original = recall(self.root, 'state.md', characters=16000)
        before = original['current']['content']['text']
        rendered = render_trail(original, 3500)
        result = json.loads(rendered)
        self.assertLessEqual(len(rendered) + 1, 3500)
        self.assertEqual(result['episodes'][0]['after_ref'], self.second + ':state.md')
        self.assertEqual(result['scope'], original['scope'])
        self.assertEqual(original['current']['content']['text'], before)
        for new, old in zip([result['current']['content']] + [e['patch'] for e in result['episodes']],
                            [original['current']['content']] + [e['patch'] for e in original['episodes']]):
            self.assertEqual(len(new['text']) + new['omitted_characters'],
                             len(old['text']) + old['omitted_characters'])
        with self.assertRaises(ValueError):
            render_trail(original, 20)
        script = str(Path(__file__).with_name('memory_trail.py'))
        output = subprocess.run([sys.executable, script, 'state.md', '--repo', str(self.root),
                                 '--characters', '3500'], capture_output=True, check=True).stdout.decode('utf-8')
        self.assertLessEqual(len(output), 3500)
        self.assertTrue(output.endswith('\n'))

    def test_batched_paths_preserve_root_rename_deletion_and_hash_filename(self):
        renamed = 'Память с пробелами.md'
        git(self.root, 'mv', 'state.md', renamed)
        (self.root / self.first).write_text('A filename can equal a commit hash.', encoding='utf-8')
        git(self.root, 'add', '--', self.first)
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', 'Rename and add hash filename')
        rename_revision = git(self.root, 'rev-parse', 'HEAD').strip()
        git(self.root, 'rm', '--', renamed)
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', 'Delete renamed file')
        deletion_revision = git(self.root, 'rev-parse', 'HEAD').strip()
        revisions = [deletion_revision, rename_revision, self.second, self.first]
        paths = changed_paths(self.root, revisions, ':(literal).')
        self.assertEqual(paths[self.first], ['state.md'])
        self.assertEqual(paths[self.second], ['state.md'])
        self.assertEqual(set(paths[rename_revision]), {self.first, 'state.md', renamed})
        self.assertEqual(paths[deletion_revision], [renamed])
        self.assertEqual(changed_paths(self.root, revisions, ':(literal)missing'), {})
        self.assertEqual(changed_paths(self.root, [], ':(literal).'), {})

    def test_batched_paths_do_not_add_merge_only_changes(self):
        git(self.root, 'checkout', '-q', '-b', 'side')
        (self.root / 'side.md').write_text('side', encoding='utf-8')
        git(self.root, 'add', '--', 'side.md')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-q', '-m', 'Side change')
        side = git(self.root, 'rev-parse', 'HEAD').strip()
        git(self.root, 'checkout', '-q', '--detach', self.second)
        self.commit('Main change', 'Main change')
        git(self.root, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            'merge', '-q', '--no-ff', 'side', '-m', 'Merge side')
        merge = git(self.root, 'rev-parse', 'HEAD').strip()
        paths = changed_paths(self.root, [merge, side, self.first], ':(literal).')
        self.assertEqual(paths.get(merge, []), [])
        self.assertEqual(paths[side], ['side.md'])
        self.assertEqual(paths[self.first], ['state.md'])


if __name__ == '__main__':
    unittest.main()
