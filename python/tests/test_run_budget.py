import asyncio
import unittest

class RunBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_tool_timeout_after_first_message_interrupts_pending_receive(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import agent_worker
        from runtime.run_budget import RunBudget, BudgetExceeded
        from runtime.claude_sdk import SDKMessage
        budget = RunBudget({'tool_timeout_ms':10})
        async def receive(**kwargs):
            yield SDKMessage(kind='stream', data={'event':{'type':'message_start','message':{}}})
            budget.start_tool('slow-tool')
            await asyncio.sleep(5)
        client = SimpleNamespace(receive_response=receive)
        with patch.object(agent_worker,'emit'), self.assertRaisesRegex(BudgetExceeded,'tool_timeout'):
            await asyncio.wait_for(agent_worker._receive_client_response(
                client, {'run_id':'budget'}, {}, asyncio.Queue(), None, budget=budget), .5)
        budget.close()

    async def test_stream_keeps_sdk_task_and_cancel_scope(self):
        import anyio
        from runtime.run_budget import RunBudget
        from runtime.claude_sdk import SDKMessage
        owner = asyncio.current_task()
        async def stream():
            with anyio.CancelScope():
                self.assertIs(asyncio.current_task(), owner)
                yield SDKMessage(kind='result', data={})
        async for _ in RunBudget({}).watch(stream()):
            pass

    async def test_tool_limit_is_reserved_before_parallel_calls(self):
        from runtime.run_budget import RunBudget
        budget=RunBudget({'max_tool_calls':1,'tool_timeout_ms':1000})
        self.assertTrue(budget.start_tool('one'))
        self.assertFalse(budget.start_tool('two'))
        self.assertEqual(budget.reason,'tool_call_budget_exceeded')
        budget.close()

    async def test_timeout_interrupts_waiting_stream(self):
        from runtime.run_budget import RunBudget, BudgetExceeded
        budget=RunBudget({'tool_timeout_ms':10})
        async def blocked():
            await asyncio.sleep(5)
            yield None
        budget.start_tool('one')
        with self.assertRaisesRegex(BudgetExceeded,'tool_timeout'):
            async for _ in budget.watch(blocked()): pass
        budget.close()

    async def test_finished_tool_does_not_time_out(self):
        from runtime.run_budget import RunBudget
        budget=RunBudget({'tool_timeout_ms':10})
        budget.start_tool('one');budget.finish_tool('one')
        await asyncio.sleep(.025)
        self.assertFalse(budget.exceeded.is_set())
        budget.close()

    async def test_usage_is_accumulated_without_double_counting_stream_deltas(self):
        from runtime.run_budget import RunBudget
        from runtime.claude_sdk import SDKMessage
        budget=RunBudget({'max_total_tokens':15,'max_model_calls':2})
        for event in [{'type':'message_start','message':{'usage':{'input_tokens':10}}},
                      {'type':'message_delta','usage':{'output_tokens':2}},
                      {'type':'message_delta','usage':{'output_tokens':4}}]:
            budget.observe(SDKMessage(kind='stream',data={'event':event}))
        self.assertEqual(budget.tokens,14)
        budget.observe(SDKMessage(kind='stream',data={'event':{'type':'message_delta','usage':{'output_tokens':6}}}))
        self.assertEqual(budget.reason,'token_budget_exceeded')
        budget.close()
