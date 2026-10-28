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
from runtime.prompt_assembly import assemble_prompt, load_prompt_assets, shared_system_prompt
from runtime.tool_registry import TOOL_CATALOG, validate_tool_provider

LOGGER = logging.getLogger('ccsdk.runtime.assets')
MAX_BODY_BYTES = 32_000
# 带文件的模板及工具私有配置由源码/部署管理；管理 API 只组合既有资产。
MANAGED_FIELDS = {'ref', 'title', 'description', 'supportsAttachments', 'skillRefs', 'requiredSkillRefs',
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
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise HTTPException(400, '能力配置无效') from None


def _draft(value):
    try:
        if set(value) != {'manifest', 'prompt'}:
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


def _preview(entry, *, active_tools=None, template_key=None):
    """离线编译；不调用运行配置装配、Provider、MCP 或数据库连接。"""
    from runtime.template_assets import load_template
    template = load_template(template_key, entry['ref'], entry=entry) if template_key is not None else None
    assets = load_prompt_assets(entry, template=template)
    active = assets['tools'] if active_tools is None else active_tools
    compiled = assemble_prompt(assets, active_tools=active, preview=True)
    slots = sorted({slot for item in compiled['sections'] for slot in item['runtimeSlots']})
    operations = []
    if entry.get('operation_refs'):
        from capability_packs.registry import read_pack_manifest
        definitions = {item.ref: item for item in read_pack_manifest(entry['ref']).operations}
        for ref in entry['operation_refs']:
            item = definitions[ref]
            operations.append({'ref': ref, 'toolName': 'mcp__capability_ops__' + ref,
                               'description': item.description, 'inputSchema': item.input_schema,
                               'outputSchema': item.output_schema})
    return {**compiled, 'capabilityRef': entry['ref'], 'templateKey': template_key,
            'operations': operations,
            'scope': 'project_instructions', 'runtimeSlots': slots,
            'sharedSystemPrompt': shared_system_prompt(),
            'assumptions': {'activeToolRefs': compiled['activeToolRefs'], 'availabilityChecked': False,
                'excluded': ['SDK 内置系统提示词及工具 Schema', '用户输入、附件正文和业务查询结果',
                             '本轮数据库上下文和可信服务端附加上下文'],
                'notice': '工具按声明或所选组合假定挂载；真实执行还需检查连接、凭据和本轮授权。'},
            'dataContext': {'sourceRefs': entry.get('data', {}).get('sourceRefs', []),
                            'contextTopics': entry.get('data', {}).get('contextTopics'), 'loaded': False}}


def _prepare(root, manifest, prompt, *, publish, preview=False, active_tools=None):
    """在发现目录外校验两份文件，成功后一次重命名；不覆盖现有能力。"""
    target = root / manifest['ref']
    if publish and (target.exists() or (CAPABILITIES_ROOT / manifest['ref']).exists()):
        raise HTTPException(409, '能力已存在')
    if publish:
        root.mkdir(parents=True, exist_ok=True)
    # 草稿使用系统临时目录；只有发布才在数据卷同盘准备，以便原子重命名。
    with TemporaryDirectory(prefix='.capability-', dir=root.parent if publish else None) as temporary:
        directory = Path(temporary) / manifest['ref']
        directory.mkdir()
        (directory / 'capability.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (directory / 'CAPABILITY.md').write_text(prompt, encoding='utf-8')
        try:
            entry = capability_entry(directory, skills_root=SKILLS_ROOT)
            compiled = _preview(entry, active_tools=active_tools)
        except (RuntimeError, DataError, ValueError, OSError):
            raise HTTPException(400, '能力配置或资产引用无效') from None
        if preview:
            return compiled
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
            if definition.implementation == 'capability-pack':
                continue
            validate_tool_provider(definition)
            tools.append({'ref': ref, 'description': definition.description,
                          'category': definition.category, 'transport': definition.transport,
                          'operations': [{'ref': operation.ref, 'description': operation.description,
                                          'inputSchema': operation.input_schema} for operation in definition.operations]})
        skills = [load_declared_asset(path.parent, 'skill.json', 'SKILL.md', path.parent.name,
                  required_fields=('description',), asset_root=SKILLS_ROOT)
                  for path in sorted(SKILLS_ROOT.glob('*/skill.json'))]
        return {'tools': tools, 'skills': [{'ref': item['ref'], 'description': item['description'],
                                          'toolRefs': item.get('toolRefs', [])} for item in skills],
                'dataSources': [{'ref': item['source_key'], 'name': item['name'],
                                 'domains': list(item['domains'])} for item in Catalog().sources()]}

    @router.post('/capabilities/validate')
    async def validate(request: Request):
        manifest, prompt = _draft(await _body(request))
        return _prepare(root, manifest, prompt, publish=False)

    @router.post('/capabilities/preview')
    async def preview(request: Request):
        value = await _body(request)
        if 'activeToolRefs' in value and not isinstance(value['activeToolRefs'], list):
            raise HTTPException(400, '预览工具组合无效')
        active = value.pop('activeToolRefs', None)
        if 'manifest' in value:
            manifest, prompt = _draft(value)
            return _prepare(root, manifest, prompt, publish=False, preview=True, active_tools=active)
        if set(value) - {'capabilityRef', 'templateKey'} or 'capabilityRef' not in value:
            raise HTTPException(400, '预览选择无效')
        ref = value['capabilityRef']
        if not isinstance(ref, str) or len(ref) > 96 or not ENTRY_NAME.fullmatch(ref):
            raise HTTPException(400, '预览能力无效')
        if 'templateKey' in value and (not isinstance(value['templateKey'], str)
                                      or not ENTRY_NAME.fullmatch(value['templateKey'])):
            raise HTTPException(400, '预览模板无效')
        owners = [owner.resolve() for owner in (CAPABILITIES_ROOT, root)
                  if (owner / ref / 'capability.json').is_file()]
        if not owners:
            raise HTTPException(404, '能力不存在')
        if len(owners) != 1 or not (owners[0] / ref).resolve().is_relative_to(owners[0]):
            raise HTTPException(400, '能力目录冲突或路径越界')
        try:
            entry = capability_entry(owners[0] / ref, skills_root=SKILLS_ROOT)
            return _preview(entry, active_tools=active, template_key=value.get('templateKey'))
        except (RuntimeError, DataError, ValueError, OSError):
            raise HTTPException(400, '能力配置或预览组合无效') from None

    @router.post('/capabilities', status_code=201)
    async def create(request: Request, claims=Depends(_authorize)):
        manifest, prompt = _draft(await _body(request))
        result = _prepare(root, manifest, prompt, publish=True)
        LOGGER.info('能力已创建：ref=%s actor=%s', manifest['ref'], claims['sub'])
        return result

    return router
