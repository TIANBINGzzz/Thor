import asyncio
import unittest
from unittest.mock import patch

from runtime.session_actor import ActorState, SessionActor, SessionActorError, SessionManager


class FakeClientWorker:
    """Deterministic persistent-worker double for actor lifecycle tests."""

    def __init__(self, scripts, *, worker_id):
        self.scripts = scripts
        self.worker_id = worker_id
        self.events = asyncio.Queue()
        self.sent = []
        self.start_payload = None
        self.started = False
        self.closed = False
        self.terminated = False

    @property
    def process(self):
        return None

    @property
    def alive(self):
        return self.started and not self.closed and not self.terminated

    async def start(self, payload):
        self.start_payload = dict(payload)
        self.started = True

    async def send(self, message):
        self.sent.append(dict(message))
        kind = message.get("type")
        if kind == "client_query":
            if not self.scripts:
                raise RuntimeError("no fake worker script")
            script = self.scripts.pop(0)
            for event in script(message):
                await self.events.put(dict(event))
        elif kind == "client_cancel":
            await self.events.put({
                "type": "client_run_cancelled",
                "run_id": message.get("run_id"),
            })
        elif kind == "client_interrupt":
            await self.events.put({
                "type": "text",
                "run_id": message.get("run_id"),
                "text": "interrupted",
                "scope": "main",
            })
            await self.events.put({
                "type": "client_run_completed",
                "run_id": message.get("run_id"),
                "session_id": "session-after-interrupt",
            })
        elif kind == "client_close":
            await self.events.put({
                "type": "client_run_cancelled",
                "run_id": message.get("run_id"),
            })

    async def next_event(self):
        return await self.events.get()

    async def close(self):
        self.closed = True

    async def terminate(self):
        self.terminated = True
        self.closed = True


def complete_script(session_id="session-1"):
    def script(message):
        run_id = message["run_id"]
        return [
            {"type": "text", "run_id": run_id, "text": "answer", "scope": "main"},
            {"type": "client_run_completed", "run_id": run_id, "session_id": session_id},
        ]

    return script


