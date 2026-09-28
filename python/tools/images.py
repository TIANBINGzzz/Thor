"""调用部署配置的 Qwen Image API；模型只提交画面要求和工作目录文件。"""

import base64
from io import BytesIO
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.declarations import operation
from tools.document_conversion import _resolve, _roots, _new_output




async def generate_image(prompt, output_path, *, base_dir, base_url, api_key,
                         model='qwen-image-3.0', additional_dirs=None, size='1536x1024',
                         reference_paths=None):
    """同步生成一张PNG；参考图只读，结果独占创建，失败不自动重复付费请求。"""
    roots = _roots(base_dir, additional_dirs)
    target = _resolve(output_path, roots, exists=False)
    if target.suffix.lower() != '.png':
        raise ValueError('输出文件须为 .png')
    _new_output(target, Path())
    body = {'model': model, 'prompt': prompt, 'size': size, 'n': 1,
            'prompt_extend': False, 'watermark': False}
    if reference_paths:
        if len(reference_paths) > 3:
            raise ValueError('最多使用3张参考图')
        images = []
        for value in reference_paths:
            source = _resolve(value, roots)
            if source.stat().st_size > 10 * 1024 * 1024:
                raise ValueError('每张参考图不得超过10MB')
            with Image.open(source) as image:
                mime = Image.MIME[image.format]
            images.append(f'data:{mime};base64,' + base64.b64encode(source.read_bytes()).decode('ascii'))
        body['image'] = images
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=600) as client:
        try:
            response = await client.post(base_url.rstrip('/') + '/images/generations', json=body,
                                         headers={'Authorization': 'Bearer ' + api_key})
        except httpx.HTTPError:
            raise RuntimeError('生图服务连接失败或超时；未自动重试，请先确认请求状态') from None
        if response.is_error:
            # 不把上游原始正文、签名URL或请求头暴露到模型/运行日志。
            try:
                code = response.json().get('error', {}).get('code') or response.json().get('code')
            except (ValueError, AttributeError):
                code = None
            raise RuntimeError(f'生图请求失败：HTTP {response.status_code}，code={code or "unknown"}')
        result = response.json()
        items = result.get('data') or []
        if not items or not items[0].get('url'):
            raise RuntimeError('生图服务未返回图片')
        try:
            # 下载使用独立请求头，不将API凭据带到临时图片地址。
            downloaded = await client.get(items[0]['url'])
            downloaded.raise_for_status()
        except httpx.HTTPError:
            raise RuntimeError('图片已生成但下载失败；未重复生成') from None
    with Image.open(BytesIO(downloaded.content)) as image:
        image.load()
        width, height = image.size
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            image.save(output, format='PNG')
    return {'path': str(target), 'model': model, 'width': width, 'height': height,
            'elapsedSeconds': round(time.monotonic() - started, 2), 'generated': True}


def create_image_server(base_dir, *, base_url, api_key, model, additional_dirs=None):
    """绑定部署侧生图配置与授权目录，模型只能提交画面要求和文件参数。"""
    spec = operation('images', 'generate')
    @sdk_tool(spec.ref, spec.description, spec.input_schema)
    async def generate(arguments):
        """调用绑定的生图服务并返回文件结果，失败不自动重试付费请求。"""
        try:
            result = await generate_image(**arguments, base_dir=base_dir, additional_dirs=additional_dirs,
                                          base_url=base_url, api_key=api_key, model=model)
            return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
        except (ValueError, OSError, RuntimeError) as error:
            return {'isError': True, 'content': [{'type': 'text', 'text': str(error)}]}
    return create_sdk_mcp_server('images', version='1.0.0', tools=[generate])


def image_configuration():
    """解析部署侧生图配置；仅受信任的阿里云工作空间可复用模型连接。"""
    base = os.environ.get('CCSDK_IMAGE_BASE_URL', '').strip()
    key = os.environ.get('CCSDK_IMAGE_API_KEY', '').strip() or os.environ.get('ANTHROPIC_AUTH_TOKEN', '').strip()
    if not base:
        url = urlsplit(os.environ.get('ANTHROPIC_BASE_URL', ''))
        if (url.scheme == 'https' and (url.hostname or '').endswith('.maas.aliyuncs.com')
                and url.path.rstrip('/') == '/apps/anthropic'
                and not url.username and not url.password and not url.query and not url.fragment):
            base = urlunsplit((url.scheme, url.netloc, '/compatible-mode/v1', '', ''))
    return base, key


def provide_tool(definition, context):
    """仅在生图连接可用时，为本轮目录创建图片 MCP。"""
    base, key = image_configuration()
    if not base or not key:
        return None
    work = context.get('work_directory') or context.get('cwd') or Path.cwd()
    server = create_image_server(work, base_url=base, api_key=key,
                                 model=os.environ.get('CCSDK_IMAGE_MODEL', 'qwen-image-3.0'),
                                 additional_dirs=context.get('additional_directories'))
    return definition.ref, server, ''
