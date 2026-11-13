"""MySQL 是可编辑执行配置的唯一来源；每次读取使用一个一致性事务。"""
import copy
import json
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, JSON, MetaData,
                        String, Table, Text, UniqueConstraint, URL, create_engine, select, literal, func, union_all)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from runtime.config_fields import SETTING_PATHS, CAPABILITY_ASSETS, ConfigurationError, ConfigurationNotFound

metadata = MetaData()

def table(name, *columns):
    return Table('ccsdk_' + name, metadata, Column('ref', String(96), primary_key=True),
                 *columns,
                 Column('updated_at', DateTime, nullable=False))

TABLES = {
    'model_connections': table('model_connection', Column('name', String(160), nullable=False),
        Column('base_url', String(1024), nullable=False), Column('adapter', String(32), nullable=False),
        Column('api_key', Text, nullable=False), Column('parameters', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'models': table('model', Column('name', String(160), nullable=False),
        Column('connection_ref', String(96), ForeignKey('ccsdk_model_connection.ref'), nullable=False),
        Column('model_name', String(160), nullable=False), Column('enabled', Boolean, nullable=False),
        Column('sort_order', Integer, nullable=False), Column('thinking_modes', JSON), Column('effort_options', JSON),
        UniqueConstraint('connection_ref', 'model_name')),
    'skills': table('skill', Column('name', String(160), nullable=False),
        Column('description', Text, nullable=False), Column('content', Text, nullable=False),
        Column('tool_refs', JSON, nullable=False), Column('resources', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'database_connections': table('database_connection', Column('name', String(160), nullable=False),
        Column('driver', String(48), nullable=False), Column('host', String(255), nullable=False),
        Column('port', Integer, nullable=False), Column('database', String(255), nullable=False),
        Column('username', String(255), nullable=False), Column('password', Text, nullable=False),
        Column('tls_mode', String(32), nullable=False), Column('tls_ca_file', String(1024)),
        Column('tenant_ids', JSON, nullable=False), Column('query_timeout_seconds', Integer, nullable=False),
        Column('query_max_rows', Integer, nullable=False), Column('dynamic_sql_enabled', Boolean, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'mcp_servers': table('mcp_server', Column('name', String(160), nullable=False),
        Column('url', String(1024), nullable=False), Column('headers', Text, nullable=False),
        Column('auth_required', Boolean, nullable=False), Column('auth_injection', String(16), nullable=False),
        Column('auth_target', String(160)), Column('auth_prefix', String(160)),
        Column('parameters', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'settings': table('setting', *[
        Column(name, Boolean if name.endswith('_enabled') else
               Text if name.endswith(('_secret', '_api_key')) else
               String(1024) if name.endswith(('_url', '_path', '_storage', '_model', '_issuer', '_audience')) else BigInteger,
               nullable=not name.startswith('runtime_')) for name in SETTING_PATHS],
        CheckConstraint("ref = 'system'")),
    'capabilities': table('capability', Column('name', String(160), nullable=False),
        Column('description', Text, nullable=False), Column('enabled', Boolean, nullable=False),
        Column('prompt', Text, nullable=False), Column('supports_attachments', Boolean, nullable=False),
        Column('attachment_max_files', Integer), Column('attachment_max_bytes', BigInteger),
        Column('attachment_allowed_extensions', JSON),
        Column('model_ref', String(96), ForeignKey('ccsdk_model.ref'), nullable=False),
        Column('thinking_mode', String(16)), Column('thinking_budget_tokens', Integer),
        Column('effort', String(16)), Column('max_output_tokens', Integer),
        Column('run_timeout_ms', Integer, nullable=False), Column('tool_timeout_ms', Integer, nullable=False),
        Column('max_turns', Integer, nullable=False), Column('max_model_calls', Integer),
        Column('max_tool_calls', Integer), Column('max_total_tokens', BigInteger),
        Column('tool_refs', JSON, nullable=False), Column('execution_mode', String(16), nullable=False),
        Column('runtime_mode', String(16)), Column('prompt_mode', String(16)),
        Column('system_prompt_snapshot', Boolean), Column('auth_required', Boolean, nullable=False),
        Column('data_context_topics', JSON), *[Column(name, JSON, nullable=False) for name in CAPABILITY_ASSETS]),
}
RELATIONS = {}
for kind, resource in [('skills', 'skills'), ('databases', 'database_connections'), ('mcps', 'mcp_servers')]:
    columns = [Column('capability_ref', String(96), ForeignKey('ccsdk_capability.ref'), primary_key=True),
               Column('ref', String(96), ForeignKey(TABLES[resource].name + '.ref'), primary_key=True)]
    columns += ([Column('allowed_tools', JSON, nullable=False)] if kind == 'mcps' else
                [Column('required', Boolean, nullable=False)])
    if kind == 'skills': columns.append(Column('sort_order', Integer, nullable=False))
    RELATIONS[kind] = Table('ccsdk_capability_' + {'skills':'skill','databases':'database','mcps':'mcp'}[kind], metadata, *columns)

SECRET_FIELDS = {'model_connections': ('api_key',), 'database_connections': ('password',),
                 'mcp_servers': ('headers',), 'settings': ('image_api_key', 'auth_runtime_jwt_secret',
                 'auth_observation_jwt_secret', 'auth_configuration_jwt_secret')}
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
        # 一个 SQL 往返取得同一时点的配置，避免每张小表一次跨网查询。
        queries = []
        for name, source in {**TABLES, **{'relation_'+k:v for k,v in RELATIONS.items()}}.items():
            fields = []
            for column in source.c:
                if column.name == 'updated_at': continue
                value = func.json_extract(column, '$') if isinstance(column.type, JSON) else column
                fields.extend((literal(column.name), value))
            queries.append(select(literal(name).label('resource'), func.json_object(*fields).label('record')))
        self.read_statement = union_all(*queries)

    def _encrypt(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def _decrypt(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))

    def _decode(self, resource, row, public=False):
        result = dict(row)
        result.pop('updated_at', None)
        for field in SECRET_FIELDS.get(resource, ()):
            value = self._decrypt(result[field]) if result[field] is not None else None
            if public: result.setdefault('configured_secrets', {})[field] = bool(value)
            result[field] = None if public else value
        return result

    def _load(self, connection):
        result = {name:{} for name in TABLES}
        bindings = []
        for resource, record in connection.execute(self.read_statement):
            row = json.loads(record) if isinstance(record, str) else record
            if resource.startswith('relation_'):
                bindings.append((resource[9:], row))
            else:
                for column in TABLES[resource].c:
                    if isinstance(column.type, Boolean) and row[column.name] is not None:
                        row[column.name] = bool(row[column.name])
                result[resource][row['ref']] = self._decode(resource, row)
        for capability in result['capabilities'].values():
            for kind in RELATIONS: capability[kind] = []
        for kind, item in bindings:
            owner = item.pop('capability_ref')
            if 'required' in item: item['required'] = bool(item['required'])
            result['capabilities'][owner][kind].append(item)
        for capability in result['capabilities'].values():
            capability['skills'].sort(key=lambda item: item['sort_order'])
        return result

    def load(self):
        try:
            with self.engine.begin() as connection:
                return self._load(connection)
        except SQLAlchemyError:
            raise RuntimeError('config_database_unavailable') from None

    def list(self, resource, *, enabled=None, connection_ref=None):
        source = TABLES[resource]
        query = select(source)
        if enabled is not None and 'enabled' in source.c: query = query.where(source.c.enabled == enabled)
        if connection_ref is not None and resource == 'models': query = query.where(source.c.connection_ref == connection_ref)
        query = query.order_by(source.c.sort_order, source.c.ref) if resource == 'models' else query.order_by(source.c.ref)
        with self.engine.connect() as connection:
            return [self._decode(resource, row, public=True) for row in
                    connection.execute(query).mappings()]

    def get(self, resource, ref):
        table = TABLES[resource]
        with self.engine.begin() as connection:
            row = connection.execute(select(table).where(table.c.ref == ref)).mappings().one_or_none()
            if row is None: raise ConfigurationNotFound(ref)
            result = self._decode(resource, row, public=True)
            if resource == 'capabilities':
                for kind, relation in RELATIONS.items():
                    result[kind] = [{k:v for k,v in row.items() if k != 'capability_ref'} for row in
                        connection.execute(select(relation).where(relation.c.capability_ref == ref)).mappings()]
            return result

    def save(self, resource, ref, value, *, validate=None, partial=False):
        """PATCH 只写传入列与关联；同一事务内锁行、校验并提交。"""
        def invalid(field, code): raise ConfigurationError(resource, ref, field, code)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', ref): invalid('ref', 'config_ref_invalid')
        if resource == 'settings' and ref != 'system': invalid('ref', 'configuration_setting_unknown')
        table = TABLES[resource]
        if not isinstance(value, dict): invalid('', 'object_required')
        value = copy.deepcopy(value)
        if value.get('ref', ref) != ref: invalid('ref', 'ref_immutable')
        value.pop('ref', None)
        value.pop('configured_secrets', None)
        relations = {key:value.pop(key) for key in RELATIONS if key in value} if resource == 'capabilities' else {}
        fields = set(table.c.keys()) - {'ref', 'updated_at'}
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
            if field == 'headers': expected = dict
            if expected is not None and type(item) is not expected: invalid(field, 'type_invalid')
            if isinstance(item, str) and getattr(column.type, 'length', None) and len(item) > column.type.length:
                invalid(field, 'too_long')
        try:
            with self.engine.begin() as connection:
                old = connection.execute(select(table).where(table.c.ref == ref).with_for_update()).mappings().one_or_none()
                if partial and old is None: raise ConfigurationNotFound(ref)
                for field in SECRET_FIELDS.get(resource, ()):
                    if field in value:
                        value[field] = old[field] if value[field] is None and old else self._encrypt(value[field])
                # SQLite 测试与 MySQL 使用相同引用语义。
                for field, other in ({'model_ref':'models'} if resource == 'capabilities' else
                                     {'connection_ref':'model_connections'} if resource == 'models' else {}).items():
                    if field in value and not connection.execute(select(TABLES[other].c.ref).where(TABLES[other].c.ref == value[field])).first():
                        invalid(field, 'config_reference_missing')
                values = {**value, 'updated_at':datetime.now(timezone.utc).replace(tzinfo=None)}
                if old: connection.execute(table.update().where(table.c.ref == ref).values(**values))
                else: connection.execute(table.insert().values(ref=ref, **values))
                if resource == 'capabilities':
                    for kind, items in relations.items():
                        if not isinstance(items, list): invalid(kind, 'array_required')
                        relation = RELATIONS[kind]
                        other = TABLES[{'skills':'skills','databases':'database_connections','mcps':'mcp_servers'}[kind]]
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
                for services in connection.execute(select(TABLES['capabilities'].c.service_refs)).scalars():
                    if ref in services: raise ValueError('config_in_use')
            if resource in ('model_connections', 'models'):
                source, field = (TABLES['models'], 'connection_ref') if resource == 'model_connections' else (TABLES['capabilities'], 'model_ref')
                referenced = connection.execute(select(source.c.ref).where(source.c[field] == ref)).first()
                if referenced: raise ValueError('config_in_use')
            for kind, name in [('skills','skills'),('databases','database_connections'),('mcps','mcp_servers')]:
                relation = RELATIONS[kind]
                if resource == name and connection.execute(select(relation.c.ref).where(relation.c.ref == ref)).first():
                    raise ValueError('config_in_use')
                if resource == 'capabilities':
                    connection.execute(relation.delete().where(relation.c.capability_ref == ref))
            connection.execute(table.delete().where(table.c.ref == ref))
