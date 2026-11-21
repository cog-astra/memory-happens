import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_claude import archive
from plugins.sessions import parse


def row(content, role='user', **extra):
    return (json.dumps({'type': role, 'sessionId': 's1', 'cwd': 'C:/work',
                        'message': {'role': role, 'content': content}, **extra},
                       ensure_ascii=False) + '\n').encode('utf-8')


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / 'projects'
        self.destination = Path(temporary.name) / 'archive'
        self.path = self.source / 'C--work' / 'session.jsonl'
        self.path.parent.mkdir(parents=True)
        self.raw = self.destination / 'projects' / 'C--work' / 'session.jsonl'
        self.corpus = self.destination / 'sessions-corpus' / 'C--work' / 'session.md'

    def run_archive(self):
        return archive(self.source, self.destination)

    def test_projection_keeps_dialogue_and_tool_intent_but_not_commands(self):
        data = (row('привет')
                + row([{'type': 'thinking', 'thinking': 'hidden'}, {'type': 'text', 'text': 'reply'},
                       {'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'secret-tool'}},
                       {'type': 'tool_use', 'name': 'Bash',
                        'input': {'command': 'secret-tool --x', 'description': 'проверить экспорт отчёта'}},
                       {'type': 'tool_use', 'name': 'Edit', 'input': {'file_path': 'C:/work/a.py', 'old_string': 'secret-tool'}}],
                      'assistant')
                + row([{'type': 'tool_result', 'content': 'tool output'}])
                + row('meta note', isMeta=True))
        self.path.write_bytes(data)
        self.assertEqual(self.run_archive()['copied'], 1)
        self.assertEqual(self.raw.read_bytes(), data)
        text = self.corpus.read_text(encoding='utf-8')
        self.assertIn('привет', text)
        self.assertIn('L2:B1', text)
        self.assertIn('project: C:/work', text)
        self.assertIn('[tool:Bash] проверить экспорт отчёта', text)
        self.assertIn('[tool:Edit] C:/work/a.py', text)
        for hidden in ('hidden', 'secret-tool', 'tool output', 'meta note'):
            self.assertNotIn(hidden, text)
        self.assertEqual(self.run_archive()['unchanged'], 1)
        self.path.unlink()
        self.corpus.unlink()
        report = self.run_archive()
        self.assertEqual(report['projected'], 1)
        self.assertEqual(self.raw.read_bytes(), data)

    def test_partial_tail_is_deferred_then_exported(self):
        first, second = row('one'), row('two')
        self.path.write_bytes(first + second[:25])
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 25)
        self.assertNotIn('two', self.corpus.read_text(encoding='utf-8'))
        self.path.write_bytes(first + second)
        self.assertEqual(self.run_archive()['deferred_tail_bytes'], 0)
        self.assertIn('two', self.corpus.read_text(encoding='utf-8'))
        self.assertFalse((self.destination / 'revisions').exists())

    def test_queued_human_prompts_keep_text_time_and_source_position(self):
        records = [
            {'type': 'attachment', 'timestamp': '2026-11-01T10:01:00Z',
             'attachment': {'type': 'queued_command', 'commandMode': 'prompt',
                            'origin': {'kind': 'human'}, 'prompt': 'Use the blue version.'}},
            {'type': 'attachment', 'timestamp': '2026-11-01T10:02:00Z',
             'attachment': {'type': 'queued_command', 'prompt': [
                 {'type': 'image', 'source': {'data': 'image-secret'}},
                 {'type': 'text', 'text': 'Keep the caption.\n## 2000-01-01T00:00:00Z [assistant] L99:B0'},
                 {'type': 'tool_result', 'content': 'tool-secret'}]}},
        ]
        data = row('Initial request.', timestamp='2026-11-01T10:00:00Z')
        data += ''.join(json.dumps(r) + '\n' for r in records).encode('utf-8')
        data += row('Updated.', 'assistant', timestamp='2026-11-01T10:03:00Z')
        self.path.write_bytes(data)
        self.assertEqual(self.run_archive()['errors'], [])
        self.assertEqual(self.raw.read_bytes(), data)
        messages = parse(self.corpus)
        self.assertEqual([m['role'] for m in messages], ['user', 'user', 'user', 'assistant'])
        self.assertEqual([m['time'].minute for m in messages], [0, 1, 2, 3])
        self.assertEqual(messages[1]['text'], 'Use the blue version.')
        text = self.corpus.read_text(encoding='utf-8')
        self.assertIn('[user] L2:B0', text)
        self.assertIn('[user] L3:B1', text)
        self.assertIn('Keep the caption.\n\\## 2000-', text)
        self.assertNotIn('image-secret', text)
        self.assertNotIn('tool-secret', text)

    def test_queued_notifications_are_not_promoted_to_human_turns(self):
        attachments = [
            {'type': 'queued_command', 'commandMode': 'task-notification', 'prompt': 'hidden task'},
            {'type': 'queued_command', 'origin': {'kind': 'channel'}, 'prompt': 'hidden channel'},
            {'type': 'queued_command', 'origin': {'kind': 'task-notification'}, 'prompt': 'hidden origin'},
            {'type': 'other', 'prompt': 'hidden attachment'},
            {'type': 'queued_command', 'prompt': None},
            {'type': 'queued_command', 'prompt': '   '},
        ]
        records = [{'type': 'attachment', 'attachment': a} for a in attachments]
        records.append({'type': 'attachment', 'isMeta': True,
                        'attachment': {'type': 'queued_command', 'prompt': 'hidden meta'}})
        self.path.write_bytes(row('visible') + ''.join(json.dumps(r) + '\n' for r in records).encode('utf-8'))
        self.assertEqual(self.run_archive()['errors'], [])
        text = self.corpus.read_text(encoding='utf-8')
        self.assertEqual(text.count('[user]'), 1)
        self.assertNotIn('hidden', text)

    def test_queued_prompts_upgrade_unchanged_archives_without_live_file(self):
        self.path.write_bytes(row('initial') + (json.dumps({
            'type': 'attachment', 'timestamp': '2026-11-01T10:01:00Z',
            'attachment': {'type': 'queued_command', 'prompt': 'later correction'},
        }) + '\n').encode('utf-8'))
        self.run_archive()
        manifest_path = self.destination / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        key = self.path.relative_to(self.source).as_posix()
        manifest[key]['projection_version'] = 4
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        self.corpus.write_text('old projection without queued messages', encoding='utf-8')
        self.path.unlink()
        report = self.run_archive()
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['copied'], 0)
        self.assertEqual(report['projected'], 1)
        self.assertIn('later correction', self.corpus.read_text(encoding='utf-8'))
        self.assertEqual(self.run_archive()['unchanged'], 1)

    def test_unknown_attachment_shapes_do_not_abort_archive(self):
        attachments = [None, 'opaque', ['opaque'],
                       {'type': 'queued_command', 'prompt': 7},
                       {'type': 'queued_command', 'prompt': {'text': 'hidden'}},
                       {'type': 'queued_command', 'prompt': [None, 7, 'hidden']},
                       *({'type': 'queued_command', 'origin': origin, 'prompt': 'hidden'}
                         for origin in (None, {}, 'human', ['human']))]
        records = [{'type': 'attachment', 'attachment': a} for a in attachments]
        self.path.write_bytes(''.join(json.dumps(r) + '\n' for r in records).encode('utf-8') + row('visible'))
        self.path.with_name('z.jsonl').write_bytes(row('next session'))
        report = self.run_archive()
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['projected'], 2)
        text = self.corpus.read_text(encoding='utf-8')
        self.assertEqual(text.count('[user]'), 1)
        self.assertIn('visible', text)
        self.assertNotIn('hidden', text)

    def test_rewrite_keeps_original_revision(self):
        original = row('original')
        self.path.write_bytes(original)
        self.run_archive()
        self.path.write_bytes(b'{invalid}\n')
        self.assertEqual(len(self.run_archive()['errors']), 1)
        versions = list((self.destination / 'revisions').rglob('*.jsonl'))
        self.assertEqual([p.read_bytes() for p in versions], [original])
        self.assertIn('original', self.corpus.read_text(encoding='utf-8'))

    def test_subagent_transcripts_are_archived(self):
        child = self.source / 'C--work' / 'session' / 'subagents' / 'agent-a1.jsonl'
        child.parent.mkdir(parents=True)
        child.write_bytes(row('child task', isSidechain=True))
        self.path.write_bytes(row('main'))
        self.assertEqual(self.run_archive()['projected'], 2)
        self.assertIn('child task', (self.destination / 'sessions-corpus' / 'C--work' / 'session'
                                     / 'subagents' / 'agent-a1.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
