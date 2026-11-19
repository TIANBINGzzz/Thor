"""将数据库记录装配为现有 Runtime 契约；没有第二套配置来源。"""
import copy

from runtime.config_fields import SETTING_SECTIONS, ConfigurationError


def setting_value(row):
    return {**copy.deepcopy(row['value']), **(row['secrets'] or {})}


def settings_document(rows):
    return {SETTING_SECTIONS[ref]: setting_value(item) for ref, item in rows.items()
            if (ref != 'files' or item['value']) and (ref != 'images' or item['value'].get('enabled', True) is not False)}


def service_refs_for(row):
    if not row['config'].get('operationRefs'):
        return ()
    from capability_packs.registry import read_pack_manifest
    return tuple(read_pack_manifest(row['ref']).services)


def database_document(item):
    tls = {'mode': item['tls_mode']}
    if item['tls_mode'] == 'verify_identity':
        tls.update(ca_file=item['tls_ca_file'], verify_identity=True)
    return {'connection': {**{key:item[key] for key in ('driver','host','port','database','username','password')}, 'tls':tls},
            'access': {'tenantIds': copy.deepcopy(item['tenant_ids'])},
            'query': {'timeout_seconds':item['query_timeout_seconds'], 'max_rows':item['query_max_rows'],
                      'dynamic_sql_enabled':item['dynamic_sql_enabled']}}


def mcp_document(item):
    config = item['config']
    rule = config.get('auth', {})
    method = rule.get('mode', 'none')
    auth = {'required': method != 'none'}
    if method == 'argument':
        auth['arguments'] = {rule['target']: 'platformBearer'}
    elif method == 'header':
        auth.update(header=rule['target'], prefix=rule['prefix'])
    return {'name': item['name'], 'url': item['url'], 'headers': copy.deepcopy(item['headers']),
            'parameters': copy.deepcopy(config.get('parameters', {})), 'auth': auth}


def read_configuration(capability_ref=None, *, include_security=False):
    from runtime.config_store import config_store
    return config_store().load(capability_ref, include_security=include_security)


def deployment_document(rows, capability_ref='conversation', *, allow_disabled=False):
    capability = rows['capabilities'].get(capability_ref)
    if capability is None or not capability['enabled'] and not allow_disabled:
        raise ValueError('capability_not_found')
    document = settings_document(rows['settings'])
    selected = rows['models'][capability['model_ref']]
    if not selected['enabled'] and not allow_disabled: raise ValueError('model_disabled')
    model = rows['model_connections'][selected['connection_ref']]
    if not model['enabled'] and not allow_disabled: raise ValueError('model_connection_disabled')
    document['model'] = {'baseUrl':model['base_url'], 'apiKey':model['api_key'], 'parameters':model['parameters']}
    name = selected['model_name']
    document['runtime']['models'] = {'default':name, 'available':[name],
                                    'sdk':{key:name for key in ('haiku','sonnet','opus','subagent')}}
    budgets = capability['config']['runtime']
    document['runtime']['timeouts'].update({'execution-ms': budgets['timeout_ms'],
                                            'mcp-http-ms': budgets['tool_timeout_ms']})
    document['runtime']['limits']['max-turns'] = budgets['max_turns']
    document['databases'] = {}
    for binding in capability['databases']:
        item = rows['database_connections'][binding['ref']]
        if not item['enabled']:
            if binding['required']: raise ValueError('database_connection_disabled')
            continue
        document['databases'][item['ref']] = database_document(item)
    document['_mcp_catalog'] = {}
    # 内部 Service 是依赖，不会因此作为 Agent Tool 挂载。
    mcp_refs = [binding['ref'] for binding in capability['mcps']]
    for ref in dict.fromkeys([*mcp_refs, *service_refs_for(capability)]):
        item = rows['mcp_servers'].get(ref)
        if item is None or not item['enabled']:
            raise ValueError('mcp_server_disabled')
        configured = mcp_document(item)
        document['_mcp_catalog'][ref] = configured
        document[ref + 'Mcp'] = {'url': configured['url'], **configured['parameters'],
                                 'headers': configured['headers']}
    return document

