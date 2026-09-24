"""输入下载与成果上传共用的部署侧文件服务配置；不向模型暴露地址。"""

import re
from urllib.parse import urlsplit

from runtime.nacos_config import NacosConfigError, fetch_config


class FileServiceError(ValueError):
    def __init__(self, code, status='failed'):
        self.code, self.status = code, status
        super().__init__(code)


def _fetch_config(env, *, transport=None):
    # 公共配置中心错误在文件边界映射为既有文件事件错误码。
    try:
        return fetch_config(env, transport=transport)
    except NacosConfigError as error:
        code = {'nacos_not_configured': 'file_service_not_configured',
                'nacos_content_invalid': 'file_service_config_invalid'}.get(error.code, 'file_service_' + error.code)
        raise FileServiceError(code) from None


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
