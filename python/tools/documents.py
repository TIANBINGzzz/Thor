"""OfficeCLI 处理原生 Office 编辑；本工具补充真实分页渲染和 PDF 阅读。"""

import asyncio
import json
from pathlib import Path

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.declarations import operation
from tools.document_conversion import render_document, read_pdf


def create_document_server(base_dir, additional_dirs=None):
    """绑定授权文件目录，注册 Office 渲染与 PDF 分页阅读工具。"""
    definitions = [
        ('render', render_document),
        ('read_pdf', read_pdf),
    ]
    registered = []
    for name, handler in definitions:
        spec = operation('documents', name)
        async def invoke(args, _handler=handler):
            """在线程中执行已绑定的文档处理器，将结果或错误编码为 MCP 文本。"""
            try:
                result = await asyncio.to_thread(_handler, base_dir=base_dir, additional_dirs=additional_dirs, **args)
                return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
            except Exception as error:
                return {'isError': True, 'content': [{'type': 'text', 'text': str(error)}]}
        registered.append(sdk_tool(spec.ref, spec.description, spec.input_schema)(invoke))
    return create_sdk_mcp_server('documents', version='1.0.0', tools=registered)


def provide_tool(definition, context):
    """绑定本轮工作目录和额外授权文件目录。"""
    work = context.get('work_directory') or context.get('cwd') or Path.cwd()
    dirs = [*(context.get('additional_directories') or []),
            *(item for item in (context.get('work_directory'), context.get('deliverables_directory')) if item)]
    return definition.ref, create_document_server(work, dirs), ''
