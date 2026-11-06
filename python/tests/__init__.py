"""测试在导入执行模块前显式安装无真实秘密的 Nacos 快照，不访问配置中心。"""
from tests.deployment_fixtures import deployment_document
from runtime.deployment_config import initialize_deployment

initialize_deployment(document=deployment_document())
