"""用真实 SDK CLI 和本地模型桩检查私有 MCP 热更新协议，升级 SDK 时必须回归。"""
import asyncio
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.claude_sdk import (
    ClientTurnPolicy, ClaudeSDKClient, build_agent_options, create_sdk_mcp_server, sdk_tool,
)
from runtime.config import agent_environment, isolated_sdk_environment


class DynamicClientCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_live_cli_replaces_mcp_model_and_rules_without_reconnecting(self):
        app = FastAPI()
        stage = {'name': '', 'tool': None, 'requests': []}
        hits = []
        with tempfile.TemporaryDirectory() as directory:
            side_effect = Path(directory) / 'forbidden.txt'

            @app.post('/{path:path}')
            async def model(request: Request, path: str):
                data = await request.json()
                if not data.get('tools'):
                    return JSONResponse({'type': 'error', 'error': {
                        'type': 'invalid_request_error', 'message': 'local probe'}}, status_code=400)
                stage['requests'].append({'model': data['model'],
                    'tools': [item['name'] for item in data['tools']],
                    'context': 'CONTEXT_' + stage['name'] in json.dumps(data)})
                tool = stage['tool'] if len(stage['requests']) == 1 else None
                arguments = {'command': f'echo forbidden > "{side_effect.as_posix()}"'} if tool == 'Bash' else {}
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
                return StreamingResponse(stream(), media_type='text/event-stream')

            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
            service = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
            serving = asyncio.create_task(service.serve(sockets=[sock]))
            policy = ClientTurnPolicy()
            options = build_agent_options(cwd=directory, model='probe-first-model', max_turns=4,
                tools={'type': 'preset', 'preset': 'claude_code'}, setting_sources=[],
                system_prompt='Follow this turn policy.', permission_mode='bypassPermissions',
                hooks=policy.hooks(), mcp_servers={}, strict_mcp_config=True,
                env={**agent_environment(), 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}',
                     'ANTHROPIC_AUTH_TOKEN': 'local-probe', 'CLAUDE_CONFIG_DIR': directory,
                     'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
            client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)

            def server(label):
                @sdk_tool('probe', 'local probe', {})
                async def probe(arguments):
                    hits.append(label)
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
                    ('DENY', {}, 'Bash', 'probe-second-model')]:
                    stage.update(name=name, tool=tool, requests=[])
                    turn = SimpleNamespace(model=model_name, mcp_servers=servers, tools=[],
                        system_prompt='CONTEXT_' + name,
                        allowed_tools=['mcp__probe__probe'] if servers else [], disallowed_tools=[])
                    policy.bind(turn)
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
                        self.assertFalse(any(tool.startswith('mcp__probe__') for tool in stage['requests'][0]['tools']))
                        self.assertIn('本轮能力未授权此工具', json.dumps(messages, ensure_ascii=False))
                    policy.clear()
                self.assertEqual(hits, ['A', 'B'])
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
