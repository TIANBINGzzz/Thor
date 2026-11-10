"""公共事件显示字典与按 Run 合并的业务阶段；正文、文件和终态独立传递。"""

from runtime.tool_catalog import display_key

# 精确匹配已登记工具，不从工具参数、命令、模型文字推导对外名称。
NATIVE_TOOL_KEYS = {'Read': 'file.read', 'Write': 'file.write', 'Edit': 'file.edit', 'Glob': 'file.find', 'Grep': 'file.search', 'Bash': 'task.execute', 'TodoWrite': 'task.plan', 'Skill': 'task.skill'}
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
    'chart.generate': '生成图表',
    'file.publish': '提交生成文件',
    'file.read': '读取资料',
    'file.write': '写入文件',
    'file.edit': '修改文件',
    'file.find': '',
    'file.search': '',
    'task.execute': '',
    'task.plan': '',
    'task.skill': '',
    'capability.operation': '执行能力操作',
    'web.search': '正在联网搜索',
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
    'model_starting': '正在思考',
    'started': '',
    'response': '',
    'working': '',
    'saving_files': '正在保存文件',
}
EVENT_DISPLAY_NAMES = {
    'message.delta': '',
    'run.started': '',
    'run.completed': '已完成',
    'run.failed': '执行失败',
    'run.cancelled': '已停止',
    'steering.accepted': '补充要求已接收',
    'steering.delivered': '补充要求已发送',
    'steering.applied': '补充要求已纳入会话',
    'steering.rejected': '补充要求未发送',
    'steering.unknown': '补充要求状态待确认',
    'artifact.pending': '等待上传',
    'artifact.uploading': '正在上传',
    'artifact.ready': '文件已保存',
    'artifact.failed': '上传失败',
    'artifact.unknown': '上传结果待确认',
}
TOOL_EVENTS = {'tool.started', 'tool.progress', 'tool.finished'}
FAILURE_MESSAGES = {
    'worker_memory_pressure': '服务器可用内存不足，暂时无法处理请求，请联系管理员释放内存后重试。',
    'worker_capacity_exceeded': '服务已达到并发处理上限，请等待其他任务结束后重试。',
    'run_queue_timeout': '请求排队等待超时，请稍后重试。',
    'worker_start_timeout': '处理进程启动超时，请稍后重试；持续失败请联系管理员。',
    'sdk_connection_timeout': '模型服务连接超时，请稍后重试；持续失败请联系管理员检查连接。',
    'sdk_connection_error': '模型服务连接失败，请稍后重试；持续失败请联系管理员检查连接。',
    'worker_send_timeout': '处理进程通信超时，请重试；持续失败请联系管理员。',
    'worker_exited': '处理进程意外退出，本次处理已中断，请重试；持续失败请联系管理员。',
    'worker_unavailable': '处理进程不可用，请重试；持续失败请联系管理员。',
    'worker_error': '处理进程异常，本次处理未完成，请重试；持续失败请联系管理员。',
    'worker_control_error': '处理进程控制失败，请重试；持续失败请联系管理员。',
    'worker_cleanup_error': '处理进程释放失败，暂时无法继续处理，请联系管理员。',
    'sdk_configuration_error': '模型服务配置无效，请联系管理员检查配置。',
    'configuration_error': '执行配置不完整或无效，请联系管理员检查配置。',
    'sdk_execution_error': '模型执行失败，本次回答未完成，请重试；持续失败请联系管理员。',
    'sdk_error': '模型服务异常，本次回答未完成，请重试；持续失败请联系管理员。',
    'sdk_cleanup_error': '模型会话收尾失败，本次处理未能正常结束，请重试；持续失败请联系管理员。',
    'session_actor_closed': '处理会话已关闭，请重新发起请求。',
    'session_actor_failed': '处理会话异常，请重新发起请求；持续失败请联系管理员。',
    'run_preparation_failed': '请求准备失败，尚未开始生成回答，请重试；持续失败请联系管理员。',
    'file_download_failed': '附件下载失败，请确认文件可用后重试；持续失败请联系管理员。',
    'file_download_timeout': '附件下载超时，请稍后重试，或缩小附件后重新上传。',
    'file_download_unavailable': '附件服务不可用，请联系管理员检查文件服务。',
    'file_download_configuration_error': '附件服务配置无效，请联系管理员检查配置。',
    'file_access_denied': '附件访问被拒绝，请确认文件访问权限后重新选择附件。',
    'file_validation_failed': '附件校验失败，请检查文件名称、大小及内容后重新上传。',
    'upstream_service_error': '查询服务暂时不可用，请稍后重试。',
    'timeout': '本次处理超时，请稍后重试。',
    'sdk_timeout': '本次处理超时，请稍后重试。',
    'nacos_unavailable': '服务暂时不可用，请稍后重试。',
    'mcp_authentication_error': '业务服务授权不可用，请重新登录；仍失败时请联系管理员。',
}


