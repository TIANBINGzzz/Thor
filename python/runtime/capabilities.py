"""从 JSON manifest 注册业务 Capability，并加载其模型正文。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from runtime.asset_registry import ENTRY_NAME, load_declared_asset, read_asset_body, read_manifest, validate_refs
from runtime.tool_registry import TOOL_CATALOG

CAPABILITIES_ROOT = Path(__file__).resolve().parents[2] / '.claude/capabilities'
WORKFLOWS_ROOT = Path(__file__).resolve().parents[2] / '.claude/workflows'
SKILLS_ROOT = Path(__file__).resolve().parents[2] / '.claude/skills'


class CapabilityError(ValueError):
    """表示请求的业务能力未登记。"""


@dataclass(frozen=True)
class Capability:
    """公开目录所需的 Capability 摘要。"""

    ref: str
    workflow_ref: str | None
    supports_attachments: bool = False
    name: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    directory: str = ''
    workflow_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()

    def to_public_dict(self) -> dict:
        """将能力转换为公开目录字典，不暴露内部装配细节。"""
        return {"capabilityRef": self.ref, "name": self.name,
                "description": self.description, "supportsAttachments": self.supports_attachments}


def _validate_runtime(value, label: str = 'runtime') -> dict:
    """校验模型运行策略，避免能力声明绕过 SDK 边界。"""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError(f'{label}配置无效')
    allowed = {'mode', 'thinking', 'max_turns', 'effort', 'prompt_mode', 'timeout_ms'}
    if set(value) - allowed:
        raise RuntimeError(f'{label}存在未知字段')
    if value.get('mode') is not None and value['mode'] not in {'query', 'client'}:
        raise RuntimeError(f'{label}.mode配置无效')
    thinking = value.get('thinking')
    if thinking is not None and (not isinstance(thinking, dict) or set(thinking) != {'type'}
                                  or thinking['type'] not in {'disabled', 'enabled', 'adaptive'}):
        raise RuntimeError(f'{label}.thinking配置无效')
    for field in ('max_turns', 'timeout_ms'):
        item = value.get(field)
        if field == 'max_turns' and item is None:
            continue
        if item is not None and (isinstance(item, bool) or not isinstance(item, int) or item <= 0):
            raise RuntimeError(f'{label}.{field}配置无效')
    if value.get('effort') is not None and value['effort'] not in {'low', 'medium', 'high', 'xhigh', 'max'}:
        raise RuntimeError(f'{label}.effort配置无效')
    if value.get('prompt_mode') is not None and value['prompt_mode'] not in {'default', 'custom'}:
        raise RuntimeError(f'{label}.prompt_mode配置无效')
    return value


def _validate_manifest(directory: Path, manifest: dict, workflows_root: Path, skills_root: Path) -> dict:
    """校验 Capability manifest，并补齐 Runtime 使用的统一字段。"""
    allowed = {'ref', 'title', 'description', 'supportsAttachments', 'workflowRefs', 'skillRefs',
               'toolRefs', 'requiredToolRefs', 'toolConfig', 'runtime', 'execution'}
    if set(manifest) - allowed or manifest.get('ref') != directory.name:
        raise RuntimeError('能力 manifest 字段或名称无效')
    for field in ('ref', 'title', 'description'):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise RuntimeError('能力 manifest 元数据缺失')
    if not ENTRY_NAME.fullmatch(manifest['ref']) or type(manifest.get('supportsAttachments', False)) is not bool:
        raise RuntimeError('能力 manifest 标识或附件配置无效')
    workflows = validate_refs(manifest.get('workflowRefs', []), 'workflowRefs')
    if len(workflows) > 1:
        raise RuntimeError('一个能力只支持一个可执行 Workflow；复用规则请声明 Skill')
    skills = validate_refs(manifest.get('skillRefs', []), 'skillRefs')
    tools = validate_refs(manifest.get('toolRefs', []), 'toolRefs')
    required = validate_refs(manifest.get('requiredToolRefs', []), 'requiredToolRefs')
    try:
        TOOL_CATALOG.resolve_many(tools)
        TOOL_CATALOG.resolve_many(required)
    except RuntimeError as error:
        raise RuntimeError('能力工具声明无效') from error
    if not set(required) <= set(tools):
        raise RuntimeError('能力工具声明无效')
    configs = manifest.get('toolConfig', {})
    if not isinstance(configs, dict) or not set(configs) <= set(tools):
        raise RuntimeError('工具配置未登记')
    for value in configs.values():
        path = (directory / value).resolve() if isinstance(value, str) else directory / '__invalid__'
        if not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts or not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise RuntimeError('工具资产路径无效')
    _validate_runtime(manifest.get('runtime', {}))
    execution = manifest.get('execution', {})
    if not isinstance(execution, dict) or set(execution) - {'mode'} or execution.get('mode', 'agent') not in ('agent', 'direct'):
        raise RuntimeError('execution.mode 配置无效')
    if execution.get('mode') == 'direct' and skills:
        raise RuntimeError('direct模式不能登记需要Read的Skill')
    for ref in workflows:
        workflow_dir = workflows_root / ref
        if not (workflow_dir / 'workflow.json').is_file() or not (workflow_dir / 'WORKFLOW.md').is_file():
            raise RuntimeError(f'Workflow 不存在：{ref}')
        workflow = load_declared_asset(workflow_dir, 'workflow.json', 'WORKFLOW.md', ref,
                                       required_fields=('description',))
        if not workflow.get('description'):
            raise RuntimeError(f'Workflow 声明无效：{ref}')
        _validate_runtime(workflow.get('runtime', {}), f'Workflow {ref}.runtime')
    for ref in skills:
        skill_dir = skills_root / ref
        if not (skill_dir / 'skill.json').is_file() or not (skill_dir / 'SKILL.md').is_file():
            raise RuntimeError(f'Skill 不存在：{ref}')
        load_declared_asset(skill_dir, 'skill.json', 'SKILL.md', ref, required_fields=('description',))
    return {**manifest, 'name': manifest['ref'], 'supports_attachments': manifest.get('supportsAttachments', False),
            'workflow_refs': workflows, 'skill_refs': skills, 'tools': list(tools),
            'required_tools': list(required), 'tool_config': configs,
            '_body': read_asset_body(directory, 'CAPABILITY.md'), '_directory': str(directory.resolve()),
            '_workflow_root': str(workflows_root.resolve()), '_skill_root': str(skills_root.resolve())}


def capability_entry(directory, *, workflows_root=WORKFLOWS_ROOT, skills_root=SKILLS_ROOT):
    """读取 JSON Capability manifest 与同目录 Markdown 正文。"""
    directory = Path(directory).resolve()
    return _validate_manifest(directory, read_manifest(directory, 'capability.json'),
                              Path(workflows_root).resolve(), Path(skills_root).resolve())


def load_capabilities(root=CAPABILITIES_ROOT):
    """发现并校验所有 Capability manifest，形成受信任目录。"""
    root = Path(root).resolve()
    workflows_root = root.parent / 'workflows'
    skills_root = root.parent / 'skills'
    catalog = {}
    for path in sorted(root.glob('*/capability.json')):
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('能力 manifest 路径越界')
        entry = capability_entry(path.parent, workflows_root=workflows_root, skills_root=skills_root)
        ref = entry['ref']
        if ref in catalog:
            raise RuntimeError(f'能力重复登记：{ref}')
        catalog[ref] = Capability(ref, entry['workflow_refs'][0] if len(entry['workflow_refs']) == 1 else None,
                                  entry['supports_attachments'], entry['title'], entry['description'],
                                  tuple(entry['tools']), str(path.parent), entry['workflow_refs'], entry['skill_refs'])
    return catalog


CAPABILITIES = load_capabilities()


def resolve_capability(ref: str | None) -> Capability:
    """根据业务能力标识返回登记的 Capability。"""
    try:
        return CAPABILITIES["conversation" if ref is None else ref]
    except KeyError as error:
        raise CapabilityError("capability_not_found") from error


__all__ = ["CAPABILITIES", "Capability", "CapabilityError", "capability_entry", "load_capabilities", "resolve_capability"]
