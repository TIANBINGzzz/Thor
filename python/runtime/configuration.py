"""将数据库记录装配为现有 Runtime 契约；没有第二套配置来源。"""
import copy
from runtime.config_fields import SETTING_PATHS, CAPABILITY_ASSETS, ConfigurationError


def settings_document(row):
    result = {}
    for field, path in SETTING_PATHS.items():
        value = row[field]
        if value is None: continue
        target = result
        for key in path[:-1]: target = target.setdefault(key, {})
        target[path[-1]] = copy.deepcopy(value)
    return result


def database_document(item):
    tls = {'mode': item['tls_mode']}
    if item['tls_mode'] == 'verify_identity':
        tls.update(ca_file=item['tls_ca_file'], verify_identity=True)
    return {'connection': {**{key:item[key] for key in ('driver','host','port','database','username','password')}, 'tls':tls},
            'access': {'tenantIds': copy.deepcopy(item['tenant_ids'])},
            'query': {'timeout_seconds':item['query_timeout_seconds'], 'max_rows':item['query_max_rows'],
                      'dynamic_sql_enabled':item['dynamic_sql_enabled']}}


def mcp_document(item):
    auth = {'required': item['auth_required']}
    if item['auth_required']:
        if item['auth_injection'] == 'argument': auth['arguments'] = {item['auth_target']: 'platformBearer'}
        else: auth.update(header=item['auth_target'], prefix=item['auth_prefix'])
    return {**copy.deepcopy(item), 'auth': auth}

def read_configuration():
    from runtime.config_store import config_store
    return config_store().load()

def deployment_document(rows, capability_ref='conversation', *, allow_disabled=False):
    document = settings_document(rows['settings']['system'])
    capability = rows['capabilities'].get(capability_ref)
    if capability is None or not capability['enabled'] and not allow_disabled:
        raise ValueError('capability_not_found')
    selected = rows['models'][capability['model_ref']]
    if not selected['enabled'] and not allow_disabled: raise ValueError('model_disabled')
    model = rows['model_connections'][selected['connection_ref']]
    if not model['enabled'] and not allow_disabled: raise ValueError('model_connection_disabled')
    if model['adapter'] != 'anthropic': raise ValueError('model_adapter_unsupported')
    document['model'] = {'baseUrl':model['base_url'], 'apiKey':model['api_key'], 'parameters':model['parameters']}
    name = selected['model_name']
    document['runtime']['models'] = {'default':name, 'available':[name],
                                    'sdk':{key:name for key in ('haiku','sonnet','opus','subagent')}}
    document['runtime']['timeouts']['execution-ms'] = capability['run_timeout_ms']
    document['runtime']['timeouts']['mcp-http-ms'] = capability['tool_timeout_ms']
    document['runtime']['limits']['max-turns'] = capability['max_turns']
    document['databases'] = {}
    for binding in capability['databases']:
        item = rows['database_connections'][binding['ref']]
        if not item['enabled']:
            if binding['required']: raise ValueError('database_connection_disabled')
            continue
        document['databases'][item['ref']] = database_document(item)
    document['_mcp_catalog'] = {}
    for binding in capability['mcps']:
        item = rows['mcp_servers'][binding['ref']]
        if not item['enabled']: raise ValueError('mcp_server_disabled')
        document['_mcp_catalog'][item['ref']] = mcp_document(item)
    # 内部 Service 的连接来自同一 MCP 表，不依赖 Agent 是否可直接调用它。
    for ref in capability['service_refs']:
        item = rows['mcp_servers'].get(ref)
        if item is None or not item['enabled']: raise ValueError('mcp_server_disabled')
        document['_mcp_catalog'][ref] = mcp_document(item)
    for ref,item in document['_mcp_catalog'].items():
        document[ref + 'Mcp'] = {'url':item['url'], **item['parameters'], 'headers':item['headers']}
        if ref == 'campus':
            document[ref+'Mcp']['headers'] = {**item['headers'], 'domain-name':item['parameters']['domainName']}
    return document

