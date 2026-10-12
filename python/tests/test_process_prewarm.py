import asyncio
import json
import unittest
from unittest.mock import patch

from runtime.process import ClientWorkerError, ClientWorkerProcess


class Process:
    def __init__(self):
        self.pid = 123
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = self
        self.writes = []
        self.exited = asyncio.Event()

    def write(self, line):
        self.writes.append(json.loads(line))
        if self.writes[-1].get('mode') == 'client':
            self.stdout.feed_data(b'{"type":"client_ready"}\n')

    async def drain(self):
        pass

    def close(self):
        self.stop()

    def stop(self):
        if self.returncode is None:
            self.returncode = 0
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.exited.set()

    async def wait(self):
        await self.exited.wait()
        return self.returncode


class ProcessPrewarmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.process = Process()
        self.worker = ClientWorkerProcess(start_timeout_ms=50)
        self.spawn = patch('runtime.process._spawn_worker_process', return_value=self.process)
        self.spawn_mock = self.spawn.start()
        async def stop(process):
            process.stop()
        self.kill = patch('runtime.process._terminate_process_tree', side_effect=stop)
        self.kill.start()
        self.addCleanup(self.spawn.stop)
        self.addCleanup(self.kill.stop)
        self.addAsyncCleanup(self.worker.terminate)

    async def test_prewarm_writes_no_identity_and_start_binds_exactly_once(self):
        self.process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        await self.worker.prewarm()
        self.assertEqual(self.process.writes, [])
        ready = await self.worker.start({'credentials':{'platformBearer':'test-token'}})
        self.assertEqual(ready['type'], 'client_ready')
        self.assertEqual(self.spawn_mock.await_count, 1)
        self.assertEqual(self.process.writes[0]['credentials']['platformBearer'], 'test-token')
        with self.assertRaises(ClientWorkerError):
            await self.worker.start({})
        await self.worker.close()
        self.assertIsNotNone(self.process.returncode)

    async def test_prewarm_timeout_and_cancel_reclaim_process(self):
        with self.assertRaises(ClientWorkerError):
            await self.worker.prewarm()
        self.assertIsNotNone(self.process.returncode)

    async def test_cancel_while_waiting_for_import_reclaims_process(self):
        task = asyncio.create_task(self.worker.prewarm())
        while self.worker.process is None:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIsNotNone(self.process.returncode)

    async def test_cold_start_consumes_import_handshake_internally(self):
        self.process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        ready = await self.worker.start({})
        self.assertEqual(ready['type'], 'client_ready')
        self.assertEqual(self.spawn_mock.await_count, 1)
