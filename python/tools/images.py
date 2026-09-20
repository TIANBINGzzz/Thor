"""调用部署配置的 Qwen Image API；模型只提交画面要求和工作目录文件。"""

import base64
from io import BytesIO
import json
from pathlib import Path
import time

import httpx
from PIL import Image

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from tools.document_conversion import _resolve, _roots, _new_output


IMAGE_INSTRUCTIONS = (
    '本轮选择图像生成能力：按用户描述及本轮授权参考图调用 mcp__images__generate，'
    '不得用文字、SVG或占位文件冒充生成图片。画面要求、尺寸和数量从用户输入理解；'
    '未指定数量时生成一张，未指定尺寸时使用工具默认尺寸。每次工具调用生成一张PNG，'
    '多张图片逐张调用并使用不同文件名，不覆盖已有结果。参考图最多3张，仅使用已准备的授权附件。'
    '生成后用Read查看图片并核对用户要求，调用 mcp__artifacts__publish_file 逐张发布最终PNG；'
    '如用户同时要求文档，文档与图片分别发布，不擅自合并或打包。'
    '生成或发布失败须如实说明，保留其他成功结果；不自动重复失败的付费生成请求。'
    '最终回答简短说明图片内容；上传与下载状态由文件卡片展示，'
    '不输出本地路径、上游临时URL、Base64或自行编造链接，不声称上传完成。'
)


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
    @sdk_tool('generate', '按需生成或编辑一张图片，保存PNG并返回路径。reference_paths可选1至3张本轮授权参考图。生成图不能作为真实成果照片或数据证据；完成后用Read查看。',
              {'type': 'object', 'properties': {
                  'prompt': {'type': 'string', 'minLength': 1},
                  'output_path': {'type': 'string'}, 'size': {'type': 'string'},
                  'reference_paths': {'type': 'array', 'maxItems': 3, 'items': {'type': 'string'}},
              }, 'required': ['prompt', 'output_path'], 'additionalProperties': False})
    async def generate(arguments):
        try:
            result = await generate_image(**arguments, base_dir=base_dir, additional_dirs=additional_dirs,
                                          base_url=base_url, api_key=api_key, model=model)
            return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
        except (ValueError, OSError, RuntimeError) as error:
            return {'isError': True, 'content': [{'type': 'text', 'text': str(error)}]}
    return create_sdk_mcp_server('images', version='1.0.0', tools=[generate])
