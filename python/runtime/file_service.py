"""输入下载与成果上传共用的部署侧文件服务配置；不向模型暴露地址。"""

import re
from urllib.parse import urlsplit

from runtime.deployment_config import ConfigSnapshot, ConfigReferenceError
from runtime.nacos_config import NacosConfigError


class FileServiceError(ValueError):
    def __init__(self, code, status='failed'):
        """保存文件服务稳定错误码及失败或不确定状态。"""
        self.code, self.status = code, status
        super().__init__(code)


def file_service_config(env, *, download=False, transport=None):
    """通过公共配置快照取值；本模块只负责文件字段校验与文件错误码。"""
    try:
        config = ConfigSnapshot(env, transport=transport).get('fileService')
    except ConfigReferenceError:
        raise FileServiceError('file_service_not_configured') from None
    except NacosConfigError as error:
        code = {'nacos_not_configured': 'file_service_not_configured',
                'nacos_content_invalid': 'file_service_config_invalid'}.get(error.code, 'file_service_' + error.code)
        raise FileServiceError(code) from None
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
