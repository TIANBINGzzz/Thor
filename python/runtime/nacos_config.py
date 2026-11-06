"""Nacos 启动配置与 HTTP 读取；不包含能力或业务字段。"""

import time
from urllib.parse import urlsplit

import httpx
import yaml

from runtime.application_config import UniqueKeyLoader, application_settings, validate_nacos


class NacosConfigError(ValueError):
    def __init__(self, code, status='failed'):
        """保存配置中心稳定错误码与状态，不携带响应或凭据。"""
        self.code, self.status = code, status
        super().__init__(code)


def _response(client, method, url, deadline, request_timeout_ms, **kwargs):
    """限制完整响应大小和持续分块读取；单次阻塞另受网络超时约束。"""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise NacosConfigError('nacos_unavailable')
    with client.stream(method, url, timeout=min(request_timeout_ms / 1000, remaining), **kwargs) as response:
        body = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() >= deadline or len(body) + len(chunk) > 128 * 1024:
                raise NacosConfigError('nacos_unavailable')
            body.extend(chunk)
        if time.monotonic() >= deadline:
            raise NacosConfigError('nacos_unavailable')
        return httpx.Response(response.status_code, content=bytes(body), request=response.request)


def _nacos_settings(settings=None):
    """只用显式启动快照或完整 YAML，不读取环境覆盖和 .local 文件。"""
    try:
        config = validate_nacos(settings if settings is not None else application_settings()['nacos'])
        address = config['server-addr']
        config['server-addr'] = address if '://' in address else 'http://' + address
        return config
    except ValueError:
        raise NacosConfigError('nacos_config_invalid') from None


def fetch_config(settings=None, *, transport=None):
    """只读 Nacos 2.x 配置 API；凭据仅发给 Nacos，不记录响应或回退本地文件。"""
    settings = _nacos_settings(settings)
    timeout_ms, request_timeout_ms = settings['timeout-ms'], settings['request-timeout-ms']
    address = settings['server-addr'].strip().rstrip('/')
    if not address:
        raise NacosConfigError('nacos_not_configured')
    try:
        deadline = time.monotonic() + timeout_ms / 1000
        url = urlsplit(address)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.port == 0
                or url.path not in ('', '/nacos') or any(c.isspace() for c in address)):
            raise ValueError()
        if not url.path:
            address += '/nacos'
        username = settings['username'].strip()
        password = settings['password']
        if bool(username) != bool(password):
            raise ValueError()
        group = settings['group'].strip()
        data_id = settings['data-id'].strip()
        if not group or not data_id:
            raise ValueError()
    except ValueError:
        raise NacosConfigError('nacos_config_invalid') from None
    params = {'group': group, 'dataId': data_id}
    namespace = settings['namespace'].strip()
    if namespace and namespace != 'public':
        params['tenant'] = namespace
    try:
        # 内网配置中心直连；不继承模型服务的工作站代理，不跟随认证重定向。
        with httpx.Client(timeout=request_timeout_ms / 1000,
                          trust_env=False, follow_redirects=False, transport=transport) as client:
            headers = {}
            if username:
                response = _response(client, 'POST', address + '/v1/auth/login', deadline, request_timeout_ms,
                                       data={'username': username, 'password': password})
                response.raise_for_status()
                token = response.json()['accessToken']
                if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                    raise ValueError()
                # Nacos 2.5 支持 Bearer Header，避免 accessToken 出现在 URL/HTTP 日志中。
                headers['Authorization'] = 'Bearer ' + token
            response = _response(client, 'GET', address + '/v1/cs/configs', deadline, request_timeout_ms,
                                 params=params, headers=headers)
            if response.status_code == 404:
                raise NacosConfigError('nacos_not_configured')
            response.raise_for_status()
    except NacosConfigError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise NacosConfigError('nacos_unavailable') from None
    try:
        value = yaml.load(response.text, Loader=UniqueKeyLoader)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, yaml.YAMLError):
        raise NacosConfigError('nacos_content_invalid') from None
