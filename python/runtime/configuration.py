"""将数据库记录装配为现有 Runtime 契约；没有第二套配置来源。"""
import copy

def read_configuration():
    from runtime.config_store import config_store
    return config_store().load()

def deployment_document(rows, capability_ref='conversation', *, allow_disabled=False):
    document = {key:copy.deepcopy(row['value']) for key,row in rows['settings'].items()}
    capability = rows['capabilities'].get(capability_ref)
    if capability is None or not capability['enabled'] and not allow_disabled:
        raise ValueError('capability_not_found')
    model = rows['model_connections'][capability['model_connection_ref']]
    if not model['enabled'] and not allow_disabled: raise ValueError('model_connection_disabled')
    if model['adapter'] != 'anthropic': raise ValueError('model_adapter_unsupported')
    document['model'] = {'baseUrl':model['base_url'], 'apiKey':model['api_key'], 'parameters':model['parameters']}
    name = capability['model_name']
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
        document['databases'][item['ref']] = {
            'connection':{key:item[key] for key in ('driver','host','port','database','username','password','tls')},
            'access':item['access'], 'query':item['query']}
    document['_mcp_catalog'] = {}
    for binding in capability['mcps']:
        item = rows['mcp_servers'][binding['ref']]
        if not item['enabled']: raise ValueError('mcp_server_disabled')
        document['_mcp_catalog'][item['ref']] = item
    # 内部 Service 的连接来自同一 MCP 表，不依赖 Agent 是否可直接调用它。
    for ref in capability['config'].get('serviceRefs', []):
        item = rows['mcp_servers'].get(ref)
        if item is None or not item['enabled']: raise ValueError('mcp_server_disabled')
        document['_mcp_catalog'][ref] = item
    for ref,item in document['_mcp_catalog'].items():
        document[ref + 'Mcp'] = {'url':item['url'], **item['parameters'], 'headers':item['headers']}
        if ref == 'campus':
            document[ref+'Mcp']['headers'] = {**item['headers'], 'domain-name':item['parameters']['domainName']}
    return document

def capability_manifest(row):
    config = copy.deepcopy(row['config'])
    runtime = config.pop('runtime', {})
    runtime.update(model=row['model_name'], thinking=row['thinking'], effort=row['effort'],
        timeout_ms=row['run_timeout_ms'], max_turns=row['max_turns'],
        **{key:row[key] for key in ('tool_timeout_ms','max_output_tokens','max_model_calls','max_tool_calls','max_total_tokens')})
    config.update(ref=row['ref'], title=row['name'], description=row['description'],
        supportsAttachments=row['supports_attachments'], runtime=runtime,
        skillRefs=[item['ref'] for item in row['skills']],
        requiredSkillRefs=[item['ref'] for item in row['skills'] if item['required']],
        toolRefs=[*row['tool_refs'], *(item['ref'] for item in row['mcps'])])
    if row['databases']:
        config['data'] = {**config.get('data', {}),
            'access':'required' if any(item['required'] for item in row['databases']) else 'optional',
            'sourceRefs':[item['ref'] for item in row['databases']]}
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
        entry = _validate_manifest(CAPABILITIES_ROOT/ref, capability_manifest(row), SKILLS_ROOT,
                                   body=row['prompt'], skills=skills)
    entry['_skills'] = skills
    entry['_mcp_allowlists'] = {item['ref']:item['allowed_tools'] for item in row['mcps']}
    entry['_attachment_policy'] = row['attachment_policy']
    return {'capability':entry, '_configuration':document}

def validate_configuration(rows):
    from pathlib import PurePosixPath
    import re
    from runtime.deployment_config import _validated, _runtime_configuration, _endpoint
    from runtime.asset_registry import validate_refs
    if set(rows['settings']) - {'security', 'images', 'fileService', 'runtime'}:
        raise ValueError('configuration_setting_unknown')
    baseline = deployment_document(rows, allow_disabled=True)
    baseline['databases'] = {ref:{'connection':{key:item[key] for key in
        ('driver','host','port','database','username','password','tls')},'access':item['access'],'query':item['query']}
        for ref,item in rows['database_connections'].items()}
    _validated(baseline)
    _runtime_configuration(baseline)
    for item in rows['model_connections'].values():
        if item['adapter'] != 'anthropic' or not isinstance(item['parameters'], dict):
            raise ValueError('model_adapter_unsupported')
        _endpoint(item, 'base_url')
        if not isinstance(item['api_key'], str) or not item['api_key']:
            raise ValueError('model_key_required')
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
        auth = item['auth']
        if not isinstance(auth,dict) or type(auth.get('required')) is not bool:
            raise ValueError('mcp_auth_invalid')
        expected = {'required'} if not auth['required'] else ({'required','arguments'} if ref=='campus' else {'required','header','prefix'})
        if set(auth) != expected: raise ValueError('mcp_auth_invalid')
        if auth['required']:
            if ref == 'campus':
                if not auth['arguments'] or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) or v!='platformBearer' for k,v in auth['arguments'].items()):
                    raise ValueError('mcp_auth_invalid')
            elif not re.fullmatch(r'[A-Za-z0-9-]+',auth['header']) or not isinstance(auth['prefix'],str) or any(c in auth['prefix'] for c in '\r\n'):
                raise ValueError('mcp_auth_invalid')
    for row in rows['capabilities'].values():
        policy = row['attachment_policy']
        if not isinstance(policy,dict) or set(policy)-{'max_files','max_bytes','allowed_extensions'}:
            raise ValueError('attachment_policy_invalid')
        for key in ('max_files','max_bytes'):
            if key in policy and (type(policy[key]) is not int or policy[key]<=0):
                raise ValueError('attachment_policy_invalid')
        if 'allowed_extensions' in policy and (not isinstance(policy['allowed_extensions'],list) or any(
                not isinstance(ext,str) or not re.fullmatch(r'\.[a-z0-9]+',ext) for ext in policy['allowed_extensions'])):
            raise ValueError('attachment_policy_invalid')
        if row['enabled']:
            entry = execution_entry(row['ref'], rows=rows)
            _validated(entry['_configuration'])
            _runtime_configuration(entry['_configuration'])


def configuration_summary(entry):
    """记录本轮实际非秘密内容；不为此引入发布表或保存连接凭据。"""
    capability=entry['capability']
    return {key:copy.deepcopy(capability.get(key)) for key in
        ('ref','title','description','_body','instructions','runtime','_skills','tools','data','_mcp_allowlists')}
