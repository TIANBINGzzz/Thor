"""将明确给出的数据转换为 Mermaid 正文；不查询数据库、不生成或上传文件。"""

from decimal import Decimal
from functools import lru_cache
import json
import math
import re
import unicodedata

from jsonschema import Draft202012Validator

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.declarations import operation


@lru_cache(maxsize=1)
def _chart_validator():
    """延迟从 Catalog 取得图表契约，避免工具模块导入时循环加载。"""
    schema = operation('charts', 'build_mermaid').input_schema
    return schema, Draft202012Validator(schema)


class ChartInputError(ValueError):
    """只暴露可修正的字段及原因，不回显原始数据或校验器堆栈。"""

    def __init__(self, field, message):
        """保存可修正字段和公开原因，不包含原始数据或校验堆栈。"""
        self.field = field
        super().__init__(message)


def _text(value, field):
    """拒绝不可见控制字符，合并空白并要求标题或标签非空。"""
    if any(unicodedata.category(char).startswith('C') and char not in '\r\n\t' for char in value):
        raise ChartInputError(field, '文本含不支持的控制字符，请提供可见标签。')
    text = re.sub(r'\s+', ' ', value).strip()
    if not text:
        raise ChartInputError(field, '标题和分类标签不能为空。')
    return text


def _escape(text):
    """用 Mermaid 数字实体编码特殊字符，包含原始井号以防实体被再次解释。"""
    return ''.join(f'#{ord(char)};' if char in '"\\`<>&#%' else char for char in text)


def _number(value):
    """将数值展开为 Mermaid 支持的十进制文本，不隐式四舍五入。"""
    if value == 0:
        return '0'
    text = format(Decimal(str(value)), 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def build_mermaid(arguments):
    """校验显式数据并返回完整Markdown块；不聚合、排序或推测缺失值。"""
    chart_schema, validator = _chart_validator()
    invalid = next(validator.iter_errors(arguments), None)
    if invalid:
        field = next(iter(invalid.absolute_path), None)
        if invalid.validator == 'required' and isinstance(arguments, dict):
            field = next((key for key in chart_schema['required'] if key not in arguments), None)
        field = field if field in chart_schema['properties'] else 'arguments'
        raise ChartInputError(field, '字段类型、长度或取值不符合工具约定，请按输入schema修正。')
    kind = arguments['chart_type']
    title = _text(arguments['title'], 'title')
    labels = [_text(label, 'labels') for label in arguments['labels']]
    values = arguments['values']
    unit = _text(arguments['unit'], 'unit') if arguments.get('unit', '').strip() else ''
    if len(labels) != len(values):
        raise ChartInputError('values', '标签和数值数量必须相同，缺失数据不能补0。')
    if len(set(labels)) != len(labels):
        raise ChartInputError('labels', '分类标签重复，请澄清分组或提供已汇总的数据。')
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ChartInputError('values', '数值必须是有限数字，不接受空值、布尔值或字符串。')
    if kind == 'line' and len(values) < 2:
        raise ChartInputError('values', '折线图至少需要两个有序数据点。')
    # Mermaid 11.12的柱形以绘图区底部为基准，负值会产生错误的相对高度。
    if kind in {'bar', 'bar-horizontal'} and any(value < 0 for value in values):
        raise ChartInputError('values', '当前柱状图只支持非负值；请保留数据表，有序趋势可选择折线图。')
    if kind == 'radar' and (not 3 <= len(values) <= 12 or any(value < 0 for value in values)):
        raise ChartInputError('values', '雷达图需要3至12个同尺度非负指标；不能自行归一化不同单位。')
    if kind == 'treemap' and any(value <= 0 for value in values):
        raise ChartInputError('values', '矩形树图只支持正数面积；含零值或负值时请保留表格或选择其他合适图表。')
    if kind == 'pie' and (len(values) > 12 or any(value < 0 for value in values) or sum(values) <= 0):
        raise ChartInputError('values', '饼图最多12项，数值必须非负且合计大于0；请澄清或先汇总。')
    # Mermaid 11.12/12会过滤占比<1%的扇区并重新分配角度，不能只靠图例保留原值。
    if kind == 'pie' and any(0 < value / sum(values) * 100 < 1 for value in values):
        raise ChartInputError('values', '当前饼图不支持占比低于1%的正值项，请改用柱状图或表格；不能删除或擅自合并小项。')
    heading = title + (f'（单位：{unit}）' if unit else '')
    numbers = ', '.join(_number(value) for value in values)
    if kind == 'pie':
        lines = ['pie showData', f'    title {_escape(heading)}',
                 *(f'    "{_escape(label)}" : {_number(value)}' for label, value in zip(labels, values))]
    elif kind == 'radar':
        axes = ', '.join(f'a{index}["{_escape(label)}"]' for index, label in enumerate(labels))
        lines = ['radar-beta', f'    title {_escape(heading)}', f'    axis {axes}',
                 f'    curve data["{_escape(unit or "数值")}"]{{{numbers}}}',
                 '    min 0', f'    max {_number(max(values) or 1)}', '    graticule polygon']
    elif kind == 'treemap':
        lines = ['treemap-beta', f'"{_escape(heading)}"',
                 *(f'    "{_escape(label)}": {_number(value)}' for label, value in zip(labels, values))]
    else:
        lower, upper = min(0, *values), max(0, *values)
        if lower == upper:
            upper = 1
        axis_title = f'"{_escape(unit)}" ' if unit else ''
        categories = ', '.join(f'"{_escape(label)}"' for label in labels)
        diagram = 'xychart-beta horizontal' if kind == 'bar-horizontal' else 'xychart-beta'
        plot = 'bar' if kind == 'bar-horizontal' else kind
        lines = [diagram, f'    title "{_escape(title)}"', f'    x-axis [{categories}]',
                 f'    y-axis {axis_title}{_number(lower)} --> {_number(upper)}', f'    {plot} [{numbers}]']
    return {'markdown': '```mermaid\n' + '\n'.join(lines) + '\n```'}


def create_chart_server(on_generated=None):
    """注册显式数据图表工具，并按需通知调用方收集生成的正文。"""
    spec = operation('charts', 'build_mermaid')
    @sdk_tool(spec.ref, spec.description, spec.input_schema)
    async def build(arguments):
        """返回 Mermaid 正文或可修正的字段错误，成功后触发生成回调。"""
        try:
            value = build_mermaid(arguments)
        except ChartInputError as error:
            return {'isError': True, 'content': [{'type': 'text', 'text': json.dumps({
                'error': {'code': 'CHART_INPUT_INVALID', 'field': error.field, 'message': str(error)}},
                ensure_ascii=False)}]}
        if on_generated is not None:
            on_generated(value['markdown'])
        return {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}

    return create_sdk_mcp_server(name='charts', version='1.0.0', tools=[build])


def provide_tool(definition, context):
    """创建本轮图表正文 Tool。"""
    return definition.ref, create_chart_server(on_generated=context.get('chart_sink')), ''
