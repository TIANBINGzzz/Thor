import json
import unittest
from unittest.mock import patch

import httpx

from tools.web_search import search_web, create_web_server
from runtime.deployment_config import configuration_scope
from tests.deployment_fixtures import deployment_document


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_thinking_switch_uses_bound_budgets_and_keeps_reasoning_private(self):
        for switch in (None, False, True):
            with self.subTest(thinking=switch):
                document = deployment_document()
                document['runtime']['limits'].update({'web-search-max-tokens':731, 'web-search-thinking-max-tokens':4097})
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
                with configuration_scope(document), patch('tools.web_search.create_sdk_mcp_server') as create:
                    create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
                    tool = create.call_args.kwargs['tools'][0]
                    self.assertEqual(tool.input_schema['properties']['thinking']['type'], 'boolean')
                    self.assertNotIn('thinking', tool.input_schema['required'])
                    arguments = {'query':'公开检索词'}
                    if switch is not None:
                        arguments['thinking'] = switch
                    with patch('tools.web_search.httpx.AsyncClient', return_value=client):
                        result = await tool.handler(arguments)
                self.assertFalse(result.get('isError'), result)
                self.assertEqual(requests[0]['thinking'], {'type':'enabled' if switch else 'disabled'})
                self.assertEqual(requests[0]['max_tokens'], 4097 if switch else 731)
                content = json.loads(result['content'][0]['text'])
                self.assertEqual(content['summary'], '简短摘要')
                self.assertEqual(len(content['sources']), 1)
                self.assertNotIn('private-reasoning', json.dumps(result))

    async def test_mcp_rejects_non_boolean_thinking_and_budget_overrides(self):
        with patch('tools.web_search.create_sdk_mcp_server') as create:
            create_web_server(base_url='https://provider.test', api_key='secret', model='qwen')
        tool = create.call_args.kwargs['tools'][0]
        invalid = [{'query':'q','thinking':value} for value in ('false', 0, 1, None, {}, [])]
        invalid += [{'query':'q','thinking':True,'max_tokens':999999}, {'thinking':True}]
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
                    result = await tool.handler({'query': '公开政策原文'})
                self.assertTrue(result.get('isError'))
                self.assertIn('不能声称已经查证', result['content'][0]['text'])
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
            result = await tool.handler({'query': 'query', 'base_url': 'https://attacker.test'})
        self.assertTrue(result['isError'])
        client.assert_not_called()
