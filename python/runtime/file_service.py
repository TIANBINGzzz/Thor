"""输入下载与成果上传共用的部署侧文件服务配置；不向模型暴露地址。"""

import re
from urllib.parse import urlsplit

from runtime.deployment_config import deployment_section


class FileServiceError(ValueError):
    def __init__(self, code, status='failed'):
        """保存文件服务稳定错误码及失败或不确定状态。"""
        self.code, self.status = code, status
        super().__init__(code)


def file_service_config(*, download=False):
    """通过公共配置快照取值；本模块只负责文件字段校验与文件错误码。"""
    config = deployment_section('fileService')
    if not config:
        raise FileServiceError('file_service_not_configured')
    validate_file_service_config(config)
    common = {key: config[key].rstrip('/') for key in ('baseUrl', 'remoteUrl')}
    return {**common, **config['download' if download else 'upload']}


def validate_file_service_config(config):
    """启动与管理保存共用文件服务约束。"""
    try:
        if set(config) != {'baseUrl', 'remoteUrl', 'download', 'upload'}:
            raise ValueError()
        for key in ('baseUrl', 'remoteUrl'):
            url = config[key]
            if not isinstance(url, str) or any(char.isspace() for char in url):
                raise ValueError()
            parsed = urlsplit(url)
            if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                    or parsed.password or parsed.query or parsed.fragment or parsed.port == 0
                    or parsed.path not in ('', '/')):
                raise ValueError()
        for section, limits in (
            ('download', {'maxBytes': 10737418240, 'timeoutMs': None, 'prepareMs': None}),
            ('upload', {'maxBytes': 10737418240, 'timeoutSeconds': 3600, 'connectMs': None}),
        ):
            values = config[section]
            if set(values) != (limits.keys() | ({'path'} if section == 'download' else set())):
                raise ValueError()
            for key, maximum in limits.items():
                number = values[key]
                if type(number) is not int or number < 1 or (maximum and number > maximum):
                    raise ValueError()
        path = config['download']['path']
        if (not isinstance(path, str) or path.count('{fileId}') != 1
                or not re.fullmatch(r'/[A-Za-z0-9_/{\}-]+', path)
                or path.startswith('//') or '{' in path.replace('{fileId}', '')
                or '}' in path.replace('{fileId}', '')):
            raise ValueError()
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise FileServiceError('file_service_config_invalid') from None


def with_run_domain(config, domain_name):
    """把已校验的 Run 域名并入部署路由配置，不读取旧全局域名字段。"""
    if not isinstance(domain_name, str) or len(domain_name) > 253:
        raise FileServiceError('file_service_domain_missing' if not domain_name else 'file_service_config_invalid')
    labels = domain_name.split('.')
    if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
           for label in labels):
        raise FileServiceError('file_service_config_invalid')
    return {**config, 'domainName': domain_name}