def capability_manifest(row, model_name):
    config = {target:copy.deepcopy(row[field]) for field,target in CAPABILITY_ASSETS.items()}
    config.update(execution={'mode':row['execution_mode']}, auth={'required':row['auth_required']})
    runtime = {target:row[field] for field,target in (
        ('runtime_mode','mode'), ('prompt_mode','prompt_mode'), ('system_prompt_snapshot','system_prompt_snapshot'))
        if row[field] is not None}
    thinking = {'type':row['thinking_mode']} if row['thinking_mode'] else None
    if thinking and row['thinking_mode'] == 'enabled': thinking['budget_tokens'] = row['thinking_budget_tokens']
    runtime.update(model=model_name, thinking=thinking, effort=row['effort'],
        timeout_ms=row['run_timeout_ms'], max_turns=row['max_turns'],
        **{key:row[key] for key in ('tool_timeout_ms','max_output_tokens','max_model_calls','max_tool_calls','max_total_tokens')})
    config.update(ref=row['ref'], title=row['name'], description=row['description'],
        supportsAttachments=row['supports_attachments'], runtime=runtime,
        skillRefs=[item['ref'] for item in row['skills']],
        requiredSkillRefs=[item['ref'] for item in row['skills'] if item['required']],
        toolRefs=[*row['tool_refs'], *(item['ref'] for item in row['mcps'])])
    if row['databases']:
        config['data'] = {
            'access':'required' if any(item['required'] for item in row['databases']) else 'optional',
            'sourceRefs':[item['ref'] for item in row['databases']]}
        if row['data_context_topics'] is not None: config['data']['contextTopics'] = row['data_context_topics']
    return config

def execution_entry(ref=None, *, rows=None):
    from runtime.capabilities import CAPABILITIES_ROOT, SKILLS_ROOT, _validate_manifest
    from runtime.deployment_config import configuration_scope
    ref = ref or 'conversation'
    rows = rows if rows is not None else read_configuration()
    document = deployment_document(rows, ref)
    row = rows['capabilities'][ref]
    skills = {}
    for binding in row['skills']:
        skill = rows['skills'][binding['ref']]
        if not skill['enabled']: raise ValueError('skill_disabled')
        skills[skill['ref']] = {'ref':skill['ref'], 'description':skill['description'],
            '_body':skill['content'], 'toolRefs':skill['tool_refs'], 'resources':skill['resources']}
    with configuration_scope(document):
        entry = _validate_manifest(CAPABILITIES_ROOT/ref, capability_manifest(row, rows['models'][row['model_ref']]['model_name']), SKILLS_ROOT,
                                   body=row['prompt'], skills=skills)
    entry['_skills'] = skills
    entry['_mcp_allowlists'] = {item['ref']:item['allowed_tools'] for item in row['mcps']}
    entry['_attachment_policy'] = {field:row['attachment_'+field] for field in
        ('max_files', 'max_bytes', 'allowed_extensions') if row['attachment_'+field] is not None}
    return {'capability':entry, '_configuration':document}

