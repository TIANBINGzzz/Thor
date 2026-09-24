"""部署配置统一取值和引用注入；业务代码不负责连接配置中心。"""

import copy
import os
import re

from runtime import nacos_config

_PATH = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*')


class ConfigReferenceError(ValueError):
    def __init__(self, code):
        """保存配置引用错误码，避免暴露配置内容。"""
        self.code = code
        super().__init__(code)


class ConfigSnapshot:
    """按需读取一次 YAML；values 模式只使用服务端传入的引用快照，禁止联网补值。"""

    def __init__(self, env=None, *, transport=None, values=None):
        """隔离调用方环境与配置副本；传入引用快照时禁用远端补值。"""
        self._env = dict(os.environ if env is None else env) if values is None else {}
        self._transport = transport
        self._offline = values is not None
        self._values = copy.deepcopy(values) if values is not None else {}
        self._document = None

    def get(self, path):
        """按点分路径取值并返回副本；只记录实际使用项，不导出整份远端配置。"""
        if not isinstance(path, str) or not _PATH.fullmatch(path):
            raise ConfigReferenceError('config_reference_invalid')
        if path not in self._values:
            if self._offline:
                raise ConfigReferenceError('config_reference_missing')
            if self._document is None:
                self._document = copy.deepcopy(nacos_config.fetch_config(self._env, transport=self._transport))
            value = self._document
            for key in path.split('.'):
                if not isinstance(value, dict) or key not in value:
                    raise ConfigReferenceError('config_reference_missing')
                value = value[key]
            if value is None:
                raise ConfigReferenceError('config_reference_missing')
            self._values[path] = copy.deepcopy(value)
        if self._values[path] is None:
            raise ConfigReferenceError('config_reference_missing')
        return copy.deepcopy(self._values[path])

    def resolve(self, asset):
        """仅解析可信资产里的完整 ${path} 值；保留原类型，不求值或递归展开远端内容。"""
        if isinstance(asset, dict):
            return {key: self.resolve(value) for key, value in asset.items()}
        if isinstance(asset, list):
            return [self.resolve(value) for value in asset]
        if isinstance(asset, str) and '${' in asset:
            if not asset.startswith('${') or not asset.endswith('}'):
                raise ConfigReferenceError('config_reference_invalid')
            return self.get(asset[2:-1])
        return copy.deepcopy(asset)

    def export(self):
        """导出已选配置项的独立副本，不包含整份远端配置。"""
        return copy.deepcopy(self._values)
