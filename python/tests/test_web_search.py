import json
import unittest
from unittest.mock import patch

import httpx

from tools.web_search import search_web, create_web_server


class WebSearchTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertEqual(result['searchRequests'], 1)
        self.assertEqual(len(result['sources']), 1)
        self.assertEqual(result['summary'], '服务支持联网搜索。')
        for private in ('omit-this', 'private-reasoning', 'model-secret'):
            self.assertNotIn(private, json.dumps(result))

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
