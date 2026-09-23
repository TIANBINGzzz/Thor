"""通用只读 MCP HTTP 请求；隔离每次连接，禁止重定向和自动重试。"""

import json
import httpx


async def call_mcp_tool(config, name, arguments):
    """窄范围只读 JSON-RPC 传输，兼容 JSON/SSE；不跟随重定向、不重试、不回传原始错误。"""
    headers = {**config['headers'], 'Accept': 'application/json, text/event-stream'}
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        async def send(body):
            async with client.stream('POST', config['url'], headers=headers, json=body) as response:
                response.raise_for_status()
                session = response.headers.get('mcp-session-id')
                if session:
                    headers['Mcp-Session-Id'] = session
                if 'id' not in body:
                    return None
                def result_of(value):
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
