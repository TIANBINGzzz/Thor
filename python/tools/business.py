"""业务 HTTP MCP 的受控装配。"""

import os


def provide_tool(definition, context):
    """按可信 Capability 配置决定是否挂载业务 MCP。"""
    if context['capability_ref'] not in context['business_capabilities']:
        return None
    url = os.environ.get('BUSINESS_MCP_URL', '').strip()
    return (definition.ref, {'type': 'http', 'url': url}, '') if url else None
