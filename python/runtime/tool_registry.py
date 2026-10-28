"""声明式 Tool Catalog 与受信任 Provider 装配。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from runtime.tool_catalog import TOOL_CATALOG, ToolCatalog, ToolDefinition, ToolOperation
from runtime.mcp_providers import provide_mcp
from tools import artifacts, attachments, data, documents, images, mermaid, web_search

@dataclass
class RegisteredTools:
    """保存一轮工具装配结果。"""
    servers: dict[str, object] = field(default_factory=dict)
    exact_tools: dict[str, list[str]] = field(default_factory=dict)
    auth_refs: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class ToolProvider:
    """显式登记可信工具实现；有状态工具与单轮工具共用此目录。"""
    create: Callable | None = None
    load_assets: Callable | None = None
    create_service: Callable | None = None
    update_service: Callable | None = None
    create_server: Callable | None = None


PROVIDERS: dict[str, ToolProvider] = {
    'web': ToolProvider(create=web_search.provide_tool),
    'data': ToolProvider(create=data.provide_tool),
    'charts': ToolProvider(create=mermaid.provide_tool),
    'artifacts': ToolProvider(create=artifacts.provide_tool),
    'documents': ToolProvider(create=documents.provide_tool),
    'stdio-mcp': ToolProvider(create=provide_mcp),
    'images': ToolProvider(create=images.provide_tool),
    'http-mcp': ToolProvider(create=provide_mcp),
    'attachments': ToolProvider(create=attachments.provide_tool),
    'capability-pack': ToolProvider(),
}


def validate_tool_provider(definition):
    """登记与执行使用同一 Provider 白名单，资产不能指定动态 import。"""
    provider = PROVIDERS.get(definition.implementation)
    if provider is None:
        raise RuntimeError(f'工具实现未注册：{definition.implementation}')
    if definition.implementation == 'capability-pack':
        if (definition.lifecycle != 'per_client' or definition.transport != 'sdk'
                or definition.operations or definition.connection):
            raise RuntimeError(f'能力 Service 声明无效：{definition.ref}')
        return provider
    if (definition.lifecycle == 'per_client') != bool(provider.create_service):
        raise RuntimeError(f'工具生命周期与实现不符：{definition.ref}')
    if definition.transport != ('http' if definition.implementation == 'http-mcp' else
                                 'stdio' if definition.implementation == 'stdio-mcp' else 'sdk'):
        raise RuntimeError(f'工具传输与实现不符：{definition.ref}')
    return provider


def build_registered_tools(entry: dict, context: dict) -> RegisteredTools:
    """装配共享 Tool 与能力显式登记的 Operation MCP。"""
    selected = TOOL_CATALOG.resolve_many(entry.get('tools', []))
    result = RegisteredTools()
    for definition in selected:
        provider = validate_tool_provider(definition)
        if definition.lifecycle == 'per_client':
            if definition.ref not in context.get('provided_tools', ()):
                raise RuntimeError(f'有状态工具未准备：{definition.ref}')
            result.auth_refs.add(definition.ref)
            continue
        if provider.create is None:
            raise RuntimeError(f'工具实现缺少单轮工厂：{definition.ref}')
        provided = provider.create(definition, context)
        if provided is None:
            continue
        name, server = provided
        if name in result.servers:
            raise RuntimeError('工具服务名称冲突')
        result.servers[name] = server
        result.auth_refs.add(definition.ref)
        result.exact_tools[name] = (['*'] if definition.scope == 'namespace'
                                    else [operation.ref for operation in definition.operations])
    attachment = None if 'attachments' in result.servers or not context.get('input_directory') else PROVIDERS['attachments'].create(
        TOOL_CATALOG.resolve('attachments'), context)
    if attachment is not None:
        name, server = attachment
        if name in result.servers:
            raise RuntimeError('工具服务名称冲突')
        result.servers[name] = server
        result.auth_refs.add('attachments')
        result.exact_tools[name] = [operation.ref for operation in TOOL_CATALOG.resolve('attachments').operations]
    provided = set(context.get('provided_tools', ()))
    missing = set(entry.get('required_tools', [])) - (set(result.servers) | provided)
    if missing:
        raise RuntimeError('能力必需工具未配置：' + ', '.join(sorted(missing)))
    if entry.get('operation_refs'):
        from runtime.capability_operations import build_operation_server

        name, server, operation_names = build_operation_server(entry, context)
        if name in result.servers:
            raise RuntimeError('能力 Operation 服务名称冲突')
        result.servers[name] = server
        result.exact_tools[name] = operation_names
    return result
