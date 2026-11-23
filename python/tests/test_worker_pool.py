"""预热池只分配未绑定进程，验证容量、故障和取消边界。"""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime.worker_pool import LOCAL_WORKER_START, WorkerPool
from runtime.observability import Observer
from runtime.process import ClientWorkerProcess, ClientWorkerError
from runtime.run_queue import RunQueue
from runtime.runtime_settings import load_worker_pool_settings


class FakeWorker:
    running = 0
    peak = 0
    created = []
    gate = None
    fail = False

    def __init__(self, **kwargs):
        self.alive = False
        self.awaiting_connection = False
        self.terminated = False
        self.process = None
        self.created.append(self)

    async def prewarm(self):
        type(self).running += 1
        type(self).peak = max(self.peak, self.running)
        try:
            await self.gate.wait()
            if self.fail:
                raise RuntimeError('private failure details')
            self.alive = True
        finally:
            type(self).running -= 1

    async def terminate(self):
        self.alive = False
        self.terminated = True

    async def start(self, payload):
        self.alive = True


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


class WorkerPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_healthy_memory_allows_more_than_24_bound_workers(self):
        pool = WorkerPool(max_idle=0, max_starting=1, min_available_memory_mib=1024, worker_factory=FakeWorker)
        self.addAsyncCleanup(pool.close)
        with patch('runtime.worker_pool.available_memory_mib', return_value=1024):
            for _ in range(25):
                worker = await pool.acquire()
                await worker.start({})
            self.assertEqual(pool.snapshot()['leased_alive'], 25)

    async def asyncSetUp(self):
        FakeWorker.running = FakeWorker.peak = 0
        FakeWorker.created = []
        FakeWorker.gate = asyncio.Event()
        FakeWorker.fail = False
        self.pool = WorkerPool(max_idle=6, max_starting=2, worker_factory=FakeWorker)
        self.addAsyncCleanup(self.pool.close)

    async def test_creation_limit_capacity_unique_leases_and_empty_pool(self):
        self.pool.start()
        await until(lambda: FakeWorker.running == 2)
        self.assertEqual(len(FakeWorker.created), 2)
        FakeWorker.gate.set()
        await until(lambda: self.pool.snapshot()['ready'] == 6)
        self.assertEqual(FakeWorker.peak, 2)
        leased = [await self.pool.acquire() for _ in range(7)]
        self.assertEqual(len({id(w) for w in leased}), 7)
        self.assertTrue(all(w.alive for w in leased[:6]))
        self.assertFalse(leased[6].alive)
        self.assertEqual(self.pool.snapshot()['hits'], 6)
        self.assertEqual(self.pool.snapshot()['misses'], 1)
        await leased[6].start({})
        await until(lambda: self.pool.snapshot()['ready'] == 6)
        await self.pool.close()
        self.assertTrue(all(not w.terminated for w in leased))
        self.assertTrue(all(w.terminated for w in FakeWorker.created if w not in leased))

    async def test_business_cold_start_admission_uses_max_starting(self):
        class ConnectingWorker:
            def __init__(self, **kwargs):
                self.alive = False
                self.awaiting_connection = True
                self.process = None
                self.terminated = False

            async def terminate(self):
                self.alive = False
                self.terminated = True

        queue = RunQueue(max_pending=3)
        pool = WorkerPool(max_idle=0, max_starting=1, worker_factory=ConnectingWorker, on_change=queue.notify)
        self.addAsyncCleanup(pool.close)

        first = await pool.acquire()
        ticket = queue.enqueue('second', timeout_ms=1000)
        second_task = asyncio.create_task(pool.acquire(queued_run=ticket))
        await asyncio.sleep(0)
        self.assertFalse(second_task.done())
        self.assertEqual(pool.snapshot()['businessStarting'], 1)

        first._ccsdk_release_start_slot()
        second = await asyncio.wait_for(second_task, 1)
        self.assertIsNot(first, second)
        self.assertEqual(pool.snapshot()['businessStarting'], 1)
        second._ccsdk_release_start_slot()
        ticket.release()
        self.assertEqual(pool.snapshot()['businessStarting'], 0)

    async def test_memory_reclaim_orders_ready_workers_by_oldest_idle_time(self):
        pool = WorkerPool(max_idle=3, max_starting=3, worker_factory=FakeWorker)
        self.addAsyncCleanup(pool.close)
        pool.start()
        FakeWorker.gate.set()
        await until(lambda: pool.snapshot()['ready'] == 3)
        workers = list(pool._ready)
        pool._idle_at[workers[0]] = 30
        pool._idle_at[workers[1]] = 10
        pool._idle_at[workers[2]] = 20

        pool.min_available_memory_mib = 1024
        with patch('runtime.worker_pool.available_memory_mib', side_effect=lambda: 1300 if workers[1].terminated else 700):
            pool.notify()
            await until(lambda: workers[1].terminated)
            self.assertFalse(workers[0].terminated)
            self.assertFalse(workers[2].terminated)

    async def test_dead_idle_worker_is_never_leased(self):
        self.pool.start()
        FakeWorker.gate.set()
        await until(lambda: self.pool.snapshot()['ready'] == 6)
        dead = FakeWorker.created[0]
        dead.alive = False
        acquired = await self.pool.acquire()
        self.assertIsNot(acquired, dead)
        await until(lambda: dead.terminated)
        await until(lambda: self.pool.snapshot()['ready'] == 6)

    async def test_refill_waits_for_all_leased_connections_including_cold_misses(self):
        self.pool.start()
        FakeWorker.gate.set()
        await until(lambda: self.pool.snapshot()['ready'] == 6)
        leases = [await self.pool.acquire() for _ in range(7)]
        for worker in leases:
            worker.awaiting_connection = True
        await asyncio.sleep(.6)
        self.assertEqual(len(FakeWorker.created), 7)
        self.assertEqual(self.pool.snapshot()['starting'], 0)
        for worker in leases[:6]:
            worker.awaiting_connection = False
        await asyncio.sleep(.6)
        self.assertEqual(len(FakeWorker.created), 7)
        leases[-1].awaiting_connection = False
        await leases[-1].start({})
        await until(lambda: self.pool.snapshot()['ready'] == 6)

    async def test_shutdown_cancels_import_and_prevents_new_leases(self):
        self.pool.start()
        await until(lambda: FakeWorker.running == 2)
        await self.pool.close()
        self.assertEqual(FakeWorker.running, 0)
        self.assertTrue(all(w.terminated for w in FakeWorker.created))
        with self.assertRaises(RuntimeError):
            await self.pool.acquire()
        await self.pool.close()

    async def test_prewarm_failure_is_cleaned_and_does_not_spin(self):
        FakeWorker.fail = True
        self.pool.start()
        FakeWorker.gate.set()
        await until(lambda: self.pool.snapshot()['failures'] >= 1)
        await asyncio.sleep(.05)
        self.assertLessEqual(len(FakeWorker.created), 2)
        self.assertTrue(all(w.terminated for w in FakeWorker.created))

    async def test_preconnect_diagnostic_keeps_warm_identity_and_failure_backoff(self):
        from tests.test_process_prewarm import Process
        process = Process()
        process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        process.client_event = [
            {'type': 'diagnostic', 'scope': 'worker_client', 'exceptionType': 'ValueError',
             'message': 'provider rejected prewarm-private-value', 'frames': []},
            {'type': 'client_error', 'code': 'sdk_connection_error'},
        ]
        async def stop(child):
            child.stop()
        with tempfile.TemporaryDirectory() as folder:
            observer = Observer(Path(folder) / 'observation.sqlite', enabled=True)
            pool = WorkerPool(max_idle=1, max_starting=1, observer=observer,
                              payload_factory=lambda: {'session_directory': 'blank'},
                              worker_factory=lambda: ClientWorkerProcess(start_timeout_ms=500))
            try:
                with patch.dict('os.environ', {'OBSERVATION_TEST_SECRET': 'prewarm-private-value'}), \
                     patch('runtime.process._spawn_worker_process', return_value=process), \
                     patch('runtime.process._terminate_process_tree', side_effect=stop):
                    await pool._prepare()
                observer.flush()
                records = observer.read(0, 100)['records']
                evidence = [record for record in records if record['kind'] == 'evidence']
                self.assertEqual([record['data']['exceptionType'] for record in evidence],
                                 ['ValueError', 'ClientWorkerError'])
                self.assertEqual(len({record['runId'] for record in records}), 1)
                self.assertTrue(evidence[0]['runId'].startswith('warm:'))
                self.assertNotIn('prewarm-private-value', json.dumps(records))
                self.assertNotIn('credentials', process.writes[0])
                self.assertNotIn('run_id', process.writes[0])
                self.assertIsNotNone(process.returncode)
                self.assertEqual(pool.snapshot()['failures'], 1)
                self.assertEqual(pool.snapshot()['ready'], 0)
                self.assertEqual(pool._backoff, 2)
                self.assertGreater(pool._retry_at, time.monotonic())
            finally:
                await pool.close()
                observer.close()

    async def test_factory_exception_has_attempt_evidence_without_a_worker(self):
        def fail_factory():
            raise ValueError('factory rejected prewarm-private-value')
        with tempfile.TemporaryDirectory() as folder:
            observer = Observer(Path(folder) / 'observation.sqlite', enabled=True)
            pool = WorkerPool(max_idle=1, max_starting=1, observer=observer, worker_factory=fail_factory)
            try:
                with patch.dict('os.environ', {'OBSERVATION_TEST_SECRET': 'prewarm-private-value'}):
                    await pool._prepare()
                observer.flush()
                evidence = [record for record in observer.read(0, 100)['records'] if record['kind'] == 'evidence']
                self.assertEqual(len(evidence), 1)
                self.assertEqual(evidence[0]['data']['exceptionType'], 'ValueError')
                self.assertTrue(evidence[0]['runId'].startswith('warm:'))
                self.assertNotIn('prewarm-private-value', json.dumps(evidence))
                self.assertEqual(pool.snapshot()['failures'], 1)
                self.assertEqual(pool.snapshot()['starting'], 0)
            finally:
                await pool.close()
                observer.close()

    async def test_diagnostic_storage_failure_does_not_fail_ready_prewarm(self):
        class Worker(FakeWorker):
            callback = None
            def set_observation_callback(self, callback, *, run_id=None):
                self.callback, self.run_id = callback, run_id
            async def prewarm(self):
                if self.callback:
                    self.callback(self.run_id, {'type': 'diagnostic', 'message': 'nonfatal startup evidence'})
                self.alive = True
        with tempfile.TemporaryDirectory() as folder:
            observer = Observer(Path(folder) / 'observation.sqlite', enabled=True)
            pool = WorkerPool(max_idle=1, max_starting=1, observer=observer, worker_factory=Worker)
            try:
                with patch.object(observer, 'emit', side_effect=OSError('observation unavailable')):
                    await pool._prepare()
                self.assertEqual(pool.snapshot()['ready'], 1)
                self.assertEqual(pool.snapshot()['failures'], 0)
                self.assertEqual(pool._backoff, 1)
            finally:
                await pool.close()
                observer.close()

    async def test_disabled_pool_creates_no_idle_workers(self):
        pool = WorkerPool(max_idle=0, max_starting=2, worker_factory=FakeWorker)
        self.addAsyncCleanup(pool.close)
        pool.start()
        await asyncio.sleep(.02)
        self.assertEqual(len(FakeWorker.created), 0)
        self.assertFalse((await pool.acquire()).alive)

    async def test_memory_pressure_releases_idle_and_recovers_without_touching_lease(self):
        self.pool.min_available_memory_mib = 1024
        with patch('runtime.worker_pool.available_memory_mib', return_value=2048) as memory:
            self.pool.start()
            FakeWorker.gate.set()
            await until(lambda: self.pool.snapshot()['ready'] == 6)
            leased = await self.pool.acquire()
            memory.return_value = 512
            await until(lambda: self.pool.snapshot()['memory_paused'])
            await until(lambda: all(w.terminated for w in FakeWorker.created if w is not leased))
            self.assertTrue(leased.alive)
            self.assertEqual(self.pool.snapshot()['ready'], 0)
            self.pool._memory_resume_at = 0
            memory.return_value = 2048
            await until(lambda: self.pool.snapshot()['ready'] == 6)

    async def test_released_memory_alone_does_not_cause_refill_thrashing(self):
        self.pool.min_available_memory_mib = 1024
        def available():
            return 1050 - 30 * sum(w.alive for w in FakeWorker.created)
        with patch('runtime.worker_pool.available_memory_mib', side_effect=available):
            self.pool.start()
            FakeWorker.gate.set()
            await until(lambda: self.pool.snapshot()['memory_paused'])
            await until(lambda: all(w.terminated for w in FakeWorker.created))
            count = len(FakeWorker.created)
            self.pool._memory_resume_at = 0
            await asyncio.sleep(.6)
            self.assertEqual(len(FakeWorker.created), count)

    async def test_factory_failure_does_not_leave_starting_slots_stuck(self):
        self.pool._factory = lambda: (_ for _ in ()).throw(RuntimeError('failed'))
        self.pool.start()
        await until(lambda: self.pool.snapshot()['failures'] > 0)
        await until(lambda: self.pool.snapshot()['starting'] == 0)

    async def test_immediate_shutdown_cleans_tasks_cancelled_before_first_step(self):
        self.pool.start()
        await asyncio.sleep(0)
        await self.pool.close()
        self.assertEqual(self.pool.snapshot()['starting'], 0)
        self.assertTrue(all(w.terminated for w in FakeWorker.created))

    async def test_cancelled_memory_wait_does_not_spawn_after_retirement(self):
        termination_started = asyncio.Event()
        allow_termination = asyncio.Event()

        class Worker(FakeWorker):
            async def preconnect(self, payload):
                await self.prewarm()

            async def terminate(self):
                termination_started.set()
                await allow_termination.wait()
                await super().terminate()

        queue = RunQueue(max_pending=2)
        pool = WorkerPool(max_idle=1, max_starting=1, min_available_memory_mib=1024,
                          payload_factory=dict, worker_factory=Worker, on_change=queue.notify)
        self.addAsyncCleanup(pool.close)
        memory = self.enterContext(patch('runtime.worker_pool.available_memory_mib', return_value=2048))
        try:
            pool.start()
            FakeWorker.gate.set()
            await until(lambda: pool.snapshot()['ready'] == 1)
            worker = FakeWorker.created[0]
            memory.return_value = 1023
            ticket = queue.enqueue('existing-session', timeout_ms=1000)
            acquisition = asyncio.create_task(pool.acquire({'resume': 'existing-session'}, queued_run=ticket))
            await until(termination_started.is_set)
            self.assertFalse(acquisition.done())
            acquisition.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await acquisition
            ticket.release()
            self.assertEqual(pool.snapshot()['retiring'], 1)
            memory.side_effect = lambda: 1024 if worker.terminated else 1023
            next_ticket = queue.enqueue('another-session', timeout_ms=1000)
            next_acquisition = asyncio.create_task(pool.acquire({'resume': 'history'}, queued_run=next_ticket))
            await until(lambda: queue.waiting_for(LOCAL_WORKER_START))
            self.assertFalse(next_acquisition.done())
            allow_termination.set()
            leased = await asyncio.wait_for(next_acquisition, 1)
            self.assertTrue(worker.terminated)
            self.assertEqual(FakeWorker.created, [worker, leased])
            await leased.start({})
            await leased.terminate()
            next_ticket.release()
        finally:
            allow_termination.set()

    async def test_failed_termination_is_retried_while_business_waits(self):
        class Worker(FakeWorker):
            fail_close = True

            async def preconnect(self, payload):
                await self.prewarm()

            async def terminate(self):
                if self.fail_close:
                    raise OSError('local termination failed')
                await super().terminate()

        queue = RunQueue(max_pending=1)
        pool = WorkerPool(max_idle=1, max_starting=1, min_available_memory_mib=1024,
                          payload_factory=dict, worker_factory=Worker, on_change=queue.notify)
        self.addAsyncCleanup(pool.close)
        memory = self.enterContext(patch('runtime.worker_pool.available_memory_mib', return_value=2048))
        pool.start()
        FakeWorker.gate.set()
        await until(lambda: pool.snapshot()['ready'] == 1)
        worker = FakeWorker.created[0]
        try:
            memory.side_effect = lambda: 1024 if worker.terminated else 700
            ticket = queue.enqueue('session', timeout_ms=2500)
            acquisition = asyncio.create_task(pool.acquire({'resume': 'history'}, queued_run=ticket))
            await until(lambda: pool.snapshot()['retiring'] == 1 and not pool._retiring)
            self.assertFalse(acquisition.done())
            self.assertEqual(pool.snapshot()['live'], 1)
            worker.fail_close = False
            leased = await asyncio.wait_for(acquisition, 2)
            self.assertTrue(worker.terminated)
            self.assertIsNot(leased, worker)
            await leased.start({})
            leased.fail_close = False
            await leased.terminate()
            ticket.release()
        finally:
            worker.fail_close = False

    async def test_compatible_prewarm_can_dispatch_while_history_waits_for_a_start(self):
        profile = {'_client_connection_fingerprint': 'default'}
        queue = RunQueue(max_pending=3)

        class Worker(FakeWorker):
            async def preconnect(self, payload):
                await self.prewarm()

        pool = WorkerPool(max_idle=1, max_starting=1, payload_factory=dict, profile_payloads=[profile],
                          worker_factory=Worker, on_change=queue.notify,
                          business_waiting=lambda: queue.waiting_for(LOCAL_WORKER_START))
        self.addAsyncCleanup(pool.close)
        self.addCleanup(queue.close)
        pool.start()
        await until(lambda: Worker.running == 1)
        history = queue.enqueue('old', timeout_ms=1500)
        fresh = queue.enqueue('new', timeout_ms=1500)
        cold_task = asyncio.create_task(pool.acquire({**profile, 'resume': 'history'}, queued_run=history))
        warm_task = asyncio.create_task(pool.acquire({**profile, 'session_directory': 'new-workspace'}, queued_run=fresh))
        await until(lambda: len(queue._waiting.get(LOCAL_WORKER_START, ())) == 2)
        self.assertEqual(len(Worker.created), 1)
        self.assertFalse(warm_task.done())
        Worker.gate.set()
        warm = await asyncio.wait_for(warm_task, 1)
        cold = await asyncio.wait_for(cold_task, 1)
        self.assertIs(warm, Worker.created[0])
        self.assertIs(cold, Worker.created[1])
        self.assertEqual(pool.snapshot()['hits'], 1)
        self.assertEqual(pool.snapshot()['starting'], 0)
        await cold.start({})
        await until(lambda: pool.snapshot()['ready'] == 1)
        history.release()
        fresh.release()


