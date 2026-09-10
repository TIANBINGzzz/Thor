import asyncio
import unittest

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

    def test_cancel_retires_worker_and_next_run_rebuilds_it(self):
        async def exercise():
            workers = []

            def hanging_script(message):
                return [{"type": "text", "run_id": message["run_id"], "text": "waiting"}]

            def factory(**_kwargs):
                scripts = [[hanging_script], [complete_script("session-2")]][len(workers)]
                worker = FakeClientWorker(scripts, worker_id=len(workers))
                workers.append(worker)
                return worker

            actor = SessionActor("session", {}, worker_factory=factory, idle_ttl_ms=10_000)
            pending = asyncio.create_task(actor.submit("run-cancel", {"prompt": "hang"}))
            await _wait_until(lambda: actor.active_run_id == "run-cancel")
            await actor.cancel("run-cancel")
            cancelled = await asyncio.wait_for(pending, timeout=1)
            self.assertEqual(cancelled["status"], "cancelled")
            self.assertTrue(workers[0].terminated)

            completed = await actor.submit("run-after-cancel", {"prompt": "recover"})
            self.assertEqual(completed["status"], "succeeded")
            self.assertEqual(len(workers), 2)
            await actor.close()

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

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
            await _wait_until(lambda: actor.state == ActorState.CLOSED, timeout=1)
            self.assertTrue(workers[0].closed)
            self.assertTrue(actor._task is None or actor._task.done())

        asyncio.run(asyncio.wait_for(exercise(), timeout=2))

    def test_manager_replaces_idle_actor_when_credential_fingerprint_changes(self):
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
                {"_credential_binding": "a"},
                "run-1",
                {"prompt": "one"},
            )
            second = await manager.submit(
                "session",
                {"_credential_binding": "b"},
                "run-2",
                {"prompt": "two"},
            )
            self.assertEqual(first["status"], "succeeded")
            self.assertEqual(second["status"], "succeeded")
            self.assertEqual(len(workers), 2)
            self.assertTrue(workers[0].closed)
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
