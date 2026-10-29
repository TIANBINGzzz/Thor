"""真实 Claude CLI、本地 Anthropic 协议桩验证运行中消息引导。"""

import asyncio
import json
import socket
import tempfile
import time
import unittest
from uuid import uuid4
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from runtime.claude_sdk import (
    ClientTurnPolicy,
    ClaudeSDKClient,
    SDKToolScope,
    SDKExecutionError,
    build_agent_options,
    create_sdk_mcp_server,
    sdk_tool,
)
from runtime.config import agent_environment, isolated_sdk_environment


class SteeringCLITests(unittest.IsolatedAsyncioTestCase):
    async def test_steering_does_not_cancel_tool_and_reaches_same_run(self):
        await self._exercise_steering('tool')

    async def test_steering_at_text_completion_is_consumed_before_next_run(self):
        await self._exercise_steering('text')

    async def test_cancel_after_steering_retires_connection_before_resuming(self):
        await self._exercise_steering('cancel')

    async def _exercise_steering(self, mode):
        app = FastAPI()
        requests = []
        tool_started, release_tool = (asyncio.Event() for _ in range(2))
        delivered_twice = asyncio.Event()
        delivered_ids = set()
        tool_calls = []

        @app.post('/{path:path}')
        async def model(request: Request, path: str):
            body = await request.json()
            requests.append(body)
            if not body.get('tools'):
                return JSONResponse({'id': 'msg_probe', 'type': 'message', 'role': 'assistant',
                    'model': body['model'], 'content': [{'type': 'text', 'text': 'OK'}],
                    'stop_reason': 'end_turn', 'stop_sequence': None,
                    'usage': {'input_tokens': 1, 'output_tokens': 1}})
            first_request = len([item for item in requests if item.get('tools')]) == 1
            if first_request and mode in {'tool', 'cancel'}:
                block = {'type': 'tool_use', 'id': 'toolu_' + uuid4().hex,
                         'name': 'mcp__steering__wait_for_release', 'input': {}}
                reason = 'tool_use'
            elif first_request:
                block = {'type': 'text', 'text': 'Original response.'}
                reason = 'end_turn'
            else:
                joined = json.dumps(body.get('messages', []), ensure_ascii=False)
                if mode != 'cancel' and '按学院统计' not in joined:
                    return JSONResponse({'type': 'error', 'error': {'type': 'invalid_request_error',
                        'message': 'steering text missing from the next model request'}}, status_code=400)
                block = {'type': 'text', 'text': '已根据补充要求按学院统计。'}
                reason = 'end_turn'
            message = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant',
                'model': body['model'], 'content': [block], 'stop_reason': reason,
                'stop_sequence': None, 'usage': {'input_tokens': 2, 'output_tokens': 2}}

            async def stream():
                yield 'event: message_start\ndata: ' + json.dumps({'type': 'message_start', 'message':
                    {**message, 'content': [], 'stop_reason': None}}) + '\n\n'
                if reason == 'tool_use':
                    yield 'event: content_block_start\ndata: ' + json.dumps({'type': 'content_block_start',
                        'index': 0, 'content_block': {**block, 'input': {}}}) + '\n\n'
                    yield 'event: content_block_delta\ndata: ' + json.dumps({'type': 'content_block_delta',
                        'index': 0, 'delta': {'type': 'input_json_delta', 'partial_json': '{}'}}) + '\n\n'
                else:
                    yield 'event: content_block_start\ndata: ' + json.dumps({'type': 'content_block_start',
                        'index': 0, 'content_block': {'type': 'text', 'text': ''}}) + '\n\n'
                    yield 'event: content_block_delta\ndata: ' + json.dumps({'type': 'content_block_delta',
                        'index': 0, 'delta': {'type': 'text_delta', 'text': block['text']}}) + '\n\n'
                    if first_request:
                        tool_started.set()
                        await release_tool.wait()
                yield 'event: content_block_stop\ndata: ' + json.dumps({'type': 'content_block_stop', 'index': 0}) + '\n\n'
                yield 'event: message_delta\ndata: ' + json.dumps({'type': 'message_delta',
                    'delta': {'stop_reason': reason}, 'usage': {'output_tokens': 2}}) + '\n\n'
                yield 'event: message_stop\ndata: ' + json.dumps({'type': 'message_stop'}) + '\n\n'

            return StreamingResponse(stream(), media_type='text/event-stream')

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        service = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
        serving = asyncio.create_task(service.serve(sockets=[sock]))
        with tempfile.TemporaryDirectory() as directory:
            policy = ClientTurnPolicy()
            scope = SDKToolScope()
            with scope.capture():
                @sdk_tool('wait_for_release', 'Waits for the test controller',
                          {'type': 'object', 'properties': {}, 'required': []})
                async def wait_for_release(_arguments):
                    tool_calls.append('started')
                    tool_started.set()
                    try:
                        await release_tool.wait()
                    except asyncio.CancelledError:
                        tool_calls.append('cancelled')
                        raise
                    tool_calls.append('finished')
                    return {'content': [{'type': 'text', 'text': 'tool finished'}]}

                tool_server = create_sdk_mcp_server(name='steering', tools=[wait_for_release])

            options = build_agent_options(cwd=directory, model='claude-sonnet-4-6', max_turns=4,
                tools={'type': 'preset', 'preset': 'claude_code'}, setting_sources=[],
                extra_args={'replay-user-messages': None},
                system_prompt='Apply each user request.', permission_mode='bypassPermissions',
                hooks=policy.hooks(), mcp_servers={}, strict_mcp_config=True,
                env={**agent_environment(), 'ANTHROPIC_BASE_URL': f'http://127.0.0.1:{port}',
                     'ANTHROPIC_AUTH_TOKEN': 'local-probe', 'CLAUDE_CONFIG_DIR': directory,
                     'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1'})
            client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=30000)
            output = []
            queue = asyncio.Queue()
            run_command = {'type': 'client_query', 'run_id': 'run-steer', 'session_id': 'session-steer'}

            def emit(event):
                output.append(event)
                if event.get('type') == 'client_steer_ack' and event.get('status') == 'delivered':
                    delivered_ids.add(event.get('message_id'))
                    if len(delivered_ids) == 2:
                        delivered_twice.set()

            async def provide_guidance():
                await tool_started.wait()
                await queue.put({'type': 'client_steer', 'run_id': 'run-steer',
                                 'message_id': 'message-steer-1', 'text': '补充要求：按学院统计'})
                async with asyncio.timeout(5):
                    while 'message-steer-1' not in delivered_ids:
                        await asyncio.sleep(.001)
                await queue.put({'type': 'client_steer', 'run_id': 'run-steer',
                                 'message_id': 'message-steer-2', 'text': '补充要求：同时列出同比变化'})
                await delivered_twice.wait()
                # 两条 delivered 到达时工具仍在等待，证明引导没有中断它。
                self.assertFalse(release_tool.is_set())
                if mode == 'cancel':
                    await queue.put({'type': 'client_cancel', 'run_id': 'run-steer'})
                else:
                    release_tool.set()

            controller = asyncio.create_task(provide_guidance())
            try:
                async with asyncio.timeout(10):
                    while not service.started:
                        if serving.done():
                            await serving
                        await asyncio.sleep(.01)
                with isolated_sdk_environment():
                    await client.connect()
                    raw_results = []
                    provider_receive = client._provider.receive_response
                    async def trace_response():
                        async for message in provider_receive():
                            if type(message).__name__ == 'ResultMessage':
                                raw_results.append(message)
                            yield message
                    client._provider.receive_response = trace_response
                    turn = build_agent_options(model='claude-sonnet-4-6', mcp_servers={'steering': tool_server},
                        tools=[], env=options.env, permission_mode='bypassPermissions',
                        system_prompt='Apply each user request.', allowed_tools=['mcp__steering__wait_for_release'],
                        disallowed_tools=[])
                    policy.bind(turn)
                    scope.start()
                    await client.configure_turn(turn)
                    await client.query('Start the paused tool', session_id='session-steer')
                    import agent_worker
                    with patch.object(agent_worker, 'emit', emit):
                        try:
                            response = await agent_worker._receive_client_response(
                                client, run_command, {}, queue, time.monotonic() + 15,
                                tool_scope=scope)
                        except Exception as error:
                            summary = [{'tools': [tool.get('name') for tool in item.get('tools', [])],
                                'messages': json.dumps(item.get('messages', []), ensure_ascii=False)[:1000]}
                                for item in requests if item.get('tools')]
                            raise AssertionError({'requests': summary, 'toolCalls': tool_calls,
                                                  'events': output}) from error
                await controller
                if mode == 'cancel':
                    self.assertTrue(response.cancelled)
                    self.assertTrue(response.close_requested)
                    self.assertFalse(client.reusable)
                    self.assertEqual(tool_calls, ['started', 'cancelled'])
                    self.assertFalse(any(event['type'] == 'result' for event in output))
                    scope.stop()
                    await scope.drain(timeout_ms=1000)
                    with self.assertRaises(SDKExecutionError):
                        await client.query('Cannot reuse this connection')
                    await client.disconnect()
                    self.assertTrue(response.session_id)
                    options.resume = response.session_id
                    client = ClaudeSDKClient(options, connect_timeout_ms=30000, receive_timeout_ms=15000)
                    with isolated_sdk_environment():
                        await client.connect()
                        await client.configure_turn(turn)
                        await client.query('NEXT_RUN')
                        following = [message async for message in client.receive_response()]
                    self.assertFalse(following[-1].data['is_error'])
                    self.assertFalse(any(message.kind == 'steering' for message in following))
                    self.assertIn('NEXT_RUN', json.dumps(requests[-1]['messages']))
                    return
                self.assertFalse(response.cancelled)
                self.assertEqual(tool_calls, ['started', 'finished'] if mode == 'tool' else [])
                acknowledgements = [e for e in output if e['type'] == 'client_steer_ack']
                states = {(e['message_id'], e['status']) for e in acknowledgements}
                self.assertEqual(states, {('message-steer-1', 'delivered'), ('message-steer-1', 'applied'),
                                          ('message-steer-2', 'delivered'), ('message-steer-2', 'applied')})
                model_requests = [item for item in requests if item.get('tools')]
                self.assertGreaterEqual(len(model_requests), 2)
                next_request = json.dumps(model_requests[-1]['messages'], ensure_ascii=False)
                self.assertIn('按学院统计', next_request)
                self.assertIn('同比变化', next_request)
                self.assertEqual(sum(e['type'] == 'result' for e in output), 1)
                self.assertTrue(client.reusable)
                self.assertEqual(len(raw_results), 2 if mode == 'text' else 1)
                result = next(event for event in output if event['type'] == 'result')
                self.assertEqual(result['turns'], 2)
                # model_usage 为连接累计值；中间 Result 不得重复累加它。
                self.assertEqual((result['inputTokens'], result['outputTokens']), (4, 4))
                # 正常结束后下一 Run 必须获得自己的最终结果，不能误领上一轮补充。
                with isolated_sdk_environment():
                    await client.query('NEXT_RUN', session_id='session-steer')
                    following = [message async for message in client.receive_response()]
                self.assertEqual(following[-1].kind, 'result')
                self.assertFalse(following[-1].data['is_error'])
                self.assertFalse(any(message.kind == 'steering' for message in following))
                self.assertIn('NEXT_RUN', json.dumps(requests[-1]['messages']))
                scope.stop()
                await scope.drain(timeout_ms=1000)
            finally:
                if not release_tool.is_set():
                    release_tool.set()
                controller.cancel()
                await asyncio.gather(controller, return_exceptions=True)
                await client.disconnect()
                service.should_exit = True
                await serving


if __name__ == '__main__':
    unittest.main()
