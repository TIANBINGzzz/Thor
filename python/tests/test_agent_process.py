import asyncio
import unittest
from unittest.mock import patch

from runtime.process import prompt_without_workflow_prefix, stream_agent, workflow_name_from_prompt


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
    def test_workflow_prefix(self):
        self.assertEqual(workflow_name_from_prompt("/database-qa 统计项目数"), "database-qa")
        self.assertEqual(workflow_name_from_prompt("  /professional-report 写报告"), "professional-report")

    def test_plain_prompt_has_no_workflow(self):
        self.assertIsNone(workflow_name_from_prompt("请统计项目数"))
        self.assertIsNone(workflow_name_from_prompt("someone@example.com"))

    def test_workflow_prefix_is_removed_before_sdk_query(self):
        self.assertEqual(prompt_without_workflow_prefix(" /database-qa 统计项目数 "), "统计项目数")
        self.assertEqual(prompt_without_workflow_prefix("请统计项目数"), "请统计项目数")

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
