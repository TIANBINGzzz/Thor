"""声明式 Tool Catalog 与受信任 Provider 装配。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from runtime.asset_registry import ENTRY_NAME, read_manifest, validate_refs
from tools import artifacts, attachments, business, campus, data, documents, images, mermaid, office, web_search

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
    version: int
    implementation: str
    transport: str
    lifecycle: str
    scope: str
    operations: tuple[ToolOperation, ...]
    directory: str

    def operation(self, ref: str) -> ToolOperation:
        """按操作引用查找声明。"""
        for operation in self.operations:
            if operation.ref == ref:
                return operation
        raise KeyError(ref)


class ToolCatalog:
    """加载并校验所有 Tool manifest，形成受信任目录。"""

    def __init__(self, root=TOOLS_ROOT):
        """扫描工具目录并拒绝重复或不完整声明。"""
        self.root = Path(root).resolve()
        self._definitions = {}
        for path in sorted(self.root.glob('*/tool.json')):
            definition = self._load(path.parent)
            if definition.ref in self._definitions:
                raise RuntimeError(f'工具重复登记：{definition.ref}')
            self._definitions[definition.ref] = definition

    def _load(self, directory: Path) -> ToolDefinition:
        """读取单个 Tool manifest 并校验运行时契约。"""
        directory = directory.resolve()
        value = read_manifest(directory, 'tool.json')
        allowed = {'ref', 'version', 'implementation', 'transport', 'lifecycle', 'scope', 'description', 'operations'}
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
            parsed.append(ToolOperation(operation_ref, item['description'], schema))
        return ToolDefinition(ref, value['version'], implementation, value['transport'],
                              value['lifecycle'], value.get('scope', 'operations'), tuple(parsed), str(directory))

    def resolve(self, ref: str) -> ToolDefinition:
        """按 Tool 引用返回声明。"""
        try:
            return self._definitions[ref]
        except KeyError as error:
            raise RuntimeError(f'工具未登记：{ref}') from error

    def resolve_many(self, refs) -> tuple[ToolDefinition, ...]:
        """批量解析 Tool 引用并保持声明顺序。"""
        values = refs if isinstance(refs, list) else list(refs)
        return tuple(self.resolve(ref) for ref in validate_refs(values, 'toolRefs'))

    @property
    def refs(self) -> frozenset[str]:
        """返回已登记的 Tool 引用集合。"""
        return frozenset(self._definitions)


@dataclass
class RegisteredTools:
    """保存一轮工具装配结果。"""
    servers: dict[str, object] = field(default_factory=dict)
    prompt_append: str = ""
    exact_tools: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolProvider:
    """显式登记可信工具实现；有状态工具与单轮工具共用此目录。"""
    create: Callable | None = None
    load_assets: Callable | None = None
    create_service: Callable | None = None
    create_server: Callable | None = None


PROVIDERS: dict[str, ToolProvider] = {
    'web': ToolProvider(create=web_search.provide_tool),
    'data': ToolProvider(create=data.provide_tool),
    'charts': ToolProvider(create=mermaid.provide_tool),
    'artifacts': ToolProvider(create=artifacts.provide_tool),
    'documents': ToolProvider(create=documents.provide_tool),
    'office': ToolProvider(create=office.provide_tool),
    'images': ToolProvider(create=images.provide_tool),
    'business': ToolProvider(create=business.provide_tool),
    'attachments': ToolProvider(create=attachments.provide_tool),
    'campus': ToolProvider(load_assets=campus.load_campus_assets,
                           create_service=campus.CampusQuery, create_server=campus.create_campus_server),
}
TOOL_CATALOG = ToolCatalog()
for _ref in TOOL_CATALOG.refs:
    _definition = TOOL_CATALOG.resolve(_ref)
    _provider = PROVIDERS.get(_definition.implementation)
    if (_provider is None or bool(_provider.create) != (_definition.lifecycle == 'per_run')
            or bool(_provider.create_service) != (_definition.lifecycle == 'per_client')
            or (_definition.lifecycle == 'per_client' and (not _provider.load_assets or not _provider.create_server))):
        raise RuntimeError(f'工具 Provider 未完整登记：{_ref}')


def build_registered_tools(entry: dict, context: dict) -> RegisteredTools:
    """解析 Tool manifest 并通过 Provider 注册本轮 MCP。"""
    selected = TOOL_CATALOG.resolve_many(entry.get('tools', []))
    result = RegisteredTools()
    for definition in selected:
        provider = PROVIDERS.get(definition.implementation)
        if provider is None:
            raise RuntimeError(f'工具实现未注册：{definition.implementation}')
        if definition.lifecycle == 'per_client':
            if definition.ref not in context.get('provided_tools', ()):
                raise RuntimeError(f'有状态工具未准备：{definition.ref}')
            continue
        if provider.create is None:
            raise RuntimeError(f'工具实现缺少单轮工厂：{definition.ref}')
        provided = provider.create(definition, context)
        if provided is None:
            continue
        name, server, prompt = provided
        result.servers[name] = server
        result.exact_tools[name] = (['*'] if definition.scope == 'namespace'
                                    else [operation.ref for operation in definition.operations])
        result.prompt_append += prompt
    attachment = None if 'attachments' in result.servers else PROVIDERS['attachments'].create(
        TOOL_CATALOG.resolve('attachments'), context)
    if attachment is not None:
        name, server, prompt = attachment
        result.servers[name] = server
        result.exact_tools[name] = [operation.ref for operation in TOOL_CATALOG.resolve('attachments').operations]
        result.prompt_append += prompt
    provided = set(context.get('provided_tools', ()))
    missing = set(entry.get('required_tools', [])) - (set(result.servers) | provided)
    if missing:
        raise RuntimeError('能力必需工具未配置：' + ', '.join(sorted(missing)))
    return result
