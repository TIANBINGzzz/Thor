"""Trusted business Capability catalog for the Python SDK runtime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from runtime.prompt_documents import read_entry

CAPABILITIES_ROOT = Path(__file__).resolve().parents[2] / '.claude/capabilities'
TOOL_NAMES = frozenset({'campus', 'charts', 'data', 'web', 'business', 'documents', 'office', 'images', 'artifacts'})
ENTRY_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class CapabilityError(ValueError):
    """Raised when a business capability is not available to the runtime."""


@dataclass(frozen=True)
class Capability:
    ref: str
    workflow_ref: str | None
    supports_attachments: bool = False
    name: str = ""
    description: str = ""
    tools: tuple[str, ...] = ()
    directory: str = ''

    def to_public_dict(self) -> dict:
        """将当前能力转换为公开目录字典，包含业务标识、说明和附件支持状态。"""
        return {"capabilityRef": self.ref, "name": self.name,
                "description": self.description, "supportsAttachments": self.supports_attachments}


def capability_entry(directory):
    """读取能力唯一入口并拒绝拼错字段、未知工具和越界引用。"""
    entry = read_entry(Path(directory) / 'CAPABILITY.md')
    allowed = {'name', 'title', 'description', 'supports_attachments', 'workflow', 'tools',
               'required_tools', 'tool_config', 'runtime', 'execution', 'skills', '_body', '_directory'}
    if set(entry) - allowed or entry.get('name') != Path(directory).name:
        raise RuntimeError('能力入口字段或名称无效')
    for field in ('name', 'title', 'description'):
        if not isinstance(entry.get(field), str) or not entry[field].strip():
            raise RuntimeError('能力元数据缺失')
    if not ENTRY_NAME.fullmatch(entry['name']):
        raise RuntimeError('能力名称无效')
    workflow = entry.get('workflow')
    if workflow is not None and (not isinstance(workflow, str) or not ENTRY_NAME.fullmatch(workflow)):
        raise RuntimeError('能力流程引用无效')
    if type(entry.get('supports_attachments', False)) is not bool:
        raise RuntimeError('附件开关必须为布尔值')
    for field in ('tools', 'required_tools'):
        values = entry.get(field, [])
        if (not isinstance(values, list) or any(not isinstance(value, str) or value not in TOOL_NAMES for value in values)
                or len(set(values)) != len(values)):
            raise RuntimeError('能力工具声明无效')
    if not set(entry.get('required_tools', [])) <= set(entry.get('tools', [])):
        raise RuntimeError('必需工具未登记')
    configs = entry.get('tool_config', {})
    if not isinstance(configs, dict) or not set(configs) <= set(entry.get('tools', [])):
        raise RuntimeError('工具配置未登记')
    for value in configs.values():
        root = Path(directory).resolve()
        if (not isinstance(value, str) or Path(value).is_absolute() or '..' in Path(value).parts
                or not (root / value).resolve().is_relative_to(root)
                or not (root / value).is_file()):
            raise RuntimeError('工具资产路径无效')
    validate_execution_config(entry)
    return entry


def validate_execution_config(entry):
    """能力与流程共用执行选项校验，配置错误不能静默退回默认权限。"""
    execution = entry.get('execution', {})
    if (not isinstance(execution, dict) or set(execution) - {'mode'}
            or execution.get('mode', 'agent') not in ('agent', 'direct')):
        raise RuntimeError('execution.mode 配置无效')
    runtime = entry.get('runtime', {})
    if (not isinstance(runtime, dict)
            or set(runtime) - {'mode', 'max_turns', 'timeout_ms', 'thinking', 'effort', 'prompt_mode'}
            or runtime.get('mode', 'query') not in ('query', 'client')
            or runtime.get('prompt_mode', 'preset') not in ('preset', 'custom')
            or runtime.get('effort', 'low') not in ('low', 'medium', 'high', 'max')):
        raise RuntimeError('runtime 配置无效')
    for field in ('max_turns', 'timeout_ms'):
        if field in runtime and not (field == 'max_turns' and runtime[field] is None):
            if type(runtime[field]) is not int or runtime[field] < 1:
                raise RuntimeError(f'runtime.{field} 必须为正整数')
    thinking = runtime.get('thinking', {'type': 'adaptive'})
    if (not isinstance(thinking, dict) or thinking.get('type') not in ('adaptive', 'enabled', 'disabled')
            or set(thinking) - {'type', 'budget_tokens'}):
        raise RuntimeError('runtime.thinking 配置无效')
    if thinking['type'] == 'enabled':
        if type(thinking.get('budget_tokens')) is not int or thinking['budget_tokens'] < 1024:
            raise RuntimeError('runtime.thinking 预算无效')
    elif 'budget_tokens' in thinking:
        raise RuntimeError('当前thinking模式不接受预算')
    skills = entry.get('skills', [])
    if (not isinstance(skills, list) or any(not isinstance(name, str) or not ENTRY_NAME.fullmatch(name) for name in skills)
            or len(set(skills)) != len(skills)):
        raise RuntimeError('skills配置无效')
    if execution.get('mode') == 'direct' and skills:
        raise RuntimeError('direct模式不能登记需要Read的Skill')


def load_capabilities(root=CAPABILITIES_ROOT):
    """发现部署侧能力目录；公开发现不等于授予执行权限。"""
    root = Path(root).resolve()
    catalog = {}
    for path in sorted(root.glob('*/CAPABILITY.md')):
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('能力入口路径越界')
        entry = capability_entry(path.parent)
        ref = entry['name']
        catalog[ref] = Capability(ref, entry.get('workflow'), entry.get('supports_attachments', False),
                                  entry['title'], entry['description'],
                                  tuple(entry.get('tools', [])), str(path.parent))
    return catalog


CAPABILITIES = load_capabilities()


def resolve_capability(ref: str | None) -> Capability:
    """根据业务能力标识返回登记的 Capability，未登记时抛出 CapabilityError。"""
    try:
        return CAPABILITIES["conversation" if ref is None else ref]
    except KeyError as error:
        raise CapabilityError("capability_not_found") from error


__all__ = ["CAPABILITIES", "Capability", "CapabilityError", "resolve_capability"]
