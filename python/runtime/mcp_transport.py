"""通用只读 MCP HTTP 请求；隔离每次连接，禁止重定向和自动重试。"""

import json
import re
from urllib.parse import urlsplit
import httpx


def validate_http_connection(connection):
    """连接与静态 Header 在注入后校验；不允许 URL 携带凭据或 Header 控制字符。"""
    try:
        url = connection['url']
        if not isinstance(url, str) or any(c.isspace() for c in url):
            raise ValueError()
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.port == 0):
            raise ValueError()
        headers = connection.get('headers', {})
        if not isinstance(headers, dict):
            raise ValueError()
        for key, value in headers.items():
            if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9-]+', key)
                    or not isinstance(value, str) or not re.fullmatch(r'[\x20-\x7e]+', value)):
                raise ValueError()
            if key.lower() == 'domain-name' and not re.fullmatch(r'[A-Za-z0-9.-]+', value):
                raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('mcp_connection_invalid') from None


async def call_mcp_tool(config, name, arguments):
    """窄范围只读 JSON-RPC 传输，兼容 JSON/SSE；不跟随重定向、不重试、不回传原始错误。"""
    headers = {**config['headers'], 'Accept': 'application/json, text/event-stream'}
    # 业务 MCP 直连，不继承仅供模型访问使用的进程代理。
    async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
        async def send(body):
            """发送本次 JSON-RPC 消息，维护会话头并限量读取 JSON 或 SSE 响应。"""
            async with client.stream('POST', config['url'], headers=headers, json=body) as response:
                response.raise_for_status()
                session = response.headers.get('mcp-session-id')
                if session:
                    headers['Mcp-Session-Id'] = session
                if 'id' not in body:
                    return None
                def result_of(value):
                    """提取当前请求的结果，拒绝标识不匹配或携带错误的响应。"""
                    if not isinstance(value, dict) or value.get('id') != body['id'] or 'error' in value:
                        raise RuntimeError('上游 MCP 查询失败')
                    return value['result']
                if 'text/event-stream' in response.headers.get('content-type', ''):
                    lines, size = [], 0
                    async for line in response.aiter_lines():
                        size += len(line.encode('utf-8'))
                        if size > 2_000_000:
                            raise RuntimeError('上游结果过大')
                        if line.startswith('data:'):
                            lines.append(line[5:].lstrip())
                        elif not line and lines:
                            value = json.loads('\n'.join(lines))
                            lines = []
                            if isinstance(value, dict) and value.get('id') == body['id']:
                                return result_of(value)
                    raise RuntimeError('上游 SSE 响应不完整')
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise RuntimeError('上游结果过大')
                    chunks.append(chunk)
                return result_of(json.loads(b''.join(chunks)))
        initialized = await send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'agent-runtime', 'version': '1.0'}}})
        headers['MCP-Protocol-Version'] = initialized['protocolVersion']
        await send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        result = await send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                             'params': {'name': name, 'arguments': arguments}})
        if result.get('isError') or len(result.get('content', [])) != 1:
            raise RuntimeError('上游 MCP 查询失败')
        return json.loads(result['content'][0]['text'])
