"""图表正文的数据保真、注入边界及普通对话挂载。"""

import json
import math
import unittest
from unittest.mock import patch

from runtime.config import build_options, create_run_services
from runtime.mcp_auth import inject_mcp_authentication


class MermaidConfigTests(unittest.TestCase):
    def test_conversation_mounts_chart_tool_without_database_or_credentials(self):
        with patch.dict('os.environ', {}, clear=True):
            payload = {'capability_ref': 'conversation'}
            self.assertIsNone(create_run_services(payload))
            options = build_options(payload)
        self.assertIn('charts', options.mcp_servers)
        self.assertIn('mcp__charts__build_mermaid', options.allowed_tools)
        self.assertNotIn('data', options.mcp_servers)

    def test_chart_tool_does_not_receive_business_credentials(self):
        servers = {'charts': {'type': 'sdk', 'name': 'charts'}}
        result = inject_mcp_authentication(servers, {'platformBearer': 'private-test-token'})
        self.assertEqual(result, servers)
        self.assertNotIn('private-test-token', json.dumps(result))

    def test_direct_qa_keeps_existing_tool_boundary(self):
        options = build_options({'capability_ref': 'national-excellence-data-qa',
                                 'workflow_name': 'double-high-qa'})
        self.assertNotIn('charts', options.mcp_servers)


