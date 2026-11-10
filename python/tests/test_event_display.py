"""公开状态只使用服务端字典，隐藏展示不改变事件的数据含义。"""

import asyncio
import json
import unittest
from unittest.mock import patch

import server
from runtime.run_store import RunStore
from runtime.event_display import RunStatusDisplays, ToolCallDisplays, with_display_name, TOOL_DISPLAY_NAMES


class EventDisplayTests(unittest.TestCase):
    def test_public_status_stays_on_tool_until_different_work_or_run_end(self):
        async def exercise():
            run_id = 'display-run-1'
            await server._publish_internal_event(run_id, {
                'runId': run_id, 'type': 'run.started', 'payload': {'status': 'running'}})
            await server._run_phase(run_id, {'name': 'model_starting'})
            await server._run_phase(run_id, {'name': 'model_starting'})
            for call_id in ('query-1', 'query-2'):
                for raw in (
                    {'type': 'tool_use', 'id': call_id, 'name': 'mcp__data__execute_query_spec'},
                    {'type': 'thinking', 'text': 'private-reasoning'},
                    {'type': 'tool_progress', 'id': call_id},
                    {'type': 'tool_result', 'id': call_id, 'text': 'private-data'},
                    {'type': 'text', 'text': '结果'},
                ):
                    await server._handle_agent_event(run_id, raw)
            await server._handle_agent_event(run_id, {
                'type': 'tool_use', 'id': 'chart', 'name': 'mcp__charts__build_mermaid'})
            await server._handle_agent_event(run_id, {'type': 'tool_result', 'id': 'chart'})
            await server._run_phase(run_id, {'name': 'model_starting'})
            await server._publish_internal_event(run_id, {
                'runId': run_id, 'type': 'run.completed', 'payload': {}})
        asyncio.run(exercise())
        events = self.store.events_after('display-run-1')
        self.assertEqual([e['payload']['displayName'] for e in events if e['payload']['displayName']],
                         ['正在思考', '查询业务数据', '生成图表', '已完成'])
        working = [e for e in events if e['type'] == 'phase' and e['payload'].get('name') == 'working']
        self.assertEqual([e['payload']['toolKey'] for e in working], ['data.query', 'chart.generate'])
        self.assertTrue(all('toolCallId' not in e['payload'] for e in working))
        self.assertFalse(any(e['type'].startswith('tool.') for e in events))
        self.assertEqual(''.join(e['payload'].get('textDelta', '') for e in events), '结果结果')
        self.assertNotIn('private-', json.dumps(events))
        self.assertNotIn('display-run-1', server.STATUS_DISPLAYS.runs)
        self.assertNotIn('display-run-1', server.STATUS_DISPLAYS.thinking_started)

    def test_scoped_parallel_tools_keep_latest_stage_on_out_of_order_finishes(self):
        async def exercise():
            for scope, name in [('main', 'mcp__data__execute_query_spec'), ('sub:task', 'mcp__images__generate')]:
                await server._handle_agent_event('display-run-1', {
                    'type': 'tool_use', 'id': 'same-id', 'scope': scope, 'name': name})
            for scope in ('main', 'sub:task'):
                await server._handle_agent_event('display-run-1', {
                    'type': 'tool_result', 'id': 'same-id', 'scope': scope, 'isError': True})
            await server._publish_internal_event('display-run-1', {
                'runId': 'display-run-1', 'type': 'run.cancelled', 'payload': {}})
        asyncio.run(exercise())
        self.assertEqual([e['payload']['displayName'] for e in self.store.events_after('display-run-1')],
                         ['查询业务数据', '生成或编辑图片', '已停止'])
        self.assertNotIn('display-run-1', server.STATUS_DISPLAYS.runs)

    def test_hidden_tools_do_not_change_status_and_run_status_is_isolated(self):
        async def exercise():
            for run_id in ('display-run-1', 'display-run-2'):
                await server._run_phase(run_id, {'name': 'model_starting'})
                await server._handle_agent_event(run_id, {
                    'type': 'tool_use', 'id': 'query', 'name': 'mcp__data__execute_query_spec'})
                await server._handle_agent_event(run_id, {
                    'type': 'tool_use', 'id': 'hidden', 'name': 'private-unknown-tool'})
                await server._handle_agent_event(run_id, {'type': 'tool_result', 'id': 'hidden'})
                await server._handle_agent_event(run_id, {'type': 'tool_result', 'id': 'query'})
        asyncio.run(exercise())
        for run_id in ('display-run-1', 'display-run-2'):
            events = self.store.events_after(run_id)
            self.assertEqual([e['payload']['displayName'] for e in events], ['正在思考', '查询业务数据'])

    def test_status_coalescing_keeps_file_progress_and_failure_data(self):
        async def exercise():
            run_id = 'display-run-1'
            for received in (10, 20):
                await server._run_phase(run_id, {
                    'name': 'downloading_file', 'fileId': 'file', 'receivedBytes': received, 'totalBytes': 30})
            await server._publish_internal_event(run_id, {
                'runId': run_id, 'type': 'run.failed', 'payload': {'code': 'sdk_execution_error'}})
        asyncio.run(exercise())
        events = self.store.events_after('display-run-1')
        self.assertEqual([e['payload']['receivedBytes'] for e in events[:-1]], [10, 20])
        self.assertEqual(events[-1]['type'], 'run.failed')
        self.assertEqual(events[-1]['payload']['code'], 'sdk_execution_error')

    def test_known_failures_explain_the_stage_without_echoing_private_details(self):
        cases = {
            'worker_memory_pressure': '内存不足', 'worker_capacity_exceeded': '并发处理上限',
            'run_queue_timeout': '排队等待超时', 'worker_start_timeout': '处理进程启动超时',
            'sdk_connection_timeout': '模型服务连接超时', 'sdk_connection_error': '模型服务连接失败',
            'worker_exited': '处理进程意外退出', 'worker_send_timeout': '处理进程通信超时',
            'sdk_configuration_error': '模型服务配置', 'sdk_execution_error': '模型执行失败',
            'file_download_timeout': '附件下载超时', 'file_download_failed': '附件下载失败',
            'file_access_denied': '附件访问被拒绝', 'file_validation_failed': '附件校验失败',
            'file_download_configuration_error': '附件服务配置', 'file_download_unavailable': '附件服务不可用',
            'worker_cleanup_error': '处理进程释放失败', 'sdk_cleanup_error': '模型会话收尾失败',
            'configuration_error': '执行配置', 'session_actor_closed': '处理会话已关闭',
        }
        for code, detail in cases.items():
            with self.subTest(code=code):
                event = with_display_name({'type': 'run.failed', 'payload': {
                    'code': code, 'message': 'private-token https://private-host/path'}})
                self.assertEqual(event['payload']['code'], code)
                self.assertIn(detail, event['payload']['message'])
                self.assertNotIn('private-', json.dumps(event))

    def test_missing_mcp_credentials_have_safe_actionable_message(self):
        event = with_display_name({'type': 'run.failed', 'payload': {
            'code': 'mcp_authentication_error', 'message': 'private-credential-details'}})
        self.assertEqual(event['payload']['message'], '业务服务授权不可用，请重新登录；仍失败时请联系管理员。')
        self.assertNotIn('private-credential-details', json.dumps(event))

    def test_failure_message_is_server_owned_even_on_replay(self):
        for code in ('sdk_execution_error', 'upstream_service_error', 'private-provider-error'):
            event = with_display_name({'type': 'run.failed', 'payload': {
                'code': code, 'message': 'private-provider-response'}})
            self.assertTrue(event['payload'].get('message'))
            self.assertNotIn('private-provider-response', json.dumps(event))
            self.assertNotEqual(event['payload']['message'], code)

    def setUp(self):
        self.enterContext(patch.object(server, 'STATUS_DISPLAYS', RunStatusDisplays()))
        self.store = RunStore(':memory:')
        self.addCleanup(self.store.close)
        for run in ('display-run-1', 'display-run-2'):
            self.store.create_run(run, tenant_id='tenant', user_id='user')
        patcher = patch.object(server, 'RUN_STORE', self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(server, 'TOOL_DISPLAYS', ToolCallDisplays())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dictionary_can_hide_tool_without_dropping_its_result(self):
        with patch.dict(TOOL_DISPLAY_NAMES, {'data.query': ''}):
            event = with_display_name({'type': 'tool.finished', 'payload': {
                'toolCallId': 'call', 'toolKey': 'data.query', 'isError': True}})
        self.assertEqual(event['payload']['displayName'], '')
        self.assertTrue(event['payload']['isError'])
        self.assertEqual(event['payload']['toolCallId'], 'call')

    def test_web_search_uses_public_search_status(self):
        event = server._public_internal_event('display-run-1', {
            'type': 'tool_use', 'id': 'search-call', 'name': 'mcp__web__search',
            'input': {'query': 'private-query'},
        })
        self.assertEqual(event['payload']['toolKey'], 'web.search')
        self.assertEqual(event['payload']['displayName'], '正在联网搜索')
        self.assertNotIn('mcp__web__search', json.dumps(event))
        self.assertNotIn('private-query', json.dumps(event))
        for kind in ('tool_progress', 'tool_result'):
            result = server._public_internal_event('display-run-1', {
                'type': kind, 'id': 'search-call', 'isError': True, 'text': 'private-results'})
            self.assertEqual(result['payload']['toolKey'], 'web.search')
            self.assertEqual(with_display_name(result)['payload']['displayName'], '正在联网搜索')
            self.assertNotIn('private-results', json.dumps(result))

    def test_replayed_old_tool_names_are_removed(self):
        event = with_display_name({'sequence': 8, 'type': 'tool.started', 'payload': {
            'toolName': 'private-host-token-tool', 'displayName': 'forged'}})
        self.assertEqual(event['payload'], {'toolKey': 'other', 'displayName': ''})
        self.assertEqual(event['sequence'], 8)

    def test_finished_run_releases_tool_name_mapping(self):
        server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'call', 'name': 'Read'})
        server.TOOL_DISPLAYS.clear('display-run-1')
        event = server._public_internal_event('display-run-1', {'type': 'tool_result', 'id': 'call'})
        self.assertEqual(event['payload']['toolKey'], 'other')

    def test_chart_tool_public_status_does_not_expose_input_values(self):
        start = server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'chart-call',
            'name': 'mcp__charts__build_mermaid', 'input': {'labels': ['private-input-marker'], 'values': [1]}})
        self.assertEqual(start['payload']['toolKey'], 'chart.generate')
        self.assertEqual(start['payload']['displayName'], '生成图表')
        self.assertNotIn('private-input-marker', json.dumps(start))
        end = server._public_internal_event('display-run-1', {'type': 'tool_result', 'id': 'chart-call'})
        self.assertEqual(end['payload']['toolKey'], 'chart.generate')

    def test_tool_name_is_mapped_and_reused_without_tool_parameters(self):
        start = server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'call-1',
            'name': 'mcp__data__execute_query_spec', 'input': {'password': 'private'}})
        self.assertEqual(start['payload'].get('toolKey'), 'data.query')
        self.assertEqual(start['payload'].get('displayName'), '查询业务数据')
        self.assertNotIn('toolName', start['payload'])
        for kind in ('tool_progress', 'tool_result'):
            event = server._public_internal_event('display-run-1', {'type': kind, 'id': 'call-1'})
            self.assertEqual(event['payload']['displayName'], '查询业务数据')
            self.assertEqual(event['payload']['toolKey'], 'data.query')
        self.assertNotIn('private', json.dumps(start))

    def test_capability_operation_uses_its_pack_display_key(self):
        for operation, expected in (('search_knowledge', 'data.prepare'),
                                    ('get_school_info', 'data.resolve'),
                                    ('get_indicator_metrics', 'data.query'),
                                    ('get_norm_metrics', 'data.query')):
            with self.subTest(operation=operation):
                event = server._public_internal_event('display-run-1', {
                    'type': 'tool_use', 'id': operation,
                    'name': 'mcp__capability_ops__' + operation,
                })
                self.assertEqual(event['payload']['toolKey'], expected)

    def test_unknown_tool_does_not_echo_name_and_runs_are_isolated(self):
        server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'shared',
            'name': 'mcp__data__execute_readonly_sql'})
        event = server._public_internal_event('display-run-2', {'type': 'tool_result', 'id': 'shared'})
        self.assertEqual(event['payload'].get('toolKey'), 'other')
        self.assertEqual(event['payload'].get('displayName'), '')
        event = server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'unknown',
            'name': 'private-host-token-tool', 'displayName': 'forged'})
        self.assertEqual(event['payload']['displayName'], '')
        self.assertNotIn('private-host', json.dumps(event))
        self.assertNotIn('forged', json.dumps(event))

    def test_empty_name_keeps_text_and_phase_data_and_is_persisted(self):
        async def exercise():
            text = server._public_internal_event('display-run-1', {'type': 'text', 'text': '你好'})
            result = await server._publish_internal_event('display-run-1', text)
            self.assertEqual(result['payload'].get('displayName'), '')
            self.assertEqual(result['payload']['textDelta'], '你好')
            await server._run_phase('display-run-1', {'name': 'saving_files', 'displayName': 'forged'})
            saved = self.store.events_after('display-run-1')[-1]
            self.assertEqual(saved['payload'].get('displayName'), '正在保存文件')
        asyncio.run(exercise())

    def test_child_tool_call_with_same_id_does_not_replace_parent_name(self):
        for scope, name in [('main', 'mcp__data__execute_query_spec'), ('sub:task', 'mcp__images__generate')]:
            server._public_internal_event('display-run-1', {'type': 'tool_use', 'id': 'same', 'scope': scope, 'name': name})
        for scope, expected in [('main', 'data.query'), ('sub:task', 'image.generate')]:
            event = server._public_internal_event('display-run-1', {'type': 'tool_result', 'id': 'same', 'scope': scope})
            self.assertEqual(event['payload'].get('toolKey'), expected)
