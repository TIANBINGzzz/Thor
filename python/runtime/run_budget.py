"""本轮工具硬计数，以及 SDK 可观察模型调用/用量的中断预算。"""
import asyncio

class BudgetExceeded(RuntimeError):
    code = 'execution_budget_exceeded'

class RunBudget:
    def __init__(self, limits):
        self.limits = limits
        self.exceeded = asyncio.Event()
        self.reason = ''
        self.tool_calls = self.model_calls = self.tokens = self.output_tokens = 0
        self.timers = {}
        self.deadline = None

    def fail(self, reason):
        if not self.reason:
            self.reason = reason
            self.exceeded.set()
            if self.deadline is not None:
                self.deadline.reschedule(asyncio.get_running_loop().time())

    def start_tool(self, call_id):
        limit = self.limits.get('max_tool_calls')
        if self.reason or limit is not None and self.tool_calls >= limit:
            self.fail('tool_call_budget_exceeded')
            return False
        self.tool_calls += 1
        timeout = self.limits.get('tool_timeout_ms')
        if timeout:
            self.timers[call_id] = asyncio.get_running_loop().call_later(timeout/1000, self.fail, 'tool_timeout')
        return True

    def finish_tool(self, call_id):
        timer = self.timers.pop(call_id, None)
        if timer: timer.cancel()

    def observe(self, message):
        if message.kind != 'stream': return
        event = message.data.get('event', {})
        if event.get('type') == 'message_start':
            self.model_calls += 1
            usage = event.get('message', {}).get('usage', {})
            self.output_tokens = usage.get('output_tokens', 0)
            self.tokens += sum(usage.get(key,0) for key in
                ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens'))
        elif event.get('type') == 'message_delta':
            output = event.get('usage', {}).get('output_tokens',self.output_tokens)
            self.tokens += max(0, output-self.output_tokens)
            self.output_tokens = output
        for name,value,reason in [('max_model_calls',self.model_calls,'model_call_budget_exceeded'),
                                  ('max_total_tokens',self.tokens,'token_budget_exceeded')]:
            limit = self.limits.get(name)
            if limit is not None and value > limit: self.fail(reason)

    async def watch(self, iterator):
        """在原 Task 消费 SDK 流，保证 AnyIO cancel scope 的进入和退出一致。"""
        try:
            async with asyncio.timeout(None) as deadline:
                self.deadline = deadline
                if self.reason: raise BudgetExceeded(self.reason)
                async for message in iterator:
                    self.observe(message)
                    if self.reason: raise BudgetExceeded(self.reason)
                    yield message
        except TimeoutError:
            if self.reason: raise BudgetExceeded(self.reason) from None
            raise
        finally:
            self.deadline = None
            await iterator.aclose()

    def close(self):
        for timer in self.timers.values(): timer.cancel()
        self.timers.clear()
