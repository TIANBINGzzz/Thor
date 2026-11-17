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

def table(name, *columns, comment):
    return Table('ccsdk_' + name, metadata,
                 Column('ref', String(96), primary_key=True, comment='稳定引用标识'),
                 *columns,
                 Column('updated_at', DateTime, nullable=False, comment='最近修改时间（UTC）'),
                 comment=comment)


SETTING_COMMENTS = {
    'runtime_client_queue_ms': '会话执行排队超时（毫秒）',
    'runtime_client_idle_ms': '会话 Client 空闲回收时限（毫秒）',
    'runtime_file_prepare_ms': '本轮附件准备总超时（毫秒）',
    'runtime_file_download_ms': '单个附件下载超时（毫秒）',
    'runtime_file_upload_connect_ms': '文件上传连接及连接池等待超时（毫秒）',
    'runtime_worker_start_ms': 'Worker 启动超时（毫秒）',
    'runtime_worker_send_ms': '向 Worker 发送请求超时（毫秒）',
    'runtime_worker_close_ms': 'Worker 关闭等待超时（毫秒）',
    'runtime_worker_control_ms': 'Worker 控制请求超时（毫秒）',
    'runtime_document_render_ms': '文档渲染超时（毫秒）',
    'runtime_document_start_ms': '文档渲染进程启动超时（毫秒）',
    'runtime_image_ms': '图像生成请求超时（毫秒）',
    'runtime_web_search_ms': '网络搜索请求超时（毫秒）',
    'runtime_file_max_bytes': '附件下载大小上限（字节）',
    'runtime_sdk_buffer_bytes': 'SDK 消息缓冲区上限（字节）',
    'runtime_http_body_bytes': 'HTTP 请求体大小上限（字节）',
    'runtime_prompt_bytes': '用户输入提示词大小上限（字节）',
    'runtime_sse_heartbeat_ms': 'SSE 心跳间隔（毫秒）',
    'runtime_pool_max_idle': '空闲预热 Worker 库存上限；0 关闭预热',
    'runtime_pool_max_starting': '预热与业务冷启动共享的并发启动上限',
    'runtime_pool_max_live': 'Worker 总存活数上限；0 不限制',
    'runtime_pool_min_available_memory_mib': 'Worker 可用内存保护阈值（MiB）；0 关闭',
    'runtime_observation_enabled': '是否启用 Runtime 私有观测采集',
    'runtime_observation_storage': '私有观测 SQLite 文件路径',
    'runtime_observation_max_records': '私有观测记录数量上限',
    'runtime_observation_retention_seconds': '私有观测记录保留时长（秒）',
    'runtime_observation_queue_size': '私有观测异步写入队列容量',
    'file_base_url': '平台文件服务基础地址',
    'file_remote_url': '文件服务 remote-url 路由头地址',
    'file_download_path': '文件下载接口路径；含 {fileId} 占位符',
    'file_timeout_seconds': '文件服务请求超时（秒）',
    'file_max_bytes': '文件服务单文件大小上限（字节）',
    'image_enabled': '是否启用图像生成服务',
    'image_base_url': '图像生成服务基础地址',
    'image_api_key': '图像服务 API Key 的加密密文',
    'image_model': '图像生成模型名称',
    'auth_runtime_jwt_secret': 'Run JWT 签名密钥的加密密文',
    'auth_runtime_jwt_issuer': 'Run JWT 与配置管理 JWT 的签发者',
    'auth_runtime_jwt_audience': 'Run JWT 的目标受众',
    'auth_observation_jwt_secret': '观测采集 JWT 签名密钥的加密密文',
    'auth_configuration_jwt_secret': '配置管理 JWT 签名密钥的加密密文',
}

ASSET_COMMENTS = {
    'instructions': '能力内联指令列表（JSON）',
    'instruction_refs': '能力指令文件引用列表（JSON）',
    'required_tool_refs': '必需工具引用列表；为 tool_refs 子集',
    'operation_refs': '能力代码包已登记的 Operation 引用列表',
    'service_refs': '能力 Operation 使用的内部 Service 引用列表',
    'tool_config': '工具或 Service 引用到配置资产路径的映射',
    'prompt_variables': '提示词变量及其可信配置来源绑定（JSON）',
    'templates': '模板标识到 template.json 相对路径的映射',
}

