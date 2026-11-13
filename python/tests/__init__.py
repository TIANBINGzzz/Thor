"""测试在导入执行模块前显式安装无真实秘密的 配置库夹具，不访问配置中心。"""
from tests.deployment_fixtures import deployment_document, application_document
from runtime.deployment_config import initialize_deployment
from runtime.application_config import install_application

install_application(application_document())
initialize_deployment(document=deployment_document())

from tests.deployment_fixtures import install_configuration_store
install_configuration_store()
