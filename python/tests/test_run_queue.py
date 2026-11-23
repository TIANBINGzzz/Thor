"""Run 等待与执行器资源独立；只替换测试中的外部容量。"""
import asyncio
import unittest
from unittest.mock import patch

from runtime.run_queue import RunQueue, RunQueueError


class RunQueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_and_resource_share_three_minutes_excluding_preparation(self):
        queue = RunQueue(max_pending=2)
        with patch('runtime.run_queue.time') as clock:
            clock.monotonic.return_value = 0
            first = queue.enqueue('session', timeout_ms=180000)
            first.dispatch()
            run = queue.enqueue('session', timeout_ms=180000)
            turn = asyncio.create_task(run.wait_turn())
            await asyncio.sleep(0)
            clock.monotonic.return_value = 170
            first.release()
            await turn
            clock.monotonic.return_value = 670  # 下载耗时不计入排队。
            wait = asyncio.create_task(run.wait_for(lambda: None, resource='start'))
            await asyncio.sleep(0)
            clock.monotonic.return_value = 679
            queue.notify()
            await asyncio.sleep(0)
            self.assertFalse(wait.done())
            clock.monotonic.return_value = 680
            queue.notify()
            with self.assertRaises(RunQueueError) as caught:
                await asyncio.wait_for(wait, 1)
            self.assertEqual(caught.exception.code, 'run_queue_timeout')
            run.release()
            self.assertEqual(queue.pending, 0)

    async def test_blocked_executor_does_not_block_other_sessions(self):
        queue = RunQueue(max_pending=4)
        a = queue.enqueue('a', timeout_ms=1000)
        a_next = queue.enqueue('a', timeout_ms=1000)
        b = queue.enqueue('b', timeout_ms=1000)
        await a.wait_turn()
        a_next_wait = asyncio.create_task(a_next.wait_turn())
        available = False
        a_wait = asyncio.create_task(a.wait_for(lambda: 'local' if available else None, resource='local'))
        await asyncio.sleep(0)
        self.assertFalse(a_wait.done())
        self.assertFalse(a_next_wait.done())
        await b.wait_turn()
        self.assertEqual(await b.wait_for(lambda: 'remote', resource='remote'), 'remote')
        b.dispatch()
        b.release()
        available = True
        queue.notify()
        self.assertEqual(await asyncio.wait_for(a_wait, .2), 'local')
        a.dispatch()
        self.assertFalse(a_next_wait.done())
        a.release()
        await asyncio.wait_for(a_next_wait, .2)
        a_next.release()

    async def test_cancelled_resource_wait_does_not_take_a_later_permit(self):
        queue = RunQueue(max_pending=2)
        first = queue.enqueue('a', timeout_ms=1000)
        second = queue.enqueue('b', timeout_ms=1000)
        permits = []
        first_wait = asyncio.create_task(first.wait_for(lambda: permits.pop(0) if permits else None, resource='local'))
        await asyncio.sleep(0)
        second_wait = asyncio.create_task(second.wait_for(lambda: permits.pop(0) if permits else None, resource='local'))
        await asyncio.sleep(0)
        first_wait.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_wait
        first.release()
        permits.append('one')
        queue.notify()
        self.assertEqual(await asyncio.wait_for(second_wait, .2), 'one')
        second.release()

    async def test_waiting_timeout_releases_queue_capacity(self):
        queue = RunQueue(max_pending=1)
        run = queue.enqueue('a', timeout_ms=20)
        with self.assertRaises(RunQueueError) as full:
            queue.enqueue('b', timeout_ms=20)
        self.assertEqual(full.exception.code, 'worker_capacity_exceeded')
        await run.wait_turn()
        with self.assertRaises(RunQueueError) as expired:
            await run.wait_for(lambda: None, resource='local')
        self.assertEqual(expired.exception.code, 'run_queue_timeout')
        run.release()
        self.assertIsNotNone(queue.enqueue('b', timeout_ms=20))
