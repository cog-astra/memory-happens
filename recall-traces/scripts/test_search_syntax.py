import json
import tempfile
import unittest
from pathlib import Path

from recall_query import syntax_problem
from test_operation_mcp import server


class SearchSyntaxTest(unittest.IsolatedAsyncioTestCase):
    def test_recognizable_syntax_and_literal_words(self):
        for query in ('alpha OR beta', 'alpha AND beta', 'NOT beta', '"Alpha Beta"',
                      '“Alpha Beta”', '"unfinished', 'alpha\nOR\tbeta'):
            with self.subTest(query=query):
                self.assertIsNotNone(syntax_problem(query))
        for query in ('', 'alpha beta', 'this or that', 'and', 'OR', 'ordinary',
                      "don't forget", 'симкарт', 'operand ORacle'):
            with self.subTest(query=query):
                self.assertIsNone(syntax_problem(query))

    async def test_configured_and_legacy_search_explain_syntax_without_findings(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            notes = base / 'notes'
            notes.mkdir()
            (notes / 'noise.md').write_text('The worker handles ordinary requests.\n', encoding='utf-8')
            (notes / 'phrase.md').write_text('Alpha appears here.\nBeta appears elsewhere.\n', encoding='utf-8')
            config = base / 'sources.json'
            config.write_text(json.dumps({'spaces': [], 'sources': [
                {'plugin': 'notes', 'name': 'notes', 'roots': [str(notes)]}]}), encoding='utf-8')
            queries = ('"unfindable" OR "missingword"', 'absent AND missing', 'NOT absent', '"Alpha Beta"')

            async with server('--sources', str(config)) as session:
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                self.assertIn('No Boolean', tools['search'].input_schema['properties']['query']['description'])
                for query in queries:
                    for target in ('all', 'root', 'notes', 'folder'):
                        with self.subTest(query=query, target=target):
                            if target in ('all', 'root'):
                                name = 'search'
                                arguments = {'query': query, 'characters': 10000}
                                if target == 'root':
                                    arguments['root'] = str(notes)
                            else:
                                name = 'operation_run'
                                parameters = {'query': query}
                                if target == 'folder':
                                    parameters['root'] = str(notes)
                                arguments = {'characters': 10000, 'steps': [
                                    {'name': 'found', 'plugin': target, 'operation': 'search', 'parameters': parameters}]}
                            response = await session.call_tool(name, arguments)
                            self.assertFalse(response.is_error, response)
                            result = response.structured_content
                            self.assertEqual(result['records'], [])
                            self.assertEqual(result['outcome']['status'], 'unsupported')
                            self.assertEqual(result['outcome']['code'], 'unsupported_query_syntax')
                            self.assertIn('No search was performed', result['outcome']['message'])
                            self.assertTrue(result['outcome']['next_steps'])
                for query, expected in (('or', 'noise.md'), ('OR', 'noise.md'), ('Alpha', 'phrase.md')):
                    response = await session.call_tool('search', {'query': query, 'characters': 10000})
                    result = response.structured_content
                    self.assertEqual(result['outcome']['status'], 'success')
                    self.assertEqual(len(result['records']), 1)
                    self.assertIn(expected, result['records'][0]['evidence'][0]['locator'])

            async with server(env={'RECALL_CONFIG': str(config)}) as session:
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                self.assertIn('No Boolean', tools['search'].input_schema['properties']['query']['description'])
                for query in queries:
                    for root in (None, str(notes)):
                        with self.subTest(legacy=query, root=root):
                            arguments = {'query': query, 'characters': 10000}
                            if root:
                                arguments['root'] = root
                            response = await session.call_tool('search', arguments)
                            self.assertFalse(response.is_error, response)
                            text = response.content[0].text
                            self.assertIn('Unsupported query syntax', text)
                            self.assertIn('No search was performed', text)
                            self.assertNotIn('read:', text)
                response = await session.call_tool('search', {'query': 'or', 'characters': 10000})
                self.assertIn('noise.md', response.content[0].text)
                self.assertIn('read:', response.content[0].text)


if __name__ == '__main__':
    unittest.main()