class MermaidTests(unittest.TestCase):
    def chart(self, **changes):
        from tools.mermaid import build_mermaid
        return build_mermaid({'chart_type': 'bar', 'title': '任务数量',
                              'labels': ['项目A', '项目B'], 'values': [120, 85], 'unit': '个', **changes})

    def test_bar_keeps_input_order_and_numbers(self):
        result = self.chart()
        self.assertEqual(result['markdown'], '```mermaid\nxychart-beta\n    title "任务数量"\n'
                         '    x-axis ["项目A", "项目B"]\n    y-axis "个" 0 --> 120\n'
                         '    bar [120, 85]\n```')

    def test_line_preserves_negative_small_decimal_and_zero(self):
        result = self.chart(chart_type='line', labels=['1月', '2月', '3月'], values=[-2.5, 0.000001, 0])
        self.assertIn('line [-2.5, 0.000001, 0]', result['markdown'])
        self.assertIn('y-axis "个" -2.5 --> 0.000001', result['markdown'])

    def test_horizontal_bar_keeps_long_labels_and_source_order(self):
        text = self.chart(chart_type='bar-horizontal', labels=['很长的项目名称甲', '很长的项目名称乙'])['markdown']
        self.assertIn('xychart-beta horizontal', text)
        self.assertIn('x-axis ["很长的项目名称甲", "很长的项目名称乙"]', text)
        self.assertIn('bar [120, 85]', text)

    def test_radar_keeps_three_to_twelve_nonnegative_metrics_and_zero_baseline(self):
        text = self.chart(chart_type='radar', title='能力评分', unit='分',
                          labels=['质量', '效率', '协作'], values=[80, 65, 90])['markdown']
        self.assertIn('radar-beta', text)
        self.assertIn('axis a0["质量"], a1["效率"], a2["协作"]', text)
        self.assertIn('curve data["分"]{80, 65, 90}', text)
        self.assertIn('min 0', text)
        self.assertIn('max 90', text)
        zero = self.chart(chart_type='radar', labels=['甲', '乙', '丙'], values=[0, 0, 0])['markdown']
        self.assertIn('max 1', zero)

    def test_treemap_preserves_small_positive_values_and_unit(self):
        text = self.chart(chart_type='treemap', values=[0.01, 200])['markdown']
        self.assertIn('treemap-beta', text)
        self.assertIn('"任务数量（单位：个）"', text)
        self.assertIn('"项目A": 0.01', text)
        self.assertIn('"项目B": 200', text)

    def test_zero_series_has_nonempty_axis_domain(self):
        self.assertIn('0 --> 1', self.chart(values=[0, 0])['markdown'])

    def test_pie_keeps_raw_values_instead_of_recalculating_percentages(self):
        text = self.chart(chart_type='pie', values=[12.5, 37.5])['markdown']
        self.assertIn('pie showData', text)
        self.assertIn('"项目A" : 12.5', text)
        self.assertIn('"项目B" : 37.5', text)
        self.assertIn('个', text)

    def test_pie_rejects_slices_the_renderer_would_drop(self):
        for values in ([1, 199], [0.01, 2], [0, 0.01, 2]):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, '1%'):
                self.chart(chart_type='pie', labels=[str(i) for i in range(len(values))], values=values)

    def test_pie_allows_one_percent_boundary_and_zero_in_legend(self):
        result = self.chart(chart_type='pie', labels=['零', '小项', '大项'], values=[0, 1, 99])
        self.assertIn('"零" : 0', result['markdown'])
        self.assertIn('"小项" : 1', result['markdown'])
        self.assertIn('"大项" : 99', result['markdown'])

    def test_user_text_cannot_close_fence_or_insert_directive_or_html(self):
        result = self.chart(title='标题\n```\n%%{init: {}}%%',
                            labels=['甲"乙\\丙', '<script>&#34;'], unit='个\n```')
        markdown = result['markdown']
        self.assertEqual(markdown.count('```'), 2)
        self.assertNotIn('%%', markdown)
        self.assertNotIn('<script>', markdown)
        self.assertNotIn('甲"乙', markdown)

    def test_invalid_data_is_rejected_without_fabricating_or_dropping_values(self):
        cases = [
            {'values': [1]}, {'values': [True, 2]}, {'values': [None, 2]},
            {'values': ['1', 2]}, {'values': [math.nan, 1]}, {'values': [math.inf, 1]},
            {'values': [1e20, 1]}, {'labels': [], 'values': []},
            {'labels': ['A', ' A ']}, {'labels': [' ', 'B']},
            {'labels': ['A\x00', 'B']}, {'title': ' '}, {'title': 'x' * 121},
            {'chart_type': 'scatter'}, {'chart_type': 'pie', 'values': [-1, 2]},
            {'chart_type': 'bar', 'values': [-3, -1]},
            {'chart_type': 'bar-horizontal', 'values': [-1, 2]},
            {'chart_type': 'radar', 'values': [1, 2]},
            {'chart_type': 'radar', 'labels': ['甲', '乙', '丙'], 'values': [-1, 2, 3]},
            {'chart_type': 'radar', 'labels': [str(i) for i in range(13)], 'values': [1] * 13},
            {'chart_type': 'treemap', 'values': [0, 2]},
            {'chart_type': 'treemap', 'values': [-1, 2]},
            {'chart_type': 'pie', 'values': [0, 0]},
            {'chart_type': 'line', 'labels': ['A'], 'values': [1]},
            {'labels': [str(i) for i in range(51)], 'values': [1] * 51},
            {'chart_type': 'pie', 'labels': [str(i) for i in range(13)], 'values': [1] * 13},
            {'config': {'securityLevel': 'loose'}},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.chart(**case)

    def test_error_does_not_echo_user_data(self):
        with self.assertRaises(ValueError) as caught:
            self.chart(chart_type='private-input-marker')
        self.assertNotIn('private-input-marker', str(caught.exception))


class MermaidToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_handler_returns_markdown_or_safe_error(self):
        from tools.mermaid import create_chart_server
        with patch('tools.mermaid.create_sdk_mcp_server', side_effect=lambda **kwargs: kwargs):
            config = create_chart_server()
        tool = config['tools'][0]
        result = await tool.handler({'chart_type': 'pie', 'title': '构成',
                                     'labels': ['甲', '乙'], 'values': [2, 3]})
        self.assertFalse(result.get('isError', False))
        self.assertTrue(json.loads(result['content'][0]['text'])['markdown'].startswith('```mermaid\npie'))
        failed = await tool.handler({'chart_type': 'pie', 'title': 'private-input-marker',
                                     'labels': ['甲'], 'values': [None]})
        self.assertTrue(failed['isError'])
        self.assertNotIn('private-input-marker', json.dumps(failed))


if __name__ == '__main__':
    unittest.main()
