"""MySQL 是可编辑执行配置的唯一来源；每次读取使用一个一致性事务。"""
import copy
import json
import re
from datetime import datetime, timezone

from cryptography.fernet import Fernet
from sqlalchemy import (Boolean, Column, DateTime, ForeignKey, Integer, JSON, MetaData,
                        String, Table, Text, URL, create_engine, select, literal, func, union_all)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

metadata = MetaData()

def table(name, *columns):
    return Table('scribe_' + name, metadata, Column('ref', String(96), primary_key=True),
                 *columns,
                 Column('updated_at', DateTime, nullable=False))

TABLES = {
    'model_connections': table('model_connection', Column('name', String(160), nullable=False),
        Column('base_url', String(1024), nullable=False), Column('adapter', String(32), nullable=False),
        Column('api_key', Text, nullable=False), Column('parameters', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'skills': table('skill', Column('name', String(160), nullable=False),
        Column('description', Text, nullable=False), Column('content', Text, nullable=False),
        Column('tool_refs', JSON, nullable=False), Column('resources', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'database_connections': table('database_connection', Column('name', String(160), nullable=False),
        Column('driver', String(48), nullable=False), Column('host', String(255), nullable=False),
        Column('port', Integer, nullable=False), Column('database', String(255), nullable=False),
        Column('username', String(255), nullable=False), Column('password', Text, nullable=False),
        Column('tls', JSON, nullable=False), Column('access', JSON, nullable=False),
        Column('query', JSON, nullable=False), Column('enabled', Boolean, nullable=False)),
    'mcp_servers': table('mcp_server', Column('name', String(160), nullable=False),
        Column('url', String(1024), nullable=False), Column('headers', Text, nullable=False),
        Column('auth', JSON, nullable=False), Column('parameters', JSON, nullable=False),
        Column('enabled', Boolean, nullable=False)),
    'settings': table('setting', Column('value', JSON, nullable=False)),
    'capabilities': table('capability', Column('name', String(160), nullable=False),
        Column('description', Text, nullable=False), Column('enabled', Boolean, nullable=False),
        Column('prompt', Text, nullable=False), Column('supports_attachments', Boolean, nullable=False),
        Column('attachment_policy', JSON, nullable=False),
        Column('model_connection_ref', String(96), ForeignKey('scribe_model_connection.ref'), nullable=False),
        Column('model_name', String(160), nullable=False), Column('thinking', JSON),
        Column('effort', String(16)), Column('max_output_tokens', Integer),
        Column('run_timeout_ms', Integer, nullable=False), Column('tool_timeout_ms', Integer, nullable=False),
        Column('max_turns', Integer, nullable=False), Column('max_model_calls', Integer),
        Column('max_tool_calls', Integer), Column('max_total_tokens', Integer),
        Column('tool_refs', JSON, nullable=False), Column('config', JSON, nullable=False)),
}
RELATIONS = {}
for kind, resource in [('skills', 'skills'), ('databases', 'database_connections'), ('mcps', 'mcp_servers')]:
    columns = [Column('capability_ref', String(96), ForeignKey('scribe_capability.ref'), primary_key=True),
               Column('ref', String(96), ForeignKey(TABLES[resource].name + '.ref'), primary_key=True)]
    columns += ([Column('allowed_tools', JSON, nullable=False)] if kind == 'mcps' else
                [Column('required', Boolean, nullable=False)])
    if kind == 'skills': columns.append(Column('sort_order', Integer, nullable=False))
    RELATIONS[kind] = Table('scribe_capability_' + {'skills':'skill','databases':'database','mcps':'mcp'}[kind], metadata, *columns)

SECRET_FIELDS = {'model_connections': ('api_key',), 'database_connections': ('password',), 'mcp_servers': ('headers',)}
SECRET_KEY = re.compile(r'password|secret|api.?key|authorization', re.I)
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

    def _settings(self, value, mode, previous=None):
        if isinstance(value, dict):
            if set(value) == {'$secret'}:
                return None if mode == 'public' else self._decrypt(value['$secret'])
            return {k: ({'$secret': self._encrypt((previous or {}).get(k) if v is None else v)}
                        if mode == 'write' and SECRET_KEY.search(k) else
                        self._settings(v, mode, (previous or {}).get(k))) for k,v in value.items()}
        if isinstance(value, list):
            return [self._settings(v,mode) for v in value]
        return value

    def _decode(self, resource, row, public=False):
        result = dict(row)
        result.pop('updated_at', None)
        for field in SECRET_FIELDS.get(resource, ()):
            result[field] = None if public else self._decrypt(result[field])
        if resource == 'settings':
            result['value'] = self._settings(result['value'], 'public' if public else 'read')
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
                    if isinstance(column.type, Boolean): row[column.name] = bool(row[column.name])
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

    def list(self, resource):
        with self.engine.connect() as connection:
            return [self._decode(resource, row, public=True) for row in
                    connection.execute(select(TABLES[resource])).mappings()]

    def get(self, resource, ref):
        table = TABLES[resource]
        with self.engine.begin() as connection:
            row = connection.execute(select(table).where(table.c.ref == ref)).mappings().one_or_none()
            if row is None: raise KeyError(ref)
            result = self._decode(resource, row, public=True)
            if resource == 'capabilities':
                for kind, relation in RELATIONS.items():
                    result[kind] = [{k:v for k,v in row.items() if k != 'capability_ref'} for row in
                        connection.execute(select(relation).where(relation.c.capability_ref == ref)).mappings()]
            return result

    def save(self, resource, ref, value, *, validate=None):
        """完整记录与关联一起提交；空秘密字段保留原值，避免管理页面回传掩码。"""
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', ref): raise ValueError('config_ref_invalid')
        table = TABLES[resource]
        if not isinstance(value, dict): raise ValueError('config_fields_invalid')
        value = copy.deepcopy(value)
        value.pop('ref', None)
        relations = {key:value.pop(key, []) for key in RELATIONS} if resource == 'capabilities' else {}
        fields = set(table.c.keys()) - {'ref', 'updated_at'}
        if set(value) != fields: raise ValueError('config_fields_invalid')
        try:
            with self.engine.begin() as connection:
                old = connection.execute(select(table).where(table.c.ref == ref).with_for_update()).mappings().one_or_none()
                for field in SECRET_FIELDS.get(resource, ()):
                    value[field] = old[field] if value[field] is None and old else self._encrypt(value[field])
                if resource == 'settings':
                    previous = self._settings(old['value'], 'read') if old else {}
                    value['value'] = self._settings(value['value'], 'write', previous)
                values = {**value, 'updated_at':datetime.now(timezone.utc).replace(tzinfo=None)}
                if old: connection.execute(table.update().where(table.c.ref == ref).values(**values))
                else: connection.execute(table.insert().values(ref=ref, **values))
                if resource == 'capabilities':
                    model = connection.execute(select(TABLES['model_connections'].c.ref).where(
                        TABLES['model_connections'].c.ref == value['model_connection_ref'])).first()
                    if model is None: raise ValueError('config_reference_missing')
                    for kind, items in relations.items():
                        relation = RELATIONS[kind]
                        other = TABLES[{'skills':'skills','databases':'database_connections','mcps':'mcp_servers'}[kind]]
                        connection.execute(relation.delete().where(relation.c.capability_ref == ref))
                        for item in items:
                            if connection.execute(select(other.c.ref).where(other.c.ref == item['ref'])).first() is None:
                                raise ValueError('config_reference_missing')
                            connection.execute(relation.insert().values(capability_ref=ref, **item))
                if validate: validate(self._load(connection))
        except IntegrityError:
            raise ValueError('config_reference_invalid') from None
        return self.get(resource, ref)

    def delete(self, resource, ref):
        table = TABLES[resource]
        with self.engine.begin() as connection:
            if resource == 'mcp_servers':
                for config in connection.execute(select(TABLES['capabilities'].c.config)).scalars():
                    if ref in config.get('serviceRefs', []): raise ValueError('config_in_use')
            if resource == 'model_connections':
                referenced = connection.execute(select(TABLES['capabilities'].c.ref).where(
                    TABLES['capabilities'].c.model_connection_ref == ref)).first()
                if referenced: raise ValueError('config_in_use')
            for kind, name in [('skills','skills'),('databases','database_connections'),('mcps','mcp_servers')]:
                relation = RELATIONS[kind]
                if resource == name and connection.execute(select(relation.c.ref).where(relation.c.ref == ref)).first():
                    raise ValueError('config_in_use')
                if resource == 'capabilities':
                    connection.execute(relation.delete().where(relation.c.capability_ref == ref))
            connection.execute(table.delete().where(table.c.ref == ref))
