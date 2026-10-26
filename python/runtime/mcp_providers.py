"""通用 HTTP/stdio MCP 装配；配置只来自可信工具资产，不能指定 Python import。"""

import os
import re

from runtime.tool_catalog import TOOL_CATALOG
from runtime.mcp_transport import validate_http_connection

_ENV_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _environment_values(value, environment):
    """仅展开明确登记的环境变量，不执行表达式、shell 或字符串插值。"""
    if isinstance(value, dict):
        if 'env' in value and isinstance(value['env'], str):
            if set(value) - {'env', 'default'} or not _ENV_NAME.fullmatch(value['env']):
                raise ValueError('mcp_environment_invalid')
            return environment.get(value['env'], value.get('default'))
        return {key: _environment_values(item, environment) for key, item in value.items()}
    if isinstance(value, list):
        return [_environment_values(item, environment) for item in value]
    return value


def load_mcp_connections(entry, settings, *, catalog=None, environment=None):
    """父进程解析所选连接，Worker 使用本轮配置；不扩大 MCP 或环境权限。"""
    result = {}
    environment = os.environ if environment is None else environment
    for definition in (catalog or TOOL_CATALOG).resolve_many(entry.get('tools', [])):
        if definition.implementation not in {'http-mcp', 'stdio-mcp'}:
            continue
        connection = settings.resolve(_environment_values(definition.connection, environment))
        required = 'url' if definition.transport == 'http' else 'command'
        if definition.optional and not connection.get(required):
            continue
        if definition.transport == 'http':
            if set(connection) - {'url', 'headers'}:
                raise ValueError('mcp_connection_invalid')
            validate_http_connection(connection)
            result[definition.ref] = {'type': 'http', **connection}
        else:
            if (set(connection) - {'command', 'args', 'env'}
                    or not isinstance(connection.get('command'), str) or not connection['command'].strip()
                    or not isinstance(connection.get('args', []), list)
                    or any(not isinstance(arg, str) for arg in connection.get('args', []))
                    or not isinstance(connection.get('env', {}), dict)
                    or any(not _ENV_NAME.fullmatch(key) or not isinstance(value, str)
                           for key, value in connection.get('env', {}).items())):
                raise ValueError('mcp_connection_invalid')
            result[definition.ref] = connection
    return result


def provide_mcp(definition, context):
    """创建已解析 MCP 配置；凭据随后由统一鉴权层逐轮注入副本。"""
    connection = context['mcp_connections'].get(definition.ref)
    return (definition.ref, connection) if connection is not None else None
