"""可信控制面配置入口：组合已登记资产，不接受代码、连接或任意文件上传。"""

import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Depends, HTTPException, Request

from data_access.catalog import Catalog
from data_access.context import DataError
from runtime.auth import JWTError, _verify_signed_claims
from runtime.asset_registry import ENTRY_NAME, load_declared_asset
from runtime.capabilities import CAPABILITIES_ROOT, MANAGED_CAPABILITIES_ROOT, SKILLS_ROOT, capability_entry
from runtime.tool_registry import TOOL_CATALOG, validate_tool_provider

LOGGER = logging.getLogger('ccsdk.runtime.assets')
MAX_BODY_BYTES = 32_000
# 带文件的模板及工具私有配置由源码/部署管理；管理 API 只组合既有资产。
MANAGED_FIELDS = {'ref', 'title', 'description', 'supportsAttachments', 'skillRefs',
                  'toolRefs', 'requiredToolRefs', 'runtime', 'execution', 'data'}


def _authorize(request: Request):
    """管理授权与执行、观测密钥隔离；未配置即关闭，授权最长五分钟。"""
    secret = os.environ.get('CCSDK_ASSET_JWT_SECRET', '').strip()
    if not secret or secret in {os.environ.get('CCSDK_RUNTIME_JWT_SECRET', '').strip(),
                                os.environ.get('CCSDK_OBSERVATION_JWT_SECRET', '').strip()}:
        raise HTTPException(401, '资产管理鉴权未配置')
    scheme, _, token = request.headers.get('authorization', '').partition(' ')
    try:
        if scheme.lower() != 'bearer':
            raise JWTError('missing bearer')
        claims = _verify_signed_claims(token.strip(), secret, audience='ccsdk-runtime-assets',
            issuer='string-ai-center-service', expected_scope='assets.manage', required_claims=('sub', 'jti'))
        scopes = {claims['scope']} if isinstance(claims['scope'], str) else set(claims['scope'])
        if (claims['aud'] != 'ccsdk-runtime-assets' or scopes != {'assets.manage'}
                or claims['exp'] - claims['iat'] > 300):
            raise JWTError('invalid management grant')
        return claims
    except JWTError:
        raise HTTPException(401, '资产管理鉴权失败') from None


async def _body(request):
    """限制读取大小，避免管理正文或额外内部字段进入文件系统。"""
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BODY_BYTES:
            raise HTTPException(413, '能力配置过大')
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or set(value) != {'manifest', 'prompt'}:
            raise ValueError()
        manifest, prompt = value['manifest'], value['prompt']
        if (not isinstance(manifest, dict) or set(manifest) - MANAGED_FIELDS
                or not isinstance(manifest.get('ref'), str)
                or len(manifest['ref']) > 96 or not ENTRY_NAME.fullmatch(manifest['ref'])
                or not isinstance(prompt, str)):
            raise ValueError()
        return manifest, prompt
    except (ValueError, UnicodeError):
        raise HTTPException(400, '能力配置无效') from None


def _prepare(root, manifest, prompt, *, publish):
    """在发现目录外校验两份文件，成功后一次重命名；不覆盖现有能力。"""
    target = root / manifest['ref']
    if publish and (target.exists() or (CAPABILITIES_ROOT / manifest['ref']).exists()):
        raise HTTPException(409, '能力已存在')
    root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.capability-', dir=root.parent) as temporary:
        directory = Path(temporary) / manifest['ref']
        directory.mkdir()
        (directory / 'capability.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (directory / 'CAPABILITY.md').write_text(prompt, encoding='utf-8')
        try:
            entry = capability_entry(directory, skills_root=SKILLS_ROOT)
        except (RuntimeError, DataError, ValueError):
            raise HTTPException(400, '能力配置或资产引用无效') from None
        result = {'capabilityRef': entry['ref'], 'name': entry['title'],
                  'description': entry['description'], 'supportsAttachments': entry['supports_attachments']}
        if publish:
            try:
                directory.rename(target)
            except (FileExistsError, OSError) as error:
                if target.exists():
                    raise HTTPException(409, '能力已存在') from error
                raise
        return result


def create_asset_router(*, root=None):
    """建立仅供服务端管理集成的接口；不影响公开能力目录与 Run 契约。"""
    root = Path(root or MANAGED_CAPABILITIES_ROOT).resolve()
    router = APIRouter(prefix='/internal/v1/assets', dependencies=[Depends(_authorize)])

    @router.get('/catalog')
    async def catalog():
        tools = []
        for ref in sorted(TOOL_CATALOG.refs):
            definition = TOOL_CATALOG.resolve(ref)
            validate_tool_provider(definition)
            tools.append({'ref': ref, 'description': definition.description,
                          'category': definition.category, 'transport': definition.transport,
                          'operations': [{'ref': operation.ref, 'description': operation.description,
                                          'inputSchema': operation.input_schema} for operation in definition.operations]})
        skills = [load_declared_asset(path.parent, 'skill.json', 'SKILL.md', path.parent.name,
                  required_fields=('description',)) for path in sorted(SKILLS_ROOT.glob('*/skill.json'))]
        return {'tools': tools, 'skills': [{'ref': item['ref'], 'description': item['description']} for item in skills],
                'dataSources': [{'ref': item['source_key'], 'name': item['name'],
                                 'domains': list(item['domains'])} for item in Catalog().sources()]}

    @router.post('/capabilities/validate')
    async def validate(request: Request):
        manifest, prompt = await _body(request)
        return _prepare(root, manifest, prompt, publish=False)

    @router.post('/capabilities', status_code=201)
    async def create(request: Request, claims=Depends(_authorize)):
        manifest, prompt = await _body(request)
        result = _prepare(root, manifest, prompt, publish=True)
        LOGGER.info('能力已创建：ref=%s actor=%s', manifest['ref'], claims['sub'])
        return result

    return router
