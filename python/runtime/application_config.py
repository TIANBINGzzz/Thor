"""完整启动 YAML：不合并环境文件，不把配置中心凭据安装到进程环境。"""
import copy
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import yaml

APPLICATION_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'config/application.yml'
FIELDS = {
    'config-database': {'host': str, 'port': int, 'database': str, 'username': str,
                        'password': str, 'encryption-key': str, 'tls-ca': str, 'timeout-seconds': int},
    'server': {'host': str, 'port': int, 'run-db': str},
    'tools': {'officecli': str, 'libreoffice': str, 'uno-python': str, 'render-image': str},
    'network': {'http-proxy': str, 'https-proxy': str, 'all-proxy': str, 'no-proxy': str},
    'diagnostics': {'timing-enabled': bool, 'disable-observability': bool},
}
_APPLICATION = None


class UniqueKeyLoader(yaml.SafeLoader):
    """重复键会隐藏遗漏或错配，必须在解析时拒绝。"""


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError('duplicate_yaml_key')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def is_placeholder(value):
    """拒绝随模板交付的占位值，避免把示例账号或地址当成可部署配置。"""
    return isinstance(value, str) and (value.startswith('replace-') or value == 'customer-example'
        or re.search(r'(?:^|[./])example\.com(?:$|[:/])', value) is not None)


def validate_application(document):
    """所有版本使用同一字段集合；空字符串明确表示可选项自动查找或关闭。"""
    if not isinstance(document, dict) or set(document) != set(FIELDS):
        raise ValueError('application_config_invalid')
    for section, fields in FIELDS.items():
        values = document[section]
        if (not isinstance(values, dict) or set(values) != set(fields)
                or any(type(values[key]) is not kind for key, kind in fields.items())):
            raise ValueError('application_config_invalid')
        if any(isinstance(value, str) and any(c in value for c in '\r\n\x00') for value in values.values()):
            raise ValueError('application_config_invalid')
    database = document['config-database']
    if (not database['host'] or not database['database'] or not database['username']
            or not database['password'] or not 1 <= database['port'] <= 65535
            or database['timeout-seconds'] <= 0 or any(is_placeholder(v) for v in database.values())):
        raise ValueError('application_config_invalid')
    from cryptography.fernet import Fernet
    try:
        Fernet(database['encryption-key'].encode())
    except (ValueError, TypeError):
        raise ValueError('application_config_invalid') from None
    server = document['server']
    if (not server['host'].strip() or any(c.isspace() for c in server['host'])
            or not 1 <= server['port'] <= 65535 or not server['run-db'].strip()
            or not document['tools']['officecli'].strip() or not document['tools']['render-image'].strip()):
        raise ValueError('application_config_invalid')
    for field in ('http-proxy', 'https-proxy', 'all-proxy'):
        value = document['network'][field]
        if value:
            try:
                url = urlsplit(value)
                if (url.scheme not in {'http', 'https'} or not url.hostname or url.port == 0
                        or url.query or url.fragment or url.path not in ('', '/')
                        or any(c.isspace() for c in value)):
                    raise ValueError()
            except ValueError:
                raise ValueError('application_config_invalid') from None
    return copy.deepcopy(document)


def load_application(path=None):
    """只读选定 YAML，路径变量仅允许本机操作系统目录，不展开密码。"""
    try:
        text = Path(path or APPLICATION_CONFIG_FILE).read_text(encoding='utf-8')
        document = validate_application(yaml.load(text, Loader=UniqueKeyLoader))
        for section, fields in (('tools', ('officecli', 'libreoffice', 'uno-python')),
                                ('server', ('run-db',))):
            for field in fields:
                def expand(match):
                    key = match.group(1)
                    if key not in {'LOCALAPPDATA', 'USERPROFILE', 'PROGRAMFILES'} or not os.environ.get(key):
                        raise ValueError()
                    return os.environ[key]
                document[section][field] = re.sub(r'\$\{([^}]+)\}', expand, document[section][field])
        return document
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise ValueError('application_config_invalid') from None


def install_application(document):
    """安装宿主机工具和网络设置；不写入任何 Run 或客户秘密。"""
    global _APPLICATION
    _APPLICATION = validate_application(document)
    mapping = {'CCSDK_OFFICECLI_PATH': ('tools', 'officecli'),
               'CCSDK_LIBREOFFICE_PATH': ('tools', 'libreoffice'),
               'CCSDK_UNO_PYTHON': ('tools', 'uno-python'), 'CCSDK_RENDER_IMAGE': ('tools', 'render-image'),
               'HTTP_PROXY': ('network', 'http-proxy'), 'HTTPS_PROXY': ('network', 'https-proxy'),
               'ALL_PROXY': ('network', 'all-proxy'),
               'NO_PROXY': ('network', 'no-proxy')}
    for key, (section, field) in mapping.items():
        os.environ.pop(key, None)
        os.environ.pop(key.lower(), None)
        if document[section][field]:
            os.environ[key] = document[section][field]
    os.environ['CCSDK_ENABLE_TIMING'] = '1' if document['diagnostics']['timing-enabled'] else '0'
    os.environ.pop('CCSDK_OBSERVABILITY_ENABLED', None)
    if document['diagnostics']['disable-observability']:
        os.environ['CCSDK_OBSERVABILITY_ENABLED'] = '0'


def application_settings():
    """返回已安装启动快照，禁止模块导入时读取其他配置。"""
    if _APPLICATION is None:
        raise ValueError('application_config_not_initialized')
    return copy.deepcopy(_APPLICATION)
