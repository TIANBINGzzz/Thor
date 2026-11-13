"""从 JSON manifest 注册业务 Capability，并加载其模型正文。"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import os
import threading

from runtime.asset_registry import ENTRY_NAME, read_asset_body, read_manifest, validate_refs
from runtime.tool_registry import TOOL_CATALOG, validate_tool_provider

CAPABILITIES_ROOT = Path(__file__).resolve().parents[2] / '.claude/capabilities'
SKILLS_ROOT = Path(__file__).resolve().parents[2] / '.claude/skills'


class CapabilityError(ValueError):
    """表示请求的业务能力未登记。"""


@dataclass(frozen=True)
class Capability:
    """公开目录所需的 Capability 摘要。"""

    ref: str
    supports_attachments: bool = False
    name: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    directory: str = ''
    skill_refs: tuple[str, ...] = ()

    def to_public_dict(self) -> dict:
        """将能力转换为公开目录字典，不暴露内部装配细节。"""
        return {"capabilityRef": self.ref, "name": self.name,
                "description": self.description, "supportsAttachments": self.supports_attachments}


def _validate_runtime(value, label: str = 'runtime') -> dict:
    """校验模型运行策略，避免能力声明绕过 SDK 边界。"""
    if not isinstance(value, dict):
        raise RuntimeError(f'{label}配置无效')
    allowed = {'model', 'mode', 'thinking', 'max_turns', 'effort', 'prompt_mode', 'timeout_ms', 'system_prompt_snapshot', 'tool_timeout_ms', 'max_output_tokens', 'max_model_calls', 'max_tool_calls', 'max_total_tokens'}
    if set(value) - allowed:
        raise RuntimeError(f'{label}存在未知字段')
    if 'model' in value:
        model = value['model']
        if (not isinstance(model, str) or any(char.isspace() for char in model) or '://' in model):
            raise RuntimeError(f'{label}.model配置无效')
    if value.get('mode') is not None and value['mode'] not in ('query', 'client'):
        raise RuntimeError(f'{label}.mode配置无效')
    thinking = value.get('thinking')
    if thinking is not None:
        if not isinstance(thinking, dict) or thinking.get('type') not in ('disabled', 'enabled', 'adaptive'):
            raise RuntimeError(f'{label}.thinking配置无效')
        enabled = thinking['type'] == 'enabled'
        expected = {'type', 'budget_tokens'} if enabled else {'type'}
        if (set(thinking) != expected or (enabled and
                (type(thinking['budget_tokens']) is not int or thinking['budget_tokens'] <= 0))):
            raise RuntimeError(f'{label}.thinking配置无效')
    for field in ('max_turns', 'timeout_ms', 'tool_timeout_ms', 'max_output_tokens', 'max_model_calls', 'max_tool_calls', 'max_total_tokens'):
        item = value.get(field)
        if field == 'max_turns' and item is None:
            continue
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item <= 0):
            raise RuntimeError(f'{label}.{field}配置无效')
    if value.get('effort') is not None and value['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'):
        raise RuntimeError(f'{label}.effort配置无效')
    if value.get('prompt_mode') is not None and value['prompt_mode'] not in ('default', 'custom'):
        raise RuntimeError(f'{label}.prompt_mode配置无效')
    if 'system_prompt_snapshot' in value and type(value['system_prompt_snapshot']) is not bool:
        raise RuntimeError(f'{label}.system_prompt_snapshot配置无效')
    return value


def _validate_manifest(directory: Path, manifest: dict, skills_root: Path, *, body=None, skills=None) -> dict:
    """校验 Capability manifest，并补齐 Runtime 使用的统一字段。"""
    allowed = {'ref', 'title', 'description', 'supportsAttachments', 'skillRefs',
               'toolRefs', 'requiredToolRefs', 'toolConfig', 'runtime', 'execution', 'data', 'templates',
               'instructionRefs', 'instructions', 'requiredSkillRefs', 'promptVariables', 'operationRefs', 'serviceRefs', 'auth'}
    if set(manifest) - allowed or manifest.get('ref') != directory.name:
        raise RuntimeError('能力 manifest 字段或名称无效')
    for field in ('ref', 'title', 'description'):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise RuntimeError('能力 manifest 元数据缺失')
    if not ENTRY_NAME.fullmatch(manifest['ref']) or type(manifest.get('supportsAttachments', False)) is not bool:
        raise RuntimeError('能力 manifest 标识或附件配置无效')
    auth = manifest.get('auth', {'required': False})
    if not isinstance(auth, dict) or set(auth) != {'required'} or type(auth.get('required')) is not bool:
        raise RuntimeError('能力业务凭据规则无效')
    skill_refs = validate_refs(manifest.get('skillRefs', []), 'skillRefs')
    tools = validate_refs(manifest.get('toolRefs', []), 'toolRefs')
    required = validate_refs(manifest.get('requiredToolRefs', []), 'requiredToolRefs')
    try:
        tool_definitions = TOOL_CATALOG.resolve_many(tools)
        for definition in tool_definitions:
            if definition.implementation == 'capability-pack':
                raise RuntimeError('能力内部 Service 不能作为 Agent Tool')
            validate_tool_provider(definition)
        TOOL_CATALOG.resolve_many(required)
    except RuntimeError as error:
        raise RuntimeError('能力工具声明无效') from error
    if not set(required) <= set(tools):
        raise RuntimeError('能力工具声明无效')
    operation_refs = validate_refs(manifest.get('operationRefs', []), 'operationRefs')
    service_refs = validate_refs(manifest.get('serviceRefs', []), 'serviceRefs')
    if (set(service_refs) & set(tools)
            or (service_refs and not operation_refs)):
        raise RuntimeError('能力 Service 声明无效')
    try:
        service_definitions = TOOL_CATALOG.resolve_many(service_refs)
        for definition in service_definitions:
            validate_tool_provider(definition)
            if definition.implementation != 'capability-pack' or definition.lifecycle != 'per_client':
                raise RuntimeError('能力 Service 声明无效')
        if set(service_refs) != {item.service_ref for item in service_definitions}:
            raise RuntimeError('能力 Service 引用无效')
    except RuntimeError as error:
        raise RuntimeError('能力 Service 声明无效') from error
    if operation_refs:
        # 业务 Python 必须随可信 Runtime 部署，不接受其他目录中的代码引用。
        source_root = CAPABILITIES_ROOT.resolve()
        if not directory.resolve().is_relative_to(source_root):
            raise RuntimeError('只有源码能力可以引用代码包')
        from capability_packs.registry import read_pack_manifest
        pack = read_pack_manifest(manifest['ref'])
        if not set(operation_refs) <= {operation.ref for operation in pack.operations}:
            raise RuntimeError('能力 Operation 未在代码包中登记')
        if set(service_refs) != set(pack.services):
            raise RuntimeError('能力 Service 依赖与代码包不一致')
    configs = manifest.get('toolConfig', {})
    if not isinstance(configs, dict) or not set(configs) <= (set(tools) | set(service_refs)):
        raise RuntimeError('工具配置未登记')
    for value in configs.values():
        path = (directory / value).resolve() if isinstance(value, str) else directory / '__invalid__'
        if not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts or not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise RuntimeError('工具资产路径无效')
    _validate_runtime(manifest.get('runtime', {}))
    execution = manifest.get('execution', {})
    if not isinstance(execution, dict) or set(execution) - {'mode'} or execution.get('mode', 'agent') not in ('agent', 'direct'):
        raise RuntimeError('execution.mode 配置无效')
    data = manifest.get('data', {})
    if (not isinstance(data, dict) or set(data) - {'access', 'sourceRefs', 'contextTopics'}
            or (data and data.get('access') not in ('optional', 'required'))):
        raise RuntimeError('能力 data 配置无效')
    sources = validate_refs(data.get('sourceRefs', []), 'data.sourceRefs')
    if data and (not sources or ('data' not in tools and not operation_refs)):
        raise RuntimeError('数据能力必须声明来源及 data 工具或业务 Operation')
    from data_access.catalog import Catalog
    catalog = Catalog()
    for source in sources:
        catalog.source(source)
    topics = data.get('contextTopics')
    if topics is not None and (not isinstance(topics, list) or not topics
            or any(item not in ('schema', 'relationships', 'business', 'metrics') for item in topics)):
        raise RuntimeError('能力 data.contextTopics 配置无效')
    templates = manifest.get('templates', {})
    if not isinstance(templates, dict):
        raise RuntimeError('能力 templates 配置无效')
    for ref, relative in templates.items():
        if not ENTRY_NAME.fullmatch(ref) or not isinstance(relative, str):
            raise RuntimeError('能力模板登记无效')
        target = (directory / relative).resolve()
        if (Path(relative).is_absolute() or '..' in Path(relative).parts
                or not target.is_relative_to(directory.resolve()) or not target.is_file()
                or target.name != 'template.json'):
            raise RuntimeError('能力模板路径无效')
    from runtime.prompt_assembly import validate_prompt_manifest
    variables = validate_prompt_manifest(directory, manifest, skills_root, body=body, skills=skills)
    return {**manifest, '_prompt_variables': variables,
            'name': manifest['ref'], 'supports_attachments': manifest.get('supportsAttachments', False),
            'skill_refs': list(skill_refs), 'tools': list(tools),
            'required_tools': list(required), 'tool_config': configs,
            'operation_refs': list(operation_refs),
            'service_refs': list(service_refs),
            '_body': body if body is not None else read_asset_body(directory, 'CAPABILITY.md'), '_directory': str(directory.resolve()),
            '_skill_root': str(skills_root.resolve())}


def capability_entry(directory, *, skills_root=None):
    """按稳定能力标识读取数据库；directory 只标识随代码交付的模板/业务资产。"""
    from runtime.configuration import execution_entry
    return execution_entry(Path(directory).name)['capability']


def load_capabilities(root=None):
    from runtime.configuration import read_configuration
    rows = read_configuration()['capabilities']
    return {ref:Capability(ref=ref, name=row['name'], description=row['description'],
        supports_attachments=row['supports_attachments'], tools=tuple(row['tool_refs']),
        directory=str(CAPABILITIES_ROOT/ref), skill_refs=tuple(item['ref'] for item in row['skills']))
        for ref,row in rows.items() if row['enabled']}

class CapabilityCatalog(Mapping):
    def __getitem__(self, ref): return load_capabilities()[ref]
    def __iter__(self): return iter(load_capabilities())
    def __len__(self): return len(load_capabilities())
    def values(self): return load_capabilities().values()
    def items(self): return load_capabilities().items()

CAPABILITIES = CapabilityCatalog()

def resolve_capability(ref: str | None) -> Capability:
    try:
        return CAPABILITIES[ref or 'conversation']
    except KeyError:
        raise CapabilityError('capability_not_found') from None
