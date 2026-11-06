"""部署配置统一取值和引用注入；业务代码不负责连接配置中心。"""

import copy
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from runtime import nacos_config

_PATH = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*')
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_CONFIG_FILE = PROJECT_ROOT / 'config' / 'application.yml'
_DEPLOYMENT = None
_WORKER = False
WORKER_CONFIGURATION_ENV = 'CCSDK_WORKER_CONFIG_SECRET'


def _merge(base, override):
    """映射逐字段覆盖，标量和列表整体替换；始终返回独立副本。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        result[key] = _merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


def application_document(path=None):
    """部署初始化后只使用启动快照；显式文件路径供离线预算核验使用。"""
    if path is None and _DEPLOYMENT is not None:
        return copy.deepcopy(_DEPLOYMENT)
    path = Path(path) if path is not None else APPLICATION_CONFIG_FILE
    result = {}
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
            result = _merge(result, document)
        return result
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        raise ValueError('application_config_invalid') from None


def deployment_section(name, default=None):
    """仅返回所需客户节点的副本；未初始化不读取旧环境或数据库文件。"""
    return copy.deepcopy((_DEPLOYMENT or {}).get(name, default))


def require_tenant(tenant_id):
    """一部署只接收绑定客户，空值和通配符不能扩大租户范围。"""
    expected = deployment_section('deployment', {}).get('tenantId')
    if not expected or tenant_id != expected:
        raise ValueError('deployment_tenant_mismatch')


def _text(section, field, *, secret=False):
    value = section.get(field)
    if not isinstance(value, str) or not value.strip() or (not secret and value != value.strip()):
        raise ValueError('deployment_config_invalid')
    return value


def _endpoint(section, field, *, allow_http=False):
    value = _text(section, field)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ({'http', 'https'} if allow_http else {'https'})
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.port == 0 or any(c.isspace() for c in value)):
            raise ValueError()
    except ValueError:
        raise ValueError('deployment_config_invalid') from None


def _validated(document, *, worker=False):
    """校验启动必需项和可选秘密，错误不包含配置值。"""
    try:
        if not isinstance(document, dict):
            raise ValueError()
        document = copy.deepcopy(document)
        tenant = _text(document['deployment'], 'tenantId')
        if tenant in {'*', 'self', 'default'}:
            raise ValueError()
        _endpoint(document['model'], 'baseUrl')
        _text(document['model'], 'apiKey', secret=True)
        if not worker:
            security = document['security']
            secret = _text(security, 'runtimeJwtSecret', secret=True)
            for field in ('runtimeJwtIssuer', 'runtimeJwtAudience'):
                if field in security:
                    _text(security, field)
            selected = [secret]
            for field in ('observationJwtSecret', 'assetJwtSecret'):
                if security.get(field):
                    selected.append(_text(security, field, secret=True))
            if len(selected) != len(set(selected)):
                raise ValueError()
        if 'images' in document:
            _endpoint(document['images'], 'baseUrl')
            _text(document['images'], 'apiKey', secret=True)
            _text(document['images'], 'model')
        if not worker and 'fileBroker' in document:
            broker = document['fileBroker']
            _endpoint(broker, 'url')
            hosts = broker.get('allowedHosts', [])
            if (not isinstance(hosts, list) or any(not isinstance(host, str) or not host
                    or any(c.isspace() for c in host) or any(c in host for c in '/?#@') for host in hosts)
                    or broker.get('authMode', 'run_jwt') not in {'run_jwt', 'service'}):
                raise ValueError()
            if broker.get('authMode') == 'service':
                _text(broker, 'serviceToken', secret=True)
            for field in ('serviceToken', 'caFile', 'clientCert', 'clientKey'):
                if field in broker:
                    _text(broker, field, secret=field == 'serviceToken')
            if bool(broker.get('clientCert')) != bool(broker.get('clientKey')):
                raise ValueError()
        if not worker and document.get('fileService') is not None:
            from runtime.file_service import validate_file_service_config
            validate_file_service_config(document['fileService'], download=True)
        if not worker and document.get('campusMcp') is not None:
            campus = document['campusMcp']
            _endpoint(campus, 'url', allow_http=True)
            domain = _text(campus, 'domainName')
            if '/' in domain or any(c.isspace() for c in domain):
                raise ValueError()
            domain.encode('ascii')
        databases = document.get('databases', {})
        if not isinstance(databases, dict):
            raise ValueError()
        for ref, entry in databases.items():
            if (not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,95}', ref)
                    or not isinstance(entry, dict) or set(entry) - {'connection', 'query'}):
                raise ValueError()
            connection = entry['connection']
            allowed = {'driver', 'host', 'port', 'database', 'username', 'password', 'tls'}
            if not isinstance(connection, dict) or set(connection) - allowed:
                raise ValueError()
            if connection.get('driver') not in {'mysql+pymysql', 'sqlite'}:
                raise ValueError()
            _text(connection, 'database')
            if connection['driver'] == 'mysql+pymysql':
                for field in ('host', 'username', 'password'):
                    _text(connection, field, secret=field == 'password')
                port = connection.get('port', 3306)
                if type(port) is not int or not 1 <= port <= 65535:
                    raise ValueError()
                tls = connection.get('tls', {})
                if not isinstance(tls, dict) or set(tls) - {'mode', 'ca_file', 'verify_identity'}:
                    raise ValueError()
                mode = tls.get('mode', 'verify_identity')
                if mode not in {'verify_identity', 'disabled'}:
                    raise ValueError()
                if mode == 'verify_identity':
                    _text(tls, 'ca_file')
                    if tls.get('verify_identity') is not True:
                        raise ValueError()
            query = entry.get('query', {})
            if not isinstance(query, dict) or set(query) - {'timeout_seconds', 'max_rows', 'dynamic_sql_enabled'}:
                raise ValueError()
            for field, maximum in (('timeout_seconds', 120), ('max_rows', 100000)):
                if field in query and (type(query[field]) is not int or not 1 <= query[field] <= maximum):
                    raise ValueError()
            if 'dynamic_sql_enabled' in query and type(query['dynamic_sql_enabled']) is not bool:
                raise ValueError()
        return document
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError('deployment_config_invalid') from None


def initialize_deployment(env=None, *, transport=None, document=None):
    """启动时读取一次 Nacos，校验完成后才原子发布；故障不回退旧秘密或地址。"""
    global _DEPLOYMENT, _WORKER
    defaults = application_document(APPLICATION_CONFIG_FILE)
    if document is None:
        budgets = defaults.get('runtime', {}).get('timeouts', {})
        document = nacos_config.fetch_config(dict(os.environ if env is None else env), transport=transport,
            timeout_ms=budgets.get('nacos-ms', 10000), request_timeout_ms=budgets.get('nacos-request-ms', 5000))
    document = _validated(document)
    runtime = document.get('runtime', {})
    if not isinstance(runtime, dict) or set(runtime) - {'timeouts', 'limits', 'sse-heartbeat-ms',
                                                      'models', 'worker-pool', 'observability'}:
        raise ValueError('deployment_config_invalid')
    document['runtime'] = _merge(defaults.get('runtime', {}), runtime)
    observation = document['runtime'].get('observability', {})
    if (not isinstance(observation, dict) or set(observation) - {'enabled', 'storage', 'max-records',
            'retention-seconds', 'queue-size'} or type(observation.get('enabled')) is not bool
            or not isinstance(observation.get('storage'), str) or not observation['storage'].strip()
            or any(type(observation.get(field)) is not int or observation[field] <= 0
                   for field in ('max-records', 'retention-seconds', 'queue-size'))):
        raise ValueError('deployment_config_invalid')
    from runtime import runtime_settings
    settings = runtime_settings.load_runtime_settings(document=document)
    runtime_settings.load_model_settings(document=document)
    runtime_settings.load_worker_pool_settings(document=document)
    _DEPLOYMENT, _WORKER = document, False
    runtime_settings.RUNTIME_SETTINGS = settings
    return copy.deepcopy(document)


def worker_configuration():
    """只向可信 Worker 提供模型、数据和运行预算；不传控制面或 Nacos 凭据。"""
    if _DEPLOYMENT is None:
        return None
    return {key: copy.deepcopy(_DEPLOYMENT[key]) for key in
            ('deployment', 'runtime', 'model', 'images', 'databases') if key in _DEPLOYMENT}


def install_worker_configuration(document):
    """Worker 导入 SDK 前安装父进程快照，后续不得连接 Nacos 补值。"""
    global _DEPLOYMENT, _WORKER
    if not isinstance(document, dict) or set(document) - {'deployment', 'runtime', 'model', 'images', 'databases'}:
        raise ValueError('worker_config_invalid')
    _DEPLOYMENT = _validated(document, worker=True)
    _WORKER = True


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
        self._document = copy.deepcopy(_DEPLOYMENT)

    def get(self, path):
        """按点分路径取值并返回副本；只记录实际使用项，不导出整份远端配置。"""
        if not isinstance(path, str) or not _PATH.fullmatch(path):
            raise ConfigReferenceError('config_reference_invalid')
        if path not in self._values:
            if self._offline:
                raise ConfigReferenceError('config_reference_missing')
            if self._document is None:
                if _WORKER:
                    raise ConfigReferenceError('config_reference_missing')
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
