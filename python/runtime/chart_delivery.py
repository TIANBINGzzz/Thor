"""逐Run交付工具生成的图表，避免模型只描述图表却遗漏正文代码块。"""

import re

_MERMAID_ENTITY = re.compile(r'#(34|35|37|38|60|62|92|96);')


def _blocks(text):
    """只计入顶层完整围栏；外层代码块里的Mermaid不能当作已展示。"""
    opened = None
    language = ''
    lines = []
    charts = set()
    for line in text.splitlines():
        fence = re.fullmatch(r' {0,3}(`{3,}|~{3,})(.*)', line)
        if opened is None:
            if fence:
                opened, language = fence[1], fence[2].strip()
                lines = []
        elif (fence and fence[1][0] == opened[0] and len(fence[1]) >= len(opened)
              and not fence[2].strip()):
            if language == 'mermaid':
                charts.add('\n'.join(lines).strip())
            opened = None
        else:
            lines.append(line.rstrip())
    return charts, opened


def _chart_key(block):
    """Compare Mermaid blocks after decoding the entities emitted by the tool.

    The model may copy ``#37;`` as ``%`` (and the other Mermaid numeric
    entities as their visible characters).  Delivery matching must compare
    those equivalent forms without changing either public response.
    """
    return _MERMAID_ENTITY.sub(lambda match: chr(int(match.group(1))), block)


class ChartDelivery:
    def __init__(self, sink):
        self.sink = sink
        self.reset()

    def reset(self):
        """持久Client每轮清空，成功、失败或取消的图表不能进入下一轮。"""
        self.generated = {}
        self.text = []

    def record(self, markdown):
        # 仅由可信图表工具在校验成功后调用，不消费通用工具结果或模型参数。
        blocks, _ = _blocks(markdown)
        if len(blocks) != 1:
            raise ValueError('图表工具必须返回一个完整Mermaid块')
        block = next(iter(blocks))
        self.generated[_chart_key(block)] = markdown

    def emit(self, event):
        if event.get('type') == 'text':
            self.text.append(event.get('text', ''))
        if event.get('type') == 'result':
            shown, unclosed = _blocks(''.join(self.text))
            shown_keys = {_chart_key(block) for block in shown}
            missing = [markdown for key, markdown in self.generated.items() if key not in shown_keys]
            if missing:
                # 模型可能截断在普通代码块内，先闭合再输出可渲染的独立图表。
                addition = '\n' + (unclosed + '\n' if unclosed else '') + '\n' + '\n\n'.join(missing) + '\n'
                self.text.append(addition)
                self.sink({'type': 'text', 'scope': 'main', 'text': addition})
            delivered, _ = _blocks(''.join(self.text))
            delivered_keys = {_chart_key(block) for block in delivered}
            if not self.generated.keys() <= delivered_keys:
                raise RuntimeError('图表正文交付校验失败')
        self.sink(event)
