"""公开状态只使用服务端字典，隐藏展示不改变事件的数据含义。"""

import asyncio
import json
import unittest
from unittest.mock import patch

import server
from runtime.run_store import RunStore
from runtime.event_display import ToolCallDisplays, with_display_name, TOOL_DISPLAY_NAMES


class EventDisplayTests(unittest.TestCase):
    def setUp(self):
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
