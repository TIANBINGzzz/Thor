"""单元测试显式安装客户快照，不读取本机凭据或配置中心。"""
from pathlib import Path
import yaml


def deployment_document(values=None):
    values = values or {}
    return {'deployment': {'tenantId': 'test-customer'},
        'runtime': yaml.safe_load((Path(__file__).resolve().parents[2] / 'config/nacos-ai-center-agent-service.example.yml')
                                 .read_text(encoding='utf-8'))['runtime'],
        'security': {'runtimeJwtSecret': 'test-runtime-secret'},
        'model': {'baseUrl': values.get('ANTHROPIC_BASE_URL', 'https://model.example.test/anthropic'),
                  'apiKey': values.get('ANTHROPIC_AUTH_TOKEN', 'model-secret')},
        'images': {'baseUrl': values.get('CCSDK_IMAGE_BASE_URL', 'https://images.example.test/v1'),
                   'apiKey': values.get('CCSDK_IMAGE_API_KEY', 'private-image-key'),
                   'model': values.get('CCSDK_IMAGE_MODEL', 'qwen-image-3.0')},
        'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'},
        'businessMcp': {'url': values.get('BUSINESS_MCP_URL', '')}}


def application_document():
    return {'nacos': {'server-addr': 'http://nacos.test:8848', 'namespace': '', 'group': 'DEFAULT_GROUP',
                     'data-id': 'ai-center-agent-service', 'username': '', 'password': '',
                     'timeout-ms': 10000, 'request-timeout-ms': 5000},
            'server': {'host': '127.0.0.1', 'port': 4310, 'run-db': '.scribe-runs/runs.sqlite3'},
            'tools': {'officecli': 'officecli', 'libreoffice': '', 'uno-python': '',
                      'render-image': 'ccsdkscribe-renderer:local'},
            'network': {'http-proxy': '', 'https-proxy': '', 'all-proxy': '', 'no-proxy': 'localhost,127.0.0.1'},
            'diagnostics': {'timing-enabled': False, 'disable-observability': False}}
