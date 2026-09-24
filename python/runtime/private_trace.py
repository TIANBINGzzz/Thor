"""开发观测事件：独立于公共SSE，只保留SDK实际返回的内容并遮盖凭据。"""
import os
import re

TRACE_TYPES = {'thinking', 'tool_use', 'tool_result', 'tool_progress', 'result', 'error'}
SENSITIVE = re.compile(r'authorization|credential|password|secret|api.?key|token|cookie|signature', re.I)

def enabled():
    """仅在部署环境显式启用时开放私有观测记录。"""
    return os.environ.get('CCSDK_ENABLE_RUN_TRACE', '').strip() == '1'

def sanitize(value, secrets=()):
    """去除结构化凭据与已知凭据原文；保留业务工具参数，二进制与超长文本不入库。"""
    known = tuple(str(v) for k, v in os.environ.items() if SENSITIVE.search(k) and len(str(v)) >= 8)
    known += tuple(str(v) for v in secrets if v)
    def clean(item, depth=0):
        """递归遮盖敏感内容，并限制层级、集合大小和文本长度。"""
        if depth > 24:
            return '[TRUNCATED]'
        if isinstance(item, dict):
            return {str(k): '[REDACTED]' if SENSITIVE.search(str(k)) else clean(v, depth + 1)
                    for k, v in item.items() if str(k) not in {'image', 'image_url', 'base64'}}
        if isinstance(item, (list, tuple)):
            return [clean(v, depth + 1) for v in item[:1000]]
        if isinstance(item, str):
            for secret in known:
                item = item.replace(secret, '[REDACTED]')
            item = re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer [REDACTED]', item)
            item = re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED JWT]', item)
            item = re.sub(r'data:[^;\s]+;base64,[A-Za-z0-9+/=]+', '[BINARY OMITTED]', item)
            return item[:65536] + ('[TRUNCATED]' if len(item) > 65536 else '')
        return item
    return clean(value)
