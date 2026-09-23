import asyncio
import copy
import json
import os
import unittest
import httpx
from unittest.mock import AsyncMock, patch

from runtime.capabilities import resolve_capability
from runtime.config import build_options, prepare_workflow_assets
from runtime.mcp_auth import MCPAuthError
from tools.campus import CampusQuery, create_campus_server, load_campus_assets


class CampusTests(unittest.IsolatedAsyncioTestCase):
    def service(self, token='test-secret'):
        return CampusQuery(load_campus_assets(), {'platformBearer': token})

    def test_capability_and_restricted_mount(self):
        self.assertIsNone(resolve_capability('campus-brain-query').workflow_ref)
        with patch.dict(os.environ, {'BUSINESS_MCP_URL': 'https://unwanted.test',
                'CCSDK_BUSINESS_MCP_CAPABILITIES': 'campus-brain-query'}, clear=True):
            before = dict(os.environ)
            payload = {'capability_ref': 'campus-brain-query', 'credentials': {'platformBearer': 'test-secret'}}
            options = build_options(payload)
            self.assertEqual(before, dict(os.environ))
        self.assertEqual(set(options.mcp_servers), {'campus'})
        self.assertEqual(options.tools, [])
        self.assertTrue(options.strict_mcp_config)
        self.assertEqual(options.setting_sources, [])
        self.assertNotIn('test-secret', str(options.system_prompt))
        self.assertIn('至少 8', str(options.system_prompt))
        self.assertNotIn('上饶幼儿师范', str(options.system_prompt))
        with self.assertRaises(MCPAuthError):
            build_options({'capability_ref': 'campus-brain-query'})

    def test_catalogs_preserve_types_years_and_leading_zeroes(self):
        service = self.service()
        for kind in ('indicator_compare', 'norm_analysis'):
            rows = service.search({'kind': kind, 'query': '备案的中外合作项目数量'})['records']
            self.assertEqual(rows[0]['code'], 'badzwhzxmsl')
            self.assertEqual(rows[0]['analysis'], kind)
            self.assertIn('2025', rows[0]['year'])
        schools = service.search({'kind': 'schools', 'query': '上饶幼儿师范高等专科学校'})['records']
        self.assertEqual(schools[0]['code'], '00312')

    async def test_private_injection_and_no_argument_override(self):
        service = self.service()
        args = {'payload': {}}
        original = copy.deepcopy(args)
        service._request = AsyncMock(return_value={'success': True, 'data': {'school_id': 'self', 'school_name': '本校'}})
        result = await service.call('get_school_info', args)
        self.assertEqual(args, original)
        self.assertNotIn('test-secret', json.dumps(result))
        remote_args = service._request.call_args.args[1]
        self.assertEqual(remote_args, {'action': 'query', 'user_context_token': 'test-secret', 'payload': {}})
        for bad in ({'payload': {}, 'user_context_token': 'other'}, {'payload': {'user_context_token': 'other'}},
                    {'payload': {}, 'url': 'https://attacker.test'}):
            with self.assertRaises(ValueError):
                await service.call('get_school_info', bad)
        self.assertEqual(service._request.await_count, 1)

    async def test_per_run_once_and_reset_credentials(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {'school_id': 'self', 'school_name': '本校'}})
        await service.call('get_school_info', {'payload': {}})
        with self.assertRaises(ValueError):
            await service.call('get_school_info', {'payload': {}})
        service.clear()
        with self.assertRaises(MCPAuthError):
            await service.call('get_school_info', {'payload': {}})
        service.bind({'platformBearer': 'second-secret'})
        await service.call('get_school_info', {'payload': {}})
        self.assertEqual(service._request.call_args.args[1]['user_context_token'], 'second-secret')

    async def test_norm_validation_and_output_allowlist(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {'school_id': '00312', 'school_name': '本校'}})
        await service.call('get_school_info', {'payload': {}})
        codes = [r['code'] for r in service.assets['catalogs']['schools'] if r['code'] != '00312'][:8]
        base = {'indicator_code': 'badzwhzxmsl', 'schools': codes}
        for bad in (codes[:7], codes[:7] + [codes[0]], codes[:7] + ['00312'], codes[:7] + ['invented']):
            with self.assertRaises(ValueError):
                await service.call('get_norm_metrics', {'payload': {**base, 'schools': bad}})
        service._request.return_value = {'success': True, 'data': {'indicator_value': 0, 'rank': 2,
            'school_count': 12, 'schools': [{'school_name': '外校', 'value': 9}], 'user_context_token': 'test-secret'}}
        result = await service.call('get_norm_metrics', {'payload': base})
        self.assertEqual(result['data'], {'indicator_value': 0, 'rank': 2, 'school_count': 12})

    async def test_schema_and_errors_do_not_expose_secrets(self):
        service = self.service()
        service._request = AsyncMock(side_effect=RuntimeError('test-secret upstream private body'))
        with patch('tools.campus.create_sdk_mcp_server') as create:
            create_campus_server(service)
        tools = create.call_args.kwargs['tools']
        self.assertNotIn('test-secret', str([t.input_schema for t in tools]))
        self.assertNotIn('user_context_token', str([t.input_schema for t in tools]))
        tool = next(t for t in tools if t.name == 'get_school_info')
        result = await tool.handler({'payload': {}})
        self.assertTrue(result['isError'])
        self.assertNotIn('test-secret', str(result))
        self.assertNotIn('private body', str(result))

    async def test_concurrent_instances_do_not_share_tokens(self):
        services = [self.service('first'), self.service('second')]
        for service in services:
            service._request = AsyncMock(return_value={'success': True, 'data': {'school_id': 'self', 'school_name': '本校'}})
        await asyncio.gather(*(s.call('get_school_info', {'payload': {}}) for s in services))
        self.assertEqual([s._request.call_args.args[1]['user_context_token'] for s in services], ['first', 'second'])

    async def test_scoped_results_filter_unrequested_and_nested_fields(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {'indicator_value': 0,
            'scoped_metrics': [{'scope': 'province_rank', 'value': 3, 'school_count': 20, 'schools': ['private']},
                               {'scope': 'national_median', 'value': 6}]}})
        result = await service.call('get_indicator_metrics', {'payload': {'indicator_code': 'hydss', 'scopes': ['province_rank']}})
        self.assertEqual(result['data']['scoped_metrics'][0], {'scope': 'province_rank', 'value': 3, 'school_count': 20})
        self.assertNotIn('private', str(result))
        self.assertNotIn('test-secret', str(result))
        self.assertNotIn('national_median', str(result))

    async def test_budget_errors_and_missing_identity_block_calls(self):
        service = self.service()
        service._request = AsyncMock(side_effect=RuntimeError('upstream'))
        for year in range(2000, 2010):
            with self.assertRaises(RuntimeError):
                await service.call('get_indicator_metrics', {'payload': {'indicator_code': 'hydss', 'year': year}})
        with self.assertRaises(ValueError):
            await service.call('get_indicator_metrics', {'payload': {'indicator_code': 'hydss', 'year': 2010}})
        self.assertEqual(service._request.await_count, 10)
        service.bind({'platformBearer': 'test-secret'})
        with self.assertRaises(RuntimeError):
            await service.call('get_school_info', {'payload': {}})
        with self.assertRaises(ValueError):
            await service.call('get_indicator_metrics', {'payload': {'indicator_code': 'hydss'}})

    async def test_json_and_sse_transport_and_static_headers(self):
        for sse in (False, True):
            requests = []
            def respond(request):
                body = json.loads(request.content);requests.append(body)
                self.assertEqual(str(request.url), load_campus_assets()['config']['url'])
                self.assertEqual(request.headers['domain-name'], 'schoolcloud.stringedu.com')
                self.assertEqual(request.headers['app-key'], 'inter-page-key')
                self.assertNotIn('authorization', request.headers)
                if body['method'] == 'notifications/initialized':
                    return httpx.Response(202)
                result = {'protocolVersion': '2024-11-05'} if body['method'] == 'initialize' else {
                    'isError': False, 'content': [{'type': 'text', 'text': json.dumps({'success': True,
                        'data': {'school_id': 'self', 'school_name': '本校'}})}]}
                value = {'jsonrpc': '2.0', 'id': body['id'], 'result': result}
                if sse:
                    return httpx.Response(200, text='event: message\ndata: ' + json.dumps(value) + '\n\n',
                        headers={'content-type': 'text/event-stream', 'mcp-session-id': 'test-session'})
                return httpx.Response(200, json=value)
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch('tools.campus.httpx.AsyncClient', return_value=client):
                result = await self.service().call('get_school_info', {'payload': {}})
            self.assertTrue(result['success'])
            self.assertNotIn('test-secret', str(requests[:2]))
            self.assertEqual(requests[2]['params']['arguments']['user_context_token'], 'test-secret')

    async def test_http_error_and_redirect_are_not_retried_or_disclosed(self):
        for status in (302, 401, 500):
            calls = []
            def respond(request):
                calls.append(request)
                return httpx.Response(status, text='test-secret private error', headers={'location': 'https://other.test'})
            client = httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False)
            with patch('tools.campus.httpx.AsyncClient', return_value=client), patch('tools.campus.create_sdk_mcp_server') as create:
                create_campus_server(self.service())
                tool = next(t for t in create.call_args.kwargs['tools'] if t.name == 'get_school_info')
                result = await tool.handler({'payload': {}})
            self.assertEqual(len(calls), 1)
            self.assertTrue(result['isError'])
            self.assertNotIn('test-secret', str(result))

    def test_school_minimum_config_controls_schema_and_prompt(self):
        from tools.campus import ASSET_ROOT
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = __import__('pathlib').Path(directory)
            for path in ASSET_ROOT.iterdir():
                shutil.copy2(path, root / path.name)
            path = root / 'capability.json'
            config = json.loads(path.read_text(encoding='utf-8'));config['minimum_schools'] = 12
            path.write_text(json.dumps(config), encoding='utf-8')
            with patch('tools.campus.ASSET_ROOT', root):
                assets = load_campus_assets()
            self.assertIn('至少 12', assets['prompt'])
            self.assertEqual(assets['config']['tools']['get_norm_metrics']['schema']['properties']['schools']['minItems'], 12)

    def test_batch_lookup_retains_ambiguous_candidates(self):
        result = self.service().search({'kind': 'schools', 'query': ['深职大', '城职院']})
        self.assertTrue(any(r['name'] == '深圳职业技术大学' for r in result['queries'][0]['records']))
        self.assertGreater(result['queries'][1]['total'], 1)

    def test_registered_assets_are_frozen_and_not_overridden_by_input(self):
        payload = {'capability_ref': 'campus-brain-query', 'credentials': {'platformBearer': 'test-secret'}}
        prepare_workflow_assets(payload)
        service = self.service();service.assets['revision'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, '资产已变化'):
            build_options(payload, campus_service=service)

    async def test_conflicting_source_code_cannot_be_queried(self):
        service = self.service()
        rows = service.search({'kind': 'indicator_compare', 'query': '开发教材被外方采用数'})['records']
        self.assertTrue(rows[0]['definition_conflict'])
        service._request = AsyncMock()
        with self.assertRaisesRegex(ValueError, '定义冲突'):
            await service.call('get_indicator_metrics', {'payload': {'indicator_code': rows[0]['code'], 'year': 2023}})
        service._request.assert_not_called()

    async def test_numeric_fields_cannot_smuggle_text_or_boolean_identity(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {
            'indicator_value': '{"school_name":"外校","value":99}', 'rank': False}})
        with self.assertRaises(RuntimeError):
            await service.call('get_indicator_metrics', {'payload': {'indicator_code': 'hydss'}})
        service.bind({'platformBearer': 'test-secret'})
        service._request.return_value = {'success': True, 'data': {'school_id': True, 'school_name': 42}}
        with self.assertRaises(RuntimeError):
            await service.call('get_school_info', {'payload': {}})

    async def test_sse_completes_on_matching_event_without_waiting_for_eof(self):
        class OpenStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05"}}\n\n'
                await asyncio.Event().wait()
        def respond(request):
            body = json.loads(request.content)
            if body['method'] == 'initialize':
                return httpx.Response(200, stream=OpenStream(), headers={'content-type': 'text/event-stream'})
            if body['method'] == 'notifications/initialized':
                return httpx.Response(202)
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': 2, 'result': {'content': [
                {'type': 'text', 'text': '{"success":true,"data":{"school_id":"self","school_name":"school"}}'}]}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch('tools.campus.httpx.AsyncClient', return_value=client):
            result = await asyncio.wait_for(self.service().call('get_school_info', {'payload': {}}), 1)
        self.assertTrue(result['success'])
