"""单元测试显式安装客户快照，不读取本机凭据或配置中心。"""
from pathlib import Path
import yaml
from contextlib import contextmanager
from unittest.mock import patch


def deployment_document(values=None):
    values = values or {}
    return {'runtime': __import__('json').loads((Path(__file__).parent / 'fixtures/runtime.json').read_text(encoding='utf-8')),
        'security': {'runtimeJwtSecret': 'test-runtime-secret'},
        'model': {'baseUrl': values.get('ANTHROPIC_BASE_URL', 'https://model.example.test/anthropic'),
                  'apiKey': values.get('ANTHROPIC_AUTH_TOKEN', 'model-secret')},
        'images': {'baseUrl': values.get('CCSDK_IMAGE_BASE_URL', 'https://images.example.test/v1'),
                   'apiKey': values.get('CCSDK_IMAGE_API_KEY', 'private-image-key'),
                   'model': values.get('CCSDK_IMAGE_MODEL', 'qwen-image-3.0')},
        'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'},
        'businessMcp': {'url': values.get('BUSINESS_MCP_URL', '')}}


def application_document():
    return {'config-database': {'host':'db.test','port':3306,'database':'test','username':'test',
            'password':'private-db','encryption-key':'dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHQ=','tls-ca':'','timeout-seconds':10},
            'server': {'host': '127.0.0.1', 'port': 4310, 'run-db': '.scribe-runs/runs.sqlite3'},
            'tools': {'officecli': 'officecli', 'libreoffice': '', 'uno-python': '',
                      'render-image': 'ccsdkscribe-renderer:local'},
            'network': {'http-proxy': '', 'https-proxy': '', 'all-proxy': '', 'no-proxy': 'localhost,127.0.0.1'},
            'diagnostics': {'timing-enabled': False, 'disable-observability': False}}


def configuration_rows():
    import copy, json
    rows = json.loads((Path(__file__).parent/'fixtures/configuration.json').read_text(encoding='utf-8'))
    document = deployment_document()
    rows['settings'] = {'system': settings_row(document)}
    # 数据目录验证仍需要来源声明；无真实业务查询会连接此地址。
    rows['database_connections']['schoolDoubleHigh']['enabled'] = True
    return rows


def settings_row(document):
    from runtime.config_fields import SETTING_PATHS
    result = {'ref':'system'}
    for field, path in SETTING_PATHS.items():
        value = document
        for key in path: value = value.get(key) if isinstance(value,dict) else None
        result[field] = value
    return result


def database_row(ref, value):
    connection = value['connection']
    tls = connection.get('tls',{})
    query = value.get('query',{})
    return {'ref':ref,'name':ref,'enabled':True,
        **{k:connection.get(k, '' if k != 'port' else 3306) for k in ('driver','host','port','database','username','password')},
        'tls_mode':tls.get('mode','verify_identity'),'tls_ca_file':tls.get('ca_file'),
        'tenant_ids':value['access']['tenantIds'],'query_timeout_seconds':query.get('timeout_seconds',30),
        'query_max_rows':query.get('max_rows',10000),'dynamic_sql_enabled':query.get('dynamic_sql_enabled',False)}


@contextmanager
def patch_configuration(document):
    """同一假配置同时供启动读取与逐 Run 数据库读取；生产没有此转换层。"""
    import copy
    def read():
        values = document() if callable(document) else document
        rows = configuration_rows()
        rows['settings'] = {'system':settings_row({'runtime':deployment_document()['runtime'], **values})}
        model = values.get('model')
        if model is not None:
            for row in rows['model_connections'].values():
                row.update(base_url=model.get('baseUrl',''), api_key=model.get('apiKey',''),
                           parameters=model.get('parameters', {}))
        for ref, row in rows['mcp_servers'].items():
            value = values.get(ref+'Mcp')
            if value is not None:
                row.update(url=value.get('url',''), parameters={k:v for k,v in value.items() if k!='url'})
        if 'databases' in values:
            for ref, value in values['databases'].items():
                rows['database_connections'][ref] = database_row(ref, value)
        return rows
    startup = document() if callable(document) else document
    startup = {**deployment_document(), **startup}
    if 'campusMcp' in startup:
        campus = startup['campusMcp']
        campus.setdefault('headers', {'app-key':'test-app-key', 'domain-name':campus['domainName']})
    with patch('runtime.deployment_config._DEPLOYMENT', startup), \
            patch('runtime.configuration.read_configuration', side_effect=read):
        yield


def install_configuration_store():
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from cryptography.fernet import Fernet
    from runtime import config_store as module
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    module.metadata.create_all(engine)
    store = module.ConfigStore(engine, Fernet.generate_key().decode())
    rows = configuration_rows()
    for resource in ('model_connections', 'models', 'skills', 'database_connections', 'mcp_servers', 'settings'):
        items = rows[resource]
        for ref,item in items.items(): store.save(resource,ref,item)
    for ref,item in configuration_rows()['capabilities'].items(): store.save('capabilities',ref,item)
    module._STORE = store
    return store


def fixture_capability_entry(directory, *, skills_root=None):
    import json
    from runtime.capabilities import _validate_manifest, capability_entry
    directory=Path(directory)
    if not (directory/'capability.json').exists():
        return capability_entry(directory)
    return _validate_manifest(directory,json.loads((directory/'capability.json').read_text(encoding='utf-8')),
                              Path(skills_root) if skills_root else directory.parent.parent/'skills')


def fixture_capabilities(root):
    from runtime.capabilities import Capability
    result={}
    for path in Path(root).glob('*/capability.json'):
        entry=fixture_capability_entry(path.parent)
        result[entry['ref']]=Capability(ref=entry['ref'],name=entry['title'],description=entry['description'],
            tools=tuple(entry['tools']),directory=str(path.parent),skill_refs=tuple(entry['skill_refs']))
    return result
