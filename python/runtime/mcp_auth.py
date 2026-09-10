"""Request-scoped MCP credential injection.

Rules are deployment-owned and cannot be supplied by the browser.  A single
opaque platform bearer may be injected only into registered MCPs that declare
``required=True``.  The function returns copied configs and never mutates
``os.environ`` or a caller's MCP dictionary.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any


MCP_AUTH_RULES: dict[str, dict[str, Any]] = {
    "business": {
        "required": True,
        "transport": "http",
        "header": "Authorization",
        "prefix": "Bearer ",
    },
    "db": {"required": False, "transport": "stdio"},
    "docx": {"required": False, "transport": "stdio"},
    "artifacts": {"required": False, "transport": "stdio"},
}

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class MCPAuthError(ValueError):
    """Raised when an MCP is unknown or cannot receive the requested token."""


def _credentials_token(credentials: Any) -> str:
    if credentials is None:
        return ""
    if hasattr(credentials, "platform_bearer"):
        value = getattr(credentials, "platform_bearer")
    elif isinstance(credentials, Mapping):
        value = credentials.get("platformBearer", credentials.get("platform_bearer"))
    else:
        raise MCPAuthError("credentials must be an object")
    if value is None:
        return ""
    if not isinstance(value, str) or not value.strip():
        raise MCPAuthError("credentials.platformBearer must be a non-empty string")
    if "\r" in value or "\n" in value:
        raise MCPAuthError("credentials.platformBearer contains control characters")
    return value.strip()


def inject_mcp_auth(mcp_ref: str, server: Mapping[str, Any], credentials: Any = None) -> dict[str, Any]:
    """接收 MCP 标识、服务配置和请求凭据，返回按登记规则注入 Token 的配置副本。

    未登记或缺少必需凭据时抛出 MCPAuthError，不修改原配置或全局环境。
    """
    if not isinstance(mcp_ref, str) or not mcp_ref.strip():
        raise MCPAuthError("mcp_ref must be a non-empty string")
    rule = MCP_AUTH_RULES.get(mcp_ref)
    if rule is None:
        raise MCPAuthError(f"MCP 未注册：{mcp_ref}")
    if not isinstance(server, Mapping):
        raise MCPAuthError("MCP server must be an object")
    result = copy.deepcopy(dict(server))
    if not bool(rule.get("required")):
        return result

    token = _credentials_token(credentials)
    if not token:
        raise MCPAuthError(f"MCP 缺少业务 Token：{mcp_ref}")
    transport = rule.get("transport")
    if transport in {"http", "sse"}:
        header = rule.get("header", "Authorization")
        prefix = rule.get("prefix", "")
        if not isinstance(header, str) or not header or "\r" in header or "\n" in header:
            raise MCPAuthError(f"MCP header 配置无效：{mcp_ref}")
        if not isinstance(prefix, str) or "\r" in prefix or "\n" in prefix:
            raise MCPAuthError(f"MCP header prefix 配置无效：{mcp_ref}")
        headers = result.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise MCPAuthError(f"MCP headers 配置无效：{mcp_ref}")
        result["headers"] = {**dict(headers), header: prefix + token}
        return result
    if transport == "stdio":
        env_name = rule.get("env")
        if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
            raise MCPAuthError(f"stdio MCP 未配置有效 env 名称：{mcp_ref}")
        env = result.get("env") or {}
        if not isinstance(env, Mapping):
            raise MCPAuthError(f"MCP env 配置无效：{mcp_ref}")
        result["env"] = {**dict(env), env_name: token}
        return result
    raise MCPAuthError(f"MCP 传输类型不支持：{mcp_ref}")


def inject_mcp_authentication(
    servers: Mapping[str, Mapping[str, Any]],
    credentials: Any = None,
    *,
    allowed_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    """接收服务映射、请求凭据和可选服务名单，返回逐项完成凭据注入的新映射，不修改输入。"""
    if not isinstance(servers, Mapping):
        raise MCPAuthError("servers must be an object")
    refs = list(servers) if allowed_refs is None else list(allowed_refs)
    unknown = [ref for ref in refs if ref not in servers]
    if unknown:
        raise MCPAuthError(f"MCP server not found: {', '.join(unknown)}")
    return {ref: inject_mcp_auth(ref, servers[ref], credentials) for ref in refs}
