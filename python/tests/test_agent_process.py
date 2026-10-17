import asyncio
import json
import unittest
from unittest.mock import patch

from runtime.process import _spawn_worker_process, stream_agent


class HangingPipe:
    async def readline(self):
        await asyncio.sleep(10)
        return b""


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, value):
        self.writes.append(value)

    async def drain(self):
        return

    def close(self):
        self.closed = True


class BlockingStdin(FakeStdin):
    def __init__(self):
        super().__init__()
        self.drain_started = asyncio.Event()

    async def drain(self):
        self.drain_started.set()
        await asyncio.sleep(10)


class FakeProcess:
    def __init__(self, stdin=None):
        self.pid = 12345
        self.returncode = None
        self.stdin = stdin or FakeStdin()
        self.stdout = HangingPipe()
        self.stderr = HangingPipe()
        self.terminated = False

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.terminated = True
        self.returncode = -9

    async def wait(self):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


class AgentProcessTests(unittest.TestCase):
    def test_query_forwards_boot_timing_without_control_handshake(self):
        async def exercise():
            process = FakeProcess()
            process.stdout = asyncio.StreamReader()
            process.stderr = asyncio.StreamReader()
            boot = {'type': 'performance', 'version': 1, 'scope': 'worker_boot',
                    'elapsedMs': {'imported': 25}, 'cpuMs': {}, 'counts': {}}
            for event in ({'type': 'worker_ready', 'performance': boot},
                          {'type': 'text', 'text': 'answer'}, {'type': 'worker_done'}):
                process.stdout.feed_data((json.dumps(event) + '\n').encode())
            process.stdout.feed_eof()
            process.stderr.feed_eof()
            with patch('runtime.process._spawn_worker_process', return_value=process) as spawn:
                events = [event async for event in stream_agent({}, timing_enabled=True)]
                spawn.assert_awaited_once_with({}, timing_enabled=True)
            self.assertEqual(events, [boot, {'type': 'text', 'text': 'answer'}])

        asyncio.run(exercise())

    def test_worker_spawn_passes_trusted_payload_to_environment_selection(self):
        async def exercise():
            payload = {"workflow_name":"qa", "_data_identity":{"tenant_id":"tenant"}}
            with patch("runtime.process.worker_environment", return_value={"SELECTED_SECRET":"test"}) as select, \
                 patch("runtime.process.asyncio.create_subprocess_exec", return_value=FakeProcess()) as spawn:
                await _spawn_worker_process(payload)
                select.assert_called_once_with()
                self.assertEqual(spawn.call_args.kwargs["env"], {"SELECTED_SECRET":"test"})
        asyncio.run(exercise())

    def test_worker_spawn_enables_timing_only_when_requested_by_runtime(self):
        async def exercise():
            with patch("runtime.process.worker_environment", return_value={"SELECTED_SECRET":"test"}), \
                 patch("runtime.process.asyncio.create_subprocess_exec", return_value=FakeProcess()) as spawn:
                await _spawn_worker_process({}, timing_enabled=True)
                self.assertEqual(spawn.call_args.kwargs["env"], {
                    "SELECTED_SECRET": "test", "CCSDK_ENABLE_TIMING": "1"
                })
        asyncio.run(exercise())

    def test_stream_agent_cancellation_terminates_worker_process(self):
        async def exercise():
            process = FakeProcess()
            async def terminate(fake_process):
                fake_process.terminate()
                await fake_process.wait()

            with patch("runtime.process._spawn_worker_process", return_value=process), \
                 patch("runtime.process._terminate_process_tree", side_effect=terminate):
                stream = stream_agent({"prompt": "hang"})
                task = asyncio.create_task(stream.__anext__())
                await asyncio.sleep(0.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await stream.aclose()
            self.assertTrue(process.terminated)
            self.assertTrue(process.stdin.closed)

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))

    def test_stream_agent_cancellation_during_initial_write_terminates_worker_process(self):
        async def exercise():
            stdin = BlockingStdin()
            process = FakeProcess(stdin=stdin)

            async def terminate(fake_process):
                fake_process.terminate()
                await fake_process.wait()

            with patch("runtime.process._spawn_worker_process", return_value=process), \
                 patch("runtime.process._terminate_process_tree", side_effect=terminate):
                stream = stream_agent({"prompt": "write-hang"})
                task = asyncio.create_task(stream.__anext__())
                await asyncio.wait_for(stdin.drain_started.wait(), timeout=1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await stream.aclose()

            self.assertTrue(process.terminated)

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))


if __name__ == "__main__":
    unittest.main()
