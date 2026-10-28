"""真实 CLI + 本地模型桩，验证新版提示词策略与恢复历史，不调用外部模型。"""
import asyncio
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.claude_sdk import (ClientTurnPolicy, ClaudeSDKClient, build_agent_options, stream_query,
                               create_sdk_mcp_server, sdk_tool)
from runtime.config import agent_environment, build_client_options, build_options, isolated_sdk_environment


class SystemPromptCLITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.requests = []
        self.read_tools = True
        self.force_read_count = 0
        app = FastAPI()

        @app.post('/{path:path}')
        async def respond(request: Request, path: str):
            data = await request.json()
            self.requests.append(data)
            read = self.read_tools and any(tool['name'] == 'Read' for tool in data.get('tools', [])) and not any(
                block.get('type') == 'tool_result' for message in data['messages']
                if isinstance(message['content'], list) for block in message['content'])
            if self.force_read_count:
                read = True
                self.force_read_count -= 1
            blocks = ([{'type': 'tool_use', 'id': 'toolu_' + uuid4().hex, 'name': 'Read',
                        'input': {'file_path': str(self.directory / 'input.txt')}}]
                      if read else [{'type': 'text', 'text': 'LOCAL_REPLY'}])
            reason = 'tool_use' if read else 'end_turn'
            message = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant',
                'model': data['model'], 'content': blocks,
                'stop_reason': reason, 'stop_sequence': None,
                'usage': {'input_tokens': 1, 'output_tokens': 1}}
            if not data.get('stream'):
                return JSONResponse(message)

            async def chunks():
                events = [
                    {'type': 'message_start', 'message': {**message, 'content': [], 'stop_reason': None}},
                    {'type': 'content_block_start', 'index': 0, 'content_block':
                     {**blocks[0], 'input': {}} if read else {'type': 'text', 'text': ''}},
                    {'type': 'content_block_delta', 'index': 0,
                     'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(blocks[0]['input'])}
                     if read else {'type': 'text_delta', 'text': 'LOCAL_REPLY'}},
                    {'type': 'content_block_stop', 'index': 0},
                    {'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 1}},
                    {'type': 'message_stop'}]
                for event in events:
                    yield 'event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
            return StreamingResponse(chunks(), media_type='text/event-stream')

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
        self.service = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        self.serving = asyncio.create_task(self.service.serve(sockets=[sock]))
        async with asyncio.timeout(10):
            while not self.service.started:
                if self.serving.done():
                    await self.serving
                await asyncio.sleep(.01)

    async def asyncTearDown(self):
        self.service.should_exit = True
        await self.serving
        # Windows CLI 退出与目录句柄释放之间可能存在短暂延迟。
        async with asyncio.timeout(5):
            while self.directory.exists():
                try:
                    shutil.rmtree(self.directory)
                except PermissionError:
                    await asyncio.sleep(.05)

    def options(self, **values):
        defaults = dict(cwd=str(self.directory), model='claude-sonnet-4-6', max_turns=2,
            tools=[], setting_sources=[], strict_mcp_config=True, verbatim_prompts=True,
            permission_mode='bypassPermissions',
            env={**agent_environment(), 'ANTHROPIC_BASE_URL': self.url,
                 'ANTHROPIC_AUTH_TOKEN': 'local-probe', 'CLAUDE_CONFIG_DIR': str(self.directory / 'config'),
                 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
        return build_agent_options(**(defaults | values))

    async def run_turn(self, options, prompt, mode):
        with isolated_sdk_environment():
            if mode == 'query':
                messages = [item async for item in stream_query(prompt, options, timeout_ms=30000)]
            else:
                client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)
                try:
                    await client.connect()
                    await client.query(prompt)
                    messages = [item async for item in client.receive_response()]
                finally:
                    await client.disconnect()
        result = next(item for item in reversed(messages) if item.kind == 'result')
        self.assertFalse(result.data['is_error'])
        return result.session_id

    async def test_snapshot_controls_rebuilt_prompt_on_resume_with_history(self):
        for mode in ('client', 'query'):
            for kind in ('custom', 'preset'):
                for snapshot in (True, False):
                    with self.subTest(mode=mode, kind=kind, snapshot=snapshot):
                        marker = 'BASE_' + uuid4().hex
                        def prompt(suffix):
                            return ({'type': 'custom', 'prompt': marker + suffix, 'snapshot': snapshot}
                                if kind == 'custom' else {'type': 'preset', 'preset': 'claude_code',
                                    'append': marker + suffix, 'snapshot': snapshot})
                        session = await self.run_turn(self.options(system_prompt=prompt('_FIRST')),
                                                      'HISTORY_' + marker, mode)
                        self.assertIn(marker + '_FIRST', json.dumps(self.requests[-1]['system']))
                        resumed = await self.run_turn(self.options(system_prompt=prompt('_SECOND'), resume=session),
                                                      'RESUMED_' + marker, mode)
                        self.assertEqual(resumed, session)
                        system = json.dumps(self.requests[-1]['system'])
                        self.assertIn(marker + ('_FIRST' if snapshot else '_SECOND'), system)
                        self.assertNotIn(marker + ('_SECOND' if snapshot else '_FIRST'), system)
                        history = json.dumps(self.requests[-1]['messages'])
                        self.assertIn('HISTORY_' + marker, history)
                        self.assertIn('LOCAL_REPLY', history)
                        self.assertIn('RESUMED_' + marker, history)

    async def test_verbatim_keeps_commands_and_file_mentions_literal(self):
        secret = self.directory / 'input.txt'
        marker = 'FILE_' + uuid4().hex
        secret.write_text(marker, encoding='utf-8')
        for mode in ('client', 'query'):
            with self.subTest(mode=mode):
                session = await self.run_turn(self.options(), f'Inspect @{secret.as_posix()}', mode)
                raw = json.dumps(self.requests[-1]['messages'])
                self.assertIn('@' + secret.as_posix(), raw)
                self.assertNotIn(marker, raw)
                resumed = await self.run_turn(self.options(resume=session), '/clear', mode)
                self.assertEqual(resumed, session)
                raw = json.dumps(self.requests[-1]['messages'])
                self.assertIn('/clear', raw)
                self.assertIn('Inspect @', raw)

    async def test_query_to_client_resume_keeps_only_shared_base_in_system(self):
        import agent_worker
        from runtime.capabilities import CAPABILITIES, capability_entry

        self.read_tools = False
        environment = self.options().env
        for prompt_mode in ('default', 'custom'):
            with self.subTest(prompt_mode=prompt_mode):
                entry = capability_entry(CAPABILITIES['conversation'].directory)
                entry.update(execution={'mode': 'direct'}, tools=[])
                entry['runtime'] = {'prompt_mode': prompt_mode, 'system_prompt_snapshot': True}
                marker = uuid4().hex
                payload = {'capability_ref': 'conversation', 'cwd': str(self.directory),
                    'model': 'claude-sonnet-4-6', 'prompt': 'HISTORY_' + marker,
                    'system_prompt_append': 'QUERY_RULE_' + marker}
                events = []
                with patch.object(agent_worker, 'load_runtime_environment'), \
                        patch.object(agent_worker, 'missing_environment', return_value=[]), \
                        patch.object(agent_worker, 'emit', events.append), \
                        patch('runtime.config.capability_entry', return_value=entry), \
                        patch('runtime.config.agent_environment', return_value=environment):
                    await agent_worker.run(payload)
                    result = next(item for item in events if item['type'] == 'result')
                    self.assertTrue(result['ok'], result)
                    resumed = {**payload, 'resume': result['sessionId'],
                               'system_prompt_append': 'CLIENT_RULE_' + marker}
                    policy = ClientTurnPolicy()
                    options = build_client_options(resumed, policy)
                    policy.bind(build_options(resumed))
                    session = await self.run_turn(options, 'RESUMED_' + marker, 'client')
                self.assertEqual(session, result['sessionId'])
                system = json.dumps(self.requests[-1]['system'], ensure_ascii=False)
                self.assertNotIn('QUERY_RULE_' + marker, system)
                self.assertIn('按可信服务端提供的本轮执行规则处理请求', system)
                history = json.dumps(self.requests[-1]['messages'])
                for text in ('HISTORY_', 'QUERY_RULE_', 'CLIENT_RULE_', 'RESUMED_'):
                    self.assertIn(text + marker, history)
                self.assertIn('LOCAL_REPLY', history)

    async def test_verbatim_still_allows_explicit_authorized_file_reads(self):
        marker = 'FILE_' + uuid4().hex
        target = self.directory / 'input.txt'
        target.write_text(marker, encoding='utf-8')
        for mode in ('client', 'query'):
            with self.subTest(mode=mode):
                await self.run_turn(self.options(tools=['Read'], allowed_tools=['Read']),
                                    f'Read the attached file: {target.as_posix()}', mode)
                raw = json.dumps(self.requests[-1]['messages'])
                self.assertIn(marker, raw)
                self.assertIn('tool_result', raw)

    async def test_profile_switch_hides_builtins_and_resumes_same_history(self):
        """使用生产连接配置，证明 direct 的模型请求确实不包含内置工具。"""
        self.read_tools = False
        environment = self.options().env
        session = None
        self.profile_evidence = []

        @sdk_tool('read', 'local read probe', {})
        async def read(arguments):
            return {'content': [{'type': 'text', 'text': 'probe'}]}

        for index, ref in enumerate(('conversation', 'campus-brain-query',
                                     'national-excellence-data-qa', 'conversation')):
            policy = ClientTurnPolicy()
            payload = {'capability_ref': ref, 'cwd': str(self.directory),
                       'model': 'claude-sonnet-4-6', 'resume': session}
            with patch('runtime.config.agent_environment', return_value=environment):
                options = build_client_options(payload, policy)
            client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)
            marker = 'TURN_RULE_' + str(index)
            turn = self.options(tools=options.tools, system_prompt=marker,
                mcp_servers={'probe': create_sdk_mcp_server(name='probe', tools=[read])},
                allowed_tools=['mcp__probe__read'])
            policy.bind(turn)
            try:
                with isolated_sdk_environment():
                    await client.connect()
                    await client.configure_turn(turn)
                    await client.query('HISTORY_' + str(index))
                    messages = [item async for item in client.receive_response()]
                result = next(item for item in reversed(messages) if item.kind == 'result')
                self.assertFalse(result.data['is_error'])
                if session:
                    self.assertEqual(result.session_id, session)
                session = result.session_id
                request = self.requests[-1]
                names = {tool['name'] for tool in request.get('tools', [])}
                self.assertIn('mcp__probe__read', names)
                if ref != 'conversation':
                    self.assertEqual(names, {'mcp__probe__read'})
                else:
                    self.assertTrue({'Read', 'Write', 'Edit', 'Glob', 'Grep', 'WebFetch'} <= names)
                    self.assertTrue(names <= {'Read', 'Write', 'Edit', 'Glob', 'Grep',
                                             'Bash', 'PowerShell', 'WebFetch', 'mcp__probe__read'})
                history = json.dumps(request['messages'])
                for previous in range(index + 1):
                    self.assertIn('HISTORY_' + str(previous), history)
                    self.assertIn('TURN_RULE_' + str(previous), history)
                self.profile_evidence.append({'capability': ref, 'tools': sorted(names),
                    'toolSchemaBytes': len(json.dumps(request.get('tools', [])).encode()),
                    'historyBytes': len(history.encode())})
            finally:
                await client.disconnect()

    async def test_builtin_base_is_fixed_but_permission_overlay_changes_execution(self):
        """锁定 CLI 假设：动态 deny 阻断调用但保留 Schema，allow 无法加载启动时缺席的工具。"""
        self.read_tools = False
        for initial in ({'type': 'preset', 'preset': 'claude_code'}, []):
            options = self.options(tools=initial)
            client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)
            try:
                with isolated_sdk_environment():
                    await client.connect()
                provider = client._provider
                control = provider._query._send_control_request
                replacement = [] if initial else ['Read']
                options.tools = replacement
                # 返回成功不等于更新了工具集合；同时验证首轮前和运行后的 deny/allow。
                await control({'subtype': 'apply_flag_settings', 'settings': {'tools': replacement}})
                session = None
                for index, denied in enumerate((True, False, True, False)):
                    marker = 'LOCAL_READ_MARKER_' + str(index)
                    (self.directory / 'input.txt').write_text(marker, encoding='utf-8')
                    await control({'subtype': 'apply_flag_settings',
                                   'settings': {'permissions': {'allow': ['Read'],
                                                                'deny': ['Read'] if denied else []}}})
                    self.force_read_count = 1
                    first = len(self.requests)
                    await client.query('Read the local test input.')
                    messages = [item.to_dict() async for item in client.receive_response()]
                    names = {tool['name'] for tool in self.requests[first].get('tools', [])}
                    self.assertEqual('Read' in names, bool(initial))
                    results = [block for message in messages if message['kind'] == 'user'
                               and isinstance(message['data'].get('content'), list)
                               for block in message['data']['content'] if block['type'] == 'tool_result']
                    self.assertTrue(results)
                    self.assertEqual(bool(results[-1].get('is_error')), denied or not initial)
                    if initial and not denied:
                        self.assertIn(marker, str(results[-1]))
                    self.assertIs(client._provider, provider)
                    result = next(item for item in reversed(messages) if item['kind'] == 'result')
                    self.assertFalse(result['data']['is_error'])
                    if session:
                        self.assertEqual(result['sessionId'], session)
                    session = result['sessionId']
            finally:
                await client.disconnect()
