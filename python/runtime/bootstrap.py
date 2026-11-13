"""正式入口：启动 YAML 只负责连接配置库及宿主机参数。"""
from runtime.application_config import load_application, install_application
from runtime.deployment_config import initialize_deployment
from runtime.config_store import configure_store


def initialize_runtime(*, config_path=None):
    document = load_application(config_path)
    install_application(document)
    configure_store(document['config-database'])
    return initialize_deployment()


def create_app():
    initialize_runtime()
    from server import app
    return app
