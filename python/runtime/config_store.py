"""MySQL 是可编辑执行配置的唯一来源；每次读取使用一个一致性事务。"""
import copy
import json
import re

from cryptography.fernet import Fernet
from sqlalchemy import (Boolean, Column, ForeignKey, Index, Integer, JSON, MetaData,
                        String, Table, Text, UniqueConstraint, URL, create_engine, select, literal, func, union_all)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from runtime.config_fields import SETTING_SECTIONS, SETTING_SECRET_KEYS, ConfigurationError, ConfigurationNotFound

metadata = MetaData()

def table(name, *columns, comment):
    return Table('runtime_' + name, metadata,
                 Column('ref', String(96), primary_key=True, comment='稳定引用标识'),
                 *columns,
                 comment=comment)


TABLES = {
    'model_connections': table('model_connection',
        Column('name', String(160), nullable=False, comment='模型连接显示名称'),
        Column('base_url', String(1024), nullable=False, comment='模型服务基础地址'),
        Column('api_key', Text, nullable=False, comment='模型 API Key 的加密密文'),
        Column('parameters', JSON, nullable=False, comment='模型协议扩展参数（JSON 对象）'),
        Column('enabled', Boolean, nullable=False, comment='是否启用模型连接'),
        comment='SDK 模型服务连接'),
    'models': table('model',
        Column('name', String(160), nullable=False, comment='模型显示名称'),
        Column('connection_ref', String(96), ForeignKey('runtime_model_connection.ref'), nullable=False,
               comment='模型服务连接引用'),
        Column('model_name', String(160), nullable=False, comment='供应商模型标识；同连接内唯一'),
        Column('enabled', Boolean, nullable=False, comment='是否启用模型'),
        Column('sort_order', Integer, nullable=False, comment='模型展示顺序；数值越小越靠前'),
        Column('thinking_modes', JSON, comment='支持的思考模式；NULL 未声明，空数组不接受显式设置'),
        Column('effort_options', JSON, comment='支持的推理强度；NULL 未声明，空数组不接受显式设置'),
        UniqueConstraint('connection_ref', 'model_name'),
        comment='SDK 模型目录及支持的推理选项'),
    'skills': table('skill',
        Column('name', String(160), nullable=False, comment='Skill 显示名称'),
        Column('description', Text, nullable=False, comment='Skill 用途及适用条件'),
        Column('content', Text, nullable=False, comment='Skill 指令正文'),
        Column('tool_refs', JSON, nullable=False, comment='Skill 依赖的工具引用列表'),
        Column('resources', JSON, nullable=False, comment='Skill 相对文件路径到文本内容的映射'),
        Column('enabled', Boolean, nullable=False, comment='是否启用 Skill'),
        comment='SDK 可复用 Skill 指令与文本资源'),
    'database_connections': table('database_connection',
        Column('name', String(160), nullable=False, comment='数据源连接显示名称'),
        Column('driver', String(48), nullable=False, comment='数据库驱动：mysql+pymysql 或 sqlite'),
        Column('host', String(255), nullable=False, comment='数据库主机地址'),
        Column('port', Integer, nullable=False, comment='数据库连接端口'),
        Column('database', String(255), nullable=False, comment='数据库名称或 SQLite 文件路径'),
        Column('username', String(255), nullable=False, comment='数据库连接用户名'),
        Column('password', Text, nullable=False, comment='数据库连接密码的加密密文'),
        Column('tls_mode', String(32), nullable=False, comment='TLS 模式：verify_identity 或 disabled'),
        Column('tls_ca_file', String(1024), comment='TLS CA 文件路径；相对路径以 config 目录为基准'),
        Column('tenant_ids', JSON, nullable=False, comment='允许访问的租户范围；self 从本轮业务 Token 解析'),
        Column('query_timeout_seconds', Integer, nullable=False, comment='单次查询超时（秒）'),
        Column('query_max_rows', Integer, nullable=False, comment='单次查询返回行数上限'),
        Column('dynamic_sql_enabled', Boolean, nullable=False, comment='是否允许受控动态 SQL 查询'),
        Column('enabled', Boolean, nullable=False, comment='是否启用数据源连接'),
        comment='SDK 业务数据源连接、访问范围与查询限制'),
    'mcp_servers': table('mcp_server',
        Column('name', String(160), nullable=False, comment='MCP 服务显示名称'),
        Column('url', String(1024), nullable=False, comment='MCP 服务端点地址'),
        Column('headers', Text, nullable=False, comment='静态请求头 JSON 的加密密文'),
        Column('config', JSON, nullable=False, comment='扩展参数和业务 Token 注入规则'),
        Column('enabled', Boolean, nullable=False, comment='是否启用 MCP 服务'),
        comment='SDK MCP 服务连接与业务凭据注入规则'),
    'knowledge_connections': table('knowledge_connection',
        Column('name', String(160), nullable=False, comment='知识库连接显示名称'),
        Column('provider', String(48), nullable=False, comment='知识库供应商适配器标识'),
        Column('base_url', String(1024), nullable=False, comment='知识库服务地址'),
        Column('tenant_id', String(96), nullable=False, comment='可使用该连接的业务租户；* 表示共享'),
        Column('credentials', Text, nullable=False, comment='供应商只读凭据的加密 JSON'),
        Column('config', JSON, nullable=False, comment='供应商连接参数 JSON'),
        Column('timeout_seconds', Integer, nullable=False, comment='单次请求超时秒数'),
        Column('max_results', Integer, nullable=False, comment='单库检索结果上限'),
        Column('enabled', Boolean, nullable=False, comment='是否启用知识库连接'),
        comment='Runtime 知识库供应商连接及租户边界'),
    'knowledge_purposes': table('knowledge_purpose',
        Column('name', String(160), nullable=False, comment='知识用途显示名称'),
        Column('description', Text, nullable=False, comment='知识用途说明'),
        comment='知识库用途词表'),
    'knowledge_libraries': table('knowledge_library',
        Column('name', String(160), nullable=False, comment='知识库显示名称'),
        Column('connection_ref', String(96), ForeignKey('runtime_knowledge_connection.ref', ondelete='RESTRICT'),
               nullable=False, comment='所属隔离连接'),
        Column('purpose_ref', String(96), ForeignKey('runtime_knowledge_purpose.ref', ondelete='RESTRICT'),
               nullable=False, comment='知识库用途'),
        Column('external_id', String(255), nullable=False, comment='供应商侧知识库标识'),
        Column('config', JSON, nullable=False, comment='库级供应商参数 JSON'),
        Column('enabled', Boolean, nullable=False, comment='是否启用知识库'),
        UniqueConstraint('connection_ref', 'external_id'),
        comment='供应商知识库目录及用途映射'),
    'settings': table('setting',
        Column('value', JSON, nullable=False, comment='按 runtime、files、images、security 分组的配置'),
        Column('secrets', Text, comment='本组秘密的加密密文'),
        comment='SDK 系统设置，每个配置组一行'),
    'capabilities': table('capability',
        Column('name', String(160), nullable=False, comment='业务能力显示名称'),
        Column('description', Text, nullable=False, comment='业务能力用途说明'),
        Column('enabled', Boolean, nullable=False, comment='是否启用业务能力'),
        Column('prompt', Text, nullable=False, comment='能力主提示词正文'),
        Column('supports_attachments', Boolean, nullable=False, comment='是否支持输入附件'),
        Column('model_ref', String(96), ForeignKey('runtime_model.ref'), nullable=False, comment='执行模型目录引用'),
        Column('config', JSON, nullable=False, comment='能力执行策略、模板名单和专属参数'),
        comment='SDK 业务能力、提示词、模型及单 Run 执行预算'),
}
Index('idx_runtime_knowledge_connection_tenant_enabled', TABLES['knowledge_connections'].c.tenant_id,
      TABLES['knowledge_connections'].c.enabled)
