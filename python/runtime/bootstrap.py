"""正式启动入口：本机仅加载引导环境，再冻结客户 Nacos 配置。"""
import os
from pathlib import Path

from dotenv import dotenv_values

from runtime.deployment_config import initialize_deployment


BOOTSTRAP_KEYS = frozenset({'CCSDK_NACOS_URL', 'CCSDK_NACOS_NAMESPACE', 'CCSDK_NACOS_GROUP',
    'CCSDK_NACOS_DATA_ID', 'CCSDK_NACOS_USERNAME', 'CCSDK_NACOS_PASSWORD',
    'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'CCSDK_OFFICECLI_PATH', 'CCSDK_LIBREOFFICE_PATH',
    'CCSDK_UNO_PYTHON', 'CCSDK_RENDER_IMAGE', 'SCRIBE_RUN_DB', 'SCRIBE_PORT'})


def initialize_runtime(*, env=None, transport=None):
    """环境变量优先，本机文件仅补缺引导项；模型/JWT/数据库只从 Nacos 读取。"""
    environment = dict(os.environ if env is None else env)
    root = Path(__file__).resolve().parents[2]
    local = {}
    for path in (root / '.env', root / '.env.local'):
        local.update({key: value for key, value in dotenv_values(path).items()
                      if key in BOOTSTRAP_KEYS and value is not None})
    selected = local | environment
    if env is None:
        for key, value in local.items():
            os.environ.setdefault(key, value)
    return initialize_deployment(selected, transport=transport)


def create_app():
    """支持 uvicorn --factory runtime.bootstrap:create_app；初始化先于 server 导入。"""
    initialize_runtime()
    from server import app
    return app
