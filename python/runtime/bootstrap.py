"""正式入口：只读完整启动 YAML，再冻结客户 Nacos 配置。"""
from runtime.application_config import load_application, install_application
from runtime.deployment_config import initialize_deployment


def initialize_runtime(*, config_path=None, transport=None):
    """启动及客户配置均拒绝本地叠加和旧 env 覆盖。"""
    document = load_application(config_path)
    result = initialize_deployment(nacos=document['nacos'], transport=transport)
    install_application(document)
    return result


def create_app():
    """支持 uvicorn --factory runtime.bootstrap:create_app；初始化先于 server 导入。"""
    initialize_runtime()
    from server import app
    return app