Index('idx_runtime_knowledge_library_connection_purpose_enabled',
      TABLES['knowledge_libraries'].c.connection_ref, TABLES['knowledge_libraries'].c.purpose_ref,
      TABLES['knowledge_libraries'].c.enabled)
RELATIONS = {}
for kind, resource in [('skills', 'skills'), ('databases', 'database_connections'), ('mcps', 'mcp_servers')]:
    label = {'skills': 'Skill', 'databases': '数据源连接', 'mcps': 'MCP 服务'}[kind]
    columns = [Column('capability_ref', String(96), ForeignKey('runtime_capability.ref', ondelete='RESTRICT'), primary_key=True,
                      comment='所属业务能力引用'),
               Column('ref', String(96), ForeignKey(TABLES[resource].name + '.ref', ondelete='RESTRICT'), primary_key=True,
                      comment=label + '引用')]
    columns += ([Column('allowed_tools', JSON, nullable=False, comment='允许的 MCP 操作名列表；空数组不授权，* 表示全部')]
                if kind == 'mcps' else
                [Column('required', Boolean, nullable=False,
                        comment='是否必载 Skill 正文' if kind == 'skills' else '是否必需数据源；停用时拒绝执行')])
    if kind == 'skills':
        columns.append(Column('sort_order', Integer, nullable=False, comment='Skill 加载顺序；数值越小越靠前'))
    RELATIONS[kind] = Table('runtime_capability_' + {'skills':'skill','databases':'database','mcps':'mcp'}[kind],
                            metadata, *columns, comment='SDK 业务能力与' + label + '的关联')
