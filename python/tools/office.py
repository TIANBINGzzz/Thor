"""OfficeCLI 的外部 MCP 进程装配。"""

import os


def provide_tool(definition, context):
    """返回受信任 OfficeCLI MCP 的启动配置。"""
    return definition.ref, {'command': os.environ.get('CCSDK_OFFICECLI_PATH', 'officecli'),
                            'args': ['mcp'], 'env': {'OFFICECLI_SKIP_UPDATE': '1'}}, ''
