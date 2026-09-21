"""真实漏图场景：工具成功但模型只回复摘要，正文仍须交付完整图表。"""
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from runtime.chart_delivery import ChartDelivery
from runtime.config import build_options
from tools.mermaid import build_mermaid


class ChartDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def chart(self, number=1):
        return build_mermaid({'chart_type': 'bar', 'title': f'图{number}',
                              'labels': ['甲', '乙'], 'values': [number, 2]})['markdown']

    def test_four_omitted_charts_are_delivered_before_success(self):
        events = []
        delivery = ChartDelivery(events.append)
        for number in range(1, 5):
            delivery.record(self.chart(number))
        delivery.emit({'type': 'text', 'text': '以上是四张图。'})
        delivery.emit({'type': 'result', 'ok': True})
        answer = ''.join(e.get('text', '') for e in events)
        self.assertEqual(answer.count('```mermaid'), 4)
        self.assertEqual(events[-1]['type'], 'result')
        for number in range(1, 5):
            self.assertIn(self.chart(number), answer)

    def test_streamed_chart_and_repeated_tool_call_are_not_duplicated(self):
        events = []
        delivery = ChartDelivery(events.append)
        chart = self.chart()
        delivery.record(chart)
        delivery.record(chart)
        for char in chart:
            delivery.emit({'type': 'text', 'text': char})
        delivery.emit({'type': 'result', 'ok': True})
        self.assertEqual(''.join(e.get('text', '') for e in events), chart)

    def test_equivalent_mermaid_numeric_entities_are_not_duplicated(self):
        events = []
        delivery = ChartDelivery(events.append)
        chart = build_mermaid({
            'chart_type': 'pie', 'title': '产业占比',
            'labels': ['第一产业', '第二产业', '第三产业'],
            'values': [7.7, 37.8, 54.5], 'unit': '%',
        })['markdown']
        # The model commonly renders the tool's Mermaid numeric entity #37;
        # back to the visible percent sign while copying the chart into text.
        model_answer = chart.replace('#37;', '%')
        delivery.record(chart)
        delivery.emit({'type': 'text', 'text': model_answer})
        delivery.emit({'type': 'result', 'ok': True})
        self.assertEqual(model_answer, ''.join(e.get('text', '') for e in events
                                               if e.get('type') == 'text'))
        self.assertEqual(1, model_answer.count('```mermaid'))

    def test_nested_or_incomplete_fence_is_not_counted_as_delivered(self):
        for answer in ('```text\n' + self.chart(), '````text\n' + self.chart() + '\n````'):
            events = []
            delivery = ChartDelivery(events.append)
            delivery.record(self.chart())
            delivery.emit({'type': 'text', 'text': answer})
            delivery.emit({'type': 'result', 'ok': True})
            self.assertGreater(len(events), 2)
            self.assertIn(self.chart(), events[-2]['text'])

    def test_reset_does_not_publish_previous_run_charts(self):
        events = []
        delivery = ChartDelivery(events.append)
        delivery.record(self.chart())
        delivery.reset()
        delivery.emit({'type': 'result', 'ok': True})
        self.assertEqual(events, [{'type': 'result', 'ok': True}])

    async def test_client_response_delivers_only_current_run_charts(self):
        import asyncio
        import agent_worker
        from runtime.claude_sdk import SDKMessage
        events = []
        delivery = ChartDelivery(events.append)

        class Client:
            async def receive_response(self, **kwargs):
                yield SDKMessage(kind='result', data={'subtype': 'success'})

        for number in (1, 2):
            delivery.reset()
            delivery.record(self.chart(number))
            offset = len(events)
            await agent_worker._receive_client_response(
                Client(), {'run_id': str(number)}, {}, asyncio.Queue(), False, None, delivery)
            answer = ''.join(e.get('text', '') for e in events[offset:])
            self.assertIn(self.chart(number), answer)
            if number == 2:
                self.assertNotIn(self.chart(1), answer)

    async def test_tool_registers_only_valid_complete_markdown(self):
        charts = []
        with patch('tools.mermaid.create_sdk_mcp_server', side_effect=lambda **kw: kw), \
                patch.dict('os.environ', {}, clear=True):
            options = build_options({'capability_ref': 'chart-generation'}, chart_sink=charts.append)
        tool = options.mcp_servers['charts']['tools'][0]
        good = await tool.handler({'chart_type': 'bar', 'title': '测试', 'labels': ['甲'], 'values': [1]})
        bad = await tool.handler({'chart_type': 'bar', 'title': '测试', 'labels': ['甲'], 'values': [-1]})
        self.assertNotIn('isError', good)
        self.assertTrue(bad['isError'])
        self.assertEqual(len(charts), 1)
        self.assertTrue(charts[0].startswith('```mermaid\n'))

    async def test_query_worker_delivers_chart_even_when_model_omits_it(self):
        import agent_worker
        from runtime.claude_sdk import SDKMessage
        events = []
        record = None

        def options(_, **kwargs):
            nonlocal record
            record = kwargs['chart_sink']
            return SimpleNamespace(tools=None, strict_mcp_config=False)

        async def query(*args, **kwargs):
            record(self.chart())
            yield SDKMessage(kind='assistant', data={'content': [{'type': 'text', 'text': '图已生成。'}]})
            yield SDKMessage(kind='result', data={'subtype': 'success'})

        with patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: None,
                            build_options=options, stream_query=query,
                            isolated_sdk_environment=nullcontext, emit=events.append):
            await agent_worker.run({'prompt': '制图'})
        self.assertIn(self.chart(), ''.join(e.get('text', '') for e in events))
        self.assertEqual(events[-1]['type'], 'result')