TABLES = {
    'model_connections': table('model_connection',
        Column('name', String(160), nullable=False, comment='模型连接显示名称'),
        Column('base_url', String(1024), nullable=False, comment='模型服务基础地址'),
        Column('adapter', String(32), nullable=False, comment='模型协议适配器；当前为 anthropic'),
        Column('api_key', Text, nullable=False, comment='模型 API Key 的加密密文'),
        Column('parameters', JSON, nullable=False, comment='模型协议扩展参数（JSON 对象）'),
        Column('enabled', Boolean, nullable=False, comment='是否启用模型连接'),
        comment='SDK 模型服务连接'),
    'models': table('model',
        Column('name', String(160), nullable=False, comment='模型显示名称'),
        Column('connection_ref', String(96), ForeignKey('ccsdk_model_connection.ref'), nullable=False,
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
        Column('auth_required', Boolean, nullable=False, comment='是否要求本轮业务 Token'),
        Column('auth_injection', String(16), nullable=False, comment='业务 Token 注入方式：none、header 或 argument'),
        Column('auth_target', String(160), comment='业务 Token 注入的 Header 名或参数名'),
        Column('auth_prefix', String(160), comment='业务 Token 请求头前缀；含必要空格'),
        Column('parameters', JSON, nullable=False, comment='MCP 连接扩展参数（JSON 对象）'),
        Column('enabled', Boolean, nullable=False, comment='是否启用 MCP 服务'),
        comment='SDK MCP 服务连接与业务凭据注入规则'),
    'settings': table('setting', *[
        Column(name, Boolean if name.endswith('_enabled') else
               Text if name.endswith(('_secret', '_api_key')) else
               String(1024) if name.endswith(('_url', '_path', '_storage', '_model', '_issuer', '_audience')) else BigInteger,
               nullable=not name.startswith('runtime_'), comment=SETTING_COMMENTS[name]) for name in SETTING_PATHS],
        CheckConstraint("ref = 'system'"),
        comment='SDK 系统设置；仅保存 ref 为 system 的一条记录'),
    'capabilities': table('capability',
        Column('name', String(160), nullable=False, comment='业务能力显示名称'),
        Column('description', Text, nullable=False, comment='业务能力用途说明'),
        Column('enabled', Boolean, nullable=False, comment='是否启用业务能力'),
        Column('prompt', Text, nullable=False, comment='能力主提示词正文'),
        Column('supports_attachments', Boolean, nullable=False, comment='是否支持输入附件'),
        Column('attachment_max_files', Integer, comment='单轮输入附件数量上限'),
        Column('attachment_max_bytes', BigInteger, comment='单个输入附件大小上限（字节）'),
        Column('attachment_allowed_extensions', JSON, comment='允许的附件扩展名列表；含点号'),
        Column('model_ref', String(96), ForeignKey('ccsdk_model.ref'), nullable=False, comment='执行模型目录引用'),
        Column('thinking_mode', String(16), comment='思考模式：disabled、enabled 或 adaptive'),
        Column('thinking_budget_tokens', Integer, comment='思考 Token 预算；仅 enabled 模式使用'),
        Column('effort', String(16), comment='推理强度：low、medium、high、xhigh 或 max'),
        Column('max_output_tokens', Integer, comment='单次模型输出 Token 上限'),
        Column('run_timeout_ms', Integer, nullable=False, comment='单 Run 模型执行阶段超时（毫秒）'),
        Column('tool_timeout_ms', Integer, nullable=False, comment='单次工具执行及 MCP HTTP 超时（毫秒）'),
        Column('max_turns', Integer, nullable=False, comment='单 Run 的 SDK 最大轮数'),
        Column('max_model_calls', Integer, comment='单 Run 模型调用次数上限；按 SDK 上报统计'),
        Column('max_tool_calls', Integer, comment='单 Run 工具调用次数上限；含失败尝试'),
        Column('max_total_tokens', BigInteger, comment='单 Run 总 Token 上限；含缓存输入，按 SDK 上报统计'),
        Column('tool_refs', JSON, nullable=False, comment='能力可用的通用工具引用列表'),
        Column('execution_mode', String(16), nullable=False, comment='能力执行模式：agent 或 direct'),
        Column('runtime_mode', String(16), comment='SDK 运行模式：query 或 client'),
        Column('prompt_mode', String(16), comment='系统提示词模式：default 或 custom'),
        Column('system_prompt_snapshot', Boolean, comment='是否启用 SDK 系统提示词快照'),
        Column('auth_required', Boolean, nullable=False, comment='能力是否要求本轮业务 Token'),
        Column('data_context_topics', JSON, comment='预加载数据库上下文主题列表'),
        *[Column(name, JSON, nullable=False, comment=ASSET_COMMENTS[name]) for name in CAPABILITY_ASSETS],
        comment='SDK 业务能力、提示词、模型及单 Run 执行预算'),
}
RELATIONS = {}
for kind, resource in [('skills', 'skills'), ('databases', 'database_connections'), ('mcps', 'mcp_servers')]:
    label = {'skills': 'Skill', 'databases': '数据源连接', 'mcps': 'MCP 服务'}[kind]
    columns = [Column('capability_ref', String(96), ForeignKey('ccsdk_capability.ref'), primary_key=True,
                      comment='所属业务能力引用'),
               Column('ref', String(96), ForeignKey(TABLES[resource].name + '.ref'), primary_key=True,
                      comment=label + '引用')]
    columns += ([Column('allowed_tools', JSON, nullable=False, comment='允许的 MCP 操作名列表；空数组不授权，* 表示全部')]
                if kind == 'mcps' else
                [Column('required', Boolean, nullable=False,
                        comment='是否必载 Skill 正文' if kind == 'skills' else '是否必需数据源；停用时拒绝执行')])
    if kind == 'skills':
        columns.append(Column('sort_order', Integer, nullable=False, comment='Skill 加载顺序；数值越小越靠前'))
    RELATIONS[kind] = Table('ccsdk_capability_' + {'skills':'skill','databases':'database','mcps':'mcp'}[kind],
                            metadata, *columns, comment='SDK 业务能力与' + label + '的关联')

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
