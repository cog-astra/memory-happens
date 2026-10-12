import json
import tempfile
import unittest
from pathlib import Path

from test_operation_mcp import server


class LegacySearchScopeTest(unittest.IsolatedAsyncioTestCase):
    async def test_scope_hint_survives_empty_results_and_keeps_private_hits_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name in ('game', 'misc', 'spaces/alice/closed'):
                folder = base / name
                folder.mkdir(parents=True)
                (folder / 'note.md').write_text('# Prologue\nmonolith\n', encoding='utf-8')
            (base / 'spaces/alice/humans.txt').write_text('[recall]\nopen = open/\n', encoding='utf-8')
            config = base / 'sources.json'
            config.write_text(json.dumps({'spaces': [str(base / 'spaces')], 'sources': [
                {'plugin': 'notes', 'roots': [str(base / 'game'), str(base / 'misc'),
                                            str(base / 'spaces/alice/closed'), str(base / 'missing')]}]}),
                encoding='utf-8')
            async with server(env={'RECALL_CONFIG': str(config)}) as session:
                async def search(**options):
                    reply = await session.call_tool('search', {'query': 'monolith', 'characters': 500, **options})
                    self.assertFalse(reply.is_error, reply)
                    return reply.content[0].text

                scoped = await search(where=str(base / 'game'))
                self.assertIn('[matching records outside where: notes: 1;', scoped)
                self.assertIn('search without where', scoped)
                self.assertIn(str(base / 'game/note.md'), scoped)
                self.assertNotIn(str(base / 'misc/note.md'), scoped)
                self.assertIn('missing', scoped)

                empty = await search(where='no-such-place')
                self.assertIn('[matching records outside where: notes: 2;', empty)
                self.assertIn('Nothing found', empty)
                self.assertNotIn('read:', empty)
                for output in (scoped, empty, await search()):
                    self.assertNotIn(str(base / 'spaces/alice/closed/note.md'), output)

                for options in ({}, {'where': str(base)}, {'root': str(base / 'game'), 'where': 'no-such-place'},
                                {'query': 'absent'}, {'query': 'absent OR missing'}):
                    self.assertNotIn('matching records outside where', await search(**options))


if __name__ == '__main__':
    unittest.main()
