"""预热池只分配未绑定进程，验证容量、故障和取消边界。"""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime.worker_pool import WorkerPool
from runtime.observability import Observer
from runtime.process import ClientWorkerProcess
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


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.005)


class WorkerPoolTests(unittest.IsolatedAsyncioTestCase):
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
        await until(lambda: self.pool.snapshot()['ready'] == 6)
        await self.pool.close()
        self.assertTrue(all(not w.terminated for w in leased))
        self.assertTrue(all(w.terminated for w in FakeWorker.created if w not in leased))

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

    async def test_cancelled_acquire_keeps_evicted_client_owned_until_terminated(self):
        termination_started = asyncio.Event()
        allow_termination = asyncio.Event()

        class Worker(FakeWorker):
            async def preconnect(self, payload):
                await self.prewarm()

            async def terminate(self):
                termination_started.set()
                await allow_termination.wait()
                await super().terminate()

        pool = WorkerPool(max_idle=1, max_starting=1, max_live=1,
                          payload_factory=lambda: {'session_directory': 'blank'},
                          worker_factory=Worker)
        self.addAsyncCleanup(pool.close)
        pool.start()
        FakeWorker.gate.set()
        try:
            await until(lambda: pool.snapshot()['ready'] == 1)
            worker = FakeWorker.created[0]
            acquisition = asyncio.create_task(pool.acquire({'resume': 'existing-session'}))
            await until(termination_started.is_set)
            acquisition.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await acquisition
            self.assertEqual(pool._live_count(), 1)
            next_acquisition = asyncio.create_task(pool.acquire({'resume': 'another-session'}))
            await asyncio.sleep(0)
            next_acquisition.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await next_acquisition
            self.assertEqual(pool._live_count(), 1)
            allow_termination.set()
            await pool.close()
            self.assertTrue(worker.terminated)
            self.assertFalse(worker.alive)
        finally:
            allow_termination.set()

    async def test_cancelled_acquire_does_not_interrupt_cancelled_prewarm_cleanup(self):
        termination_started = asyncio.Event()
        allow_termination = asyncio.Event()

        class Worker(FakeWorker):
            async def terminate(self):
                termination_started.set()
                await allow_termination.wait()
                await super().terminate()

        pool = WorkerPool(max_idle=1, max_starting=1, max_live=1, worker_factory=Worker)
        self.addAsyncCleanup(pool.close)
        pool.start()
        try:
            await until(lambda: Worker.running == 1)
            worker = FakeWorker.created[0]
            acquisition = asyncio.create_task(pool.acquire())
            await until(termination_started.is_set)
            acquisition.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await acquisition
            self.assertEqual(pool._live_count(), 1)
            allow_termination.set()
            await pool.close()
            self.assertTrue(worker.terminated)
        finally:
            allow_termination.set()


class WorkerPoolConfigTests(unittest.TestCase):
    def test_yaml_partial_local_override_and_disable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.yml'
            path.write_text('runtime:\n  worker-pool:\n    max-idle: 6\n    max-starting: 2\n', encoding='utf-8')
            local = path.with_name('application.local.yml')
            local.write_text('runtime:\n  worker-pool:\n    max-idle: 0\n', encoding='utf-8')
            config = load_worker_pool_settings(path)
            self.assertEqual((config.max_idle, config.max_starting), (0, 2))

    def test_missing_section_disables_pool_and_invalid_values_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'application.yml'
            path.write_text('nacos: {}', encoding='utf-8')
            self.assertEqual(load_worker_pool_settings(path).max_idle, 0)
            for body in ('max-idle: true', 'max-idle: -1', 'max-starting: 0',
                         'max-starting: "2"', 'unknown: 5'):
                path.write_text('runtime:\n  worker-pool:\n    '+body+'\n', encoding='utf-8')
                with self.subTest(body=body), self.assertRaises(ValueError):
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
