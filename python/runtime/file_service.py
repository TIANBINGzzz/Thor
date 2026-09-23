"""输入下载与成果上传共用的部署侧文件服务配置；不向模型暴露地址。"""

import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import yaml

APPLICATION_CONFIG_FILE = Path(__file__).resolve().parents[2] / 'application.yml'


class FileServiceError(ValueError):
    def __init__(self, code, status='failed'):
        self.code, self.status = code, status
        super().__init__(code)


def _response(client, method, url, deadline, **kwargs):
    """限制完整响应大小和持续分块读取；单次阻塞另受网络超时约束。"""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise FileServiceError('file_service_nacos_unavailable')
    with client.stream(method, url, timeout=min(5, remaining), **kwargs) as response:
        body = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() >= deadline or len(body) + len(chunk) > 128 * 1024:
                raise FileServiceError('file_service_nacos_unavailable')
            body.extend(chunk)
        if time.monotonic() >= deadline:
            raise FileServiceError('file_service_nacos_unavailable')
        return httpx.Response(response.status_code, content=bytes(body), request=response.request)


def _nacos_settings(env):
    """按公共文件、本地文件、环境变量顺序覆盖；密钥只从调用方环境获取。"""
    fields = {'server-addr': 'CCSDK_NACOS_URL', 'namespace': 'CCSDK_NACOS_NAMESPACE',
              'group': 'CCSDK_NACOS_GROUP', 'data-id': 'CCSDK_NACOS_DATA_ID'}
    try:
        document = yaml.safe_load(APPLICATION_CONFIG_FILE.read_text(encoding='utf-8'))
        config = document['nacos']
        if (not isinstance(config, dict) or set(config) != set(fields)
                or any(not isinstance(value, str) for value in config.values())):
            raise ValueError()
        local_path = APPLICATION_CONFIG_FILE.with_name('application.local.yml')
        try:
            local_text = local_path.read_text(encoding='utf-8')
        except FileNotFoundError:
            pass
        else:
            local = yaml.safe_load(local_text)['nacos']
            if (not isinstance(local, dict) or not set(local).issubset(fields)
                    or any(not isinstance(value, str) for value in local.values())):
                raise ValueError()
            config.update(local)
        settings = {variable: env.get(variable, config[field]) for field, variable in fields.items()}
        address = settings['CCSDK_NACOS_URL'].strip()
        if address and '://' not in address:
            address = 'http://' + address
        settings['CCSDK_NACOS_URL'] = address
        return settings
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        raise FileServiceError('file_service_nacos_config_invalid') from None


def _fetch_config(env, *, transport=None):
    """只读 Nacos 2.x 配置 API；凭据仅发给 Nacos，不记录响应或回退本地文件。"""
    settings = _nacos_settings(env)
    address = settings['CCSDK_NACOS_URL'].strip().rstrip('/')
    if not address:
        raise FileServiceError('file_service_not_configured')
    try:
        deadline = time.monotonic() + 10
        url = urlsplit(address)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username
                or url.password or url.query or url.fragment or url.port == 0
                or url.path not in ('', '/nacos') or any(c.isspace() for c in address)):
            raise ValueError()
        if not url.path:
            address += '/nacos'
        username = env.get('CCSDK_NACOS_USERNAME', '').strip()
        password = env.get('CCSDK_NACOS_PASSWORD', '')
        if bool(username) != bool(password):
            raise ValueError()
        group = settings['CCSDK_NACOS_GROUP'].strip()
        data_id = settings['CCSDK_NACOS_DATA_ID'].strip()
        if not group or not data_id:
            raise ValueError()
    except ValueError:
        raise FileServiceError('file_service_nacos_config_invalid') from None
    params = {'group': group, 'dataId': data_id}
    namespace = settings['CCSDK_NACOS_NAMESPACE'].strip()
    if namespace and namespace != 'public':
        params['tenant'] = namespace
    try:
        # 内网配置中心直连；不继承模型服务的工作站代理，不跟随认证重定向。
        with httpx.Client(timeout=5, trust_env=False, follow_redirects=False, transport=transport) as client:
            headers = {}
            if username:
                response = _response(client, 'POST', address + '/v1/auth/login', deadline,
                                       data={'username': username, 'password': password})
                response.raise_for_status()
                token = response.json()['accessToken']
                if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                    raise ValueError()
                # Nacos 2.5 支持 Bearer Header，避免 accessToken 出现在 URL/HTTP 日志中。
                headers['Authorization'] = 'Bearer ' + token
            response = _response(client, 'GET', address + '/v1/cs/configs', deadline,
                                 params=params, headers=headers)
            if response.status_code == 404:
                raise FileServiceError('file_service_not_configured')
            response.raise_for_status()
    except FileServiceError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise FileServiceError('file_service_nacos_unavailable') from None
    try:
        value = yaml.safe_load(response.text)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, yaml.YAMLError):
        raise FileServiceError('file_service_config_invalid') from None


def file_service_config(env, *, download=False, transport=None):
    """每次传输从 Nacos 读取独立快照；下载须显式配置含 fileId 的站内路径。"""
    value = _fetch_config(env, transport=transport)
    config = value.get('fileService')
    if not config:
        raise FileServiceError('file_service_not_configured')
    try:
        config = dict(config)
        for key in ('baseUrl', 'remoteUrl'):
            url = config[key]
            if not isinstance(url, str) or url != url.strip() or any(c.isspace() for c in url):
                raise ValueError()
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.port == 0
                    or parsed.path not in ('', '/')):
                raise ValueError()
            config[key] = url.rstrip('/')
        domain = config['domainName']
        if not isinstance(domain, str) or not domain or any(c.isspace() for c in domain) or '/' in domain:
            raise ValueError()
        domain.encode('ascii')
        for key, default, maximum in (('timeoutSeconds', 600, 3600), ('maxFileBytes', 1073741824, 10737418240)):
            config.setdefault(key, default)
            if type(config[key]) is not int or not 1 <= config[key] <= maximum:
                raise ValueError()
        if download:
            path = config['downloadPath']
            if (not isinstance(path, str) or path.count('{fileId}') != 1
                    or not re.fullmatch(r'/[A-Za-z0-9_/{\}-]+', path)
                    or path.startswith('//') or '{' in path.replace('{fileId}', '')
                    or '}' in path.replace('{fileId}', '')):
                raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise FileServiceError('file_service_config_invalid') from None
    return config
