import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


HERE = Path(__file__).resolve().parent
SERVER = HERE.parents[1] / 'recall-traces/scripts/recall_mcp.py'
WORKFLOWS = ('literal', 'trigram')


async def compare(queries, characters):
    config = {
        'sources': [{'name': 'notes', 'plugin': 'notes', 'roots': [str(HERE / 'notes')]}],
        'operations': [{'name': 'fuzzy', 'module': 'trigram_selector'}],
    }
    results, calls = [], []
    with tempfile.TemporaryDirectory(prefix='recall-workflows-') as folder:
        config_path = Path(folder) / 'sources.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        server = StdioServerParameters(command=sys.executable, args=[str(SERVER), '--sources', str(config_path)])
        async with stdio_client(server) as streams, ClientSession(*streams) as session:
            await session.initialize()

            async def call(name, arguments):
                response = await session.call_tool(name, arguments)
                if response.is_error:
                    raise RuntimeError(str(response.content))
                result = response.structured_content
                if result != json.loads(response.content[0].text):
                    raise RuntimeError('MCP text and structured results differ.')
                calls.append({'tool': name, 'arguments': arguments, 'response': result})
                if result['outcome']['status'] != 'success':
                    raise RuntimeError(json.dumps(result['outcome'], ensure_ascii=False))
                return result

            for query in queries:
                for workflow in WORKFLOWS:
                    recipe = json.loads((HERE / f'{workflow}.json').read_text(encoding='utf-8'))
                    recipe['steps'][-1]['parameters']['query'] = query
                    recipe['characters'] = characters
                    found = await call('operation_run', recipe)
                    sources = []
                    for record in found['records']:
                        evidence = record['evidence'][0]
                        reopened = await call('read', {'evidence': evidence, 'lines': 40, 'characters': characters})
                        locator = evidence['locator'].split(' start=')[0]
                        sources.append({'file': Path(locator).name, 'evidence': evidence,
                                        'text': '\n'.join(r['text'] for r in reopened['records'])})
                    results.append({'query': query, 'workflow': workflow, 'outcome': found['outcome'], 'sources': sources})
    return {'kind': 'Synthetic corpus; actual MCP calls. Queries supplied by the caller, no model involved.',
            'results': results, 'calls': calls}


def failure_messages(error):
    if isinstance(error, BaseExceptionGroup):
        return '\n'.join(failure_messages(child) for child in error.exceptions)
    return str(error)


def main():
    parser = argparse.ArgumentParser(description='Compare two starter recall workflows on the same synthetic notes.')
    parser.add_argument('--query', action='append', help='Repeat for several queries; default: invoice, gardens, duplicate')
    parser.add_argument('--characters', type=int, default=6000, help='Explicit budget sent to each MCP call')
    parser.add_argument('--json', action='store_true', help='Include the full MCP calls and responses')
    args = parser.parse_args()
    if args.characters < 1:
        parser.error('--characters must be positive')
    try:
        result = asyncio.run(compare(args.query or ['invoice', 'gardens', 'duplicate'], args.characters))
    except Exception as error:
        print(f'Comparison failed: {failure_messages(error)}', file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print('Synthetic notes, actual MCP calls; no model or personal source configuration.\n')
    print('| Query | Workflow | Hits | Sources |\n|---|---|---:|---|')
    for row in result['results']:
        query = row['query'].replace('|', '\\|').replace('\n', ' ')
        files = ', '.join(source['file'] for source in row['sources']) or '(none)'
        print(f"| {query} | {row['workflow']} | {len(row['sources'])} | {files} |")
    for row in result['results']:
        for source in row['sources']:
            print(f"\n{row['workflow']} / {row['query']} / {source['file']} — source read:\n{source['text']}")
    print('\nThe examples illustrate matching behavior, not comparative retrieval quality.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
