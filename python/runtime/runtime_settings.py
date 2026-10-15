"""部署侧 Runtime 启动参数；不读取 Nacos 或装配业务能力。"""
from dataclasses import dataclass, fields
from pathlib import Path
from types import MappingProxyType
from collections.abc import Mapping

import yaml


APPLICATION_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'config' / 'application.yml'


@dataclass(frozen=True)
class TimeoutSettings:
    execution_ms: int
    client_queue_ms: int
    client_idle_ms: int
    file_prepare_ms: int
    file_broker_ms: int
    file_upload_connect_ms: int
    worker_start_ms: int
    worker_send_ms: int
    worker_close_ms: int
    worker_control_ms: int
    document_render_ms: int
    document_start_ms: int
    image_ms: int
    web_search_ms: int
    mcp_http_ms: int
    nacos_ms: int
    nacos_request_ms: int


@dataclass(frozen=True)
class LimitSettings:
    max_turns: int
    file_max_bytes: int
    sdk_buffer_bytes: int
    http_body_bytes: int
    prompt_bytes: int


@dataclass(frozen=True)
class RuntimeSettings:
    timeouts: TimeoutSettings
    limits: LimitSettings
    sse_heartbeat_ms: int


def load_runtime_settings(path=None):
    """从公共与本地 YAML 读取完整部署预算；缺失、拼错或非法值在启动时失败。"""
    path = Path(path) if path is not None else APPLICATION_CONFIG_FILE
    sections = {'timeouts': TimeoutSettings, 'limits': LimitSettings}
    values = {name: {} for name in sections}
    heartbeat = None
    try:
        for candidate in (path, path.with_name('application.local.yml')):
            try:
                document = yaml.safe_load(candidate.read_text(encoding='utf-8'))
            except FileNotFoundError:
                if candidate == path:
                    raise
                continue
            if not isinstance(document, dict) or not isinstance(document.get('runtime', {}), dict):
                raise ValueError()
            runtime = document.get('runtime', {})
            for name, kind in sections.items():
                section = runtime.get(name, {})
                allowed = {field.name.replace('_', '-') for field in fields(kind)}
                if (not isinstance(section, dict) or set(section) - allowed
                        or any(type(v) is not int or v <= 0 for v in section.values())):
                    raise ValueError()
                values[name].update({k.replace('-', '_'): v for k, v in section.items()})
            if 'sse-heartbeat-ms' in runtime:
                heartbeat = runtime['sse-heartbeat-ms']
                if type(heartbeat) is not int or heartbeat <= 0:
                    raise ValueError()
        if heartbeat is None:
            raise ValueError()
        return RuntimeSettings(**{name: kind(**values[name]) for name, kind in sections.items()},
                               sse_heartbeat_ms=heartbeat)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        raise ValueError('runtime.timeouts / limits / sse-heartbeat-ms 配置无效：须完整声明正整数预算') from None


RUNTIME_SETTINGS = load_runtime_settings()


@dataclass(frozen=True)
class ModelSettings:
    default: str
    available: tuple[str, ...]
    sdk: Mapping[str, str]

    def environment(self):
        """仅为 SDK 子进程生成模型变量，旧宿主环境不参与选模。"""
        return {'ANTHROPIC_MODEL': self.default,
                'ANTHROPIC_DEFAULT_HAIKU_MODEL': self.sdk['haiku'],
                'ANTHROPIC_DEFAULT_SONNET_MODEL': self.sdk['sonnet'],
                'ANTHROPIC_DEFAULT_OPUS_MODEL': self.sdk['opus'],
                'CLAUDE_CODE_SUBAGENT_MODEL': self.sdk['subagent']}


def load_model_settings(path=None):
    """启动时读取明确的模型配置；本地逐字段覆盖，列表整体替换，缺失或非法即失败。"""
    path = Path(path) if path is not None else APPLICATION_CONFIG_FILE
    values = {}
    sdk = {}
    try:
        for candidate in (path, path.with_name('application.local.yml')):
            try:
                document = yaml.safe_load(candidate.read_text(encoding='utf-8'))
            except FileNotFoundError:
                if candidate == path:
                    raise
                continue
            if not isinstance(document, dict) or not isinstance(document.get('runtime', {}), dict):
                raise ValueError()
            runtime = document.get('runtime', {})
            if 'models' not in runtime:
                continue
            models = runtime['models']
            if not isinstance(models, dict) or not models or set(models) - {'default', 'available', 'sdk'}:
                raise ValueError()
            values.update({k: v for k, v in models.items() if k != 'sdk'})
            if 'sdk' in models:
                if not isinstance(models['sdk'], dict):
                    raise ValueError()
                sdk.update(models['sdk'])
        available = values['available']
        if (not isinstance(available, list) or not available
                or any(not isinstance(v, str) or not v.strip() or v != v.strip() for v in available)
                or len(set(available)) != len(available)):
            raise ValueError()
        if (not isinstance(values['default'], str) or values['default'] not in available
                or set(sdk) != {'haiku', 'sonnet', 'opus', 'subagent'}
                or any(not isinstance(v, str) or v not in available for v in sdk.values())):
            raise ValueError()
        return ModelSettings(values['default'], tuple(available), MappingProxyType(sdk))
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
        raise ValueError('runtime.models 配置无效：须声明可用列表、有效默认模型及完整 SDK 映射') from None


@dataclass(frozen=True)
class WorkerPoolSettings:
    max_idle: int = 0
    max_starting: int = 2
    min_available_memory_mib: int = 1024
    max_live: int = 24


def load_worker_pool_settings(path=None):
    """公共 YAML 后叠加本地同名字段；缺省不开池，非法配置在启动时失败。"""
    path = Path(path) if path is not None else APPLICATION_CONFIG_FILE
    values = {}
    fields = {'max-idle': 'max_idle', 'max-starting': 'max_starting',
              'min-available-memory-mib': 'min_available_memory_mib', 'max-live': 'max_live'}
    try:
        for candidate in (path, path.with_name('application.local.yml')):
            try:
                document = yaml.safe_load(candidate.read_text(encoding='utf-8'))
            except FileNotFoundError:
                if candidate == path:
                    raise
                continue
            if not isinstance(document, dict):
                raise ValueError()
            runtime = document.get('runtime', {})
            if not isinstance(runtime, dict):
                raise ValueError()
            pool = runtime.get('worker-pool', {})
            if not isinstance(pool, dict) or set(pool) - fields.keys():
                raise ValueError()
            for key, value in pool.items():
                minimum = 1 if key == 'max-starting' else 0
                if type(value) is not int or value < minimum:
                    raise ValueError()
                values[fields[key]] = value
        settings = WorkerPoolSettings(**values)
        if settings.max_live and settings.max_idle > settings.max_live:
            raise ValueError()
        return settings
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        raise ValueError('runtime.worker-pool 配置无效') from None