class WorkerPoolConfigTests(unittest.TestCase):
    def test_explicit_pool_settings_ignore_local_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.yml'
            path.write_text('runtime:\n  worker-pool:\n    max-idle: 6\n    max-starting: 2\n    min-available-memory-mib: 1024\n', encoding='utf-8')
            local = path.with_name('application.local.yml')
            local.write_text('runtime:\n  worker-pool:\n    max-idle: 0\n', encoding='utf-8')
            config = load_worker_pool_settings(path)
            self.assertEqual((config.max_idle, config.max_starting), (6, 2))

    def test_missing_section_and_invalid_values_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.yml'
            path.write_text('nacos: {}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_worker_pool_settings(path)
            for field, value in (('max-idle', True), ('max-idle', -1), ('max-starting', 0),
                                 ('max-starting', '2'), ('max-live', 24), ('min-available-memory-mib', 1023)):
                body = {'max-idle': 6, 'max-starting': 2, 'min-available-memory-mib': 1024, field: value}
                path.write_text(json.dumps({'runtime': {'worker-pool': body}}), encoding='utf-8')
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    load_worker_pool_settings(path)


class WorkerPoolActorTests(unittest.IsolatedAsyncioTestCase):
    async def test_hot_reuse_and_fixed_config_change_keep_history_but_allocate_fresh_worker(self):
        from runtime.session_actor import SessionManager
        from tests.test_session_actor import FakeClientWorker, complete_script
        workers = []
        class Worker(FakeClientWorker):
            @property
            def awaiting_connection(self):
                return self.start_payload is None and not self.closed

            async def prewarm(self):
                self.started = True
        def factory(**kwargs):
            worker = Worker([complete_script(), complete_script()], worker_id=len(workers))
            workers.append(worker)
            return worker
        pool = WorkerPool(max_idle=2, max_starting=1, worker_factory=factory)
        manager = SessionManager(worker_factory=pool.acquire)
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 2)
            first = {'_client_connection_fingerprint':'a','credentials':{'platformBearer':'first-token'}}
            await manager.submit('tenant/user/session', first, 'one', {'prompt':'one'})
            await manager.submit('tenant/user/session', first, 'two', {'prompt':'two'})
            self.assertEqual(pool.snapshot()['hits'], 1)
            self.assertEqual(manager.snapshots()[0]['workerReuses'], 1)
            second = {'_client_connection_fingerprint':'b','credentials':{'platformBearer':'second-token'}}
            await manager.submit('tenant/user/session', second, 'three', {'prompt':'three'})
            self.assertTrue(workers[0].terminated)
            self.assertEqual(workers[1].start_payload['credentials'], second['credentials'])
            self.assertEqual(workers[1].start_payload['resume'], 'session-1')
            self.assertEqual(manager.snapshots()[0]['lastWorkerStartReason'], 'config_changed')
            await manager.submit('other-tenant/user/session', first, 'four', {'prompt':'four'})
            self.assertNotIn('resume', workers[2].start_payload)
        finally:
            await pool.close()
            await manager.close_all()

    async def test_startup_recovery_failure_also_closes_pool(self):
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        import server
        pool = WorkerPool(max_idle=2,max_starting=1,worker_factory=FakeWorker)
        FakeWorker.created = []
        FakeWorker.gate = asyncio.Event()
        delivery = SimpleNamespace(recover=AsyncMock(side_effect=RuntimeError('recover failed')),close=AsyncMock())
        with patch.object(server, 'WorkerPool', return_value=pool), \
             patch.object(server, '_artifact_delivery', return_value=delivery):
            with self.assertRaisesRegex(RuntimeError, 'recover failed'):
                async with server.lifespan(server.app):
                    pass
        self.assertIsNone(server.WORKER_POOL)
        self.assertIsNone(server.SESSION_MANAGER)
        self.assertTrue(pool._closed)
