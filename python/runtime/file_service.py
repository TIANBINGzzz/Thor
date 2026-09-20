"""输入下载与成果上传共用的部署侧文件服务配置；不向模型暴露地址。"""

import json
import re
from urllib.parse import urlsplit

from data_access.connections import config_path


class FileServiceError(ValueError):
    def __init__(self, code, status='failed'):
        self.code, self.status = code, status
        super().__init__(code)


def file_service_config(env, *, download=False):
    """从数据源配置读取文件服务；下载必须显式配置含 fileId 的站内路径。"""
    try:
        value = json.loads(config_path(env).read_text(encoding='utf-8'))
        config = value.get('fileService')
    except (OSError, ValueError, AttributeError):
        raise FileServiceError('file_service_not_configured') from None
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
