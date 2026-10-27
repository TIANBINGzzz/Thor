"""可信工具元数据；不导入执行实现，供装配、鉴权和公共事件共用。"""

from dataclasses import dataclass
from pathlib import Path
import re
from jsonschema import Draft202012Validator, SchemaError
from runtime.asset_registry import ENTRY_NAME, read_manifest, validate_refs
from runtime.prompt_documents import read_documents

TOOLS_ROOT = Path(__file__).resolve().parents[2] / '.claude/tools'


@dataclass(frozen=True)
class ToolOperation:
    """描述一个 Tool 操作的稳定名称和输入契约。"""
    ref: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolDefinition:
    """描述可由 Runtime 装配的受信任 Tool。"""
    ref: str
    implementation: str
    lifecycle: str
    scope: str
    operations: tuple[ToolOperation, ...]
    transport: str
    category: str
    description: str
    auth: dict
    connection: dict
    optional: bool
    display_keys: dict
    service_ref: str | None
    instructions: tuple[dict, ...]

    def operation(self, ref: str) -> ToolOperation:
        """按操作引用查找声明。"""
        for operation in self.operations:
            if operation.ref == ref:
                return operation
        raise KeyError(ref)


class ToolCatalog:
    """加载并校验所有 Tool manifest，形成受信任目录。"""

    def __init__(self, root=TOOLS_ROOT):
        """绑定可信工具目录；每次解析校验所选声明。"""
        self.root = Path(root).resolve()

    def _load(self, directory: Path) -> ToolDefinition:
        """读取单个 Tool manifest 并校验运行时契约。"""
        directory = directory.resolve()
        value = read_manifest(directory, 'tool.json')
        allowed = {'ref', 'version', 'implementation', 'transport', 'lifecycle', 'scope', 'description', 'operations', 'category', 'auth', 'connection', 'optional', 'displayKeys', 'instructionRefs', 'serviceRef'}
        if set(value) - allowed or value.get('ref') != directory.name:
            raise RuntimeError(f'工具 manifest 字段或名称无效：{directory}')
        ref = value.get('ref')
        if not isinstance(ref, str) or not ENTRY_NAME.fullmatch(ref):
            raise RuntimeError(f'工具引用无效：{directory}')
        if type(value.get('version')) is not int or value['version'] < 1:
            raise RuntimeError(f'工具版本无效：{ref}')
        implementation = value.get('implementation')
        if not isinstance(implementation, str) or not ENTRY_NAME.fullmatch(implementation):
            raise RuntimeError(f'工具实现标识无效：{ref}')
        if value.get('transport') not in {'sdk', 'http', 'stdio'}:
            raise RuntimeError(f'工具传输方式无效：{ref}')
        if value.get('lifecycle') not in {'per_run', 'per_client'}:
            raise RuntimeError(f'工具生命周期无效：{ref}')
        if value.get('scope', 'operations') not in {'operations', 'namespace'}:
            raise RuntimeError(f'工具 scope 无效：{ref}')
        scope = value.get('scope', 'operations')
        operations = value.get('operations')
        if not isinstance(operations, list) or (scope == 'operations' and not operations) or (scope == 'namespace' and operations):
            raise RuntimeError(f'工具操作声明无效：{ref}')
        parsed, refs = [], []
        for item in operations:
            if not isinstance(item, dict) or set(item) - {'ref', 'description', 'inputSchema'}:
                raise RuntimeError(f'工具操作声明无效：{ref}')
            operation_ref = item.get('ref')
            schema = item.get('inputSchema')
            if (not isinstance(operation_ref, str) or not ENTRY_NAME.fullmatch(operation_ref)
                    or not isinstance(item.get('description'), str) or not item['description'].strip()
                    or not isinstance(schema, dict) or schema.get('type') != 'object'):
                raise RuntimeError(f'工具操作声明无效：{ref}.{operation_ref}')
            if operation_ref in refs:
                raise RuntimeError(f'工具操作重复登记：{ref}.{operation_ref}')
            refs.append(operation_ref)
            required = schema.get('required', [])
            if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
                raise RuntimeError(f'工具操作 required 无效：{ref}.{operation_ref}')
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError:
                raise RuntimeError(f'工具参数 Schema 无效：{ref}.{operation_ref}') from None
            parsed.append(ToolOperation(operation_ref, item['description'], schema))
        category = value.get('category')
        if category not in {'data', 'document', 'image', 'chart', 'web', 'file', 'integration'}:
            raise RuntimeError(f'工具分类无效：{ref}')
        description = value.get('description')
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(f'工具说明无效：{ref}')
        auth = value.get('auth', {'required': False})
        if not isinstance(auth, dict) or set(auth) - {'required', 'header', 'prefix', 'env', 'arguments'} or type(auth.get('required')) is not bool:
            raise RuntimeError(f'工具凭据规则无效：{ref}')
        if auth['required']:
            transport = value['transport']
            fields = {'sdk': {'arguments'}, 'http': {'header', 'prefix'}, 'stdio': {'env'}}[transport]
            if set(auth) - {'required'} != fields:
                raise RuntimeError(f'工具凭据目标无效：{ref}')
            if transport == 'sdk':
                mapping = auth['arguments']
                if not isinstance(mapping, dict) or not mapping or any(not isinstance(k, str) or not ENTRY_NAME.fullmatch(k) or v != 'platformBearer' for k, v in mapping.items()):
                    raise RuntimeError(f'工具凭据参数无效：{ref}')
            elif any(not isinstance(auth[k], str) or '\r' in auth[k] or '\n' in auth[k] for k in fields):
                raise RuntimeError(f'工具凭据目标无效：{ref}')
            if transport == 'http' and not re.fullmatch(r'[A-Za-z0-9-]+', auth['header']):
                raise RuntimeError(f'工具凭据 Header 无效：{ref}')
            if transport == 'stdio' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', auth['env']):
                raise RuntimeError(f'工具凭据环境变量无效：{ref}')
        elif set(auth) != {'required'}:
            raise RuntimeError(f'无凭据工具不能声明注入目标：{ref}')
        connection = value.get('connection', {})
        if not isinstance(connection, dict) or type(value.get('optional', False)) is not bool:
            raise RuntimeError(f'MCP连接配置无效：{ref}')
        if (implementation in {'http-mcp', 'stdio-mcp'} and
                (value['transport'] != implementation.split('-')[0] or value['lifecycle'] != 'per_run' or not connection)):
            raise RuntimeError(f'MCP Provider配置无效：{ref}')
        if value['transport'] == 'sdk' and connection:
            raise RuntimeError(f'SDK工具不能声明MCP连接：{ref}')
        service_ref = value.get('serviceRef')
        if implementation == 'capability-pack':
            if (not isinstance(service_ref, str) or not ENTRY_NAME.fullmatch(service_ref)
                    or value['transport'] != 'sdk' or value['lifecycle'] != 'per_client'
                    or scope != 'namespace' or operations):
                raise RuntimeError(f'能力 Service 配置无效：{ref}')
        elif service_ref is not None:
            raise RuntimeError(f'普通 Tool 不能声明 Service 引用：{ref}')
        display = value.get('displayKeys', {})
        if not isinstance(display, dict) or any(not isinstance(k, str) or not ENTRY_NAME.fullmatch(k) or not isinstance(v, str) for k, v in display.items()):
            raise RuntimeError(f'工具显示规则无效：{ref}')
        return ToolDefinition(ref, implementation, value['lifecycle'], scope, tuple(parsed),
                              value['transport'], category, description, auth, connection,
                              value.get('optional', False), display, service_ref,
                              tuple(read_documents(directory, value.get('instructionRefs', []), asset_root=self.root)))

    def resolve(self, ref: str) -> ToolDefinition:
        """按 Tool 引用返回声明。"""
        if not isinstance(ref, str) or not ENTRY_NAME.fullmatch(ref):
            raise RuntimeError('工具引用无效')
        directory = (self.root / ref).resolve()
        if not directory.is_relative_to(self.root) or not (directory / 'tool.json').is_file():
            raise RuntimeError(f'工具未登记：{ref}')
        return self._load(directory)

    def resolve_many(self, refs) -> tuple[ToolDefinition, ...]:
        """批量解析 Tool 引用并保持声明顺序。"""
        values = refs if isinstance(refs, list) else list(refs)
        return tuple(self.resolve(ref) for ref in validate_refs(values, 'toolRefs'))

    @property
    def refs(self) -> frozenset[str]:
        """返回已登记的 Tool 引用集合。"""
        return frozenset(self.resolve(path.parent.name).ref for path in self.root.glob('*/tool.json'))


TOOL_CATALOG = ToolCatalog()


def auth_rule(ref):
    """只接受可信工具目录声明的逐 MCP 注入规则。"""
    definition = TOOL_CATALOG.resolve(ref)
    return {**definition.auth, 'transport': definition.transport}


def display_key(name):
    """只把已登记操作映射到安全分类，未知工具不展示内部名称。"""
    if not isinstance(name, str) or not name.startswith('mcp__'):
        return 'other'
    parts = name.split('__', 2)
    if len(parts) != 3:
        return 'other'
    if parts[1] == 'capability_ops':
        from capability_packs.registry import operation_display_key
        return operation_display_key(parts[2]) or 'capability.operation'
    try:
        return TOOL_CATALOG.resolve(parts[1]).display_keys.get(parts[2], 'other')
    except RuntimeError:
        return 'other'
