import asyncio
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from runtime.process import ClientWorkerError, ClientWorkerProcess
from runtime.session_actor import SessionActor, SessionActorError


class Process:
    def __init__(self):
        self.pid = 123
        self.returncode = None
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdin = self
        self.writes = []
        self.exited = asyncio.Event()
        self.client_sent = asyncio.Event()
        self.client_event = {'type': 'client_ready'}
        self.exit_on_bind = False

    def write(self, line):
        self.writes.append(json.loads(line))
        if self.writes[-1].get('mode') == 'client':
            self.client_sent.set()
            if self.exit_on_bind:
                self.stop()
            elif self.client_event is not None:
                events = self.client_event if isinstance(self.client_event, list) else [self.client_event]
                for event in events:
                    self.stdout.feed_data((json.dumps(event) + '\n').encode())

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
        # 成功路径不以事件循环能否在 50ms 内调度作为验收条件。
        self.worker = ClientWorkerProcess(start_timeout_ms=2000)
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
        self.assertTrue(self.worker.awaiting_connection)
        self.assertEqual(self.process.writes, [])
        ready = await self.worker.start({'credentials':{'platformBearer':'test-token'}})
        self.assertEqual(ready['type'], 'client_ready')
        self.assertFalse(self.worker.awaiting_connection)
        self.assertEqual(self.spawn_mock.await_count, 1)
        self.assertEqual(self.process.writes[0]['credentials']['platformBearer'], 'test-token')
        with self.assertRaises(ClientWorkerError):
            await self.worker.start({})
        await self.worker.close()
        self.assertIsNotNone(self.process.returncode)

    async def test_prewarm_timeout_and_cancel_reclaim_process(self):
        self.worker.start_timeout_ms = 50
        with self.assertRaises(ClientWorkerError):
            await self.worker.prewarm()
        self.assertFalse(self.worker.awaiting_connection)
        self.assertIsNotNone(self.process.returncode)

    async def test_cancel_while_waiting_for_import_reclaims_process(self):
        task = asyncio.create_task(self.worker.prewarm())
        while self.worker.process is None:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.worker.awaiting_connection)
        self.assertIsNotNone(self.process.returncode)

    async def test_cold_start_consumes_import_handshake_internally(self):
        self.process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        ready = await self.worker.start({})
        self.assertEqual(ready['type'], 'client_ready')
        self.assertEqual(self.spawn_mock.await_count, 1)

    async def test_worker_start_milestones_are_forwarded_with_startup_trace(self):
        event = {
            'type': 'performance', 'version': 1, 'scope': 'worker_start',
            'originUnixMs': 1000, 'clockId': 'worker-1',
            'elapsedMs': {'connect_begin': 5}, 'cpuMs': {}, 'counts': {}, 'live': True,
        }
        self.process.client_event = [event, {'type': 'client_ready', 'state': 'ready'}]
        self.process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        received = []
        self.worker.set_observation_callback(lambda run_id, timing: received.append((run_id, timing)), run_id='run-1')
        ready = await self.worker.start({})
        self.assertEqual(ready['type'], 'client_ready')
        self.assertEqual(received, [('run-1', event)])
        self.assertTrue(all(not trace.get('live') for trace in self.worker.startup_traces))
        self.assertIsNone(self.worker._on_observation)

    async def test_pool_capacity_includes_leased_worker_until_process_cleanup_finishes(self):
        from runtime.worker_pool import WorkerPool
        pool = WorkerPool(max_idle=0, max_starting=1, max_live=1)
        worker = await pool.acquire()
        self.process.stdout.feed_data(b'{"type":"worker_ready"}\n')
        await worker.start({})
        termination_started = asyncio.Event()
        allow_termination = asyncio.Event()

        async def stop(process):
            termination_started.set()
            await allow_termination.wait()
            process.stop()

        with patch('runtime.process._terminate_process_tree', side_effect=stop):
            termination = asyncio.create_task(worker.terminate())
            try:
                await termination_started.wait()
                self.assertFalse(worker.alive)
                self.assertIsNone(self.process.returncode)
                with self.assertRaises(ClientWorkerError):
                    await pool.acquire()
            finally:
                allow_termination.set()
                await termination
                await pool.close()
        self.assertEqual(pool._live_count(), 0)

    async def test_pool_refills_after_connection_error_timeout_cancel_or_exit(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        # 使用真实通道状态机，验证连接失败不会永久阻止补池。
        for failure in ('error', 'timeout', 'cancel', 'exit'):
            with self.subTest(failure=failure):
                spawned = []
                def spawn():
                    process = Process()
                    process.stdout.feed_data(b'{"type":"worker_ready"}\n')
                    spawned.append(process)
                    return process
                self.spawn_mock.side_effect = spawn
                pool = WorkerPool(max_idle=1, max_starting=1,
                    worker_factory=lambda **kwargs: ClientWorkerProcess(start_timeout_ms=2000))
                try:
                    pool.start()
                    await until(lambda: pool.snapshot()['ready'] == 1)
                    worker = await pool.acquire()
                    if failure == 'timeout':
                        worker.start_timeout_ms = 50
                    self.assertEqual(pool.snapshot()['leased_connecting'], 1)
                    self.assertEqual(len(spawned), 1)
                    process = spawned[0]
                    process.client_event = {'type': 'client_error'} if failure == 'error' else None
                    process.exit_on_bind = failure == 'exit'
                    task = asyncio.create_task(worker.start({}))
                    await process.client_sent.wait()
                    if failure == 'cancel':
                        task.cancel()
                    expected = asyncio.CancelledError if failure == 'cancel' else ClientWorkerError
                    with self.assertRaises(expected):
                        await task
                    self.assertFalse(worker.awaiting_connection)
                    self.assertEqual(pool.snapshot()['leased_connecting'], 0)
                    await until(lambda: pool.snapshot()['ready'] == 1)
                    self.assertEqual(len(spawned), 2)
                    self.assertIsNotNone(process.returncode)
                finally:
                    await pool.close()


class WorkerTerminalEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_actor_consumes_disconnect_evidence_before_failed_or_closing_terminal(self):
        # 真正启动 Worker 子进程，只替换外部 SDK Provider；父进程使用原 JSONL 通道和 Actor。
        script = r'''
import asyncio, sys
from contextlib import nullcontext
from types import SimpleNamespace
import agent_worker as worker
from runtime.claude_sdk import ClaudeSDKClient, SDKMessage, build_agent_options
mode = sys.argv[1]
class Provider:
    def __init__(self):
        self.interrupted = asyncio.Event()
    async def connect(self, prompt=None):
        pass
    async def query(self, prompt, session_id):
        pass
    async def receive_response(self):
        yield SDKMessage(kind='assistant', data={'message_id': 'm1', 'content': [{'type': 'text', 'text': 'ready to close'}]})
        await self.interrupted.wait()
        yield SDKMessage(kind='result', data={'subtype': 'success', 'is_error': False})
    async def interrupt(self):
        self.interrupted.set()
    async def disconnect(self):
        raise ValueError('disconnect rejected business-private-value')
class Client(ClaudeSDKClient):
    async def connect(self, prompt=None):
        await super().connect(prompt)
        if mode == 'connect':
            raise ValueError('startup failed before ready')
def options(*args, **kwargs):
    if mode == 'failed':
        raise ValueError('run setup failed')
    return build_agent_options(tools=[], strict_mcp_config=True)
worker.load_runtime_environment = lambda _: None
worker.missing_environment = lambda: []
worker.prepare_workflow_assets = lambda _: {}
worker.create_run_services = lambda _: None
worker.ToolServices = lambda *args: SimpleNamespace(clear=lambda: None)
worker.build_client_options = lambda *args: build_agent_options(tools=[], strict_mcp_config=True)
worker.build_options = options
worker.isolated_sdk_environment = nullcontext
worker.ClaudeSDKClient = lambda *args, **kwargs: Client(*args, **kwargs, client_factory=lambda _: Provider())
asyncio.run(worker.main())
'''
        for mode in ('failed', 'closing', 'connect'):
            with self.subTest(mode=mode):
                observations, processes = [], []
                text_received = asyncio.Event()
                async def consume(run_id, event):
                    observations.append((run_id, event))
                    if event.get('type') == 'text':
                        text_received.set()
                async def spawn(*args, **kwargs):
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, '-u', '-c', script, mode,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]),
                             'CCSDK_ENABLE_TIMING': '1'})
                    processes.append(process)
                    return process
                actor = SessionActor('diagnostic-test-session',
                                     {'credentials': {'platformBearer': 'business-private-value'}},
                                     on_public_event=consume,
                                     on_observation=lambda run_id, event: observations.append((run_id, event)),
                                     worker_start_timeout_ms=10000, worker_close_timeout_ms=2000)
                try:
                    with patch('runtime.process._spawn_worker_process', side_effect=spawn):
                        pending = asyncio.create_task(actor.submit('diagnostic-run', {
                            'prompt': 'test', 'credentials': {'platformBearer': 'business-private-value'}}))
                        if mode == 'closing':
                            ready = asyncio.create_task(text_received.wait())
                            done, _ = await asyncio.wait({pending, ready}, timeout=10,
                                                         return_when=asyncio.FIRST_COMPLETED)
                            if ready not in done:
                                ready.cancel()
                                pending.cancel()
                                await asyncio.gather(ready, return_exceptions=True)
                                await asyncio.gather(pending, return_exceptions=True)
                                self.fail(str(observations))
                            await asyncio.wait_for(actor.close(), 10)
                            await pending
                        else:
                            with self.assertRaises(SessionActorError):
                                await asyncio.wait_for(pending, 10)
                        evidence = [(run_id, event) for run_id, event in observations
                                    if event.get('scope') == 'worker_client_disconnect']
                        self.assertEqual(len(evidence), 1, observations)
                        self.assertEqual(evidence[0][0], 'diagnostic-run')
                        self.assertEqual(evidence[0][1]['exceptionType'], 'SDKCleanupError')
                        self.assertEqual(evidence[0][1]['causes'][0]['exceptionType'], 'ValueError')
                        self.assertNotIn('business-private-value', json.dumps(evidence))
                finally:
                    await actor.close()
                    for process in processes:
                        if process.returncode is None:
                            process.kill()
                        await process.wait()
