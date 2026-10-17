import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import agent_worker
from runtime.claude_sdk import ClaudeSDKClient, ClientState, SDKMessage, SDKTimeoutError, build_agent_options


class ClientWorkerLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_drains_result_cleans_credentials_and_reuses_connection(self):
        events, terminal_cleanup = [], []
        text_seen, interrupted, result_allowed, completed = (asyncio.Event() for _ in range(4))
        cleanup_started, cleanup_allowed = asyncio.Event(), asyncio.Event()
        tools = SimpleNamespace(token=None)
        tools.configure = lambda assets, credentials: setattr(tools, 'token', credentials['platformBearer'])
        tools.clear = lambda: setattr(tools, 'token', None)

        def services(assets, credentials):
            tools.configure(assets, credentials)
            return tools

        class Data:
            active = False

            async def bind(self, command):
                self.active = True

            def prepare_prompt(self, prompt):
                return prompt

            async def close(self):
                cleanup_started.set()
                await cleanup_allowed.wait()
                self.active = False

        class Provider:
            queries, tokens = [], []
            interrupts = disconnects = 0

            async def connect(self, prompt=None):
                pass

            async def query(self, prompt, session_id):
                self.queries.append(prompt)
                self.tokens.append(tools.token)

            async def interrupt(self):
                self.interrupts += 1
                interrupted.set()

            async def receive_response(self):
                if len(self.queries) == 1:
                    yield SDKMessage(kind='assistant', data={'message_id': 'before', 'content': [{'type': 'text', 'text': 'before'}]})
                    await interrupted.wait()
                    yield SDKMessage(kind='assistant', data={'message_id': 'late', 'content': [{'type': 'text', 'text': 'late'}]})
                    await result_allowed.wait()
                else:
                    yield SDKMessage(kind='assistant', data={'message_id': 'next', 'content': [{'type': 'text', 'text': 'next'}]})
                yield SDKMessage(kind='result', data={'subtype': 'success'}, session_id='same-session')

            async def disconnect(self):
                self.disconnects += 1

        async def commands(queue):
            await queue.put({'type': 'client_query', 'run_id': 'r1', 'prompt': 'first',
                             'credentials': {'platformBearer': 'token-one'}})
            await text_seen.wait()
            for _ in range(2):
                await queue.put({'type': 'client_cancel', 'run_id': 'r1'})
            await interrupted.wait()
            await asyncio.sleep(0)
            self.assertFalse(completed.is_set(), 'interrupt acknowledgement is not a completed response')
            result_allowed.set()
            await cleanup_started.wait()
            self.assertFalse(completed.is_set(), 'terminal must wait for cleanup')
            cleanup_allowed.set()
            await completed.wait()
            completed.clear()
            await queue.put({'type': 'client_query', 'run_id': 'r2', 'prompt': 'second',
                             'credentials': {'platformBearer': 'token-two'}})
            await completed.wait()
            await queue.put({'type': 'client_close'})

        def emit(event):
            events.append(event)
            if event.get('text') == 'before':
                text_seen.set()
            if event['type'] in {'client_run_completed', 'client_run_cancelled'}:
                terminal_cleanup.append((tools.token, data.active))
                completed.set()

        provider, data = Provider(), Data()
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None, missing_environment=lambda: [],
                            prepare_workflow_assets=lambda _: {}, ToolServices=services,
                            create_run_services=lambda _: data,
                            build_client_options=lambda *a: build_agent_options(),
                            build_options=lambda *a, **kw: build_agent_options(),
                            ClaudeSDKClient=lambda *a, **kw: ClaudeSDKClient(*a, **kw, client_factory=lambda _: provider),
                            isolated_sdk_environment=nullcontext, _read_client_commands=commands, emit=emit):
            try:
                await asyncio.wait_for(agent_worker.run_client({}), 3)
            except TimeoutError:
                self.fail(f'Worker did not finish: {events}; queries={provider.queries}')
        self.assertEqual(provider.queries, ['first', 'second'])
        self.assertEqual(provider.tokens, ['token-one', 'token-two'])
        self.assertEqual(provider.interrupts, 1)
        self.assertEqual(provider.disconnects, 1)  # 最后显式关闭，取消时未断开。
        self.assertEqual(terminal_cleanup, [(None, False), (None, False)])
        self.assertEqual([e['text'] for e in events if e['type'] == 'text'], ['before', 'next'])
        self.assertIn({'type': 'client_run_cancelled', 'run_id': 'r1', 'session_id': 'same-session'}, events)
        self.assertFalse(any(e['type'] == 'client_error' for e in events))

    async def test_result_and_cancel_arriving_together_do_not_interrupt_ready_client(self):
        for control in ('client_cancel', 'client_close', 'worker_stdin_closed'):
            with self.subTest(control=control):
                class Provider:
                    async def connect(self, prompt=None):
                        pass

                    async def query(self, prompt, session_id):
                        pass

                    async def receive_response(self):
                        yield SDKMessage(kind='result', data={'subtype': 'success'}, session_id='session')

                    interrupt = AsyncMock()
                    disconnect = AsyncMock()

                provider = Provider()
                client = ClaudeSDKClient(build_agent_options(), client_factory=lambda _: provider)
                await client.connect()
                await client.query('question')
                queue = asyncio.Queue()
                queue.put_nowait({'type': control, 'run_id': 'r1'})
                with patch.object(agent_worker, 'emit') as output:
                    response = await agent_worker._receive_client_response(
                        client, {'run_id': 'r1'}, {}, queue, False, None)
                self.assertTrue(response.cancelled)
                self.assertEqual(response.close_requested, control != 'client_cancel')
                self.assertEqual(response.session_id, 'session')
                self.assertEqual(client.state, ClientState.READY)
                provider.interrupt.assert_not_awaited()
                output.assert_not_called()
                await client.disconnect()

    async def test_cancel_without_result_fails_connection_within_control_budget(self):
        class Provider:
            async def connect(self, prompt=None):
                pass

            async def query(self, prompt, session_id):
                pass

            async def receive_response(self):
                await asyncio.Event().wait()
                yield

            interrupt = AsyncMock()
            disconnect = AsyncMock()

        provider = Provider()
        client = ClaudeSDKClient(build_agent_options(), client_factory=lambda _: provider)
        await client.connect()
        await client.query('question')
        queue = asyncio.Queue()
        queue.put_nowait({'type': 'client_cancel', 'run_id': 'r1'})
        settings = SimpleNamespace(timeouts=SimpleNamespace(worker_control_ms=20))
        with patch.object(agent_worker, 'RUNTIME_SETTINGS', settings):
            with self.assertRaises(SDKTimeoutError):
                async with asyncio.timeout(1):
                    await agent_worker._receive_client_response(client, {'run_id': 'r1'}, {}, queue, False, None)
        self.assertEqual(client.state, ClientState.FAILED)
        provider.interrupt.assert_awaited_once()
        provider.disconnect.assert_awaited_once()

    async def test_performance_output_failure_preserves_result_and_cleanup(self):
        for failure in (None, ValueError('query failed')):
            with self.subTest(failure=type(failure).__name__):
                events = []
                tools = Mock()
                data = SimpleNamespace(bind=AsyncMock(), close=AsyncMock(), prepare_prompt=lambda p: p)

                async def query(*args, **kwargs):
                    if failure:
                        raise failure
                    yield SDKMessage(kind='stream', data={'event': {'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': 'answer'}}})
                    yield SDKMessage(kind='result', data={'subtype': 'success', 'is_error': False})

                def emit(event):
                    if event['type'] == 'performance':
                        raise BrokenPipeError('diagnostic output unavailable')
                    events.append(event)

                with patch.dict('os.environ', {'CCSDK_ENABLE_RUN_TRACE': '1'}), \
                     patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                                    missing_environment=lambda: [], create_run_services=lambda _: data,
                                    ToolServices=lambda *args: tools,
                                    build_options=lambda _, **kw: build_agent_options(tools=[], strict_mcp_config=True),
                                    stream_query=query, isolated_sdk_environment=nullcontext, emit=emit):
                    if failure:
                        with self.assertRaisesRegex(ValueError, 'query failed'):
                            await agent_worker.run({'prompt': 'question'})
                    else:
                        await agent_worker.run({'prompt': 'question'})
                        self.assertEqual([e['type'] for e in events], ['text', 'result'])
                        self.assertTrue(events[-1]['ok'])
                tools.clear.assert_called_once()
                data.close.assert_awaited_once()

    async def test_private_timings_are_per_turn_and_precede_terminal(self):
        events = []
        completed = asyncio.Event()

        class Client:
            state = ClientState.NEW

            async def configure_turn(self, options):
                pass

            async def connect(self):
                self.state = ClientState.READY

            async def query(self, prompt, session_id):
                pass

            async def receive_response(self, **kwargs):
                for text in ('O', 'K'):
                    yield SDKMessage(kind='stream', data={'event': {'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': text}}})
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
            events.append(event)
            if event['type'] == 'client_run_completed':
                completed.set()

        with patch.dict('os.environ', {'CCSDK_ENABLE_RUN_TRACE': '1'}), \
             patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: None,
                            build_options=lambda _, **kw: build_agent_options(tools=[], strict_mcp_config=True),
                            ClaudeSDKClient=lambda *a, **kw: Client(), isolated_sdk_environment=nullcontext,
                            _read_client_commands=commands, emit=emit):
            await asyncio.wait_for(agent_worker.run_client({}), 3)
        terminals = [i for i, e in enumerate(events) if e['type'] == 'client_run_completed']
        self.assertEqual(len(terminals), 2)
        for index in terminals:
            timing = events[index - 1]
            self.assertEqual(timing['scope'], 'worker_run')
            stages = timing['elapsedMs']
            self.assertLessEqual(stages['query_begin'], stages['query_sent'])
            self.assertLessEqual(stages['query_sent'], stages['first_message'])
            self.assertLessEqual(stages['first_message'], stages['first_text'])
            self.assertLessEqual(stages['first_text'], stages['completed'])
        self.assertEqual(len([e for e in events if e['type'] == 'text']), 4)

    async def _setup_failure(self, expected_code='sdk_execution_error', **overrides):
        events = []
        class Client:
            state = ClientState.NEW
            async def connect(self):
                self.state = ClientState.READY
            async def disconnect(self):
                self.state = ClientState.CLOSED
        async def commands(queue):
            await queue.put({'type': 'client_query', 'run_id': 'failed', 'prompt': 'test'})
        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [],
                            ClaudeSDKClient=lambda *a, **kw: Client(),
                            isolated_sdk_environment=nullcontext,
                            _read_client_commands=commands, emit=events.append, **overrides):
            await asyncio.wait_for(agent_worker.run_client({}), 3)
        self.assertIn({'type': 'client_error', 'run_id': 'failed', 'code': expected_code}, events)
        self.assertNotIn('private-token', str(events))

    async def test_missing_business_credentials_fail_before_query_with_safe_auth_code(self):
        from runtime.mcp_auth import MCPAuthError
        data_factory = Mock()
        await self._setup_failure(expected_code='mcp_authentication_error',
            create_run_services=data_factory,
            ToolServices=Mock(side_effect=MCPAuthError('private-token')))
        data_factory.assert_not_called()

    async def test_client_tool_setup_failure_does_not_allocate_data_services(self):
        data_factory = Mock()
        await self._setup_failure(create_run_services=data_factory,
            ToolServices=Mock(side_effect=RuntimeError('tool setup failed')))
        data_factory.assert_not_called()

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
        await self._setup_failure(create_run_services=lambda _: data,
            ToolServices=lambda *args: services,
            build_options=Mock(side_effect=RuntimeError('invalid config')))
        self.assertGreaterEqual(services.clear.call_count, 1)
        data.close.assert_awaited_once()

    async def test_upstream_failure_overrides_success_in_query(self):
        from server import _public_internal_event
        callback = None
        events = []
        def options(_, **kwargs):
            nonlocal callback
            callback = kwargs['mcp_error_sink']
            return build_agent_options(tools=[], strict_mcp_config=True)
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
                            build_options=lambda _, **kwargs: build_agent_options(tools=[], strict_mcp_config=True),
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
            return build_agent_options(tools=[], strict_mcp_config=True)

        class Services:
            async def bind(self, command):
                self.run_id = command['run_id']

            def prepare_prompt(self, prompt):
                return self.run_id + ':' + prompt

            async def close(self):
                self.run_id = None

        class Client:
            state = ClientState.NEW

            async def configure_turn(self, options):
                pass

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
        client = ClaudeSDKClient(build_agent_options(), client_factory=lambda _: provider)
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

            async def configure_turn(self, options):
                pass

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
                            build_options=lambda _, **kwargs: build_agent_options(tools=None, strict_mcp_config=False),
                            ClaudeSDKClient=lambda *args, **kwargs: client,
                            isolated_sdk_environment=nullcontext,
                            _read_client_commands=commands, emit=emit):
            await asyncio.wait_for(agent_worker.run_client({}), 3)
        self.assertEqual(queries, [("hello", "default")])
        self.assertIn({"type": "client_run_completed", "run_id": "run-test", "session_id": "provider-test"}, sent)
        self.assertFalse(any(e["type"] == "client_error" for e in sent))
        self.assertEqual(client.state, ClientState.CLOSED)
