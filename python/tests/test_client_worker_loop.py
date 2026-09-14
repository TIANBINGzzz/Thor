import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import agent_worker
from runtime.claude_sdk import ClaudeSDKClient, ClientState, SDKMessage


class ClientWorkerLoopTests(unittest.IsolatedAsyncioTestCase):
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