class SessionActorTests(unittest.TestCase):
    def test_close_simultaneous_with_run_terminal_waits_for_cleanup_and_exit(self):
        async def exercise(terminal):
            cleaned = False
            worker = FakeClientWorker([lambda _: [{'type': terminal, 'code': 'model_failed'}]], worker_id=0)
            actor = SessionActor('session', {}, worker_factory=lambda **_: worker)
            original_wait = asyncio.wait
            original_close = worker.close

            async def wait_for_both(tasks, **kwargs):
                # 固定重现终态和 close 在同一轮被取到的竞态，不依赖调度时机。
                return await original_wait(tasks, timeout=kwargs.get('timeout'),
                                           return_when=asyncio.ALL_COMPLETED)

            async def cleanup():
                nonlocal cleaned
                cleaned = True

            async def close():
                self.assertTrue(cleaned)
                await original_close()

            worker.close = close
            try:
                with patch('runtime.session_actor.asyncio.wait', side_effect=wait_for_both):
                    run = asyncio.create_task(actor.submit('run', {}, cleanup=cleanup))
                    await _wait_until(lambda: bool(worker.sent))
                    closing = asyncio.create_task(actor.close())
                    outcome, close_result = await asyncio.gather(run, closing, return_exceptions=True)
                self.assertIsNone(close_result)
                self.assertEqual(actor.state, ActorState.CLOSED)
                self.assertTrue(worker.closed)
                self.assertIsNone(actor._worker)
                if terminal == 'client_error':
                    self.assertIsInstance(outcome, SessionActorError)
                    self.assertEqual(outcome.code, 'model_failed')
                else:
                    self.assertEqual(outcome['status'],
                                     'succeeded' if terminal == 'client_run_completed' else 'cancelled')
            finally:
                await actor.close()

        for terminal in ('client_run_completed', 'client_run_cancelled', 'client_error'):
            with self.subTest(terminal=terminal):
                asyncio.run(asyncio.wait_for(exercise(terminal), 2))

    def test_failed_explicit_close_keeps_owner_and_blocks_replacement_until_exit(self):
        async def exercise():
            workers = []
            allow_exit = False
            close_attempts = 0

            def factory(**kwargs):
                worker = FakeClientWorker([complete_script('kept-history')], worker_id=len(workers))
                workers.append(worker)
                original_close = worker.close

                async def close():
                    nonlocal close_attempts
                    close_attempts += 1
                    if not allow_exit:
                        raise OSError('process still running')
                    await original_close()

                async def terminate():
                    if not allow_exit:
                        raise OSError('termination failed')
                    await original_close()

                worker.close, worker.terminate = close, terminate
                return worker

            manager = SessionManager(worker_factory=factory)
            try:
                await manager.submit('session', {}, 'first', {})
                actor = manager._actors['session']
                with self.assertRaises(SessionActorError):
                    await asyncio.wait_for(manager.close_all(), .5)
                self.assertIs(manager._actors['session'], actor)
                self.assertIs(actor._worker, workers[0])
                self.assertNotEqual(actor.state, ActorState.CLOSED)
                with self.assertRaises(SessionActorError):
                    await asyncio.wait_for(manager.submit('session', {}, 'blocked', {}), .5)
                self.assertEqual(len(workers), 1)
                self.assertTrue(workers[0].alive)
                previous_attempts = close_attempts
                await _wait_until(lambda: close_attempts > previous_attempts)
                allow_exit = True
                await _wait_until(lambda: actor.state == ActorState.CLOSED)
                self.assertIsNone(actor._worker)
                result = await manager.submit('session', {}, 'restored', {})
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(workers[1].start_payload['resume'], 'kept-history')
            finally:
                allow_exit = True
                await manager.close_all()
        asyncio.run(asyncio.wait_for(exercise(), 3))

    def test_close_during_run_settles_failure_and_retries_without_hanging(self):
        async def exercise():
            worker = FakeClientWorker([lambda message: []], worker_id=0)
            allow_exit = False
            original = worker.close

            async def close():
                if not allow_exit:
                    raise OSError('close failed')
                await original()

            worker.close = close
            actor = SessionActor('session', {}, worker_factory=lambda **_: worker)
            try:
                run = asyncio.create_task(actor.submit('run', {}))
                await _wait_until(lambda: bool(worker.sent))
                with self.assertRaises(SessionActorError):
                    await asyncio.wait_for(actor.close(), .5)
                self.assertEqual((await run)['status'], 'cancelled')
                self.assertIs(actor._worker, worker)
                allow_exit = True
                await _wait_until(lambda: actor.state == ActorState.CLOSED)
                self.assertIsNone(actor._worker)
            finally:
                allow_exit = True
                await actor.close()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_run_failure_and_termination_failure_still_settle_and_retry_safely(self):
        async def exercise():
            workers, cleaned = [], []
            def factory(**kwargs):
                scripts = [lambda message: [{'type': 'client_error', 'code': 'model_failed'}]] if not workers else [complete_script()]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                if len(workers) == 1:
                    original = worker.terminate
                    attempts = 0
                    async def terminate():
                        nonlocal attempts
                        attempts += 1
                        if attempts == 1:
                            raise OSError('termination failed')
                        await original()
                    worker.terminate = terminate
                return worker
            async def cleanup():
                cleaned.append(True)
            actor = SessionActor('s', {}, worker_factory=factory)
            try:
                with self.assertRaises(SessionActorError) as caught:
                    await asyncio.wait_for(actor.submit('broken', {}, cleanup=cleanup), .5)
                self.assertEqual(caught.exception.code, 'model_failed')
                self.assertEqual(cleaned, [True])
                self.assertIs(actor._worker, workers[0])
                self.assertTrue(workers[0].alive)
                result = await actor.submit('retry', {})
                self.assertEqual(result['status'], 'succeeded')
                self.assertTrue(workers[0].terminated)
            finally:
                await actor.close()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_async_capacity_failure_does_not_poison_next_submission(self):
        from runtime.process import ClientWorkerError
        async def exercise():
            attempts = 0
            async def factory(**kwargs):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ClientWorkerError('Client 容量已满，请稍后重试')
                return FakeClientWorker([complete_script()], worker_id=0)
            manager = SessionManager(worker_factory=factory)
            try:
                with self.assertRaises(SessionActorError):
                    await manager.submit('s', {}, 'full', {})
                result = await manager.submit('s', {}, 'retry', {})
                self.assertEqual(result['status'], 'succeeded')
            finally:
                await manager.close_all()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_runtime_applied_marker_is_private_and_marks_effective_snapshot(self):
        async def exercise():
            snapshots, public = [], []
            def script(message):
                return [{'type': 'client_runtime_applied'}, *complete_script('sdk-session')(message)]
            worker = FakeClientWorker([script], worker_id=0)
            async def on_state(snapshot):
                snapshots.append(dict(snapshot))
            async def on_public(_run_id, event):
                public.append(event)
            actor = SessionActor('s', {}, worker_factory=lambda **_: worker,
                                 on_state=on_state, on_public_event=on_public)
            try:
                result = await actor.submit('run', {}, initial_payload={
                    '_client_runtime': {'effort': 'low'},
                })
                self.assertEqual(result['status'], 'succeeded')
                self.assertTrue(any(snapshot['runtimeApplied'] and snapshot['activeRunId'] == 'run'
                                    for snapshot in snapshots))
                self.assertFalse(any(event.get('type') == 'client_runtime_applied' for event in public))
            finally:
                await actor.close()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_unapplied_runtime_does_not_replace_last_applied_or_restored_preferences(self):
        async def exercise(restored):
            workers = []
            def applied(message):
                return [{'type': 'client_runtime_applied'}, *complete_script()(message)]
            scripts_by_worker = (
                [[lambda _: [{'type': 'client_error', 'code': 'configuration_failed'}]],
                 [applied]] if restored else
                [[applied, lambda _: [{'type': 'client_error', 'code': 'configuration_failed'}]], [applied]])

            def factory(**kwargs):
                scripts = scripts_by_worker[len(workers)]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                return worker

            def payload(effort=None):
                return {'_workflow_assets': {'runtime': {} if effort is None else {'effort': effort}}}

            actor = SessionActor('session', {
                '_client_runtime': {'effort': 'low'} if restored else {},
            }, worker_factory=factory)
            try:
                with patch('runtime.config.prepare_workflow_assets', side_effect=lambda p: p['_workflow_assets']):
                    if not restored:
                        await actor.submit('applied', {}, initial_payload=payload('low'))
                    with self.assertRaises(SessionActorError):
                        await actor.submit('unapplied', {}, initial_payload=payload('high'))
                    result = await actor.submit('inherited', {}, initial_payload=payload())
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(workers[-1].sent[0]['_client_runtime']['effort'], 'low')
                self.assertEqual(actor.snapshot()['effectiveRuntime']['effort'], 'low')
            finally:
                await actor.close()

        for restored in (False, True):
            with self.subTest(restored=restored):
                asyncio.run(asyncio.wait_for(exercise(restored), 2))

    def test_capacity_reclaim_protects_input_and_waits_for_process_exit_then_resumes(self):
        async def exercise():
            workers = []
            exiting, exited = asyncio.Event(), asyncio.Event()
            def factory(**kwargs):
                worker = FakeClientWorker([complete_script('history')], worker_id=len(workers))
                workers.append(worker)
                if len(workers) == 1:
                    async def terminate():
                        exiting.set()
                        await exited.wait()
                        worker.terminated = True
                    worker.terminate = terminate
                return worker
            manager = SessionManager(worker_factory=factory)
            try:
                await manager.submit('old', {}, 'one', {})
                await manager.submit('new', {}, 'two', {})
                manager.pin_session('old')
                self.assertTrue(await manager.reclaim_oldest_idle())
                self.assertTrue(workers[1].terminated)
                self.assertFalse(workers[0].terminated)
                manager.unpin_session('old')
                reclaim = asyncio.create_task(manager.reclaim_oldest_idle())
                await exiting.wait()
                self.assertFalse(reclaim.done())
                self.assertIs(manager._actors['old']._worker, workers[0])
                pending = asyncio.create_task(manager.submit('old', {}, 'three', {}))
                await asyncio.sleep(0)
                self.assertEqual(len(workers), 2)
                exited.set()
                self.assertTrue(await reclaim)
                self.assertEqual((await pending)['status'], 'succeeded')
                self.assertEqual(workers[2].start_payload['resume'], 'history')
            finally:
                exited.set()
                await manager.close_all()
        asyncio.run(asyncio.wait_for(exercise(), 3))

    def test_failed_idle_reclaim_keeps_actor_as_retry_owner(self):
        async def exercise():
            workers = []
            def factory(**kwargs):
                worker = FakeClientWorker([complete_script('preserved-history')], worker_id=len(workers))
                workers.append(worker)
                if len(workers) == 1:
                    original = worker.terminate
                    attempts = 0
                    async def terminate():
                        nonlocal attempts
                        attempts += 1
                        if attempts == 1:
                            raise OSError('temporary termination failure')
                        await original()
                    worker.terminate = terminate
                return worker

            manager = SessionManager(idle_ttl_ms=10, worker_factory=factory)
            try:
                await manager.submit('session', {}, 'first', {})
                actor = manager._actors['session']
                worker = workers[0]
                self.assertFalse(await manager.reclaim_oldest_idle())
                self.assertIs(actor._worker, worker)
                self.assertNotEqual(actor.state, ActorState.CLOSED)
                await _wait_until(lambda: worker.terminated, timeout=1)
                self.assertIsNone(actor._worker)
                self.assertNotEqual(actor.state, ActorState.CLOSED)
                result = await manager.submit('session', {}, 'restored', {})
                self.assertEqual(result['status'], 'succeeded')
                self.assertEqual(workers[1].start_payload['resume'], 'preserved-history')
            finally:
                await manager.close_all()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_cleanup_and_queued_preparation_are_not_idle_candidates(self):
        async def exercise():
            cleaning, release = asyncio.Event(), asyncio.Event()
            worker = FakeClientWorker([complete_script(), complete_script()], worker_id=0)
            manager = SessionManager(worker_factory=lambda **kw: worker)
            async def cleanup():
                cleaning.set()
                await release.wait()
            try:
                first = asyncio.create_task(manager.submit('s', {}, 'one', {}, cleanup=cleanup))
                await cleaning.wait()
                self.assertFalse(await manager.reclaim_oldest_idle())
                second = asyncio.create_task(manager.submit('s', {}, 'two', {}))
                await asyncio.sleep(0)
                self.assertFalse(await manager.reclaim_oldest_idle())
                release.set()
                await asyncio.gather(first, second)
                self.assertTrue(await manager.reclaim_oldest_idle())
            finally:
                release.set()
                await manager.close_all()
        asyncio.run(asyncio.wait_for(exercise(), 3))

    def test_preparation_exception_keeps_private_cause_through_actor_boundary(self):
        from runtime.telemetry import exception_event
        async def exercise():
            async def prepare():
                raise ValueError('preparation rejected business-private-value')
            actor = SessionActor('diagnostic-session', {})
            try:
                with self.assertRaises(SessionActorError) as caught:
                    await actor.submit('diagnostic-run', {}, prepare=prepare)
                self.assertEqual(caught.exception.code, 'session_actor_error')
                event = exception_event(caught.exception, scope='runtime', secrets=('business-private-value',))
                self.assertTrue(event['causes'])
                self.assertEqual(event['causes'][0]['exceptionType'], 'ValueError')
                self.assertEqual(event['causes'][0]['message'], 'preparation rejected [REDACTED]')
                self.assertTrue(event['causes'][0]['frames'])
            finally:
                await actor.close()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_concurrent_cancel_sends_only_one_worker_command(self):
        async def exercise():
            sent, release = asyncio.Event(), asyncio.Event()
            worker = FakeClientWorker([lambda _: []], worker_id=0)
            original_send = worker.send
            async def send(message):
                if message['type'] == 'client_cancel':
                    sent.set()
                    await release.wait()
                await original_send(message)
            worker.send = send
            actor = SessionActor('session', {}, worker_factory=lambda **kw: worker)
            pending = asyncio.create_task(actor.submit('run-1', {}))
            await _wait_until(lambda: any(m['type'] == 'client_query' for m in worker.sent))
            first = asyncio.create_task(actor.cancel('run-1'))
            await sent.wait()
            second = asyncio.create_task(actor.cancel('run-1'))
            await asyncio.sleep(0)
            release.set()
            results = await asyncio.gather(first, second, return_exceptions=True)
            self.assertEqual(results, [None, None])
            self.assertEqual((await pending)['status'], 'cancelled')
            self.assertEqual(len([m for m in worker.sent if m['type'] == 'client_cancel']), 1)
            await actor.close()
        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_performance_callback_failure_does_not_fail_run_or_next_command(self):
        async def exercise():
            async def receive(run_id, event):
                if event['type'] == 'performance':
                    raise OSError('private diagnostic storage unavailable')

            def script(message):
                return [{'type': 'performance', 'version': 1, 'scope': 'worker_run',
                         'elapsedMs': {}, 'cpuMs': {}, 'counts': {}}] + complete_script()(message)

            worker = FakeClientWorker([script, script], worker_id=0)
            worker.startup_traces = [{'type': 'performance', 'version': 1, 'scope': 'worker_boot',
                                     'elapsedMs': {'imported': 10}, 'cpuMs': {}, 'counts': {}}]
            actor = SessionActor('session', {}, on_public_event=receive, worker_factory=lambda **kw: worker)
            try:
                results = await asyncio.gather(actor.submit('r1', {}), actor.submit('r2', {}))
                self.assertEqual([r['status'] for r in results], ['succeeded', 'succeeded'])
                await _wait_until(lambda: actor.snapshot()['activeRunId'] is None)
                self.assertEqual(actor.state, ActorState.READY)
                self.assertFalse(worker.closed)
            finally:
                await actor.close()

        with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1'}):
            asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_actor_observation_publishes_live_milestones_with_run_identity(self):
        async def exercise():
            observations = []

            def observe(run_id, event):
                observations.append((run_id, event))

            actor = SessionActor(
                'session', {}, on_public_event=lambda *_: asyncio.sleep(0),
                on_observation=observe,
                worker_factory=lambda **kw: FakeClientWorker([complete_script()], worker_id=0),
            )
            try:
                await actor.submit('run-live', {})
            finally:
                await actor.close()

            actor_events = [(run_id, event) for run_id, event in observations
                            if event.get('scope') == 'actor']
            live = [(run_id, event) for run_id, event in actor_events
                    if event.get('live') is True]
            self.assertTrue(live)
            self.assertIn('queue_exit', live[0][1]['elapsedMs'])
            self.assertEqual({run_id for run_id, _ in actor_events}, {'run-live'})

        asyncio.run(asyncio.wait_for(exercise(), 2))

    def test_timing_distinguishes_new_worker_and_reuse_with_fresh_origin(self):
        async def exercise():
            events = []

            async def receive(run_id, event):
                events.append((run_id, event))

            actor = SessionActor('session', {}, on_public_event=receive,
                worker_factory=lambda **kw: FakeClientWorker([complete_script(), complete_script()], worker_id=0))
            await actor.submit('r1', {})
            await actor.submit('r2', {})
            await actor.close()
            timings = {r: e for r, e in events if e['type'] == 'performance' and e['scope'] == 'actor'}
            self.assertEqual(timings['r1']['counts']['worker_created'], 1)
            self.assertEqual(timings['r1']['counts']['worker_reused'], 0)
            self.assertEqual(timings['r2']['counts']['worker_created'], 0)
            self.assertEqual(timings['r2']['counts']['worker_reused'], 1)
            self.assertLessEqual(timings['r2']['elapsedMs']['queue_exit'], timings['r2']['elapsedMs']['query_sent'])
            self.assertEqual(len([e for r, e in events if e['type'] == 'text']), 2)

        with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1'}):
            asyncio.run(exercise())

    def test_preparation_can_be_cancelled_without_starting_sdk(self):
        async def exercise(operation):
            workers = []
            started = asyncio.Event()
            cleaned = []

            def factory(**kwargs):
                worker = FakeClientWorker([complete_script()], worker_id=0)
                workers.append(worker)
                return worker

            async def prepare():
                started.set()
                await asyncio.Event().wait()

            async def cleanup():
                cleaned.append(True)

            actor = SessionActor("session", {}, worker_factory=factory)
            pending = asyncio.create_task(actor.submit("run-1", {}, prepare=prepare, cleanup=cleanup))
            await started.wait()
            await getattr(actor, operation)("run-1")
            self.assertEqual((await pending)["status"], "cancelled")
            self.assertEqual(cleaned, [True])
            self.assertEqual(workers, [])
            self.assertEqual((await actor.submit("run-2", {}))["status"], "succeeded")
            await actor.close()

        for operation in ("cancel", "interrupt"):
            with self.subTest(operation=operation):
                asyncio.run(asyncio.wait_for(exercise(operation), timeout=2))

    def test_preparation_and_queue_have_separate_execution_budgets(self):
        async def exercise():
            prepared = []
            started = asyncio.Event()
            release = asyncio.Event()
            actor = SessionActor("session", {}, worker_factory=lambda **kw: FakeClientWorker(
                [complete_script(), complete_script()], worker_id=0))

            async def prepare():
                started.set()
                await release.wait()
                return {"timeout_ms": 50}

            async def queued_prepare():
                prepared.append(True)
                return {}

            active = asyncio.create_task(actor.submit("active", {"timeout_ms": 10}, prepare=prepare))
            await started.wait()
            with self.assertRaises(SessionActorError) as caught:
                await actor.submit("queued", {"queue_timeout_ms": 20}, prepare=queued_prepare)
            self.assertEqual(caught.exception.code, "run_queue_timeout")
            self.assertFalse(active.done())
            release.set()
            self.assertEqual((await active)["status"], "succeeded")
            self.assertEqual((await actor.submit("after", {}))["status"], "succeeded")
            self.assertEqual(prepared, [])
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_preparation_and_cleanup_are_serialized_with_queued_runs(self):
        async def exercise():
            workers = []
            order = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script(), complete_script()], worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)

            async def prepare(run_id):
                order.append(f"prepare:{run_id}")
                return {"prompt": f"prepared-{run_id}"}

            async def cleanup(run_id):
                order.append(f"cleanup:{run_id}")

            first, second = await asyncio.wait_for(
                asyncio.gather(
                    actor.submit(
                        "run-1",
                        {"prompt": "base-1"},
                        prepare=lambda: prepare("run-1"),
                        cleanup=lambda: cleanup("run-1"),
                    ),
                    actor.submit(
                        "run-2",
                        {"prompt": "base-2"},
                        prepare=lambda: prepare("run-2"),
                        cleanup=lambda: cleanup("run-2"),
                    ),
                ),
                timeout=1,
            )

            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(second["status"], "succeeded")
            self.assertEqual(
                order,
                ["prepare:run-1", "cleanup:run-1", "prepare:run-2", "cleanup:run-2"],
            )
            queries = [item for item in workers[0].sent if item.get("type") == "client_query"]
            self.assertEqual([item["prompt"] for item in queries], ["prepared-run-1", "prepared-run-2"])
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_preparation_failure_still_runs_cleanup_before_rejecting_run(self):
        async def exercise():
            cleanup_called = []

            async def prepare():
                raise SessionActorError("cannot prepare", code="run_preparation_failed")

            async def cleanup():
                cleanup_called.append(True)

            actor = SessionActor("session", {}, idle_ttl_ms=10_000)
            with self.assertRaises(SessionActorError) as error:
                await actor.submit("run-prepare-failed", {}, prepare=prepare, cleanup=cleanup)
            self.assertEqual(error.exception.code, "run_preparation_failed")
            self.assertEqual(cleanup_called, [True])
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_same_session_serializes_multiple_runs_and_reuses_worker(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script(), complete_script()], worker_id=len(workers))
                workers.append(worker)
                return worker

            public = []

            async def on_public(run_id, event):
                public.append((run_id, event))

            actor = SessionActor(
                "tenant:user:session:writing-docx",
                {"resume": ""},
                on_public_event=on_public,
                worker_factory=factory,
                idle_ttl_ms=10_000,
            )
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    actor.submit("run-1", {"prompt": "one"}),
                    actor.submit("run-2", {"prompt": "two"}),
                ),
                timeout=1,
            )

            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(second["status"], "succeeded")
            self.assertEqual(len(workers), 1)
            self.assertEqual([item[0] for item in public], ["run-1", "run-2"])
            self.assertEqual(actor.state, ActorState.READY)
            self.assertEqual(actor.snapshot()["runtimeSessionRef"], "session-1")
            await actor.close()
            self.assertEqual(actor.state, ActorState.CLOSED)
            self.assertTrue(workers[0].closed)

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_cancel_keeps_worker_and_next_run_reuses_it(self):
        async def exercise():
            workers = []

            def hanging_script(message):
                return [{"type": "text", "run_id": message["run_id"], "text": "waiting"}]

            def factory(**_kwargs):
                scripts = [hanging_script, complete_script("session-2")]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)
            pending = asyncio.create_task(actor.submit("run-cancel", {"prompt": "hang"}))
            await _wait_until(lambda: actor.active_run_id == "run-cancel")
            await actor.cancel("run-cancel")
            cancelled = await asyncio.wait_for(pending, timeout=1)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertFalse(workers[0].terminated)
            self.assertEqual(actor.state, ActorState.READY)

            completed = await actor.submit("run-after-cancel", {"prompt": "recover"})
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(len(workers), 1)
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_cancel_without_worker_terminal_times_out_and_rebuilds(self):
        async def exercise():
            workers = []

            def factory(**kwargs):
                worker = FakeClientWorker([lambda _: []] if not workers else [complete_script()],
                                          worker_id=len(workers))
                original_send = worker.send

                async def send(message):
                    if message['type'] != 'client_cancel':
                        await original_send(message)
                worker.send = send
                workers.append(worker)
                return worker

            actor = SessionActor('session', {}, worker_factory=factory, control_timeout_ms=20)
            try:
                pending = asyncio.create_task(actor.submit('r1', {'timeout_ms': 2000}))
                await _wait_until(lambda: bool(workers and workers[0].sent))
                await actor.cancel('r1')
                with self.assertRaises(SessionActorError) as failure:
                    await asyncio.wait_for(pending, .5)
                self.assertEqual(failure.exception.code, 'sdk_timeout')
                self.assertTrue(workers[0].terminated)
                self.assertEqual((await actor.submit('r2', {}))['status'], 'succeeded')
                self.assertEqual(len(workers), 2)
            finally:
                await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), 3))

    def test_next_run_waits_for_cancelled_run_cleanup_and_reuses_worker(self):
        async def exercise():
            cleaning, release, prepared = (asyncio.Event() for _ in range(3))
            worker = FakeClientWorker([lambda _: [], complete_script()], worker_id=0)
            factory = unittest.mock.Mock(return_value=worker)
            actor = SessionActor('session', {}, worker_factory=factory)

            async def cleanup():
                cleaning.set()
                await release.wait()

            async def prepare():
                prepared.set()
                return {}

            try:
                first = asyncio.create_task(actor.submit('r1', {}, cleanup=cleanup))
                await _wait_until(lambda: bool(worker.sent))
                second = asyncio.create_task(actor.submit('r2', {}, prepare=prepare))
                await _wait_until(lambda: 'r2' in actor._run_commands)
                await actor.cancel('r1')
                await cleaning.wait()
                self.assertFalse(prepared.is_set())
                self.assertFalse(first.done())
                self.assertEqual([m['run_id'] for m in worker.sent if m['type'] == 'client_query'], ['r1'])
                release.set()
                self.assertEqual((await first)['status'], 'cancelled')
                self.assertEqual((await second)['status'], 'succeeded')
                factory.assert_called_once()
                self.assertFalse(worker.terminated)
            finally:
                release.set()
                await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), 3))

    def test_cancelled_queued_run_never_prepares_or_reaches_worker(self):
        async def exercise():
            workers = []
            prepared = []

            def hanging_script(message):
                return [{"type": "text", "run_id": message["run_id"], "text": "waiting"}]

            def factory(**_kwargs):
                worker = FakeClientWorker([hanging_script], worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)
            first = asyncio.create_task(actor.submit("run-active", {"prompt": "hang"}))
            await _wait_until(lambda: actor.active_run_id == "run-active")
            second = asyncio.create_task(actor.submit(
                "run-queued",
                {"prompt": "must-not-run"},
                prepare=lambda: _record_preparation(prepared),
            ))
            await _wait_until(lambda: "run-queued" in actor._run_commands)
            await actor.cancel("run-queued")
            await asyncio.wait_for(actor.cancel("run-queued"), timeout=0.1)
            await actor.cancel("run-active")

            queued = await asyncio.wait_for(second, timeout=1)
            active = await asyncio.wait_for(first, timeout=1)
            self.assertEqual(queued["status"], "cancelled")
            self.assertEqual(active["status"], "cancelled")
            self.assertEqual(prepared, [])
            queries = [item for item in workers[0].sent if item.get("type") == "client_query"]
            self.assertEqual([item["run_id"] for item in queries], ["run-active"])
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_worker_silence_hits_actor_deadline_and_next_run_rebuilds(self):
        async def exercise():
            workers = []

            def silent_script(_message):
                return []

            def factory(**_kwargs):
                scripts = [[silent_script], [complete_script("session-recovered")]][len(workers)]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)
            with self.assertRaises(SessionActorError) as caught:
                await actor.submit("run-timeout", {"prompt": "hang", "timeout_ms": 20})
            self.assertEqual(caught.exception.code, "sdk_timeout")
            self.assertTrue(workers[0].terminated)

            recovered = await actor.submit("run-recovered", {"prompt": "recover", "timeout_ms": 1000})
            self.assertEqual(recovered["status"], "succeeded")
            self.assertEqual(len(workers), 2)
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_worker_exit_is_reported_and_next_run_can_rebuild(self):
        async def exercise():
            workers = []

            def broken_script(_message):
                return [{"type": "worker_exit", "code": 17}]

            def factory(**_kwargs):
                scripts = [[broken_script], [complete_script("session-rebuilt")]][len(workers)]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)
            with self.assertRaises(SessionActorError) as error:
                await actor.submit("run-broken", {"prompt": "break"})
            self.assertIn(error.exception.code, {"worker_error", "session_actor_error"})
            self.assertEqual(actor.snapshot()["streamingState"], "failed")

            result = await actor.submit("run-rebuilt", {"prompt": "recover"})
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(len(workers), 2)
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_idle_ttl_closes_worker_without_leaking_actor_task(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script()], worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=20)
            result = await actor.submit("run-1", {"prompt": "one"})
            self.assertEqual(result["status"], "succeeded")
            await _wait_until(lambda: workers[0].closed, timeout=1)
            self.assertTrue(workers[0].closed)
            self.assertTrue(actor._task is None or actor._task.done())
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_manager_reconfigures_worker_and_resumes_history_when_binding_changes(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script()], worker_id=len(workers))
                workers.append(worker)
                return worker

            manager = SessionManager(
                idle_ttl_ms=10_000,
                worker_factory=factory,
            )
            first = await manager.submit(
                "session",
                {"_client_connection_fingerprint": "a"},
                "run-1",
                {"prompt": "one"},
            )
            second = await manager.submit(
                "session",
                {"_client_connection_fingerprint": "b"},
                "run-2",
                {"prompt": "two"},
            )
            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(second["status"], "succeeded")
            self.assertEqual(len(workers), 2)
            self.assertTrue(workers[0].closed)
            self.assertEqual(workers[1].start_payload['resume'], 'session-1')
            self.assertEqual(workers[1].start_payload['_client_connection_fingerprint'], 'b')
            self.assertEqual(len(manager.snapshots()), 1)
            await manager.close_all()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_queued_capability_changes_apply_current_config_after_previous_run(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                script = (lambda message: []) if not workers else complete_script()
                worker = FakeClientWorker([script], worker_id=len(workers))
                workers.append(worker)
                return worker

            manager = SessionManager(worker_factory=factory)
            first = asyncio.create_task(manager.submit('s', {'_client_connection_fingerprint': 'a'}, 'one', {'prompt': 'one'}))
            await _wait_until(lambda: workers and workers[0].sent)
            second = asyncio.create_task(manager.submit('s', {
                '_client_connection_fingerprint': 'b', 'capability_ref': 'image-generation',
                'credentials': {'platformBearer': 'new-token'},
            }, 'two', {'prompt': 'two'}))
            await _wait_until(lambda: manager.snapshots()[0]['pendingRuns'] == 1)
            self.assertFalse(workers[0].closed)
            await workers[0].events.put({'type': 'client_run_completed', 'session_id': 'session-1'})
            await asyncio.gather(first, second)
            await manager.submit('s', {'_client_connection_fingerprint': 'a', 'capability_ref': 'conversation'},
                                 'three', {'prompt': 'three'})
            self.assertEqual([w.start_payload.get('resume') for w in workers], [None, 'session-1', 'session-1'])
            self.assertEqual(workers[1].start_payload['credentials'], {'platformBearer': 'new-token'})
            self.assertNotIn('credentials', workers[2].start_payload)
            await manager.close_all()

        asyncio.run(asyncio.wait_for(exercise(), timeout=3))

    def test_idle_actor_recreation_keeps_last_provider_session(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script()], worker_id=len(workers))
                workers.append(worker)
                return worker

            manager = SessionManager(idle_ttl_ms=10, worker_factory=factory)
            await manager.submit('s', {}, 'one', {'prompt': 'one'})
            await _wait_until(lambda: workers[0].closed)
            await manager.submit('s', {'resume': 'outdated'}, 'two', {'prompt': 'two'})
            self.assertEqual(workers[1].start_payload['resume'], 'session-1')
            await manager.close_all()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_manager_runs_different_sessions_concurrently(self):
        async def exercise():
            workers = []

            def factory(**_kwargs):
                worker = FakeClientWorker([complete_script(f"session-{len(workers)}")], worker_id=len(workers))
                workers.append(worker)
                return worker

            manager = SessionManager(idle_ttl_ms=10_000, worker_factory=factory)
            results = await asyncio.gather(
                manager.submit("session-a", {}, "run-a", {"prompt": "a"}),
                manager.submit("session-b", {}, "run-b", {"prompt": "b"}),
            )
            self.assertEqual([result["status"] for result in results], ["succeeded", "succeeded"])
            self.assertEqual(len(workers), 2)
            self.assertEqual(len(manager.snapshots()), 2)
            await manager.close_all()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))


async def _wait_until(predicate, *, timeout=1):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.001)


async def _record_preparation(target):
    target.append(True)
    return {}


if __name__ == "__main__":
    unittest.main()
