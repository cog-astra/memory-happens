import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import recall_bounds
import recall_mcp
from recall_core import Recall

SESSION = """# Claude session {name}.jsonl
raw: {name}.jsonl
session: {name}
project: {project}
origin: cli

## 2026-09-20T08:00:00.000Z [user] L1:B0

Let's build a garden with a stone path

## 2026-09-20T08:01:00.000Z [assistant] L2:B0

## A heading inside the reply

Built the Garden scene.

## 2026-09-20T09:00:00.000Z [user] L3:B0

[timer: fired]

## 2026-09-20T09:05:00.000Z [user] L4:B0

great, orchard next

## 2026-09-22T10:00:00.000Z [user] L5:B0

back to the fence

## 2026-09-22T10:01:00.000Z [assistant] L6:B0

The fence is ready.
"""

PLUGIN = """from datetime import datetime, timezone
from recall_core import Source

class Plugin(Source):
    title = 'diary'

    def recent(self, since):
        yield {'time': datetime(2026, 9, 21, 12, tzinfo=timezone.utc), 'where': 'diary',
               'bound': {'path': None}, 'headline': 'entry about the lighthouse', 'locator': None}

    def search(self, words, since):
        if 'lighthouse' in words:
            yield {'time': datetime(2026, 9, 21, 12, tzinfo=timezone.utc), 'where': 'diary',
                   'bound': {'path': None}, 'label': 'diary', 'matched': ['lighthouse'], 'total': 1,
                   'places': [], 'excerpt': 'entry about the lighthouse', 'locator': 'diary'}
"""


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


def commit(repo, path, text, message):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text, encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)


class RecallTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = base = Path(temporary.name)
        self.work = base / 'work'
        self.work.mkdir()
        git(self.work, 'init', '-q')
        commit(self.work, 'garden.gd', 'x', 'Add the garden\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')
        self.space = base / 'spaces' / 'alice'
        self.space.mkdir(parents=True)
        git(self.space, 'init', '-q')
        commit(self.space, 'open/f.txt', 'o', 'game: open change')
        commit(self.space, 'closed/f.txt', 'c', 'game: private change')
        self.rules = self.space / 'humans.txt'
        self.rules.write_text('Bounds.\n\n[recall]\nopen = open/\nguests = guests/\n', encoding='utf-8')
        self.corpus = base / 'archive' / 'corpus'
        for name, project in (('abc', self.work), ('closed', self.space / 'closed'), ('open', self.space / 'open')):
            path = self.corpus / 'C--Work' / f'{name}.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SESSION.format(name=name, project=project), encoding='utf-8')
        (self.corpus / 'C--Work' / 'abc' / 'subagents').mkdir(parents=True)
        (self.corpus / 'C--Work' / 'abc' / 'subagents' / 'agent.md').write_text(
            SESSION.format(name='agent', project=self.work), encoding='utf-8')
        projects = base / 'projects'
        for project in (self.work, self.space, self.space / 'open'):
            memory = projects / recall_bounds.slug(project) / 'memory'
            memory.mkdir(parents=True)
            (memory / 'MEMORY.md').write_text('- index\n', encoding='utf-8')
            (memory / 'garden.md').write_text('---\nname: garden\ndescription: "Garden scene, game"\n---\n', encoding='utf-8')
        vault = base / 'vault'
        (vault / 'Places').mkdir(parents=True)
        (vault / '.obsidian').mkdir()
        (vault / '.obsidian' / 'x.md').write_text('# service garden\n', encoding='utf-8')
        (vault / 'Places' / 'Cape.md').write_text('# Cape\n\nA lighthouse on the northern cape.\n', encoding='utf-8')
        self.cfg = {'spaces': [str(base / 'spaces')], 'sources': [
            {'plugin': 'sessions', 'stores': [{'corpus': str(self.corpus), 'archiver': 'archive_claude.py'}],
             'service_prefixes': ['<', '[timer:']},
            {'plugin': 'memory', 'roots': [str(projects)]},
            {'plugin': 'notes', 'roots': [str(vault)]},
            {'plugin': 'git', 'repos': [str(self.work)], 'discover': [str(base / 'spaces')]}]}
        self.outsider = base / 'elsewhere'
        self.since = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def recall(self, reader=None, **changes):
        return Recall({**self.cfg, **changes}, reader=str(reader or self.outsider))

    def assert_locators_read(self, recall, text):
        for target in re.findall(r'read: (.+)$', text, re.MULTILINE):
            answer = recall.read(target, lines=2)
            self.assertFalse(answer.startswith(('No file', 'Closed', 'No revision')), target)

    def sessions_seen(self, recall):
        return {Path(hit['locator'].split(' start=')[0]).stem
                for title, hits in recall.search(['game', 'garden']) if title == 'sessions' for hit in hits}

    def test_session_splits_by_day_and_service_lines_are_not_the_human(self):
        traces = [t for t in self.recall().recent(self.since) if t['source'] == 'sessions']
        days = sorted(traces, key=lambda t: t['time'])
        self.assertEqual(len(days), 4)
        self.assertEqual(days[0]['quotes'][:2], ["> Let's build a garden with a stone path", '> great, orchard next'])
        self.assertIn('human turns: 2', days[0]['headline'])
        self.assertIn('open since', days[-1]['headline'])
        self.assertTrue(days[-1]['automated'])

    def test_recent_collects_every_source_and_every_locator_reads(self):
        recall = self.recall()
        traces = recall.recent(self.since)
        self.assertEqual({t['source'] for t in traces}, {'sessions', 'memory', 'notes', 'git'})
        self.assertNotIn('.obsidian', ' '.join(str(t.get('locator')) for t in traces))
        self.assert_locators_read(recall, recall_mcp.render_recent(traces, 50000))

    def test_window_and_where_narrow_the_ribbon(self):
        late = datetime(2026, 9, 21, tzinfo=timezone.utc)
        quotes = [t['quotes'][0] for t in self.recall().recent(late, where='work') if t['source'] == 'sessions']
        self.assertEqual(quotes, ['> back to the fence'])
        self.assertEqual(self.recall().recent(self.since, where='no-such-place'), [])

    def test_no_day_disappears_silently_under_any_budget(self):
        traces = self.recall().recent(self.since)
        days = {recall_mcp.local(t['time']).date() for t in traces}
        for characters in (100, 150, 300, 600, 50000):
            text = recall_mcp.render_recent(traces, characters)
            hidden = re.search(r'earlier days that did not fit: (\d+)', text)
            shown = len(re.findall(r'^## ', text, re.MULTILINE))
            self.assertEqual(shown + (int(hidden[1]) if hidden else 0), len(days), characters)

    def test_search_ranks_by_distinct_words_dates_the_reply_and_splits_long_sessions(self):
        recall = self.recall()
        found = dict(recall.search(['lighthouse', 'cape']))
        self.assertEqual(found['notes'][0]['matched'], ['lighthouse', 'cape'])
        found = dict(recall.search(['fence', 'garden'], where='work'))
        days = sorted(recall_mcp.local(hit['time']).date().isoformat() for hit in found['sessions'])
        self.assertEqual(days, ['2026-09-20', '2026-09-22'])
        self.assertTrue(found['git'] and found['project memory'])
        self.assertIn('[co-author: Claude Opus 5.5]', found['git'][0]['excerpt'])
        self.assert_locators_read(recall, recall_mcp.render_search(recall.search(['garden']), ['garden'], 8, 50000))

    def test_read_continues_where_it_stopped_and_accepts_the_whole_read_line(self):
        recall = self.recall()
        path = self.corpus / 'C--Work' / 'abc.md'
        text = recall.read(f'read: {path} start=7', lines=2)
        self.assertTrue(text.startswith('7: '))
        following = int(re.search(r'start=(\d+)', text)[1])
        self.assertTrue(recall.read(str(path), following, 1).startswith(f'{following}: '))

    def test_broken_or_silent_sources_announce_what_and_how(self):
        live = self.base / 'live'
        live.mkdir()
        (live / 'new.jsonl').write_text('{}\n', encoding='utf-8')
        for path in self.corpus.rglob('*.md'):
            os.utime(path, (time.time() - 7200, time.time() - 7200))
        (self.corpus.parent / 'status.json').write_text(
            json.dumps({'checked_at': '2026-09-01T00:00:00+00:00', 'errors': [{}]}), encoding='utf-8')
        sources = [{**self.cfg['sources'][0], 'stores': [{'corpus': str(self.corpus), 'live': str(live),
                                                          'archiver': 'archive_claude.py'}]},
                   {'plugin': 'notes', 'roots': [str(self.base / 'missing-vault')]}]
        text = recall_mcp.preface(self.recall(sources=sources))
        for expected in ('archive_claude.py', 'status.json', 'silent', 'missing-vault'):
            self.assertIn(expected, text)

    def test_neighbour_sees_only_what_the_owner_opened(self):
        recall = self.recall()
        self.assertEqual(self.sessions_seen(recall), {'abc', 'open'})
        commits = [hit['excerpt'] for title, hits in recall.search(['game']) if title == 'git' for hit in hits]
        self.assertEqual([c.split(' ', 1)[1] for c in commits], ['game: open change'])
        memory = {hit['where'] for title, hits in recall.search(['game']) if title == 'project memory' for hit in hits}
        self.assertNotIn(recall_bounds.slug(self.space), {m.casefold() for m in memory})

    def test_owner_sees_everything_and_guest_stays_a_neighbour(self):
        self.assertEqual(self.sessions_seen(self.recall(self.space)), {'abc', 'open', 'closed'})
        self.assertEqual(self.sessions_seen(self.recall(self.space / 'guests' / 'visitor')), {'abc', 'open'})

    def test_rules_decide_and_the_rules_themselves_stay_readable(self):
        self.rules.write_text('For people only.\n', encoding='utf-8')
        self.assertEqual(self.sessions_seen(self.recall()), {'abc'})
        self.rules.write_text('[recall]\nopen = .\nprivate = closed/\n', encoding='utf-8')
        self.assertEqual(self.sessions_seen(self.recall()), {'abc', 'open'})
        self.rules.write_text('[recall]\nopen = .\n', encoding='utf-8')
        self.assertEqual(self.sessions_seen(self.recall()), {'abc', 'open', 'closed'})
        self.assertEqual(self.recall().bounds.notice(), '')
        self.rules.write_text('For people only.\n', encoding='utf-8')
        refusal = self.recall().read(str(self.space / 'closed' / 'f.txt'))
        self.assertIn(str(self.rules), refusal)
        self.assertIn('[recall] open', refusal)
        self.assertTrue(self.recall().read(str(self.rules)).startswith('1: For people only.'))

    def test_folder_search_needs_no_backend_and_keeps_bounds(self):
        found = dict(self.recall().search_folder(self.base / 'vault', ['lighthouse']))
        self.assertEqual(len(found[f"folder {self.base / 'vault'}"]), 1)
        (self.space / 'open' / 'n.md').write_text('game open', encoding='utf-8')
        (self.space / 'closed' / 'n.md').write_text('game closed', encoding='utf-8')
        hits = dict(self.recall().search_folder(self.space, ['game']))[f'folder {self.space}']
        self.assertEqual([Path(hit['locator'].split(' start=')[0]).parent.name for hit in hits], ['open'])

    def test_search_hit_names_the_excerpt_line_and_counts_what_it_left_out(self):
        rows = ['filler'] * 200
        for number in range(10, 80, 10):
            rows[number - 1] = 'alpha'
        rows[199] = 'alpha beta'
        (self.base / 'vault' / 'Log.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
        text = recall_mcp.render_search(self.recall().search_folder(self.base / 'vault', ['alpha', 'beta']),
                                        ['alpha', 'beta'], 8, 5000)
        self.assertIn('line 200 | alpha beta · also 10, 20, 30, 40, 50 +2 more\n', text)
        self.assertIn('Log.md start=200\n', text)

    def test_hits_made_by_external_plugins_render_without_the_newer_fields(self):
        hit = {'time': datetime.now(timezone.utc), 'label': 'synthetic', 'matched': ['alpha'], 'total': 2,
               'places': [2, 4], 'line': 2, 'excerpt': 'alpha', 'locator': 'synthetic start=2'}
        self.assertIn('  line 2 | alpha · also 4\n', recall_mcp.hit_block(hit, ['alpha']))
        del hit['line']
        self.assertIn('  lines 2, 4 | alpha\n', recall_mcp.hit_block(hit, ['alpha']))

    def test_new_source_plugs_in_without_touching_the_core(self):
        plugin = self.base / 'diary.py'
        plugin.write_text(PLUGIN, encoding='utf-8')
        recall = self.recall(sources=[{'plugin': str(plugin)}])
        self.assertIn('entry about the lighthouse', recall_mcp.render_recent(recall.recent(self.since), 5000))
        self.assertIn('### diary: 1', recall_mcp.render_search(recall.search(['lighthouse']), ['lighthouse'], 8, 5000))


if __name__ == '__main__':
    unittest.main()
