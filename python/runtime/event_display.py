"""公共事件显示字典：空名称只隐藏状态提示，不丢弃事件和业务数据。"""

# 精确匹配已登记工具，不从工具参数、命令、模型文字推导对外名称。
TOOL_KEYS = {
    'mcp__data__list_data_sources': 'data.sources',
    'mcp__data__describe_data_source': 'data.describe',
    'mcp__data__resolve_entities': 'data.resolve',
    'mcp__data__find_query_specs': 'data.prepare',
    'mcp__data__execute_query_spec': 'data.query',
    'mcp__data__execute_readonly_sql': 'data.query',
    'mcp__data__read_query_result': 'data.read',
    'mcp__office__officecli': 'document.process',
    'mcp__documents__render': 'document.preview',
    'mcp__documents__read_pdf': 'document.read',
    'mcp__images__generate': 'image.generate',
    'mcp__artifacts__publish_file': 'file.publish',
    'Read': 'file.read',
    'Write': 'file.write',
    'Edit': 'file.edit',
    'Glob': 'file.find',
    'Grep': 'file.search',
    'Bash': 'task.execute',
    'TodoWrite': 'task.plan',
    'Skill': 'task.skill',
}
TOOL_DISPLAY_NAMES = {
    'data.sources': '',
    'data.describe': '了解数据内容',
    'data.resolve': '查找相关对象',
    'data.prepare': '',
    'data.query': '查询业务数据',
    'data.read': '读取查询结果',
    'document.process': '处理文档',
    'document.preview': '生成文档预览',
    'document.read': '阅读文档',
    'image.generate': '生成或编辑图片',
    'file.publish': '提交生成文件',
    'file.read': '读取资料',
    'file.write': '写入文件',
    'file.edit': '修改文件',
    'file.find': '',
    'file.search': '',
    'task.execute': '',
    'task.plan': '',
    'task.skill': '',
    'other': '',
}
PHASE_DISPLAY_NAMES = {
    'queued': '等待处理',
    'preparing_files': '正在准备附件',
    'preparing_file': '正在准备文件',
    'downloading_file': '正在获取文件',
    'validating_file': '正在校验文件',
    'file_ready': '',
    'files_ready': '',
    'model_starting': '正在处理',
    'started': '',
    'thinking': '正在思考',
    'response': '',
    'working': '',
    'saving_files': '正在保存文件',
}
EVENT_DISPLAY_NAMES = {
    'message.delta': '',
    'run.started': '正在处理',
    'run.completed': '已完成',
    'run.failed': '执行失败',
    'run.cancelled': '已停止',
    'artifact.pending': '等待上传',
    'artifact.uploading': '正在上传',
    'artifact.ready': '文件已保存',
    'artifact.failed': '上传失败',
    'artifact.unknown': '上传结果待确认',
}
TOOL_EVENTS = {'tool.started', 'tool.progress', 'tool.finished'}


def with_display_name(event):
    """写入及回放都使用可信字典；旧记录的内部工具名也不能通过SSE泄漏。"""
    payload = dict(event.get('payload') or {})
    payload.pop('toolName', None)
    kind = event.get('type')
    if kind in TOOL_EVENTS:
        key = payload.get('toolKey')
        if key not in TOOL_DISPLAY_NAMES:
            key = 'other'
        payload['toolKey'] = key
        name = TOOL_DISPLAY_NAMES[key]
    elif kind == 'phase':
        name = PHASE_DISPLAY_NAMES.get(payload.get('name'), '')
    else:
        name = EVENT_DISPLAY_NAMES.get(kind, '')
    payload['displayName'] = name
    return {**event, 'payload': payload}


class ToolCallDisplays:
    """工具结果通常不含名称，按Run和调用作用域记住安全标识，结束后释放。"""

    def __init__(self):
        self.runs = {}

    def resolve(self, run_id, raw):
        call = (raw.get('scope') or 'main', raw.get('id'))
        calls = self.runs.setdefault(run_id, {})
        key = calls.get(call)
        if raw.get('type') == 'tool_use' or key is None:
            key = TOOL_KEYS.get(raw.get('name'), 'other')
        if call[1]:
            calls[call] = key
        return {'toolKey': key, 'displayName': TOOL_DISPLAY_NAMES[key]}

    def clear(self, run_id):
        self.runs.pop(run_id, None)
