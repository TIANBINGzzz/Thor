"""回归运行中消息引导的协议、持久化和 SDK 流式确认。"""

import asyncio
import json
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from runtime.auth import JWTError, encode_hs256_jwt, verify_run_jwt
from runtime.claude_sdk import ClaudeSDKClient, SDKMessage
from runtime.protocol import ProtocolError, SteeringRequest
from runtime.run_store import RunStore


class SteeringProtocolTests(unittest.TestCase):
    def test_steering_accepts_text_only_and_rejects_commands_or_extra_fields(self):
        request = SteeringRequest.from_dict({
            "messageId": "message-steer-1",
            "input": {"text": "补充要求：按学院统计"},
        })
        self.assertEqual(request.message_id, "message-steer-1")
        self.assertEqual(request.text, "补充要求：按学院统计")
        for body in (
            {"messageId": "message-steer-2", "input": {"text": "  "}},
            {"messageId": "message-steer-2", "input": {"text": "/clear"}},
            {"messageId": "message-steer-2", "input": {"text": "!help"}},
            {"messageId": "message-steer-2", "input": {"text": "补充", "attachmentRefs": []}},
            {"messageId": "message-steer-2", "input": {"text": "补充"}, "credentials": {}},
        ):
            with self.subTest(body=body), self.assertRaises(ProtocolError):
                SteeringRequest.from_dict(body)

    def test_run_steer_keeps_original_message_claim_and_uses_execute_scope(self):
        now = int(time.time())
        claims = {
            "iss": "issuer", "aud": "audience", "iat": now, "exp": now + 60,
            "jti": uuid.uuid4().hex, "sub": "user-1", "tenant": "tenant-1",
            "runId": "run-1", "capabilityRef": "conversation",
            "businessSessionId": "session-1", "messageId": "message-original-1",
            "scope": "run.execute",
        }
        token = encode_hs256_jwt(claims, "secret")
        verified = verify_run_jwt(token, "secret", run_id="run-1", capability_ref="conversation",
                                  business_session_id="session-1",
                                  tenant_id="tenant-1", user_id="user-1", audience="audience",
                                  issuer="issuer", expected_scope={"run.execute"}, consume_jti=False)
        self.assertEqual(verified["messageId"], "message-original-1")
        with self.assertRaises(JWTError):
            verify_run_jwt(token, "secret", run_id="other-run", capability_ref="conversation",
                           business_session_id="session-1",
                           tenant_id="tenant-1", user_id="user-1", audience="audience",
                           issuer="issuer", expected_scope={"run.execute"}, consume_jti=False)
        self.assertNotEqual(verified["messageId"], "message-steer-1")
        with self.assertRaises(JWTError):
            verify_run_jwt(token, "secret", run_id="run-1", capability_ref="conversation",
                           business_session_id="session-1",
                           tenant_id="tenant-1", user_id="user-1", audience="audience",
                           issuer="issuer", expected_scope={"run.read"}, consume_jti=False)


class SteeringStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = RunStore(":memory:")
        self.addCleanup(self.store.close)
        self.store.create_run("run-1", status="running", tenant_id="tenant-1", user_id="user-1",
                              business_session_id="session-1", capability_ref="conversation",
                              metadata={"messageId": "trigger-1"})

    def test_steering_receipts_are_idempotent_and_never_store_message_text(self):
        text = "补充要求：不要丢失这个敏感内容"
        record, created = self.store.create_steering("run-1", "message-steer-1", text)
        self.assertTrue(created)
        self.assertEqual(record["status"], "accepted")
        duplicate, created_again = self.store.create_steering("run-1", "message-steer-1", text)
        self.assertFalse(created_again)
        self.assertEqual(duplicate, record)
        with self.assertRaises(ValueError):
            self.store.create_steering("run-1", "message-steer-1", "改成另一条消息")
        self.store.update_steering("run-1", "message-steer-1", "delivered")
        self.store.update_steering("run-1", "message-steer-1", "applied")
        self.assertEqual(self.store.get_steering("run-1", "message-steer-1")["status"], "applied")
        serialized = json.dumps(self.store.events_after("run-1"), ensure_ascii=False)
        self.assertNotIn(text, serialized)
        self.assertNotIn("补充要求", self.store._connection.execute(
            "SELECT request_hash FROM run_steering").fetchone()[0])

    def test_event_failure_rolls_back_receipt_and_state(self):
        with patch.object(self.store, 'append_event', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.create_steering('run-1', 'message-steer-1', '补充')
        self.assertIsNone(self.store.get_steering('run-1', 'message-steer-1'))
        self.store.create_steering('run-1', 'message-steer-1', '补充')
        with patch.object(self.store, 'append_event', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.update_steering('run-1', 'message-steer-1', 'delivered')
        self.assertEqual(self.store.get_steering('run-1', 'message-steer-1')['status'], 'accepted')

    def test_restart_settles_inflight_receipt_without_replaying_message_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = directory + '/runs.sqlite3'
            first = RunStore(path)
            first.create_run('run-restart', status='running', tenant_id='tenant-1', user_id='user-1',
                             business_session_id='session-1', capability_ref='conversation',
                             metadata={'messageId': 'trigger'})
            first.create_steering('run-restart', 'message-steer-1', '只留在本次 SDK 输入里的内容')
            first.update_steering('run-restart', 'message-steer-1', 'delivered')
            first.close()

            recovered = RunStore(path)
            try:
                self.assertEqual(recovered.settle_steering(code='runtime_restarted')[0]['status'], 'unknown')
                self.assertEqual(recovered.get_steering('run-restart', 'message-steer-1')['code'], 'runtime_restarted')
                self.assertNotIn('只留在本次 SDK 输入里的内容', json.dumps(recovered.events_after('run-restart'), ensure_ascii=False))
                recovered.update_status('run-restart', 'running')
                self.assertEqual(recovered.create_steering('run-restart', 'message-steer-1', '只留在本次 SDK 输入里的内容')[0]['status'], 'unknown')
            finally:
                recovered.close()

    def test_late_ack_cannot_downgrade_applied_or_append_after_terminal(self):
        self.store.create_steering('run-1', 'm1', '补充')
        self.store.update_steering('run-1', 'm1', 'delivered')
        self.store.update_steering('run-1', 'm1', 'applied')
        self.store.update_steering('run-1', 'm1', 'unknown', code='control_timeout')
        self.assertEqual(self.store.get_steering('run-1', 'm1')['status'], 'applied')
        self.store.create_steering('run-1', 'm2', '第二条')
        self.store.settle_steering('run-1')
        self.store.update_status('run-1', 'succeeded')
        sequence = self.store.get_run('run-1')['lastSequence']
        self.store.update_steering('run-1', 'm2', 'applied')
        self.assertEqual(self.store.get_steering('run-1', 'm2')['status'], 'unknown')
        self.assertEqual(self.store.get_run('run-1')['lastSequence'], sequence)
        self.store.update_status('run-1', 'running')
        self.store.create_steering('run-1', 'm3', '无法确定是否已写入')
        self.store.update_steering('run-1', 'm3', 'unknown', code='control_timeout')
        self.store.update_steering('run-1', 'm3', 'applied')
        self.assertEqual(self.store.get_steering('run-1', 'm3')['status'], 'applied')


async def _until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


class SteeringActorTests(unittest.TestCase):
    def test_actor_gates_readiness_and_routes_receipts_without_interrupt(self):
        from runtime.session_actor import SessionActor, SessionActorError
        from tests.test_session_actor import FakeClientWorker

        async def exercise():
            events = []
            worker = FakeClientWorker([lambda _: []], worker_id=0)
            async def receive(run_id, event):
                events.append((run_id, event))
            actor = SessionActor('session', {}, worker_factory=lambda **_: worker, on_public_event=receive)
            run = asyncio.create_task(actor.submit('run-1', {}))
            try:
                await _until(lambda: bool(worker.sent))
                self.assertFalse(actor.can_steer('run-1'))
                with self.assertRaises(SessionActorError):
                    await actor.steer('run-1', 'm-early', '太早')
                await worker.events.put({'type': 'client_input_ready', 'run_id': 'run-1'})
                await _until(lambda: actor.can_steer('run-1'))
                steering = asyncio.create_task(actor.steer('run-1', 'm1', '补充要求'))
                await _until(lambda: any(e['type'] == 'client_steer' for e in worker.sent))
                self.assertFalse(steering.done())
                # 其他 Run 的确认不能结算本轮等待者。
                await worker.events.put({'type': 'client_steer_ack', 'run_id': 'other', 'message_id': 'm1', 'status': 'delivered'})
                await asyncio.sleep(0.01)
                self.assertFalse(steering.done())
                for status in ('delivered', 'applied'):
                    await worker.events.put({'type': 'client_steer_ack', 'run_id': 'run-1', 'message_id': 'm1', 'status': status})
                self.assertEqual((await steering)['status'], 'delivered')
                await _until(lambda: len(events) == 2)
                self.assertEqual([e[1]['status'] for e in events], ['delivered', 'applied'])
                self.assertNotIn('client_interrupt', [e['type'] for e in worker.sent])
                await worker.events.put({'type': 'result', 'sessionId': 'sdk-history'})
                await _until(lambda: not actor.can_steer('run-1'))
                await worker.events.put({'type': 'client_run_completed', 'run_id': 'run-1'})
                self.assertEqual((await run)['status'], 'succeeded')
            finally:
                await actor.close()
                await asyncio.gather(run, return_exceptions=True)
        asyncio.run(asyncio.wait_for(exercise(), 5))

    def test_unconfirmed_input_retires_worker_before_next_run(self):
        from runtime.session_actor import SessionActor
        from tests.test_session_actor import FakeClientWorker, complete_script

        async def exercise():
            workers = [FakeClientWorker([lambda _: [{'type': 'client_input_ready', 'run_id': 'run-1'}]], worker_id=0),
                       FakeClientWorker([complete_script()], worker_id=1)]
            actor = SessionActor('session', {}, worker_factory=lambda **_: next(pool))
            pool = iter(workers)
            first = asyncio.create_task(actor.submit('run-1', {}))
            try:
                await _until(lambda: actor.can_steer('run-1'))
                steering = asyncio.create_task(actor.steer('run-1', 'm1', '补充'))
                await _until(lambda: len(workers[0].sent) == 2)
                await workers[0].events.put({'type': 'client_run_cancelled', 'run_id': 'run-1',
                                             'session_id': 'history', 'reusable': False})
                self.assertEqual((await steering)['status'], 'unknown')
                await first
                self.assertTrue(workers[0].terminated)
                self.assertEqual((await actor.submit('run-2', {}))['status'], 'succeeded')
                self.assertEqual(workers[1].start_payload['resume'], 'history')
                self.assertEqual([e['type'] for e in workers[1].sent], ['client_query'])
            finally:
                await actor.close()
                await asyncio.gather(first, return_exceptions=True)
        asyncio.run(asyncio.wait_for(exercise(), 5))

    def test_receipt_callback_failure_does_not_fail_a_completed_run_or_strand_waiter(self):
        from runtime.session_actor import SessionActor
        from tests.test_session_actor import FakeClientWorker

        async def exercise():
            worker = FakeClientWorker([lambda _: [{'type': 'client_input_ready', 'run_id': 'run-1'}]], worker_id=0)

            async def fail_receipt(_run_id, event):
                if event.get('status') == 'unknown':
                    raise OSError('receipt storage unavailable')

            actor = SessionActor('session', {}, worker_factory=lambda **_: worker, on_public_event=fail_receipt)
            run = asyncio.create_task(actor.submit('run-1', {}))
            try:
                await _until(lambda: actor.can_steer('run-1'))
                steering = asyncio.create_task(actor.steer('run-1', 'm1', '补充要求'))
                await _until(lambda: len(worker.sent) == 2)
                await worker.events.put({'type': 'client_run_completed', 'run_id': 'run-1'})
                self.assertEqual((await run)['status'], 'succeeded')
                self.assertEqual((await steering)['status'], 'unknown')
            finally:
                await actor.close()
                await asyncio.gather(run, return_exceptions=True)

        asyncio.run(asyncio.wait_for(exercise(), 5))


class SteeringHTTPTests(unittest.TestCase):
    from tests.test_runtime_http import RuntimeHTTPTests as _Fixture
    setUp = _Fixture.setUp
    headers = _Fixture.headers
    seed = _Fixture.seed

    def test_http_routes_steering_to_same_run_with_auth_and_durable_idempotency(self):
        import httpx
        import server
        from runtime.session_actor import SessionActor
        from tests.test_session_actor import FakeClientWorker

        self.seed()
        async def exercise():
            worker = FakeClientWorker([lambda _: [{'type': 'client_input_ready', 'run_id': 'run-test'}]], worker_id=0)
            actor = SessionActor('session', {}, worker_factory=lambda **_: worker,
                                 on_public_event=server._handle_client_public_event)
            manager = SimpleNamespace(actor_for_run=lambda run_id: actor if run_id == 'run-test' else None)
            execution = asyncio.create_task(actor.submit('run-test', {}))
            try:
                await _until(lambda: actor.can_steer('run-test'))
                with patch.object(server, 'SESSION_MANAGER', manager), patch.object(server, 'internal_steering_tasks', {}):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as client:
                        path = '/internal/v1/runs/run-test/steer'
                        body = {'messageId': 'm-steer', 'input': {'text': '补充要求：按学院统计'}}
                        headers = self.headers('run.execute')
                        for invalid in (self.headers('run.read'),
                                        self.headers('run.steer', messageId='m-steer'),
                                        self.headers('run.execute', messageId='m-steer', tenant='other')):
                            self.assertEqual((await client.post(path, json=body, headers=invalid)).status_code, 401)
                        first = await client.post(path, json=body, headers=headers)
                        self.assertEqual(first.status_code, 202, first.text)
                        self.assertEqual(first.json()['steering']['status'], 'accepted')
                        await _until(lambda: len(worker.sent) == 2)
                        await worker.events.put({'type': 'client_steer_ack', 'run_id': 'run-test',
                                                 'message_id': 'm-steer', 'status': 'delivered'})
                        await worker.events.put({'type': 'client_steer_ack', 'run_id': 'run-test',
                                                 'message_id': 'm-steer', 'status': 'applied'})
                        await _until(lambda: self.store.get_steering('run-test', 'm-steer')['status'] == 'applied')
                        duplicate = await client.post(path, json=body, headers=headers)
                        self.assertEqual(duplicate.status_code, 200)
                        self.assertEqual(duplicate.json()['steering']['status'], 'applied')
                        conflict = await client.post(path, json={**body, 'input': {'text': '另一个要求'}}, headers=headers)
                        self.assertEqual(conflict.status_code, 409)
                        receipt = await client.get('/internal/v1/runs/run-test/steering/m-steer',
                                                   headers=self.headers('run.read'))
                        self.assertEqual(receipt.json()['steering']['status'], 'applied')
                        legacy_receipt = await client.get('/internal/v1/runs/run-test/steering/m-steer',
                                                          headers=self.headers('run.steer', messageId='m-steer'))
                        self.assertEqual(legacy_receipt.status_code, 401)
                        await worker.events.put({'type': 'client_run_completed', 'run_id': 'run-test'})
                        await execution
                        await server._finish_run('run-test', {'type': 'run.completed', 'runId': 'run-test', 'payload': {}})
                        self.assertEqual((await client.post(path, json=body, headers=headers)).status_code, 200)
                        late = await client.post(path, json={'messageId': 'm-late', 'input': {'text': '结束后'}},
                                                 headers=self.headers('run.execute', messageId='m-late'))
                        self.assertEqual(late.status_code, 409)
                        self.assertEqual(sum(e['type'] == 'client_steer' for e in worker.sent), 1)
                        serialized = json.dumps(self.store.events_after('run-test'), ensure_ascii=False)
                        self.assertNotIn('按学院统计', serialized)
                        events = [e for e in self.store.events_after('run-test') if e['type'].startswith('steering.')]
                        self.assertEqual([e['type'] for e in events], ['steering.accepted', 'steering.delivered', 'steering.applied'])
                        self.assertTrue(all(e['protocolVersion'] == 'agent-events/v1' for e in events))
                        self.assertTrue(all(e['payload']['displayName'] for e in events))
            finally:
                await actor.close()
                await asyncio.gather(execution, return_exceptions=True)
        asyncio.run(asyncio.wait_for(exercise(), 8))

    def test_control_timeout_is_unknown_and_a_duplicate_never_resends(self):
        import httpx
        import server

        self.seed()
        class SlowActor:
            calls = 0
            def can_steer(self, _run_id):
                return True
            async def steer(self, _run_id, _message_id, _text):
                self.calls += 1
                await asyncio.Event().wait()

        async def exercise():
            actor = SlowActor()
            manager = SimpleNamespace(actor_for_run=lambda _run_id: actor)
            settings = SimpleNamespace(timeouts=SimpleNamespace(worker_control_ms=5))
            with patch.object(server, 'SESSION_MANAGER', manager), \
                 patch.object(server, 'RUNTIME_SETTINGS', settings), \
                 patch.object(server, 'internal_steering_tasks', {}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as client:
                    path = '/internal/v1/runs/run-test/steer'
                    body = {'messageId': 'm-timeout', 'input': {'text': '补充要求'}}
                    token = self.headers('run.execute', messageId='m-timeout')
                    first = await client.post(path, json=body, headers=token)
                    self.assertEqual(first.status_code, 202)
                    await _until(lambda: self.store.get_steering('run-test', 'm-timeout')['status'] == 'unknown')
                    receipt = await client.get('/internal/v1/runs/run-test/steering/m-timeout', headers=token)
                    self.assertEqual(receipt.json()['steering']['code'], 'control_timeout')
                    duplicate = await client.post(path, json=body, headers=token)
                    self.assertEqual(duplicate.status_code, 200)
                    self.assertEqual(duplicate.json()['steering']['status'], 'unknown')
                    await asyncio.sleep(.01)
                    self.assertEqual(actor.calls, 1)

        asyncio.run(asyncio.wait_for(exercise(), 5))

    def test_live_sse_recovers_delayed_steering_notification_in_sequence(self):
        import server
        from starlette.requests import Request

        self.seed()
        async def exercise():
            request = Request({'type': 'http', 'headers': [
                (key.lower().encode(), value.encode()) for key, value in self.headers().items()
            ]})
            response = await server.internal_run_events('run-test', request, afterSequence=0)
            stream = response.body_iterator
            first = asyncio.create_task(anext(stream))
            try:
                await _until(lambda: bool(server.internal_subscribers.get('run-test')))
                self.store.create_steering('run-test', 'm-delayed', '补充要求')
                accepted = self.store.events_after('run-test')[0]
                # accepted 通知尚未运行时，其他生产者已提交并通知更高序号。
                for _ in range(501):
                    self.store.append_event('run-test', {'runId': 'run-test', 'type': 'message.delta',
                        'payload': {'textDelta': '继续回答'}})
                await server._publish_internal_event('run-test', {
                    'runId': 'run-test', 'type': 'run.completed', 'payload': {}})
                await server._notify_stored_event(accepted)
                frames = [await first]
                frames.extend([frame async for frame in stream])
                events = [json.loads(line[6:]) for frame in frames
                          for line in frame.splitlines() if line.startswith('data: ')]
                self.assertEqual([event['sequence'] for event in events], list(range(1, 504)))
                self.assertEqual(events[0]['type'], 'steering.accepted')
                self.assertEqual(events[-1]['type'], 'run.completed')
            finally:
                if not first.done():
                    first.cancel()
                await asyncio.gather(first, return_exceptions=True)
                await stream.aclose()

        asyncio.run(asyncio.wait_for(exercise(), 5))

    def test_slow_request_notifies_only_its_newly_accepted_receipt(self):
        import httpx
        import server

        self.seed()
        async def exercise():
            entered = asyncio.Event()
            release = asyncio.Event()
            class Actor:
                def can_steer(self, _run_id):
                    return True
                async def steer(self, *_args):
                    entered.set()
                    await release.wait()
                    return {'status': 'delivered'}

            async def slow_body():
                # 读取 HTTP 正文时 Run 仍在输出，超过默认事件分页上限。
                for _ in range(501):
                    self.store.append_event('run-test', {'runId': 'run-test',
                        'type': 'message.delta', 'payload': {'textDelta': '继续回答'}})
                yield json.dumps({'messageId': 'm-slow', 'input': {'text': '补充要求'}}).encode()

            queue = asyncio.Queue()
            manager = SimpleNamespace(actor_for_run=lambda _run_id: Actor())
            with patch.object(server, 'SESSION_MANAGER', manager), \
                 patch.object(server, 'internal_steering_tasks', {}), \
                 patch.dict(server.internal_subscribers, {'run-test': {queue}}):
                try:
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://test') as client:
                        response = await client.post('/internal/v1/runs/run-test/steer', content=slow_body(),
                            headers={**self.headers('run.execute', messageId='m-slow'), 'content-type': 'application/json'})
                    self.assertEqual(response.status_code, 202, response.text)
                    await entered.wait()
                    notified = []
                    while not queue.empty():
                        notified.append(queue.get_nowait())
                    self.assertEqual([(event['sequence'], event['type']) for event in notified],
                                     [(502, 'steering.accepted')])
                finally:
                    release.set()
                    await asyncio.gather(*server.internal_steering_tasks.values(), return_exceptions=True)

        asyncio.run(asyncio.wait_for(exercise(), 5))


class _StreamingProvider:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.inputs = []

    async def connect(self, *_args):
        return None

    async def disconnect(self):
        return None

    async def query(self, prompt, session_id="default"):
        if isinstance(prompt, str):
            return None
        async for message in prompt:
            if "session_id" not in message:
                message["session_id"] = session_id
            self.inputs.append(message)

    async def receive_response(self):
        while True:
            message = await self.messages.get()
            yield message
            if message.kind == "result":
                return

    async def interrupt(self):
        return None


class SteeringClientTests(unittest.TestCase):
    def test_streamed_steer_survives_intermediate_result_and_is_acknowledged_by_uuid(self):
        async def exercise():
            provider = _StreamingProvider()
            options = SimpleNamespace(mcp_servers={}, model="model", env={},
                                      thinking=None, effort=None, add_dirs=[], permission_mode="bypassPermissions")
            client = ClaudeSDKClient(options, client_factory=lambda _options: provider,
                                     connect_timeout_ms=1000, query_timeout_ms=1000,
                                     receive_timeout_ms=1000, disconnect_timeout_ms=1000)
            await client.connect()
            await client.query("initial prompt")
            messages = []
            iterator = client.receive_response(timeout_ms=1000)
            next_message = asyncio.create_task(iterator.__anext__())
            await asyncio.sleep(0)
            await client.steer("补充要求：按学院统计", "message-steer-1", session_id="default")
            self.assertEqual(provider.inputs[0]["message"]["content"], "补充要求：按学院统计")
            steer_uuid = provider.inputs[0]["uuid"]
            await provider.messages.put(SDKMessage(kind="result", data={"subtype": "success",
                "num_turns": 2, "duration_ms": 12, "duration_api_ms": 8,
                "usage": {"input_tokens": 3, "output_tokens_details": {"thinking_tokens": 1}}}))
            await asyncio.sleep(0)
            await provider.messages.put(SDKMessage(kind="user", data={"message": {"role": "user"}}, uuid=steer_uuid))
            await provider.messages.put(SDKMessage(kind="result", data={"subtype": "success",
                "num_turns": 1, "duration_ms": 20, "duration_api_ms": 13,
                "usage": {"input_tokens": 4, "output_tokens_details": {"thinking_tokens": 2}},
                "model_usage": {"model": {"inputTokens": 7}}}, session_id="sdk-session"))
            while True:
                try:
                    messages.append(await asyncio.wait_for(next_message, 1))
                except StopAsyncIteration:
                    break
                if messages[-1].kind == "result":
                    break
                next_message = asyncio.create_task(iterator.__anext__())
            await iterator.aclose()
            steering = [message for message in messages if message.kind == "steering"]
            self.assertEqual(len(steering), 1)
            self.assertEqual(steering[0].data, {"messageId": "message-steer-1", "status": "applied"})
            self.assertEqual(sum(message.kind == "result" for message in messages), 1)
            result = messages[-1].data
            self.assertEqual((result['num_turns'], result['duration_ms'], result['duration_api_ms']), (3, 32, 21))
            self.assertEqual(result['usage'], {'input_tokens': 7, 'output_tokens_details': {'thinking_tokens': 3}})
            self.assertEqual(result['model_usage'], {'model': {'inputTokens': 7}})

        asyncio.run(exercise())

if __name__ == "__main__":
    unittest.main()
