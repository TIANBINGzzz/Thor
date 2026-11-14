import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from tools.web_search import search_web, create_web_server


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_thinking_switch_keeps_reasoning_private(self):
        for switch in (None, False, True):
            with self.subTest(thinking=switch):
                requests = []
                def respond(request):
                    requests.append(json.loads(request.content))
                    return httpx.Response(200, json={'content': [
                        {'type':'server_tool_use','id':'search-1','name':'web_search'},
                        {'type':'web_search_tool_result','tool_use_id':'search-1','content':[
                            {'type':'web_search_result','title':'公开来源','url':'https://example.org/source'}]},
                        {'type':'thinking','thinking':'private-reasoning'},
                        {'type':'text','text':'简短摘要'},
                    ]})
                client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                with patch('tools.web_search.create_sdk_mcp_server') as create:
                    create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
                    tool = create.call_args.kwargs['tools'][0]
                    schema = tool.input_schema
                    self.assertEqual(schema['properties']['thinking']['type'], 'boolean')
                    self.assertNotIn('thinking', tool.input_schema['required'])
                    self.assertEqual(schema['properties']['queries']['maxItems'], 10)
                    arguments = {'queries':['公开检索词']}
                    if switch is not None:
                        arguments['thinking'] = switch
                    with patch('tools.web_search.httpx.AsyncClient', return_value=client):
                        result = await tool.handler(arguments)
                self.assertFalse(result.get('isError'), result)
                self.assertEqual(requests[0]['thinking'], {'type':'enabled' if switch else 'disabled'})
                content = json.loads(result['content'][0]['text'])
                self.assertEqual(content['results'][0]['summary'], '简短摘要')
                self.assertEqual(len(content['results'][0]['sources']), 1)
                self.assertNotIn('private-reasoning', json.dumps(result))

    async def test_mcp_batches_distinct_queries_concurrently_and_keeps_results_grouped(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        started = []
        both_started = asyncio.Event()

        async def search(query, **kwargs):
            started.append(query)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=1)
            return {'summary': f'摘要:{query}', 'sources': [{'url': f'https://example.org/{query}'}],
                    'searchRequests': 1}

        with patch('tools.web_search.search_web', side_effect=search):
            result = await tool.handler({'queries':['政策年份', '行业趋势']})

        self.assertFalse(result.get('isError'), result)
        self.assertCountEqual(started, ['政策年份', '行业趋势'])
        payload = json.loads(result['content'][0]['text'])
        self.assertEqual([item['query'] for item in payload['results']], ['政策年份', '行业趋势'])
        self.assertEqual(payload['results'][0]['summary'], '摘要:政策年份')
        self.assertEqual(payload['results'][1]['sources'][0]['url'], 'https://example.org/行业趋势')

    async def test_mcp_batch_preserves_success_when_one_query_fails(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]

        async def search(query, **kwargs):
            if query == '无结果':
                raise RuntimeError('该查询没有可核验来源')
            return {'summary': '有来源', 'sources': [{'url': 'https://example.org/ok'}], 'searchRequests': 1}

        with patch('tools.web_search.search_web', side_effect=search):
            result = await tool.handler({'queries':['有结果', '无结果']})

        self.assertFalse(result.get('isError'), result)
        payload = json.loads(result['content'][0]['text'])
        self.assertEqual(payload['results'][0]['summary'], '有来源')
        self.assertIn('error', payload['results'][1])

    async def test_search_budget_is_shared_across_server_recreation_within_run(self):
        run_state = {}
        queries = [f'q{index}' for index in range(14)]

        calls = []

        async def record_search(query, **kwargs):
            calls.append(query)
            return {'summary': query, 'sources': [{'url': f'https://example.org/{query}'}],
                    'searchRequests': 1}

        with patch('tools.web_search.create_sdk_mcp_server') as create, \
                patch('tools.web_search.search_web', side_effect=record_search):
            create_web_server(base_url='https://provider.test', api_key='secret',
                              model='qwen', run_state=run_state)
            first_tool = create.call_args.kwargs['tools'][0]
            first = await first_tool.handler({'queries': queries[:8]})
            create_web_server(base_url='https://provider.test', api_key='secret',
                              model='qwen', run_state=run_state)
            second_tool = create.call_args.kwargs['tools'][0]
            second = await second_tool.handler({'queries': queries[8:]})

        first_payload = json.loads(first['content'][0]['text'])
        second_payload = json.loads(second['content'][0]['text'])
        self.assertEqual(len(calls), 10)
        self.assertEqual([item['query'] for item in second_payload['results'][:2]], ['q8', 'q9'])
        self.assertTrue(all('error' in item for item in second_payload['results'][2:]))
        self.assertNotIn('error', first_payload['results'][0])

    async def test_concurrent_batches_cannot_exceed_run_search_budget(self):
        run_state = {}
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen',
                              run_state=run_state)
        tool = create.call_args.kwargs['tools'][0]
        calls = []

        async def search(query, **kwargs):
            calls.append(query)
            await asyncio.sleep(0)
            return {'summary': query, 'sources': [{'url': f'https://example.org/{query}'}],
                    'searchRequests': 1}

        with patch('tools.web_search.search_web', side_effect=search):
            batches = await asyncio.gather(
                tool.handler({'queries':[f'a{i}' for i in range(8)]}),
                tool.handler({'queries':[f'b{i}' for i in range(8)]}),
            )

        self.assertEqual(len(calls), 10)
        capped = sum('error' in item for result in batches
                     for item in json.loads(result['content'][0]['text'])['results'])
        self.assertEqual(capped, 6)

    async def test_mcp_batch_rejects_duplicate_or_more_than_ten_queries(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        invalid = [
            {'queries':[' same ', 'same']},
            {'queries':['q'] * 11},
            {'queries':['']},
            {'queries':['q' * 2001]},
            {'query':'legacy single query'},
        ]
        for arguments in invalid:
            with self.subTest(arguments=arguments):
                with patch('tools.web_search.search_web') as search:
                    result = await tool.handler(arguments)
                self.assertTrue(result.get('isError'))
                search.assert_not_called()

    async def test_mcp_rejects_non_boolean_thinking_and_budget_overrides(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        invalid = [{'queries':['q'],'thinking':value} for value in ('false', 0, 1, None, {}, [])]
        invalid += [{'queries':['q'],'thinking':True,'max_tokens':999999}, {'thinking':True}]
        for arguments in invalid:
            with self.subTest(arguments=arguments), patch('tools.web_search.httpx.AsyncClient') as client:
                result = await tool.handler(arguments)
                self.assertTrue(result.get('isError'))
                client.assert_not_called()

    async def test_native_search_uses_client_marker_and_only_returns_verified_sources(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={'content': [
                {'type': 'server_tool_use', 'id': 'search-1', 'name': 'web_search'},
                {'type': 'web_search_tool_result', 'tool_use_id': 'search-1', 'content': [
                    {'type': 'web_search_result', 'title': '官方文档', 'url': 'https://help.aliyun.com/zh/model-studio/web-search',
                     'encrypted_content': 'omit-this'},
                    {'type': 'web_search_result', 'title': '重复', 'url': 'https://help.aliyun.com/zh/model-studio/web-search'}]},
                {'type': 'thinking', 'thinking': 'private-reasoning'},
                {'type': 'text', 'text': '服务支持联网搜索。'},
            ], 'usage': {'server_tool_use': {'web_search_requests': 1}}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch('tools.web_search.httpx.AsyncClient', return_value=client):
            result = await search_web('百炼联网搜索', base_url='https://provider.test/apps/anthropic',
                                      api_key='model-secret', model='deepseek-v4.1-flash')
        self.assertEqual(len(requests), 1)
        request = requests[0]
        self.assertEqual(request.url.path, '/apps/anthropic/v1/messages')
        self.assertEqual(request.headers['Authorization'], 'Bearer model-secret')
        body = json.loads(request.content)
        self.assertEqual(body['model'], 'deepseek-v4.1-flash')
        self.assertEqual(body['system'][0]['text'], 'x-anthropic-billing-header: cc_entrypoint=cli;')
        self.assertEqual(body['tools'][0]['name'], 'web_search')
        self.assertEqual(body['tools'][0]['max_uses'], 1)
        self.assertEqual(body['thinking'], {'type': 'disabled'})
        self.assertEqual(result['searchRequests'], 1)
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['summary'], '服务支持联网搜索。')
        for private in ('omit-this', 'private-reasoning', 'model-secret'):
            self.assertNotIn(private, json.dumps(result))

    async def test_placeholder_only_results_are_reported_as_unverified_to_agent(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        for url in ('https://dashscope.aliyuncs.com/', 'https://dashscope.aliyuncs.com'):
            with self.subTest(url=url):
                client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
                    'content': [
                        {'type': 'server_tool_use', 'id': 'search-1', 'name': 'web_search'},
                        {'type': 'web_search_tool_result', 'tool_use_id': 'search-1', 'content': [
                            {'type': 'web_search_result', 'title': 'Search result', 'url': url}]},
                        {'type': 'text', 'text': '没有找到可靠来源。'},
                    ]})))
                with patch('tools.web_search.httpx.AsyncClient', return_value=client):
                    result = await tool.handler({'queries': ['公开政策原文']})
                self.assertFalse(result.get('isError'))
                payload = json.loads(result['content'][0]['text'])
                self.assertIn('不能声称已经查证', payload['results'][0]['error'])
                self.assertNotIn(url, result['content'][0]['text'])

    async def test_mixed_results_keep_real_sources_and_available_page_dates(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
            'content': [
                {'type': 'server_tool_use', 'id': 'search-1', 'name': 'web_search'},
                {'type': 'web_search_tool_result', 'tool_use_id': 'search-1', 'content': [
                    {'type': 'web_search_result', 'title': 'Search result', 'url': 'https://dashscope.aliyuncs.com/'},
                    {'type': 'web_search_result', 'title': '政策原文', 'url': 'https://example.gov.cn/policy',
                     'page_age': '2025-09-22', 'encrypted_content': 'private-content'},
                    {'type': 'web_search_result', 'title': 'Search result', 'url': 'https://example.org/article',
                     'page_age': None},
                ]},
            ]})))
        with patch('tools.web_search.httpx.AsyncClient', return_value=client):
            result = await search_web('公开政策', base_url='https://provider.test', api_key='secret', model='qwen')
        self.assertEqual(result['sources'], [
            {'title': '政策原文', 'url': 'https://example.gov.cn/policy', 'page_age': '2025-09-22'},
            {'title': 'Search result', 'url': 'https://example.org/article'},
        ])

    async def test_plain_text_or_unmatched_sources_are_not_successful_searches(self):
        for content in ([{'type': 'text', 'text': '<tool_call>web_search</tool_call>'}],
                        [{'type': 'web_search_tool_result', 'tool_use_id': 'unknown', 'content': [
                            {'type': 'web_search_result', 'url': 'https://fake.test'}]}]):
            with self.subTest(content=content):
                client = httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json={'content': content})))
                with patch('tools.web_search.httpx.AsyncClient', return_value=client), self.assertRaisesRegex(RuntimeError, '来源'):
                    await search_web('query', base_url='https://provider.test', api_key='secret', model='qwen')

    async def test_errors_are_sanitized_and_not_retried(self):
        for response in (httpx.Response(401, text='private-key'), httpx.Response(200, text='private-invalid-json')):
            calls = []
            def respond(request):
                calls.append(request)
                return response
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch('tools.web_search.httpx.AsyncClient', return_value=client), self.assertRaises(RuntimeError) as caught:
                await search_web('query', base_url='https://provider.test', api_key='secret', model='qwen')
            self.assertNotIn('private', str(caught.exception))
            self.assertEqual(len(calls), 1)

    async def test_mcp_rejects_credentials_or_endpoint_in_tool_arguments(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        with patch('tools.web_search.httpx.AsyncClient') as client:
            result = await tool.handler({'queries': ['query'], 'base_url': 'https://attacker.test'})
        self.assertTrue(result['isError'])
        client.assert_not_called()
