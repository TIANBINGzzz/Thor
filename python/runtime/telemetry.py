"""私有观测基础：进程内计时、SDK 证据筛选与凭据遮盖，不负责存储。"""
import os
import json
import re
import math
import time
import traceback
from pathlib import Path

EVIDENCE_TYPES = {'init', 'thinking', 'tool_use', 'tool_result', 'tool_progress', 'result', 'error', 'diagnostic', 'assistant_turn'}
SENSITIVE = re.compile(r'authorization|credential|password|secret|api.?key|token|cookie|signature', re.I)
TIMING_STAGES = {
    'runtime': {'accepted', 'scheduled', 'assembled', 'enqueued', 'prepare_begin', 'prepared',
                'first_message', 'first_thinking', 'first_text', 'text_stored', 'sse_yield', 'completed'},
    'actor': {'queue_exit', 'prepared', 'worker_ready', 'query_sent', 'first_text', 'completed'},
    'worker_boot': {'imported'},
    'worker_start': {'configured', 'connect_begin', 'connected'},
    'worker_run': {'bound', 'configured', 'query_begin', 'query_sent', 'first_message', 'first_thinking', 'first_text', 'completed'},
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

    anchors = {}
    wall = raw.get('originUnixMs')
    if type(wall) in (int, float) and math.isfinite(wall) and wall > 0:
        anchors = {'originUnixMs': wall, 'clockId': str(raw.get('clockId', ''))[:128]}
    return {**anchors, 'type': 'performance', 'version': 1, 'scope': scope,
            'elapsedMs': numbers(raw.get('elapsedMs'), TIMING_STAGES[scope]),
            'cpuMs': numbers(raw.get('cpuMs'), TIMING_STAGES[scope]),
            'counts': numbers(raw.get('counts'), TIMING_COUNTS),
            **({'live': True} if raw.get('live') is True else {})}


class Timing:
    """同进程单调时钟的首次里程碑；开关在创建时冻结，避免 SDK 隔离环境影响采集。"""

    def __init__(self, scope, *, origin=None, active=None, on_mark=None):
        self.scope = scope
        self.active = (os.environ.get('CCSDK_ENABLE_TIMING') == '1') if active is None else active
        self.origin = (origin or (time.perf_counter(), time.process_time())) if self.active else None
        self.origin_unix_ms = time.time_ns() / 1000000 if self.active else None
        if self.active and origin:
            self.origin_unix_ms -= (time.perf_counter()-origin[0])*1000
        self.clock_id = str(os.getpid())
        self.on_mark = on_mark
        self.elapsed = {}
        self.cpu = {}
        self.counts = {}

    def mark(self, stage):
        if self.active and stage in TIMING_STAGES[self.scope] and stage not in self.elapsed:
            self.elapsed[stage] = round(max(0, time.perf_counter() - self.origin[0]) * 1000, 3)
            self.cpu[stage] = round(max(0, time.process_time() - self.origin[1]) * 1000, 3)
            if self.on_mark:
                try:
                    self.on_mark(stage, self.elapsed[stage])
                except Exception:
                    pass

    def count(self, name, value):
        if self.active and name in TIMING_COUNTS:
            self.counts[name] = value

    def event(self):
        if not self.active:
            return None
        return performance_event({'type': 'performance', 'version': 1, 'scope': self.scope,
                                  'originUnixMs': self.origin_unix_ms, 'clockId': self.clock_id,
                                  'elapsedMs': dict(self.elapsed), 'cpuMs': dict(self.cpu),
                                  'counts': dict(self.counts)})

def exception_event(error, *, scope, secrets=()):
    """异常只保留位置和脱敏消息，不读取局部变量或源代码中的潜在凭据。"""
    root = Path(__file__).resolve().parents[2]
    chain, seen, truncated = [], set(), False
    while error is not None and id(error) not in seen and len(chain) < 5:
        seen.add(id(error))
        frames = []
        stack = list(traceback.walk_tb(error.__traceback__))
        truncated = truncated or len(stack) > 20
        for frame, line in stack[-20:]:
            path = Path(frame.f_code.co_filename)
            try:
                filename = path.resolve().relative_to(root).as_posix()
            except ValueError:
                filename = path.name
            frames.append({'file': filename, 'line': line, 'function': frame.f_code.co_name})
        chain.append({'exceptionType': type(error).__name__, 'message': str(error), 'frames': frames})
        # SDK 的安全包装通过 from 保留原始异常，私有证据须能追溯这一因果链。
        error = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    event = sanitize({'type': 'diagnostic', 'scope': scope, **chain[0], 'causes': chain[1:]}, secrets)
    details = [event, *event['causes']]
    event['scope'] = str(event['scope'])[:128]
    event['truncated'] = truncated or error is not None
    for detail in details:
        detail['exceptionType'] = detail['exceptionType'][:128]
        if len(detail['message']) > 2048:
            detail['message'] = detail['message'][:2048]
            event['truncated'] = True
    # Worker JSONL 的 readline 有 64 KiB 上限；按整条 UTF-8 字节留足余量。
    while len(json.dumps(event, ensure_ascii=False).encode('utf-8')) > 32768:
        event['truncated'] = True
        for detail in details:
            detail['message'] = detail['message'][:len(detail['message']) // 2]
            detail['frames'] = detail['frames'][len(detail['frames']) // 2 + 1:]
    return event

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