def with_display_name(event):
    """写入及回放都使用可信字典；旧记录的内部工具名也不能通过SSE泄漏。"""
    payload = dict(event.get('payload') or {})
    payload.pop('toolName', None)
    kind = event.get('type')
    if kind == 'run.failed':
        # 回放也覆盖旧消息，供应商及异常正文不能成为公共错误文案。
        payload['message'] = FAILURE_MESSAGES.get(payload.get('code'), '本次处理未能完成，请稍后重试。')
    if kind in TOOL_EVENTS:
        key = payload.get('toolKey')
        if key not in TOOL_DISPLAY_NAMES:
            key = 'other'
        payload['toolKey'] = key
        name = TOOL_DISPLAY_NAMES[key]
    elif kind == 'phase':
        if payload.get('name') == 'working':
            key = payload.get('toolKey')
            if key not in TOOL_DISPLAY_NAMES:
                key = 'other'
            payload['toolKey'] = key
            name = TOOL_DISPLAY_NAMES[key]
        else:
            name = PHASE_DISPLAY_NAMES.get(payload.get('name'), '')
    else:
        name = EVENT_DISPLAY_NAMES.get(kind, '')
    payload['displayName'] = name
    return {**event, 'payload': payload}


class RunStatusDisplays:
    """工具生命周期只进观测；公共提示保持到下一业务阶段，不回退到思考。"""

    def __init__(self):
        self.runs = {}
        self.thinking_started = set()

    def project(self, event):
        """合并纯状态提示；带文件进度的数据事件不得因同名而丢失。"""
        kind = event['type']
        if kind in TOOL_EVENTS:
            if kind != 'tool.started':
                return None
            event = with_display_name({**event, 'type': 'phase', 'payload': {
                'name': 'working', 'toolKey': event['payload']['toolKey']}})
        if event['type'] == 'phase':
            payload = event['payload']
            if payload.get('name') == 'model_starting' and event['runId'] in self.thinking_started:
                return None
            if set(payload) <= {'name', 'toolKey', 'displayName'}:
                name = payload['displayName']
                if not name or name == self.runs.get(event['runId']):
                    return None
        return event

    def remember(self, event):
        """只跟踪已落盘事件；终态清理，不影响其他 Run。"""
        run_id = event['runId']
        if event['type'] in {'run.started', 'run.completed', 'run.failed', 'run.cancelled'}:
            self.clear(run_id)
        elif event.get('payload', {}).get('displayName'):
            self.runs[run_id] = event['payload']['displayName']
            if event['type'] == 'phase' and event['payload'].get('name') in {'model_starting', 'working'}:
                self.thinking_started.add(run_id)

    def clear(self, run_id):
        self.runs.pop(run_id, None)
        self.thinking_started.discard(run_id)


class ToolCallDisplays:
    """工具结果通常不含名称，按Run和调用作用域记住安全标识，结束后释放。"""

    def __init__(self):
        """初始化按 Run 隔离的工具调用显示标识缓存。"""
        self.runs = {}

    def resolve(self, run_id, raw):
        """按 Run 和调用作用域关联可信显示名称，未知工具使用默认标识。"""
        call = (raw.get('scope') or 'main', raw.get('id'))
        calls = self.runs.setdefault(run_id, {})
        key = calls.get(call)
        if raw.get('type') == 'tool_use' or key is None:
            key = NATIVE_TOOL_KEYS.get(raw.get('name'), display_key(raw.get('name')))
            if key not in TOOL_DISPLAY_NAMES:
                key = 'other'
        if call[1]:
            calls[call] = key
        return {'toolKey': key, 'displayName': TOOL_DISPLAY_NAMES[key]}

    def clear(self, run_id):
        """释放指定 Run 的工具显示缓存，不影响其他 Run。"""
        self.runs.pop(run_id, None)
