import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import agent_worker
from runtime.claude_sdk import ClaudeSDKClient, ClientState, SDKMessage


class ClientWorkerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_tool_service_setup_failure_closes_data_services(self):
        data = SimpleNamespace(close=AsyncMock())
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: data,
                            ToolServices=Mock(side_effect=RuntimeError('tool setup failed'))):
            with self.assertRaisesRegex(RuntimeError, 'tool setup failed'):
                await agent_worker.run_client({})
        data.close.assert_awaited_once()

    async def test_one_shot_tool_service_setup_failure_closes_data_services(self):
        data = SimpleNamespace(close=AsyncMock())
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: data,
                            ToolServices=Mock(side_effect=RuntimeError('tool setup failed'))):
            with self.assertRaisesRegex(RuntimeError, 'tool setup failed'):
                await agent_worker.run({'prompt': 'question'})
        data.close.assert_awaited_once()

    async def test_client_setup_failure_clears_bound_tool_credentials(self):
        from unittest.mock import Mock
        services = Mock()
        data = SimpleNamespace(close=AsyncMock())
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: data,
                            ToolServices=lambda *args: services,
                            build_options=Mock(side_effect=RuntimeError('invalid config'))):
            with self.assertRaisesRegex(RuntimeError, 'invalid config'):
                await agent_worker.run_client({})
        services.clear.assert_called_once()
        data.close.assert_awaited_once()

    async def test_upstream_failure_overrides_success_in_query(self):
        from server import _public_internal_event
        callback = None
        events = []
        def options(_, **kwargs):
            nonlocal callback
            callback = kwargs['mcp_error_sink']
            return SimpleNamespace(tools=[], strict_mcp_config=True)
        async def query(*args, **kwargs):
            callback()
            yield SDKMessage(kind='result', data={'subtype': 'success', 'is_error': False})
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: None,
                            build_options=options, stream_query=query,
                            isolated_sdk_environment=nullcontext, emit=events.append):
            await agent_worker.run({'prompt': 'question'})
        result = next(e for e in events if e['type'] == 'result')
        self.assertFalse(result['ok'])
        public = _public_internal_event('run-test', result)
        self.assertEqual(public['type'], 'run.failed')
        self.assertEqual(public['payload']['code'], 'upstream_service_error')

    async def test_one_shot_prepares_prompt_before_query_and_cleans_up_on_failure(self):
        services = SimpleNamespace(bind=AsyncMock(), close=AsyncMock(),
                                   prepare_prompt=lambda prompt: 'prepared:' + prompt)
        seen = []

        async def query(prompt, options, timeout_ms):
            services.bind.assert_awaited_once()
            seen.append(prompt)
            yield SDKMessage(kind='result', data={'subtype': 'success'})

        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: services,
                            build_options=lambda _, **kwargs: SimpleNamespace(tools=[], strict_mcp_config=True),
                            stream_query=query, isolated_sdk_environment=nullcontext, emit=lambda _: None):
            await agent_worker.run({'prompt': 'question'})
            self.assertEqual(seen, ['prepared:question'])
            services.close.assert_awaited_once()
            services.close.reset_mock()
            services.bind.side_effect = ValueError('preparation failed')
            with self.assertRaisesRegex(ValueError, 'preparation failed'):
                await agent_worker.run({'prompt': 'failed-question'})
            self.assertEqual(seen, ['prepared:question'])
            services.close.assert_awaited_once()

    async def test_client_injects_fresh_prepared_context_into_each_query(self):
        queries = []
        completed = asyncio.Event()
        results = []
        error_sink = None

        def options(_, **kwargs):
            nonlocal error_sink
            error_sink = kwargs['mcp_error_sink']
            return SimpleNamespace(tools=[], strict_mcp_config=True)

        class Services:
            async def bind(self, command):
                self.run_id = command['run_id']

            def prepare_prompt(self, prompt):
                return self.run_id + ':' + prompt

            async def close(self):
                self.run_id = None

        class Client:
            state = ClientState.NEW

            async def connect(self):
                self.state = ClientState.READY

            async def query(self, prompt, session_id):
                queries.append(prompt)
                if len(queries) == 1:
                    error_sink()

            async def receive_response(self, **kwargs):
                yield SDKMessage(kind='result', data={'subtype': 'success', 'is_error': False})

            async def disconnect(self):
                self.state = ClientState.CLOSED

        async def commands(queue):
            for run_id in ('r1', 'r2'):
                completed.clear()
                await queue.put({'type': 'client_query', 'run_id': run_id, 'prompt': 'question', 'timeout_ms': 2000})
                await completed.wait()
            await queue.put({'type': 'client_close'})

        def emit(event):
            if event['type'] == 'result':
                results.append(event['ok'])
            if event['type'] == 'client_run_completed':
                completed.set()

        services = Services()
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: services,
                            build_options=options,
                            ClaudeSDKClient=lambda *args, **kwargs: Client(),
                            isolated_sdk_environment=nullcontext, _read_client_commands=commands, emit=emit):
            await asyncio.wait_for(agent_worker.run_client({}), 3)
        self.assertEqual(queries, ['r1:question', 'r2:question'])
        self.assertEqual(results, [False, True])
        self.assertIsNone(services.run_id)

    async def test_closing_at_result_keeps_client_ready_for_next_query(self):
        class Provider:
            disconnects = 0

            async def connect(self, prompt=None):
                pass

            async def query(self, prompt, session_id):
                pass

            async def receive_response(self):
                yield SDKMessage(kind="result", data={"subtype": "success"})

            async def disconnect(self):
                self.disconnects += 1

        provider = Provider()
        client = ClaudeSDKClient(object(), client_factory=lambda _: provider)
        await client.connect()
        for _ in range(2):
            await client.query("hello")
            response = client.receive_response()
            self.assertEqual((await anext(response)).kind, "result")
            await response.aclose()
            self.assertEqual(client.state, ClientState.READY)
            self.assertEqual(provider.disconnects, 0)
        await client.disconnect()

    async def test_query_deadline_and_response_loop_complete(self):
        sent = []
        queries = []
        completed = asyncio.Event()

        class Client:
            state = ClientState.NEW

            async def connect(self):
                self.state = ClientState.READY

            async def query(self, prompt, session_id):
                queries.append((prompt, session_id))
                self.state = ClientState.RUNNING

            def receive_response(self, *, timeout_ms):
                self_timeout = timeout_ms

                async def response():
                    assert 0 < self_timeout <= 2000
                    yield SDKMessage(kind="assistant", data={"content": [{"type": "text", "text": "answer"}]})
                    yield SDKMessage(kind="result", data={"subtype": "success", "is_error": False}, session_id="provider-test")
                return response()

            async def disconnect(self):
                self.state = ClientState.CLOSED

        async def commands(queue):
            await queue.put({"type": "client_query", "run_id": "run-test", "prompt": "hello", "timeout_ms": 2000})
            await completed.wait()
            await queue.put({"type": "client_close"})

        def emit(event):
            sent.append(event)
            if event["type"] == "client_run_completed":
                completed.set()

        client = Client()
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [],
                            build_options=lambda _, **kwargs: SimpleNamespace(tools=None, strict_mcp_config=False),
                            ClaudeSDKClient=lambda *args, **kwargs: client,
                            isolated_sdk_environment=nullcontext,
                            _read_client_commands=commands, emit=emit):
            await asyncio.wait_for(agent_worker.run_client({}), 3)
        self.assertEqual(queries, [("hello", "default")])
        self.assertIn({"type": "client_run_completed", "run_id": "run-test", "session_id": "provider-test"}, sent)
        self.assertFalse(any(e["type"] == "client_error" for e in sent))
        self.assertEqual(client.state, ClientState.CLOSED)