knowledge_relation = Table('runtime_capability_knowledge', metadata,
    Column('capability_ref', String(96), ForeignKey('runtime_capability.ref', ondelete='RESTRICT'), primary_key=True,
           comment='所属业务能力引用'),
    Column('ref', String(96), ForeignKey('runtime_knowledge_purpose.ref', ondelete='RESTRICT'), primary_key=True,
           comment='知识用途引用'),
    Column('required', Boolean, nullable=False, comment='是否必须提供该用途知识库'))
RELATIONS['knowledge'] = knowledge_relation
Index('idx_runtime_capability_knowledge_purpose', knowledge_relation.c.ref)

SECRET_FIELDS = {'model_connections': ('api_key',), 'database_connections': ('password',),
                 'knowledge_connections': ('credentials',),
                 'mcp_servers': ('headers',), 'settings': ('secrets',)}
DOCUMENT_FIELDS = {'capabilities': 'config', 'mcp_servers': 'config', 'knowledge_connections': 'config',
                   'knowledge_libraries': 'config', 'settings': 'value'}
OBJECT_FIELDS = {'headers', 'secrets', 'credentials', 'config', 'value'}


def merge_document(old, patch):
    result = dict(old) if isinstance(old, dict) else {}
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = merge_document(result.get(key), value) if isinstance(value, dict) else value
    return result


_STORE = None

def configure_store(config):
    """配置库连接只在父进程持有；模型、数据库和 MCP 秘密按需交给 Worker。"""
    global _STORE
    url = URL.create('mysql+pymysql', username=config['username'], password=config['password'],
                     host=config['host'], port=config['port'], database=config['database'])
    args = {'connect_timeout': config['timeout-seconds'], 'read_timeout': config['timeout-seconds'],
            'write_timeout': config['timeout-seconds'], 'charset': 'utf8mb4'}
    if config['tls-ca']:
        from pathlib import Path
        ca = Path(config['tls-ca'])
        if not ca.is_absolute(): ca = Path(__file__).resolve().parents[2] / 'config' / ca
        args.update(ssl_ca=str(ca), ssl_verify_cert=True, ssl_verify_identity=True)
    engine = create_engine(url, pool_size=4, max_overflow=4, pool_pre_ping=True,
                           isolation_level='REPEATABLE READ', connect_args=args, hide_parameters=True)
    _STORE = ConfigStore(engine, config['encryption-key'])
    return _STORE

def config_store():
    if _STORE is None:
        raise RuntimeError('config_database_not_initialized')
    return _STORE

