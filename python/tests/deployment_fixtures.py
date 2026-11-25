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
        'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test',
                      'headers': {'app-key': 'test-app-key', 'domain-name': 'campus.example.test'}},
        '_mcp_catalog': {'campus': campus_connection()}}


def application_document():
    return {'config-database': {'host':'db.test','port':3306,'database':'test','username':'test',
            'password':'private-db','encryption-key':'dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHR0dHQ=','tls-ca':'','timeout-seconds':10},
            'server': {'host': '127.0.0.1', 'port': 4310, 'run-db': '.scribe-runs/runs.sqlite3'},
            'tools': {'officecli': 'officecli', 'libreoffice': '', 'uno-python': '',
                      'render-image': 'ccsdkscribe-renderer:local'},
            'network': {'http-proxy': '', 'https-proxy': '', 'all-proxy': '', 'no-proxy': 'localhost,127.0.0.1'},
            'diagnostics': {'timing-enabled': False, 'disable-observability': False}}


def configuration_rows():
    import json
    rows = json.loads((Path(__file__).parent/'fixtures/configuration.json').read_text(encoding='utf-8'))
    rows['knowledge_connections'] = {}
    rows['knowledge_purposes'] = {}
    rows['knowledge_libraries'] = {}
    for capability in rows['capabilities'].values():
        capability['knowledge'] = []
    document = deployment_document()
    rows['settings'] = settings_rows(document)
    # 数据目录验证仍需要来源声明；无真实业务查询会连接此地址。
    rows['database_connections']['schoolDoubleHigh']['enabled'] = True
    return rows


def settings_rows(document):
    from copy import deepcopy
    from runtime.config_fields import SETTING_SECTIONS, SETTING_SECRET_KEYS
    result = {}
    for ref, section in SETTING_SECTIONS.items():
        value = deepcopy(document.get(section, {}))
        secrets = {key: value.pop(key) for key in SETTING_SECRET_KEYS.get(ref, ()) if key in value}
        if ref == 'runtime':
            value.pop('models')
            value['limits'].pop('max-turns')
            for name in ('execution-ms', 'mcp-http-ms'):
                value['timeouts'].pop(name)
        result[ref] = {'ref': ref, 'value': value, 'secrets': secrets or None}
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
    def read(*args, **kwargs):
        values = document() if callable(document) else document
        rows = configuration_rows()
        rows['settings'] = settings_rows({'runtime': deployment_document()['runtime'], **values})
        model = values.get('model')
        if model is not None:
            for row in rows['model_connections'].values():
                row.update(base_url=model.get('baseUrl',''), api_key=model.get('apiKey',''),
                           parameters=model.get('parameters', {}))
        for ref, row in rows['mcp_servers'].items():
            value = values.get(ref+'Mcp')
            if value is not None:
                row.update(url=value['url'], headers={'app-key': 'test-app-key', 'domain-name': value['domainName']})
        if 'databases' in values:
            for ref, value in values['databases'].items():
                rows['database_connections'][ref] = database_row(ref, value)
        return rows
    startup = document() if callable(document) else document
    startup = {**deployment_document(), **startup}
    if 'campusMcp' in startup:
        campus = startup['campusMcp']
        campus.setdefault('headers', {'app-key':'test-app-key', 'domain-name':campus['domainName']})
    startup['_mcp_catalog'] = {**startup.get('_mcp_catalog', {}), 'campus': campus_connection()}
    with patch('runtime.deployment_config._DEPLOYMENT', startup), \
            patch('runtime.configuration.read_configuration', side_effect=read):
        yield


def campus_connection():
    return {'auth': {'required': True, 'arguments': {'user_context_token': 'platformBearer'}}}


def campus_assets(settings=None, *, directory=None, params=None, operations=None):
    from runtime.capabilities import CAPABILITIES_ROOT
    from runtime.deployment_config import ConfigSnapshot
    from capability_packs.registry import load_pack
    ref = 'campus-brain-query'
    pack = load_pack(ref)
    return pack.load_service_assets('campus', settings or ConfigSnapshot(), directory or CAPABILITIES_ROOT / ref,
                                    pack.service_assets['campus'], operations or pack.operations,
                                    params or {'max_calls': 10, 'minimum_schools': 12})


def file_settings(base_url='https://files.test', remote_url='https://public.test', path='/file/{fileId}/download'):
    return {'baseUrl': base_url, 'remoteUrl': remote_url,
            'download': {'path': path, 'maxBytes': 268435456, 'timeoutMs': 15000, 'prepareMs': 600000},
            'upload': {'maxBytes': 1073741824, 'timeoutSeconds': 600, 'connectMs': 10000}}


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
    from runtime.asset_registry import validate_refs
    from runtime.capabilities import _validate_manifest, capability_entry
    from runtime.prompt_documents import read_documents
    directory=Path(directory)
    if not (directory/'capability.json').exists():
        return capability_entry(directory)
    manifest = json.loads((directory/'capability.json').read_text(encoding='utf-8'))
    skill_root = Path(skills_root) if skills_root else directory.parent.parent/'skills'
    skills = {}
    for ref in validate_refs(manifest.get('skillRefs', []), 'skillRefs'):
        skill_dir = skill_root/ref
        skills[ref] = {**json.loads((skill_dir/'skill.json').read_text(encoding='utf-8')),
                       '_body': read_documents(skill_dir, ['SKILL.md'], asset_root=skill_root)[0]['text'].strip()}
    body = read_documents(directory, ['CAPABILITY.md'])[0]['text'].strip()
    return _validate_manifest(directory, manifest, body=body, skills=skills)


def fixture_capabilities(root):
    from runtime.capabilities import Capability
    result={}
    for path in Path(root).glob('*/capability.json'):
        entry=fixture_capability_entry(path.parent)
        result[entry['ref']]=Capability(ref=entry['ref'],name=entry['title'],description=entry['description'],
            tools=tuple(entry['tools']),directory=str(path.parent),skill_refs=tuple(entry['skill_refs']))
    return result
