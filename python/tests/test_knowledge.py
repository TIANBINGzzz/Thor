import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx


def result(index, *, locator=None):
    return {
        'id': f'chunk-{index}',
        'knowledge_id': f'doc-{index}',
        'chunk_index': index,
        'knowledge_title': f'标题 {index}',
        'knowledge_filename': f'doc-{index}.pdf',
        'content': f'依据正文 {index}',
        'score': 0.9 - index / 100,
        'source_locators': locator if isinstance(locator, list) else [locator] if locator else [],
    }


def knowledge_config(*, results=1):
    return {
        'purposes': [{'ref':'policy','name':'政策','description':'政策文件'}],
        'connections': {
            'school': {'provider':'weknora','baseUrl':'https://weknora.test',
                'credentials':{'api_key':'retrieve-key'},'config':{'workspace_id':51},
                'timeoutSeconds':10,'maxResults':results},
        },
        'libraries': [{'ref':'policy-lib','purposeRef':'policy','name':'政策库',
            'connectionRef':'school','externalId':'external-kb','config':{}}],
    }


class KnowledgeAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_emits_bounded_normalized_sources_and_deduplicates_chunks(self):
        from runtime.knowledge import KnowledgeSession

        locators = [
            {'type':'pdf','page':3,'bbox':[0.1,0.2,0.5,0.6], 'quote':'引文' + '界' * 310,
             'source_id':'private-source','source_hash':'private-hash'},
            {'type':'docx','block':8,'quote':'段落'},
            {'type':'slide','slide':2,'title':'目录','quote':'幻灯片'},
            {'type':'sheet','sheet':'招生','row_start':10,'row_end':12,'quote':'表格'},
            {'type':'text','start':25,'end':48,'quote':'文本'},
            {'type':'section','section':4,'partial':True,'title':'附录','quote':'部分'},
        ]
        data = [result(index, locator=locators if index == 1 else None) for index in range(1, 22)]
        data.append(result(1, locator=locators))
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'data':data})

        transport = httpx.MockTransport(respond)
        client_factory = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
        events = []
        session = KnowledgeSession(knowledge_config(results=30), 'run-knowledge', events.append,
                                   client_factory=client_factory)
        output = await session.search('政策的适用对象？', purpose='policy', limit=30)

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path,
                         '/api/v1/knowledge-bases/external-kb/hybrid-search')
        self.assertEqual(requests[0].headers['x-tenant-id'], '51')
        self.assertEqual(json.loads(requests[0].content)['match_count'], 30)
        hits = output['libraries'][0]['results']
        self.assertEqual(len(hits), 21)
        self.assertEqual(hits[0]['ref'], 'k1')
        self.assertEqual(hits[-1]['ref'], 'k21')
        self.assertNotIn('external-kb', json.dumps(output))
        self.assertNotIn('chunk-1', json.dumps(output))
        self.assertEqual([len(event['payload']['items']) for event in events], [20, 1])
        snapshot = events[0]['payload']['items'][0]
        self.assertEqual(snapshot['documentTitle'], '标题 1')
        self.assertEqual(len(snapshot['sources']), 5)
        self.assertEqual(snapshot['moreLocations'], 1)
        self.assertTrue(snapshot['sources'][0]['quoteTruncated'])
        self.assertEqual(len(snapshot['sources'][0]['quote']), 300)
        self.assertNotIn('source_id', json.dumps(snapshot))
        self.assertNotIn('source_hash', json.dumps(snapshot))
        self.assertEqual(snapshot['sources'][0]['label'], '第 3 页')
        self.assertEqual(snapshot['sources'][4]['label'], '字符 25-48')
        self.assertEqual(events[0]['_source_records'][0]['chunk_id'], 'chunk-1')
        self.assertNotIn('source_locators', json.dumps(events[0]['_source_records'][0]))

    async def test_search_uses_all_purposes_when_omitted_and_passes_library_tags(self):
        from runtime.knowledge import KnowledgeSession

        config = knowledge_config()
        config['libraries'][0]['config']['tag_ids'] = ['tag-policy']
        requests = []
        transport = httpx.MockTransport(lambda request: (
            requests.append(request) or httpx.Response(200, json={'data': []})))
        client_factory = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
        session = KnowledgeSession(config, 'run-knowledge', lambda event: None,
                                   client_factory=client_factory)

        output = await session.search('政策问题')

        self.assertEqual(len(output['libraries']), 1)
        self.assertEqual(json.loads(requests[0].content)['tag_ids'], ['tag-policy'])

    def test_partial_source_has_no_display_label_and_preserves_typed_fields(self):
        from runtime.knowledge import _normalize_locator

        source = _normalize_locator({'type':'audio','section':4,'startMs':100,'endMs':220,
                                     'partial':True,'quote':'原文'})

        self.assertEqual(source['label'], '')
        self.assertEqual(source['section'], 4)
        self.assertEqual(source['startMs'], 100)
        self.assertEqual(source['endMs'], 220)

    def test_knowledge_is_registered_as_a_trusted_tool_provider(self):
        from runtime.tool_registry import PROVIDERS, TOOL_CATALOG

        definition = TOOL_CATALOG.resolve('knowledge')

        self.assertEqual([item.ref for item in definition.operations],
                         ['knowledge_search', 'knowledge_read'])
        self.assertIsNotNone(PROVIDERS['knowledge'].create)

    async def test_read_uses_the_run_reference_and_returns_the_full_chunk(self):
        from runtime.knowledge import KnowledgeSession

        def respond(request):
            if request.method == 'POST':
                return httpx.Response(200, json={'data':[result(1)]})
            self.assertEqual(request.url.path, '/api/v1/chunks/by-id/chunk-1')
            return httpx.Response(200, json={'success':True,
                'data':{'id':'chunk-1','content':'分块完整正文','knowledge_id':'doc-1'}})

        transport = httpx.MockTransport(respond)
        client_factory = lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs)
        session = KnowledgeSession(knowledge_config(), 'run-read', lambda event: None,
                                   client_factory=client_factory)
        await session.search('政策问题', purpose='policy')
        content = await session.read('k1')
        self.assertEqual(content, {'ref':'k1','libraryName':'政策库','documentTitle':'标题 1',
                                   'content':'分块完整正文'})

    def test_public_event_translation_drops_private_source_records(self):
        from server import _public_internal_event

        snapshot = {'ref':'k1','libraryName':'政策库','documentTitle':'政策.pdf',
                    'excerpt':'原文','excerptTruncated':False,'sources':[],'moreLocations':0}
        raw = {'type':'knowledge.sources','payload':{'items':[snapshot]},
               '_source_records':[{'external_library_id':'private-kb','chunk_id':'private-chunk'}]}
        public = _public_internal_event('run-knowledge', raw)
        self.assertEqual(public, {'runId':'run-knowledge','type':'knowledge.sources',
                                  'payload':{'items':[snapshot]}})
        self.assertNotIn('private-kb', json.dumps(public))
        self.assertNotIn('private-chunk', json.dumps(public))

    async def test_agent_event_stores_private_mapping_and_publishes_only_snapshot(self):
        from runtime.run_store import RunStore
        import server

        store = RunStore(':memory:')
        store.create_run('run-knowledge', status='running', tenant_id='school')
        snapshot = {'ref':'k1','libraryName':'政策库','documentTitle':'政策.pdf',
                    'excerpt':'引用原文','excerptTruncated':False,'sources':[],'moreLocations':0}
        raw = {'type':'knowledge.sources','payload':{'items':[snapshot]},
               '_source_records':[{'ref':'k1','connection_ref':'school','library_ref':'policy',
                   'external_library_id':'private-kb','knowledge_id':'private-doc','chunk_id':'private-chunk',
                   'chunk_index':1,'snapshot':snapshot}]}
        with (
            patch.object(server, 'RUN_STORE', store),
            patch.object(server, '_notify_stored_event', new=AsyncMock()),
        ):
            await server._handle_agent_event('run-knowledge', raw)

        saved = store._connection.execute(
            'SELECT external_library_id,chunk_id FROM run_knowledge_sources').fetchone()
        event = store.events_after('run-knowledge')[0]
        self.assertEqual(saved['external_library_id'], 'private-kb')
        self.assertEqual(saved['chunk_id'], 'private-chunk')
        self.assertNotIn('private-kb', json.dumps(event))
        self.assertNotIn('private-chunk', json.dumps(event))
        store.close()
