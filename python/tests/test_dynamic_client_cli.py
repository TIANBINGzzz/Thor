"""用真实 SDK CLI 和本地模型桩检查私有 MCP 热更新协议，升级 SDK 时必须回归。"""
import asyncio
import json
import shutil
import socket
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.claude_sdk import (
    ClientState, ClientTurnPolicy, ClaudeSDKClient, SDKToolScope, build_agent_options, create_sdk_mcp_server, sdk_tool,
)
from runtime.config import agent_environment, isolated_sdk_environment
from runtime.claude_sdk import AGENT_BUILTIN_TOOLS


class DynamicClientCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_live_cli_replaces_mcp_model_and_rules_without_reconnecting(self):
        app = FastAPI()
        stage = {'name': '', 'tool': None, 'requests': []}
        hits = []
        validations = []
        model_started, tool_started, tool_cleaned = (asyncio.Event() for _ in range(3))
        tool_scope = SDKToolScope()
        with tempfile.TemporaryDirectory() as directory:
            side_effect = Path(directory) / 'forbidden.txt'

            @app.post('/{path:path}')
            async def model(request: Request, path: str):
                data = await request.json()
                if not data.get('tools'):
                    # 新 CLI 切换自定义模型时先发无工具的模型可用性校验。
                    if data['model'] == 'probe-new-gateway-model':
                        valid = path == 'changed/v1/messages' and request.headers.get('authorization') == 'Bearer changed-probe'
                        validations.append(valid)
                        if not valid:
                            return JSONResponse({'type': 'error', 'error': {'type': 'not_found_error',
                                'message': 'Model is available only at the new gateway with the new token'}}, status_code=404)
                    return JSONResponse({'id': 'msg_validation', 'type': 'message', 'role': 'assistant',
                        'model': data['model'], 'content': [{'type': 'text', 'text': 'OK.'}],
                        'stop_reason': 'end_turn', 'stop_sequence': None,
                        'usage': {'input_tokens': 1, 'output_tokens': 1}})
                stage['requests'].append({'model': data['model'],
                    'tools': [item['name'] for item in data['tools']],
                    'thinking': data.get('thinking'), 'effort': data.get('output_config', {}).get('effort'),
                    'path': path, 'marker': data.get('probe_marker'),
                    'auth_matches': request.headers.get('authorization') == 'Bearer ' + stage.get('auth', 'local-probe'),
                    'context': 'CONTEXT_' + stage['name'] in json.dumps(data)})
                tool = stage['tool'] if len(stage['requests']) == 1 else None
                hang = stage['name'] == 'CANCEL_MODEL'
                arguments = ({'command': f'echo forbidden > "{side_effect.as_posix()}"'} if tool == 'Bash'
                             else stage.get('arguments', {}))
                if tool == 'Write':
                    arguments = {'file_path': str(stage['target']), 'content': 'local probe'}
                blocks = [{'type': 'tool_use', 'id': 'toolu_' + uuid4().hex,
                           'name': tool, 'input': arguments}] if tool else [{'type': 'text', 'text': 'OK.'}]
                reason = 'tool_use' if tool else 'end_turn'
                message = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant',
                    'model': data['model'], 'content': blocks, 'stop_reason': reason,
                    'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
                if not data.get('stream'):
                    return JSONResponse(message)

                async def stream():
                    events = [{'type': 'message_start', 'message': {**message, 'content': [], 'stop_reason': None}}]
                    for index, block in enumerate(blocks):
                        events.extend([
                            {'type': 'content_block_start', 'index': index, 'content_block':
                                {**block, 'input': {}} if tool else {**block, 'text': ''}},
                            {'type': 'content_block_delta', 'index': index, 'delta':
                                {'type': 'input_json_delta', 'partial_json': json.dumps(block['input'])} if tool else
                                {'type': 'text_delta', 'text': block['text']}},
                            {'type': 'content_block_stop', 'index': index}])
                    events.extend([
                        {'type': 'message_delta', 'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 1}},
                        {'type': 'message_stop'}])
                    for event in events:
                        yield 'event: ' + event['type'] + '\ndata: ' + json.dumps(event) + '\n\n'
                        if hang and event['type'] == 'content_block_delta':
                            model_started.set()
                            await asyncio.Event().wait()
                return StreamingResponse(stream(), media_type='text/event-stream')

            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            service = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
            serving = asyncio.create_task(service.serve(sockets=[sock]))
            policy = ClientTurnPolicy()
            options = build_agent_options(cwd=directory, model='probe-first-model', max_turns=4,
                tools=list(AGENT_BUILTIN_TOOLS), setting_sources=[],
                system_prompt='Follow this turn policy.', permission_mode='bypassPermissions',
                hooks=policy.hooks(), mcp_servers={}, strict_mcp_config=True,
                env={**agent_environment(), 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}',
                     'ANTHROPIC_AUTH_TOKEN': 'local-probe', 'CLAUDE_CONFIG_DIR': directory,
                     'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
            client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)

            def server(label):
                with tool_scope.capture():
                    @sdk_tool('probe', 'local probe', {})
                    async def probe(arguments):
                        hits.append(label)
                        if stage['name'] == 'CANCEL_TOOL':
                            tool_started.set()
                            try:
                                await asyncio.Event().wait()
                            finally:
                                await asyncio.sleep(.01)
                                tool_cleaned.set()
                        return {'content': [{'type': 'text', 'text': label}]}
                    return create_sdk_mcp_server(name='probe', tools=[probe])

            try:
                async with asyncio.timeout(10):
                    while not service.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(.01)
                with isolated_sdk_environment():
                    await client.connect()
                provider = client._provider
                for name, servers, tool, model_name in [
                    ('A', {'probe': server('A')}, 'mcp__probe__probe', 'probe-first-model'),
                    ('B', {'probe': server('B')}, 'mcp__probe__probe', 'probe-second-model'),
                    ('DENY', {}, 'Write', 'probe-second-model')]:
                    stage.update(name=name, tool=tool, target=side_effect, requests=[])
                    turn = build_agent_options(model=model_name, mcp_servers=servers, tools=[],
                        env=options.env, permission_mode='bypassPermissions',
                        system_prompt='CONTEXT_' + name,
                        allowed_tools=['mcp__probe__probe'] if servers else [], disallowed_tools=[])
                    policy.bind(turn)
                    tool_scope.start()
                    with isolated_sdk_environment():
                        await client.configure_turn(turn)
                        await client.query('Perform the probe for ' + name)
                        messages = [message.to_dict() async for message in client.receive_response()]
                    self.assertIs(client._provider, provider)
                    self.assertTrue(stage['requests'][0]['context'])
                    self.assertEqual(stage['requests'][0]['model'], model_name)
                    self.assertFalse(side_effect.exists())
                    if servers:
                        self.assertEqual(hits[-1], name)
                    else:
                        self.assertFalse(any(tool.startswith('mcp__probe__') for tool in stage['requests'][0]['tools']),
                                         stage['requests'])
                        self.assertIn('本轮能力未授权此工具', json.dumps(messages, ensure_ascii=False))
                    policy.clear()
                    tool_scope.stop()
                    await tool_scope.drain(timeout_ms=1000)
                self.assertEqual(hits, ['A', 'B'])

                # 真实代码包经过 SDK bridge 同名替换，切换能力后仅使用新 Run 上下文。
                from runtime.capability_operations import build_operation_server
                from tests.test_capability_operations import create_pack, operation
                packs = Path(directory) / 'packs'
                for ref in ('alpha-capability', 'beta-capability'):
                    create_pack(packs, [operation()], '''
                        async def calculate(context, args):
                            return {'answer': context.capability_ref + ':' + context.run_id}
                    ''', ref=ref)
                for ref in ('alpha-capability', 'beta-capability', None):
                    name = ref or 'REVOKE_OPERATION'
                    stage.update(name=name, tool='mcp__capability_ops__calculate',
                                 arguments={'value': 'probe'}, requests=[])
                    tool_scope.start()
                    servers = {}
                    if ref:
                        with patch('capability_packs.registry.PACK_ROOT', packs), tool_scope.capture():
                            namespace, server_config, _ = build_operation_server({'ref': ref,
                                'operation_refs': ['calculate']},
                                {'run_id': 'run-' + ref})
                        servers[namespace] = server_config
                    turn = build_agent_options(model='probe-second-model', mcp_servers=servers, tools=[],
                        env=options.env, permission_mode='bypassPermissions', system_prompt='CONTEXT_' + name,
                        allowed_tools=['mcp__capability_ops__calculate'] if ref else [], disallowed_tools=[])
                    policy.bind(turn)
                    try:
                        with isolated_sdk_environment():
                            await client.configure_turn(turn)
                            await client.query('Perform the operation probe for ' + name)
                            messages = [message.to_dict() async for message in client.receive_response()]
                        self.assertIs(client._provider, provider)
                        serialized = json.dumps(messages, ensure_ascii=False)
                        if ref:
                            self.assertIn(ref + ':run-' + ref, serialized)
                        else:
                            self.assertNotIn('mcp__capability_ops__calculate', stage['requests'][0]['tools'])
                            results = [block for message in messages if message['kind'] == 'user'
                                       for block in message['data']['content'] if block['type'] == 'tool_result']
                            self.assertTrue(results)
                            self.assertTrue(all(result.get('is_error') for result in results))
                            self.assertNotIn('beta-capability:run-beta-capability', serialized)
                    finally:
                        policy.clear()
                        tool_scope.stop(cancel=True)
                        await tool_scope.drain(timeout_ms=1000)
                stage.pop('arguments')

                # 验证 SDK 私有设置真正改变模型请求，并能清除上轮环境覆盖。
                changed_env = {'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}/changed',
                    'ANTHROPIC_AUTH_TOKEN': 'changed-probe', 'CLAUDE_CODE_EXTRA_BODY': '{"probe_marker":"hot"}'}
                for name, model_name, thinking, effort, env in [
                    ('HOT_GATEWAY', 'probe-new-gateway-model', {'type': 'adaptive'}, 'low', changed_env),
                    ('HOT_ON', 'claude-sonnet-4-5', {'type': 'enabled', 'budget_tokens': 2048}, 'low', changed_env),
                    ('HOT_LOW', 'claude-sonnet-4-6', {'type': 'adaptive'}, 'low', {}),
                    ('HOT_OFF', 'claude-sonnet-4-6', {'type': 'disabled'}, 'high', {}),
                    ('HOT_RESET', 'claude-sonnet-4-6', None, None, {}),
                ]:
                    stage.update(name=name, tool=None, requests=[], auth='changed-probe' if env else 'local-probe')
                    turn = build_agent_options(model=model_name, thinking=thinking, effort=effort, env=env,
                        permission_mode='bypassPermissions',
                        mcp_servers={}, tools=[], allowed_tools=[], disallowed_tools=[],
                        system_prompt='CONTEXT_' + name)
                    policy.bind(turn)
                    with isolated_sdk_environment():
                        await client.configure_turn(turn)
                        await client.query('Perform the probe for ' + name)
                        messages = [message async for message in client.receive_response()]
                    request = stage['requests'][0]
                    self.assertIs(client._provider, provider)
                    self.assertFalse(messages[-1].data['is_error'])
                    self.assertTrue(request['auth_matches'])
                    self.assertEqual(request['path'], 'changed/v1/messages' if env else 'v1/messages')
                    self.assertEqual(request['marker'], 'hot' if env else None)
                    self.assertEqual(request['thinking']['type'],
                                     {'HOT_GATEWAY': 'adaptive', 'HOT_ON': 'enabled', 'HOT_LOW': 'adaptive',
                                      'HOT_OFF': 'disabled', 'HOT_RESET': 'adaptive'}[name])
                    if name == 'HOT_GATEWAY':
                        self.assertTrue(validations)
                        self.assertTrue(all(validations))
                    if name == 'HOT_ON':
                        self.assertEqual(request['thinking']['budget_tokens'], 2048)
                    if name != 'HOT_ON':
                        self.assertEqual(request['effort'], effort or 'high')

                # 原生目录权限增删也须实际生效；acceptEdits 下仅获准目录可以自动写入。
                with tempfile.TemporaryDirectory() as external:
                    for name, directories, allowed in [('DIR_DENY', [], False),
                            ('DIR_ALLOW', [external], True), ('DIR_REVOKE', [], False)]:
                        target = Path(external) / (name + '.txt')
                        stage.update(name=name, tool='Write', target=target, requests=[])
                        turn.add_dirs, turn.permission_mode = directories, 'acceptEdits'
                        turn.tools = ['Write']
                        turn.allowed_tools, turn.system_prompt = ['Write'], 'CONTEXT_' + name
                        policy.bind(turn)
                        with isolated_sdk_environment():
                            await client.configure_turn(turn)
                            await client.query('Perform the local directory probe')
                            messages = [message async for message in client.receive_response()]
                        self.assertIs(client._provider, provider)
                        self.assertEqual(target.exists(), allowed)
                turn.permission_mode = 'bypassPermissions'

                # 真实 CLI 的模型流中断、MCP 工具中断，均须能在原连接继续下一轮。
                import agent_worker
                cached = server('C')
                for name, began in [('CANCEL_MODEL', model_started), ('CANCEL_TOOL', tool_started)]:
                    stage.update(name=name, tool='mcp__probe__probe' if name == 'CANCEL_TOOL' else None, requests=[])
                    turn.mcp_servers = {'probe': cached}
                    turn.allowed_tools = ['mcp__probe__probe']
                    turn.system_prompt = 'CONTEXT_' + name
                    policy.bind(turn)
                    tool_scope.start()
                    queue, output = asyncio.Queue(), []

                    async def cancel():
                        await began.wait()
                        await queue.put({'type': 'client_cancel', 'run_id': name})
                    controller = asyncio.create_task(cancel())
                    try:
                        with isolated_sdk_environment(), patch.object(agent_worker, 'emit', output.append):
                            await client.configure_turn(turn)
                            await client.query('Perform the probe for ' + name)
                            response = await agent_worker._receive_client_response(
                                client, {'run_id': name}, {}, queue, False, time.monotonic() + 30,
                                tool_scope=tool_scope)
                        tool_scope.stop()
                        await tool_scope.drain(timeout_ms=1000)
                        self.assertTrue(response.cancelled)
                        self.assertEqual(client.state, ClientState.READY)
                        self.assertIs(client._provider, provider)
                        if name == 'CANCEL_TOOL':
                            self.assertTrue(tool_cleaned.is_set())
                        self.assertFalse(any(e['type'] == 'result' for e in output))

                        stage.update(name='AFTER_CANCEL', tool='mcp__probe__probe', requests=[])
                        policy.bind(turn)
                        tool_scope.start()
                        with isolated_sdk_environment():
                            await client.query('Perform the probe after cancellation')
                            messages = [message async for message in client.receive_response()]
                        tool_scope.stop()
                        await tool_scope.drain(timeout_ms=1000)
                        self.assertEqual(messages[-1].kind, 'result')
                        self.assertFalse(messages[-1].data['is_error'])
                        self.assertEqual(hits[-1], 'C')
                        self.assertIs(client._provider, provider)
                    finally:
                        controller.cancel()
                        await asyncio.gather(controller, return_exceptions=True)
            finally:
                await client.disconnect()
                service.should_exit = True
                await serving
                # Windows CLI 的子进程退出后目录句柄可能稍晚释放，等待实际释放再清理。
                async with asyncio.timeout(5):
                    while Path(directory).exists():
                        try:
                            shutil.rmtree(directory)
                        except PermissionError:
                            await asyncio.sleep(.05)
