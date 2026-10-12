"""部署侧 Runtime 启动参数；不读取 Nacos 或装配业务能力。"""
from dataclasses import dataclass
from pathlib import Path

import yaml


APPLICATION_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'config' / 'application.yml'


@dataclass(frozen=True)
class WorkerPoolSettings:
    max_idle: int = 0
    max_starting: int = 2
    min_available_memory_mib: int = 1024


def load_worker_pool_settings(path=None):
    """公共 YAML 后叠加本地同名字段；缺省不开池，非法配置在启动时失败。"""
    path = Path(path) if path is not None else APPLICATION_CONFIG_FILE
    values = {}
    fields = {'max-idle': 'max_idle', 'max-starting': 'max_starting',
              'min-available-memory-mib': 'min_available_memory_mib'}
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
        return WorkerPoolSettings(**values)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        raise ValueError('runtime.worker-pool 配置无效') from None
