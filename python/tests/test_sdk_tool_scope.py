import asyncio
import threading
import unittest

from runtime.claude_sdk import SDKExecutionError, SDKTimeoutError, SDKToolScope, run_tool_thread, sdk_tool


class SDKToolScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_only_tool_cannot_reuse_previous_turn_context(self):
        scope = SDKToolScope()
        calls = []
        scope.start()
        with scope.capture():
            @sdk_tool('operation', 'probe', {}, run_only=True)
            async def operation(args):
                calls.append('first-run')
                return {'content': []}
        await operation.handler({})
        scope.stop()
        await scope.drain(timeout_ms=1000)
        scope.start()
        self.assertTrue((await operation.handler({}))['isError'])
        self.assertEqual(calls, ['first-run'])
        scope.stop()

    async def test_cancel_waits_for_handler_cleanup_and_reuses_cached_tool(self):
        scope = SDKToolScope()
        started, cleaning, released = (asyncio.Event() for _ in range(3))
        tokens = []
        token = 'first'

        with scope.capture():
            @sdk_tool('probe', 'test', {})
            async def probe(args):
                tokens.append(token)
                if len(tokens) == 1:
                    started.set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        cleaning.set()
                        await released.wait()
                return {'content': []}

        scope.start()
        call = asyncio.create_task(probe.handler({}))
        try:
            await started.wait()
            scope.stop(cancel=True)
            await cleaning.wait()
            scope.stop(cancel=True)  # 不重复取消正在收尾的工具。
            with self.assertRaises(SDKTimeoutError):
                await scope.drain(timeout_ms=10)
            with self.assertRaises(SDKExecutionError):
                scope.start()
            denied = await probe.handler({})
            self.assertTrue(denied['isError'])
        finally:
            released.set()
            await asyncio.gather(call, return_exceptions=True)
        await scope.drain(timeout_ms=1000)
        token = 'second'
        scope.start()
        await probe.handler({})
        scope.stop()
        await scope.drain(timeout_ms=1000)
        self.assertEqual(tokens, ['first', 'second'])

    async def test_cancelled_thread_remains_in_flight_until_it_exits(self):
        scope = SDKToolScope()
        started, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()

        def blocking():
            loop.call_soon_threadsafe(started.set)
            release.wait(3)

        with scope.capture():
            @sdk_tool('thread', 'test', {})
            async def probe(args):
                await run_tool_thread(blocking)
                return {'content': []}

        scope.start()
        call = asyncio.create_task(probe.handler({}))
        try:
            await started.wait()
            call.cancel()  # 模拟 SDK 先发来工具取消，再进入 Run 收尾。
            await asyncio.gather(call, return_exceptions=True)
            scope.stop(cancel=True)
            with self.assertRaises(SDKTimeoutError):
                await scope.drain(timeout_ms=10)
        finally:
            release.set()
            await scope.drain(timeout_ms=1000)

    async def test_distinct_clients_do_not_cancel_each_others_tools(self):
        scopes = [SDKToolScope(), SDKToolScope()]
        started, release = asyncio.Event(), asyncio.Event()
        with scopes[1].capture():
            @sdk_tool('probe', 'test', {})
            async def probe(args):
                started.set()
                await release.wait()
                return {'content': []}
        for scope in scopes:
            scope.start()
        call = asyncio.create_task(probe.handler({}))
        await started.wait()
        scopes[0].stop(cancel=True)
        await scopes[0].drain(timeout_ms=10)
        self.assertFalse(call.done())
        release.set()
        await call
        scopes[1].stop()
        await scopes[1].drain(timeout_ms=1000)