class ConfigStore:
    def __init__(self, engine, key):
        self.engine = engine
        self.cipher = Fernet(key.encode())
        self.sources = {**TABLES, **{'relation_'+key: value for key, value in RELATIONS.items()}}
        self.queries = {}
        for name, source in self.sources.items():
            fields = []
            for column in source.c:
                value = func.json_extract(column, '$') if isinstance(column.type, JSON) else column
                fields.extend((literal(column.name), value))
            self.queries[name] = select(literal(name).label('resource'), func.json_object(*fields).label('record'))
        self.read_statement = union_all(*self.queries.values())

    def _encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def _decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))

    def _decode(self, resource, row, public=False):
        result = dict(row)
        for field in SECRET_FIELDS.get(resource, ()):
            value = self._decrypt(result[field]) if result[field] is not None else None
            if public and resource == 'settings':
                keys = sorted(SETTING_SECRET_KEYS.get(result['ref'], ()))
                result['secrets'] = {key: None for key in keys} if keys else None
                result['configured_secrets'] = {key: bool((value or {}).get(key)) for key in keys}
            else:
                if public:
                    result.setdefault('configured_secrets', {})[field] = bool(value)
                result[field] = None if public else value
        return result

    def _statement_for(self, ref, service_refs, include_security, tenant_id, include_knowledge):
        owners = {kind: relation.c.capability_ref == ref for kind, relation in RELATIONS.items()}
        related = {kind: select(relation.c.ref).where(owners[kind]) for kind, relation in RELATIONS.items()}
        capability = TABLES['capabilities']
        model = TABLES['models']
        knowledge_connection = TABLES['knowledge_connections']
        knowledge_library = TABLES['knowledge_libraries']
        knowledge_purpose_refs = related['knowledge']
        tenant_scope = knowledge_connection.c.tenant_id.in_((tenant_id, '*')) if include_knowledge else literal(False)
        knowledge_connection_refs = select(knowledge_connection.c.ref).where(
            knowledge_connection.c.enabled, tenant_scope)
        knowledge_library_refs = select(knowledge_library.c.ref).where(
            knowledge_library.c.enabled,
            knowledge_library.c.purpose_ref.in_(knowledge_purpose_refs),
            knowledge_library.c.connection_ref.in_(knowledge_connection_refs))
        selected_knowledge_connections = select(knowledge_library.c.connection_ref).where(
            knowledge_library.c.ref.in_(knowledge_library_refs))
        model_ref = select(capability.c.model_ref).where(capability.c.ref == ref)
        connection_ref = select(model.c.connection_ref).where(model.c.ref.in_(model_ref))
        groups = tuple(SETTING_SECTIONS) if include_security else ('runtime', 'files', 'images')
        filters = {
            'models': model.c.ref.in_(model_ref),
            'model_connections': TABLES['model_connections'].c.ref.in_(connection_ref),
            'settings': TABLES['settings'].c.ref.in_(groups),
            'skills': TABLES['skills'].c.ref.in_(related['skills']),
            'database_connections': TABLES['database_connections'].c.ref.in_(related['databases']),
            'knowledge_purposes': (TABLES['knowledge_purposes'].c.ref.in_(knowledge_purpose_refs)
                                   if include_knowledge else literal(False)),
            'knowledge_connections': knowledge_connection.c.ref.in_(selected_knowledge_connections),
            'knowledge_libraries': knowledge_library.c.ref.in_(knowledge_library_refs),
            'mcp_servers': TABLES['mcp_servers'].c.ref.in_(related['mcps']) | TABLES['mcp_servers'].c.ref.in_(service_refs),
            **{'relation_'+kind: owner for kind, owner in owners.items()},
        }
        return union_all(*(self.queries[name].where(condition) for name, condition in filters.items()))

    def _load(self, connection, ref=None, *, include_security=False, tenant_id=None, include_knowledge=False):
        if include_knowledge and tenant_id is None:
            raise ValueError('knowledge_tenant_required')
        result = {name: {} for name in TABLES}
        statement = self.read_statement
        if ref is not None:
            from runtime.configuration import service_refs_for

            table = TABLES['capabilities']
            row = connection.execute(select(table).where(table.c.ref == ref)).mappings().one_or_none()
            if row is None:
                return result
            result['capabilities'][row['ref']] = dict(row)
            statement = self._statement_for(ref, service_refs_for(row), include_security, tenant_id,
                                            include_knowledge)
        bindings = []
        for resource, record in connection.execute(statement):
            row = json.loads(record) if isinstance(record, str) else record
            if resource.startswith('relation_'):
                bindings.append((resource[9:], row))
            else:
                for column in TABLES[resource].c:
                    if isinstance(column.type, Boolean) and row[column.name] is not None:
                        row[column.name] = bool(row[column.name])
                result[resource][row['ref']] = self._decode(resource, row)
        for capability in result['capabilities'].values():
            for kind in RELATIONS:
                capability[kind] = []
        for kind, item in bindings:
            owner = item.pop('capability_ref')
            if 'required' in item:
                item['required'] = bool(item['required'])
            result['capabilities'][owner][kind].append(item)
        for capability in result['capabilities'].values():
            capability['skills'].sort(key=lambda item: item['sort_order'])
        return result

    def load(self, capability_ref=None, *, include_security=False, tenant_id=None, include_knowledge=None):
        if include_knowledge is None:
            include_knowledge = tenant_id is not None
        if include_knowledge and tenant_id is None:
            raise ValueError('knowledge_tenant_required')
        try:
            with self.engine.begin() as connection:
                return self._load(connection, capability_ref, include_security=include_security,
                                  tenant_id=tenant_id, include_knowledge=include_knowledge)
        except SQLAlchemyError:
            raise RuntimeError('config_database_unavailable') from None

    def capability_summaries(self):
        table = TABLES['capabilities']
        query = select(table.c.ref, table.c.name, table.c.description, table.c.supports_attachments).where(table.c.enabled)
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(query.order_by(table.c.ref)).mappings()]

    def list(self, resource, *, enabled=None, connection_ref=None):
        source = TABLES[resource]
        query = select(source)
        if enabled is not None and 'enabled' in source.c: query = query.where(source.c.enabled == enabled)
        if connection_ref is not None and resource in {'models', 'knowledge_libraries'}:
            query = query.where(source.c.connection_ref == connection_ref)
        query = query.order_by(source.c.sort_order, source.c.ref) if resource == 'models' else query.order_by(source.c.ref)
        with self.engine.connect() as connection:
            return [self._decode(resource, row, public=True) for row in
                    connection.execute(query).mappings()]

    def get(self, resource, ref, *, public=True):
        table = TABLES[resource]
        with self.engine.begin() as connection:
            row = connection.execute(select(table).where(table.c.ref == ref)).mappings().one_or_none()
            if row is None: raise ConfigurationNotFound(ref)
            result = self._decode(resource, row, public=public)
            if resource == 'capabilities':
                for kind, relation in RELATIONS.items():
                    result[kind] = [{k:v for k,v in row.items() if k != 'capability_ref'} for row in
                        connection.execute(select(relation).where(relation.c.capability_ref == ref)).mappings()]
            return result

    def save(self, resource, ref, value, *, validate=None, partial=False):
        """PATCH 只写传入列与关联；同一事务内锁行、校验并提交。"""
        def invalid(field, code): raise ConfigurationError(resource, ref, field, code)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', ref): invalid('ref', 'config_ref_invalid')
        if resource == 'settings' and ref not in SETTING_SECTIONS: invalid('ref', 'configuration_setting_unknown')
        table = TABLES[resource]
        if not isinstance(value, dict): invalid('', 'object_required')
        value = copy.deepcopy(value)
        if value.get('ref', ref) != ref: invalid('ref', 'ref_immutable')
        value.pop('ref', None)
        value.pop('configured_secrets', None)
        relations = {key:value.pop(key) for key in RELATIONS if key in value} if resource == 'capabilities' else {}
        fields = set(table.c.keys()) - {'ref'}
        for field in sorted(set(value) - fields): invalid(field, 'unknown_field')
        if not partial:
            for field in sorted(fields - set(value)): invalid(field, 'field_required')
            if resource == 'capabilities':
                for key in RELATIONS:
                    if key not in relations: invalid(key, 'field_required')
        for field, item in value.items():
            column = table.c[field]
            if item is None:
                if not column.nullable and field not in SECRET_FIELDS.get(resource, ()): invalid(field, 'field_required')
                continue
            expected = bool if isinstance(column.type, Boolean) else int if isinstance(column.type, Integer) else str if isinstance(column.type, (String, Text)) else None
            if field in OBJECT_FIELDS:
                expected = dict
            if expected is not None and type(item) is not expected:
                invalid(field, 'type_invalid')
            if resource == 'settings' and field == 'secrets' and (
                    set(item) - SETTING_SECRET_KEYS.get(ref, set()) or any(
                        entry is not None and (not isinstance(entry, str) or not entry.strip())
                        for entry in item.values())):
                invalid(field, 'setting_secrets_invalid')
            if isinstance(item, str) and getattr(column.type, 'length', None) and len(item) > column.type.length:
                invalid(field, 'too_long')
        try:
            with self.engine.begin() as connection:
                old = connection.execute(select(table).where(table.c.ref == ref).with_for_update()).mappings().one_or_none()
                if partial and old is None: raise ConfigurationNotFound(ref)
                document = DOCUMENT_FIELDS.get(resource)
                if partial and document in value:
                    value[document] = merge_document(old[document], value[document])
                for field in SECRET_FIELDS.get(resource, ()):
                    if field not in value:
                        continue
                    if value[field] is None:
                        value[field] = old[field] if old else None
                    elif resource == 'settings':
                        previous = self._decrypt(old[field]) if old and old[field] else {}
                        secrets = {key: previous.get(key) if entry is None else entry
                                   for key, entry in value[field].items()}
                        if partial:
                            secrets = {**previous, **secrets}
                        value[field] = self._encrypt(secrets) if secrets else None
                    else:
                        value[field] = self._encrypt(value[field])
                # SQLite 测试与 MySQL 使用相同引用语义。
                for field, other in ({'model_ref':'models'} if resource == 'capabilities' else
                                     {'connection_ref':'model_connections'} if resource == 'models' else {}).items():
                    if field in value and not connection.execute(select(TABLES[other].c.ref).where(TABLES[other].c.ref == value[field])).first():
                        invalid(field, 'config_reference_missing')
                if old is None:
                    connection.execute(table.insert().values(ref=ref, **value))
                elif value:
                    connection.execute(table.update().where(table.c.ref == ref).values(**value))
                if resource == 'capabilities':
                    for kind, items in relations.items():
                        if not isinstance(items, list): invalid(kind, 'array_required')
                        relation = RELATIONS[kind]
                        other = TABLES[{'skills':'skills','databases':'database_connections','mcps':'mcp_servers',
                                        'knowledge':'knowledge_purposes'}[kind]]
                        connection.execute(relation.delete().where(relation.c.capability_ref == ref))
                        for item in items:
                            if not isinstance(item, dict) or set(item) != set(relation.c.keys()) - {'capability_ref'}:
                                invalid(kind, 'relation_fields_invalid')
                            if connection.execute(select(other.c.ref).where(other.c.ref == item['ref'])).first() is None:
                                invalid(kind, 'config_reference_missing')
                            connection.execute(relation.insert().values(capability_ref=ref, **item))
                if validate: validate(self._load(connection))
        except IntegrityError:
            invalid('model_name' if resource == 'models' else '', 'config_constraint_invalid')
        return self.get(resource, ref)

    def delete(self, resource, ref):
        table = TABLES[resource]
        with self.engine.begin() as connection:
            if resource == 'mcp_servers':
                from runtime.configuration import service_refs_for
                capability = TABLES['capabilities']
                for row in connection.execute(select(capability.c.ref, capability.c.config)).mappings():
                    if ref in service_refs_for(row):
                        raise ValueError('config_in_use')
            if resource in ('model_connections', 'models'):
                source, field = (TABLES['models'], 'connection_ref') if resource == 'model_connections' else (TABLES['capabilities'], 'model_ref')
                referenced = connection.execute(select(source.c.ref).where(source.c[field] == ref)).first()
                if referenced: raise ValueError('config_in_use')
            for kind, name in [('skills','skills'),('databases','database_connections'),('mcps','mcp_servers'),
                               ('knowledge','knowledge_purposes')]:
                relation = RELATIONS[kind]
                if resource == name and connection.execute(select(relation.c.ref).where(relation.c.ref == ref)).first():
                    raise ValueError('config_in_use')
                if resource == 'capabilities':
                    connection.execute(relation.delete().where(relation.c.capability_ref == ref))
            if resource == 'knowledge_connections' and connection.execute(
                    select(TABLES['knowledge_libraries'].c.ref).where(
                        TABLES['knowledge_libraries'].c.connection_ref == ref)).first():
                raise ValueError('config_in_use')
            if resource == 'knowledge_purposes' and connection.execute(
                    select(TABLES['knowledge_libraries'].c.ref).where(
                        TABLES['knowledge_libraries'].c.purpose_ref == ref)).first():
                raise ValueError('config_in_use')
            connection.execute(table.delete().where(table.c.ref == ref))
