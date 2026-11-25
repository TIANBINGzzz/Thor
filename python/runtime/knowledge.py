"""通过 WeKnora REST API 检索授权库并保存本 Run 的分块引用。"""

import json
import httpx

from knowledge.providers import PROVIDERS
from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.declarations import operation


MAX_SOURCE_LOCATORS = 5
MAX_SOURCE_QUOTE = 300
MAX_SOURCE_REFS_PER_EVENT = 20


class KnowledgeSession:
    def __init__(self, configuration, run_id, event_sink, *, client_factory=httpx.AsyncClient):
        self.configuration = configuration
        self.run_id = run_id
        self.event_sink = event_sink
        self.client_factory = client_factory
        self._sources = {}
        self._dedupe = {}

    async def search(self, query, *, purpose=None, limit=None):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('knowledge_query_required')
        purposes = {item['ref'] for item in self.configuration['purposes']}
        if purpose is not None and purpose not in purposes:
            raise ValueError('knowledge_purpose_unavailable')

        libraries = [item for item in self.configuration['libraries']
                     if purpose is None or item['purposeRef'] == purpose]
        output_libraries = []
        new_snapshots = []
        new_records = []
        seen_this_search = set()
        for library in libraries:
            connection = self.configuration['connections'][library['connectionRef']]
            match_count = min(limit or connection['maxResults'], connection['maxResults'])
            provider = PROVIDERS[connection['provider']]
            hits = await provider.search(connection, library, query.strip(), match_count,
                                         client_factory=self.client_factory)
            results = []
            for hit in hits:
                key = (library['connectionRef'], library['externalId'], hit['chunkId'])
                if key in seen_this_search:
                    continue
                seen_this_search.add(key)
                ref = self._dedupe.get(key)
                if ref is None:
                    ref = f'k{len(self._sources) + 1}'
                    snapshot = _source_snapshot(ref, library, hit)
                    record = {
                        'ref': ref,
                        'connection_ref': library['connectionRef'],
                        'library_ref': library['ref'],
                        'external_library_id': library['externalId'],
                        'knowledge_id': hit['documentId'],
                        'chunk_id': hit['chunkId'],
                        'chunk_index': hit['chunkIndex'],
                        'snapshot': snapshot,
                    }
                    self._dedupe[key] = ref
                    self._sources[ref] = (connection, library, record)
                    new_snapshots.append(snapshot)
                    new_records.append(record)
                snapshot = self._sources[ref][2]['snapshot']
                results.append({
                    'ref': ref,
                    'citation': f'[^{ref}]',
                    'libraryName': library['name'],
                    'documentTitle': hit['documentTitle'],
                    'chunkIndex': hit['chunkIndex'],
                    'excerpt': snapshot['excerpt'],
                    'excerptTruncated': snapshot['excerptTruncated'],
                    'sources': snapshot['sources'],
                    'score': hit['score'],
                })
            output_libraries.append({'purposeRef': library['purposeRef'], 'libraryName': library['name'], 'results': results})

        for start in range(0, len(new_snapshots), MAX_SOURCE_REFS_PER_EVENT):
            self.event_sink({
                'type': 'knowledge.sources',
                'payload': {'items': new_snapshots[start:start + MAX_SOURCE_REFS_PER_EVENT]},
                '_source_records': new_records[start:start + MAX_SOURCE_REFS_PER_EVENT],
            })
        return {'libraries': output_libraries}

    async def read(self, ref):
        connection, library, record = self._sources[ref]
        content = await PROVIDERS[connection['provider']].read(
            connection, record['chunk_id'], client_factory=self.client_factory)
        return {
            'ref': ref,
            'libraryName': library['name'],
            'documentTitle': record['snapshot']['documentTitle'],
            'content': content,
        }


def _source_snapshot(ref, library, result):
    content = result['content']
    locators = result['locations']
    sources = [_normalize_locator(item) for item in locators[:MAX_SOURCE_LOCATORS]]
    return {
        'ref': ref,
        'libraryName': library['name'],
        'documentTitle': result['documentTitle'],
        'excerpt': content[:MAX_SOURCE_QUOTE],
        'excerptTruncated': len(content) > MAX_SOURCE_QUOTE,
        'sources': sources,
        'moreLocations': max(0, len(locators) - MAX_SOURCE_LOCATORS),
    }


def _normalize_locator(locator):
    quote = locator['quote']
    partial = locator.get('partial', False)
    normalized = {
        'type': locator['type'],
        'label': '' if partial else _locator_label(locator),
        'partial': partial,
        'quote': quote[:MAX_SOURCE_QUOTE],
        'quoteTruncated': len(quote) > MAX_SOURCE_QUOTE,
    }
    for source, target in (
        ('page', 'page'), ('bbox', 'bbox'), ('block', 'block'), ('slide', 'slide'),
        ('sheet', 'sheet'), ('rowStart', 'rowStart'), ('rowEnd', 'rowEnd'),
        ('start', 'start'), ('end', 'end'),
        ('startMs', 'startMs'), ('endMs', 'endMs'), ('section', 'section'),
    ):
        if source in locator:
            normalized[target] = locator[source]
    return normalized


def _locator_label(locator):
    if 'page' in locator:
        return f"第 {locator['page']} 页"
    if 'block' in locator:
        return f"第 {locator['block']} 段"
    if 'slide' in locator:
        title = locator.get('title')
        return f"第 {locator['slide']} 页" + (f"：{title}" if title else '')
    if 'sheet' in locator and 'rowStart' in locator:
        rows = str(locator['rowStart'])
        if locator.get('rowEnd') != locator['rowStart']:
            rows += '-' + str(locator['rowEnd'])
        return f"工作表 {locator['sheet']} 第 {rows} 行"
    if 'start' in locator and 'end' in locator:
        return f"字符 {locator['start']}-{locator['end']}"
    return ''


def provide_tool(definition, context):
    configuration = context['knowledge']
    if not configuration['libraries']:
        return None
    session = KnowledgeSession(configuration, context['run_id'], context['knowledge_sink'])
    search_spec = operation('knowledge', 'knowledge_search')
    read_spec = operation('knowledge', 'knowledge_read')

    @sdk_tool(search_spec.ref, search_spec.description, search_spec.input_schema)
    async def search(arguments):
        result = await session.search(arguments['query'], purpose=arguments.get('purpose'),
                                      limit=arguments.get('limit'))
        return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}

    @sdk_tool(read_spec.ref, read_spec.description, read_spec.input_schema)
    async def read(arguments):
        result = await session.read(arguments['ref'])
        return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}

    return definition.ref, create_sdk_mcp_server('knowledge', version='1.0.0', tools=[search, read])