def validate_configuration(rows):
    from pathlib import PurePosixPath
    import re
    from runtime.deployment_config import _validated, _runtime_configuration, _endpoint, validate_database_access
    from runtime.asset_registry import validate_refs
    if set(rows['settings']) != {'system'}:
        raise ValueError('configuration_setting_unknown')
    setting = rows['settings']['system']
    for field, value in setting.items():
        if type(value) is int:
            minimum = 0 if field.startswith('runtime_pool_') else 1
            if value < minimum: raise ConfigurationError('settings','system',field,'value_out_of_range')
    for ref, item in rows['database_connections'].items():
        def invalid(field, code='value_invalid'): raise ConfigurationError('database_connections', ref, field, code)
        if item['driver'] not in ('mysql+pymysql','sqlite'): invalid('driver')
        for field, maximum in (('port',65535),('query_timeout_seconds',120),('query_max_rows',100000)):
            if type(item[field]) is not int or not 1 <= item[field] <= maximum: invalid(field,'value_out_of_range')
        if item['tls_mode'] not in ('verify_identity','disabled'): invalid('tls_mode')
        if item['driver'] == 'mysql+pymysql' and item['tls_mode'] == 'verify_identity' and not item['tls_ca_file']:
            invalid('tls_ca_file','field_required')
        try: validate_database_access({'tenantIds':item['tenant_ids']})
        except ValueError: invalid('tenant_ids')
    for item in rows['model_connections'].values():
        def invalid(field, code): raise ConfigurationError('model_connections',item['ref'],field,code)
        if item['adapter'] != 'anthropic': invalid('adapter','model_adapter_unsupported')
        if not isinstance(item['parameters'],dict): invalid('parameters','object_required')
        try: _endpoint(item, 'base_url')
        except ValueError: invalid('base_url','endpoint_invalid')
        if not isinstance(item['api_key'], str) or not item['api_key']:
            invalid('api_key','model_key_required')
    for ref, item in rows['models'].items():
        def invalid(field, code): raise ConfigurationError('models', ref, field, code)
        if item['connection_ref'] not in rows['model_connections']: invalid('connection_ref','config_reference_missing')
        if not item['name'].strip(): invalid('name','field_required')
        if not item['model_name'] or any(c.isspace() for c in item['model_name']) or '://' in item['model_name']:
            invalid('model_name','model_name_invalid')
        for field, allowed in [('thinking_modes', {'disabled','enabled','adaptive'}),
                               ('effort_options', {'low','medium','high','xhigh','max'})]:
            options = item[field]
            if options is not None and (not isinstance(options,list) or any(not isinstance(v,str) or v not in allowed for v in options)
                                         or len(options) != len(set(options))): invalid(field,'options_invalid')
    for item in rows['skills'].values():
        validate_refs(item['tool_refs'], 'Skill.toolRefs')
        if not all(isinstance(item[key],str) and item[key].strip() for key in ('name','description','content')):
            raise ValueError('skill_content_required')
        if not isinstance(item['resources'], dict): raise ValueError('skill_resource_invalid')
        for name, content in item['resources'].items():
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                    or path.suffix.lower() not in {'.md','.txt','.json','.csv'} or not isinstance(content,str)):
                raise ValueError('skill_resource_invalid')
    for ref, item in rows['mcp_servers'].items():
        if item['enabled']: _endpoint(item, 'url', allow_http=True)
        if not isinstance(item['headers'],dict) or not isinstance(item['parameters'],dict):
            raise ValueError('mcp_parameters_invalid')
        if ref == 'campus' and not item['parameters'].get('domainName'):
            raise ConfigurationError('mcp_servers', ref, 'parameters.domainName', 'field_required')
        def invalid(field): raise ConfigurationError('mcp_servers', ref, field, 'mcp_auth_invalid')
        if not item['auth_required']:
            if item['auth_injection'] != 'none': invalid('auth_injection')
            if item['auth_target'] is not None: invalid('auth_target')
            if item['auth_prefix'] is not None: invalid('auth_prefix')
        else:
            if item['auth_injection'] != ('argument' if ref == 'campus' else 'header'): invalid('auth_injection')
            pattern = r'[A-Za-z_][A-Za-z0-9_]*' if ref == 'campus' else r'[A-Za-z0-9-]+'
            if not isinstance(item['auth_target'],str) or not re.fullmatch(pattern,item['auth_target']): invalid('auth_target')
            if ref != 'campus' and (not isinstance(item['auth_prefix'],str) or any(c in item['auth_prefix'] for c in '\r\n')): invalid('auth_prefix')
            if ref == 'campus' and item['auth_prefix'] is not None: invalid('auth_prefix')
    for row in rows['capabilities'].values():
        def invalid(field, code): raise ConfigurationError('capabilities', row['ref'], field, code)
        model = rows['models'].get(row['model_ref'])
        if model is None: invalid('model_ref', 'config_reference_missing')
        for field in ('attachment_max_files','attachment_max_bytes','run_timeout_ms','tool_timeout_ms',
                      'max_turns','max_model_calls','max_tool_calls','max_total_tokens','max_output_tokens','thinking_budget_tokens'):
            if row[field] is not None and (type(row[field]) is not int or row[field] <= 0): invalid(field,'positive_integer_required')
        for field, allowed in [('thinking_mode',('disabled','enabled','adaptive')), ('effort',('low','medium','high','xhigh','max')),
                               ('execution_mode',('agent','direct')), ('runtime_mode',('query','client')), ('prompt_mode',('default','custom'))]:
            if row[field] is not None and row[field] not in allowed: invalid(field,'option_invalid')
        if (row['thinking_mode'] == 'enabled') != (row['thinking_budget_tokens'] is not None):
            invalid('thinking_budget_tokens','thinking_budget_invalid')
        for field, support in [('thinking_mode','thinking_modes'),('effort','effort_options')]:
            if row[field] is not None and model[support] is not None and row[field] not in model[support]:
                invalid(field,'model_parameter_unsupported')
        extensions = row['attachment_allowed_extensions']
        if extensions is not None and (not isinstance(extensions,list) or any(
                not isinstance(ext,str) or not re.fullmatch(r'\.[a-z0-9]+',ext) for ext in extensions)):
            invalid('attachment_allowed_extensions','extensions_invalid')
        if row['enabled'] and (not model['enabled'] or not rows['model_connections'][model['connection_ref']]['enabled']):
            invalid('model_ref','model_disabled')
        if row['enabled']:
            entry = execution_entry(row['ref'], rows=rows)
            _validated(entry['_configuration'])
            _runtime_configuration(entry['_configuration'])
    baseline = deployment_document(rows, allow_disabled=True)
    baseline['databases'] = {ref:database_document(item)
        for ref,item in rows['database_connections'].items()}
    _validated(baseline)
    _runtime_configuration(baseline)



def configuration_summary(entry):
    """记录本轮实际非秘密内容；不为此引入发布表或保存连接凭据。"""
    capability=entry['capability']
    return {key:copy.deepcopy(capability.get(key)) for key in
        ('ref','title','description','_body','instructions','runtime','_skills','tools','data','_mcp_allowlists')}
