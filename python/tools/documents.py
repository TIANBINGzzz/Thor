"""OfficeCLI 处理原生 Office 编辑；本工具补充真实分页渲染和 PDF 阅读。"""

import asyncio
import json

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.document_conversion import render_document, read_pdf


def create_document_server(base_dir, additional_dirs=None):
    string = {'type': 'string'}
    integer = {'type': 'integer'}
    definitions = [
        ('render', 'Office引擎更新DOCX目录和字段，另存DOCX与PDF；output_dir为新目录。OfficeCLI编辑后先close，再调用此工具；版式通过PDF核验。',
         {'path': string, 'output_dir': string}, ['path', 'output_dir'], render_document),
        ('read_pdf', '按页读取PDF文字，可render=true生成页面图片。页码从1开始；用Read查看返回图片。',
         {'path': string, 'start': integer, 'limit': integer, 'render': {'type': 'boolean'}, 'output_dir': string}, ['path'], read_pdf),
    ]
    registered = []
    for name, description, properties, required, handler in definitions:
        async def invoke(args, _handler=handler):
            try:
                result = await asyncio.to_thread(_handler, base_dir=base_dir, additional_dirs=additional_dirs, **args)
                return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
            except Exception as error:
                return {'isError': True, 'content': [{'type': 'text', 'text': str(error)}]}
        registered.append(sdk_tool(name, description, {'type': 'object', 'properties': properties,
                                                       'required': required, 'additionalProperties': False})(invoke))
    return create_sdk_mcp_server('documents', version='1.0.0', tools=registered)
