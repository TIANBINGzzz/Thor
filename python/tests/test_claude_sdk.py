import asyncio
import unittest

from claude_agent_sdk import AssistantMessage, TextBlock

from runtime.claude_sdk import (
    ClaudeSDKFacade,
    SDKConfigurationError,
    SDKExecutionError,
    SDKMessage,
    SDKTimeoutError,
    normalize_message,
)


class ClaudeSDKFacadeTests(unittest.TestCase):
    def test_normalize_message_keeps_provider_fields_as_plain_data(self):
        message = AssistantMessage(
            content=[TextBlock(text="hello")],
            model="test-model",
            message_id="message-1",
            session_id="session-1",
            uuid="uuid-1",
        )

        normalized = normalize_message(message)

        self.assertIsInstance(normalized, SDKMessage)
        self.assertEqual(normalized.kind, "assistant")
        self.assertEqual(normalized.data["model"], "test-model")
        self.assertEqual(normalized.data["content"], [{"type": "text", "text": "hello"}])
        self.assertEqual(normalized.session_id, "session-1")
        self.assertEqual(normalized.uuid, "uuid-1")

    def test_query_stream_returns_normalized_messages_and_closes_source(self):
        closed = False

        async def source():
            nonlocal closed
            try:
                yield AssistantMessage(content=[TextBlock(text="hello")], model="test-model")
            finally:
                closed = True

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=lambda **_: source())
            result = []
            async for message in facade.stream_query("hello", object(), timeout_ms=1000):
                result.append(message)
            return result

        messages = asyncio.run(asyncio.wait_for(exercise(), timeout=1))

        self.assertEqual([message.kind for message in messages], ["assistant"])
        self.assertTrue(closed)

    def test_query_timeout_is_hard_and_closes_source(self):
        closed = False

        async def source():
            nonlocal closed
            try:
                await asyncio.sleep(10)
                yield AssistantMessage(content=[TextBlock(text="never")], model="test-model")
            finally:
                closed = True

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=lambda **_: source())
            with self.assertRaises(SDKTimeoutError):
                async for _ in facade.stream_query("hello", object(), timeout_ms=10):
                    pass

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))
        self.assertTrue(closed)

    def test_query_cancellation_is_propagated_and_closes_source(self):
        closed = False

        async def source():
            nonlocal closed
            try:
                await asyncio.sleep(10)
                yield AssistantMessage(content=[TextBlock(text="never")], model="test-model")
            finally:
                closed = True

        async def consume(facade):
            async for _ in facade.stream_query("hello", object(), timeout_ms=10_000):
                pass

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=lambda **_: source())
            task = asyncio.create_task(consume(facade))
            await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))
        self.assertTrue(closed)

    def test_provider_error_is_mapped_to_project_error(self):
        async def source():
            raise RuntimeError("provider detail must not cross the boundary")
            yield  # Make this an async generator.

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=lambda **_: source())
            with self.assertRaises(SDKExecutionError) as raised:
                async for _ in facade.stream_query("hello", object(), timeout_ms=1000):
                    pass
            return raised.exception

        error = asyncio.run(asyncio.wait_for(exercise(), timeout=1))
        self.assertEqual(str(error), "Claude SDK 执行失败")

    def test_stream_terminating_after_partial_output_is_closed_and_mapped(self):
        closed = False

        async def source():
            nonlocal closed
            try:
                yield "partial"
                raise RuntimeError("provider stream terminated")
            finally:
                closed = True

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=lambda **_: source())
            with self.assertRaises(SDKExecutionError):
                async for _ in facade.stream_query("hello", object(), timeout_ms=1000):
                    pass

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))
        self.assertTrue(closed)

    def test_invalid_prompt_and_timeout_fail_before_provider_call(self):
        called = False

        def query_impl(**_):
            nonlocal called
            called = True
            raise AssertionError("provider must not be called")

        async def exercise():
            facade = ClaudeSDKFacade(query_impl=query_impl)
            with self.assertRaises(SDKConfigurationError):
                async for _ in facade.stream_query("", object(), timeout_ms=1000):
                    pass
            with self.assertRaises(SDKConfigurationError):
                async for _ in facade.stream_query("hello", object(), timeout_ms=0):
                    pass

        asyncio.run(asyncio.wait_for(exercise(), timeout=1))
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
