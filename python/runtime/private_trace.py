"""开发观测事件：独立于公共SSE，只保留SDK实际返回的内容并遮盖凭据。"""
import os
import re
import math
import time

TRACE_TYPES = {'thinking', 'tool_use', 'tool_result', 'tool_progress', 'result', 'error'}
SENSITIVE = re.compile(r'authorization|credential|password|secret|api.?key|token|cookie|signature', re.I)
TIMING_STAGES = {
    'runtime': {'accepted', 'scheduled', 'assembled', 'enqueued', 'prepare_begin', 'prepared',
                'first_message', 'first_thinking', 'first_text', 'text_stored', 'sse_yield', 'completed'},
    'actor': {'queue_exit', 'prepared', 'worker_ready', 'query_sent', 'first_text', 'completed'},
    'worker_boot': {'imported'},
    'worker_start': {'configured', 'connect_begin', 'connected'},
    'worker_run': {'bound', 'query_begin', 'query_sent', 'first_message', 'first_thinking', 'first_text', 'completed'},
}
TIMING_COUNTS = {'worker_created', 'worker_reused', 'pool_hit', 'rebuilt'}


def performance_event(raw):
    """计时事件只允许已登记阶段和有限数值，拒绝正文、凭据及任意扩展字段。"""
    scope = raw.get('scope')
    if raw.get('type') != 'performance' or raw.get('version') != 1 or not isinstance(scope, str) or scope not in TIMING_STAGES:
        return None

    def numbers(value, names):
        if not isinstance(value, dict):
            return {}
        return {k: v for k, v in value.items() if k in names and type(v) in (int, float)
                and math.isfinite(v) and v >= 0}

    return {'type': 'performance', 'version': 1, 'scope': scope,
            'elapsedMs': numbers(raw.get('elapsedMs'), TIMING_STAGES[scope]),
            'cpuMs': numbers(raw.get('cpuMs'), TIMING_STAGES[scope]),
            'counts': numbers(raw.get('counts'), TIMING_COUNTS)}


class Timing:
    """同进程单调时钟的首次里程碑；开关在创建时冻结，避免 SDK 隔离环境影响采集。"""

    def __init__(self, scope, *, origin=None, active=None):
        self.scope = scope
        self.active = enabled() if active is None else active
        self.origin = (origin or (time.perf_counter(), time.process_time())) if self.active else None
        self.elapsed = {}
        self.cpu = {}
        self.counts = {}

    def mark(self, stage):
        if self.active and stage in TIMING_STAGES[self.scope] and stage not in self.elapsed:
            self.elapsed[stage] = round(max(0, time.perf_counter() - self.origin[0]) * 1000, 3)
            self.cpu[stage] = round(max(0, time.process_time() - self.origin[1]) * 1000, 3)

    def count(self, name, value):
        if self.active and name in TIMING_COUNTS:
            self.counts[name] = value

    def event(self):
        if not self.active:
            return None
        return performance_event({'type': 'performance', 'version': 1, 'scope': self.scope,
                                  'elapsedMs': dict(self.elapsed), 'cpuMs': dict(self.cpu),
                                  'counts': dict(self.counts)})

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