def capability_manifest(row, model_name):
    config = copy.deepcopy(row['config'])
    config.pop('attachments', None)
    runtime = config['runtime']
    runtime['model'] = model_name
    config.update(ref=row['ref'], title=row['name'], description=row['description'],
        supportsAttachments=row['supports_attachments'],
        skillRefs=[item['ref'] for item in row['skills']],
        requiredSkillRefs=[item['ref'] for item in row['skills'] if item['required']],
        toolRefs=[*config.get('toolRefs', []), *(item['ref'] for item in row['mcps'])])
    if row['databases']:
        config.setdefault('data', {}).update(
            access='required' if any(item['required'] for item in row['databases']) else 'optional',
            sourceRefs=[item['ref'] for item in row['databases']])
    return config

def execution_entry(ref=None, *, rows=None):
    from runtime.capabilities import CAPABILITIES_ROOT, SKILLS_ROOT, _validate_manifest
    from runtime.deployment_config import configuration_scope
    ref = ref or 'conversation'
    rows = rows if rows is not None else read_configuration(ref)
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
    entry['_attachment_policy'] = copy.deepcopy(row['config'].get('attachments', {}))
    return {'capability':entry, '_configuration':document}

def validate_configuration(rows):
    from pathlib import PurePosixPath
    import re
    from data_access.context import DataError
    from runtime.deployment_config import _validated, _runtime_configuration, _endpoint, validate_database_access
    from runtime.asset_registry import validate_refs
    from runtime.template_assets import template_definition
    if set(rows['settings']) != set(SETTING_SECTIONS):
        raise ValueError('configuration_setting_unknown')
    for ref, fields in {
        'runtime': {'timeouts', 'limits', 'sse-heartbeat-ms', 'worker-pool', 'observability'},
        'files': {'baseUrl', 'remoteUrl', 'download', 'upload'},
        'images': {'enabled', 'baseUrl', 'model'},
        'security': {'runtimeJwtIssuer', 'runtimeJwtAudience'},
    }.items():
        value = rows['settings'][ref]['value']
        if not isinstance(value, dict) or set(value) - fields:
            raise ConfigurationError('settings', ref, 'value', 'setting_fields_invalid')
    images = rows['settings']['images']['value']
    if 'enabled' in images and type(images['enabled']) is not bool:
        raise ConfigurationError('settings', 'images', 'value.enabled', 'boolean_required')
    timeouts = rows['settings']['runtime']['value'].get('timeouts', {})
    if isinstance(timeouts, dict):
        for key, value in timeouts.items():
            if type(value) is not int or value <= 0:
                raise ConfigurationError('settings', 'runtime', f'value.timeouts.{key}', 'positive_integer_required')
    for name in ('timeouts', 'limits'):
        derived = {'execution-ms', 'mcp-http-ms'} if name == 'timeouts' else {'max-turns'}
        section = rows['settings']['runtime']['value'].get(name)
        if not isinstance(section, dict) or derived & section.keys():
            raise ConfigurationError('settings', 'runtime', 'value.' + name, 'setting_fields_invalid')
    security = setting_value(rows['settings']['security'])
    secrets = [security.get(key) for key in ('runtimeJwtSecret', 'observationJwtSecret', 'configurationJwtSecret')]
    configured = [secret for secret in secrets if secret]
    if len(set(configured)) != len(configured):
        raise ConfigurationError('settings', 'security', 'secrets', 'authentication_secret_reused')
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
    from runtime.tool_catalog import TOOL_CATALOG
    from runtime.mcp_transport import validate_http_connection

    for ref, item in rows['mcp_servers'].items():
        def invalid(field, code='mcp_auth_invalid'):
            raise ConfigurationError('mcp_servers', ref, field, code)

        config = item['config']
        if (not isinstance(config, dict) or set(config) - {'auth', 'parameters'}
                or not isinstance(config.get('parameters', {}), dict)
                or set(config.get('parameters', {})) & {'url', 'headers'}):
            invalid('config', 'mcp_parameters_invalid')
        rule = config.get('auth', {})
        if not isinstance(rule, dict):
            invalid('config.auth')
        mode = rule.get('mode', 'none')
        declaration = TOOL_CATALOG.declaration(ref)
        internal = declaration is not None and declaration.implementation == 'capability-pack'
        if (declaration is not None and not internal) or ref == 'capability_ops':
            invalid('ref', 'mcp_ref_reserved')
        if item['url'] or item['enabled']:
            validate_http_connection({'url': item['url'], 'headers': item['headers']})
        allowed = {'mode', 'target'} if internal else {'mode', 'target', 'prefix'}
        if mode == 'none' and not internal and set(rule) <= {'mode'}:
            continue
        if mode != ('argument' if internal else 'header') or set(rule) - allowed:
            invalid('config.auth.mode')
        pattern = r'[A-Za-z_][A-Za-z0-9_]*' if internal else r'[A-Za-z0-9-]+'
        if not isinstance(rule.get('target'), str) or not re.fullmatch(pattern, rule['target']):
            invalid('config.auth.target')
        if not internal and (not isinstance(rule.get('prefix'), str) or any(c in rule['prefix'] for c in '\r\n')):
            invalid('config.auth.prefix')
    for row in rows['capabilities'].values():
        def invalid(field, code): raise ConfigurationError('capabilities', row['ref'], field, code)
        for binding in row['mcps']:
            allowed_tools = binding['allowed_tools']
            if not isinstance(allowed_tools, list) or any(
                    not isinstance(name, str) or (name != '*' and not re.fullmatch(r'[A-Za-z0-9_.-]+', name))
                    for name in allowed_tools):
                invalid('mcps', 'mcp_allowlist_invalid')
        model = rows['models'].get(row['model_ref'])
        if model is None: invalid('model_ref', 'config_reference_missing')
        config = row['config']
        allowed = {'runtime', 'execution', 'attachments', 'toolRefs', 'requiredToolRefs', 'instructions',
                   'instructionRefs', 'operationRefs', 'params', 'templates', 'data', 'auth'}
        if not isinstance(config, dict) or set(config) - allowed:
            invalid('config', 'capability_config_invalid')
        for group, keys in [
            ('data', {'contextTopics'}), ('attachments', {'max_files', 'max_bytes', 'allowed_extensions'}),
        ]:
            value = config.get(group, {})
            if not isinstance(value, dict) or set(value) - keys:
                invalid('config.' + group, 'capability_config_invalid')
        runtime = config.get('runtime')
        if not isinstance(runtime, dict) or 'model' in runtime:
            invalid('config.runtime', 'capability_config_invalid')
        positive = ('timeout_ms', 'tool_timeout_ms', 'max_turns')
        for field in (*positive, 'max_model_calls', 'max_tool_calls', 'max_total_tokens', 'max_output_tokens'):
            value = runtime.get(field)
            if (value is not None or field in positive) and (type(value) is not int or value <= 0):
                invalid('config.runtime.' + field, 'positive_integer_required')
        from runtime.capabilities import _validate_runtime
        try:
            _validate_runtime(runtime)
        except RuntimeError:
            invalid('config.runtime', 'capability_runtime_invalid')
        thinking = runtime.get('thinking')
        for field, value, support in [('thinking', thinking['type'] if thinking else None, 'thinking_modes'),
                                      ('effort', runtime.get('effort'), 'effort_options')]:
            if value is not None and model[support] is not None and value not in model[support]:
                invalid('config.runtime.' + field, 'model_parameter_unsupported')
        attachments = config.get('attachments', {})
        for field in ('max_files', 'max_bytes'):
            if field in attachments and (type(attachments[field]) is not int or attachments[field] <= 0):
                invalid('config.attachments.' + field, 'positive_integer_required')
        extensions = attachments.get('allowed_extensions')
        if 'allowed_extensions' in attachments and (not isinstance(extensions, list) or any(
                not isinstance(ext, str) or not re.fullmatch(r'\.[a-z0-9]+', ext) for ext in extensions)):
            invalid('config.attachments.allowed_extensions', 'extensions_invalid')
        if row['enabled'] and (not model['enabled'] or not rows['model_connections'][model['connection_ref']]['enabled']):
            invalid('model_ref','model_disabled')
        try:
            validate_refs(config.get('templates', []), '模板名单')
        except RuntimeError:
            invalid('config.templates', 'template_refs_invalid')
        if row['enabled']:
            entry = execution_entry(row['ref'], rows=rows)
            for ref in config.get('templates', []):
                try:
                    template_definition(ref, row['ref'], entry['capability'])
                except DataError:
                    invalid('config.templates', 'template_unavailable')
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
        ('ref','title','description','_body','instructions','runtime','_skills','tools','data','_mcp_allowlists','params','templates')}
