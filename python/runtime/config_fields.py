"""数据库列到 Runtime 契约的固定映射；不提供配置默认值。"""

SETTING_SECTIONS = {'runtime': 'runtime', 'files': 'fileService', 'images': 'images', 'security': 'security'}
SETTING_SECRET_KEYS = {
    'images': {'apiKey'},
    'security': {'runtimeJwtSecret', 'observationJwtSecret', 'configurationJwtSecret'},
}


class ConfigurationError(ValueError):
    """只携带字段和错误码，避免秘密进入管理错误响应。"""
    def __init__(self, resource, ref, field, code):
        self.detail = {'resource': resource, 'ref': ref, 'field': field, 'code': code}
        super().__init__(code)


class ConfigurationNotFound(KeyError):
    """区分记录不存在和配置内容缺字段。"""
