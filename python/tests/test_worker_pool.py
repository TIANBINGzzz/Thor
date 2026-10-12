"""预热池只分配未绑定进程，验证容量、故障和取消边界。"""
import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.worker_pool import WorkerPool
from runtime.runtime_settings import load_worker_pool_settings


class FakeWorker:
    running = 0
    peak = 0
    created = []
    gate = None
    fail = False

    def __init__(self, **kwargs):
        self.alive = False
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
        leased = [self.pool.acquire() for _ in range(7)]
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
        acquired = self.pool.acquire()
        self.assertIsNot(acquired, dead)
        await until(lambda: dead.terminated)
        await until(lambda: self.pool.snapshot()['ready'] == 6)

    async def test_shutdown_cancels_import_and_prevents_new_leases(self):
        self.pool.start()
        await until(lambda: FakeWorker.running == 2)
        await self.pool.close()
        self.assertEqual(FakeWorker.running, 0)
        self.assertTrue(all(w.terminated for w in FakeWorker.created))
        with self.assertRaises(RuntimeError):
            self.pool.acquire()
        await self.pool.close()

    async def test_prewarm_failure_is_cleaned_and_does_not_spin(self):
        FakeWorker.fail = True
        self.pool.start()
        FakeWorker.gate.set()
        await until(lambda: self.pool.snapshot()['failures'] >= 1)
        await asyncio.sleep(.05)
        self.assertLessEqual(len(FakeWorker.created), 2)
        self.assertTrue(all(w.terminated for w in FakeWorker.created))

    async def test_disabled_pool_creates_no_idle_workers(self):
        pool = WorkerPool(max_idle=0, max_starting=2, worker_factory=FakeWorker)
        self.addAsyncCleanup(pool.close)
        pool.start()
        await asyncio.sleep(.02)
        self.assertEqual(len(FakeWorker.created), 0)
        self.assertFalse(pool.acquire().alive)

    async def test_memory_pressure_releases_idle_and_recovers_without_touching_lease(self):
        self.pool.min_available_memory_mib = 1024
        with patch('runtime.worker_pool.available_memory_mib', return_value=2048) as memory:
            self.pool.start()
            FakeWorker.gate.set()
            await until(lambda: self.pool.snapshot()['ready'] == 6)
            leased = self.pool.acquire()
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
    async def test_hot_reuse_and_token_change_keep_history_but_allocate_fresh_worker(self):
        from runtime.session_actor import SessionManager
        from tests.test_session_actor import FakeClientWorker, complete_script
        workers = []
        class Worker(FakeClientWorker):
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
            first = {'_credential_binding':'a','credentials':{'platformBearer':'first-token'}}
            await manager.submit('tenant/user/session', first, 'one', {'prompt':'one'})
            await manager.submit('tenant/user/session', first, 'two', {'prompt':'two'})
            self.assertEqual(pool.snapshot()['hits'], 1)
            self.assertEqual(manager.snapshots()[0]['workerReuses'], 1)
            second = {'_credential_binding':'b','credentials':{'platformBearer':'second-token'}}
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
