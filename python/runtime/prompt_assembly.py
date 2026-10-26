"""显式提示词资产的唯一编译入口；不创建工具、不读取连接或运行凭据。"""

from datetime import date
import math
from pathlib import Path
import re

from data_access.context import fingerprint
from runtime.asset_registry import ENTRY_NAME, load_declared_asset, read_manifest, validate_refs
from runtime.prompt_documents import MAX_DOCUMENT_TOTAL_BYTES, read_documents
from runtime.tool_catalog import TOOL_CATALOG

PROMPTS_ROOT = Path(__file__).resolve().parents[2] / '.claude/prompts'
SLOTS = {'current_date', 'work_directory', 'deliverables_directory', 'template_path', 'template_file_name', 'skill_path'}
VARIABLE = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_]*)\}\}')


def _render(text, values):
    """只替换具名标量，不支持表达式、属性访问或递归渲染。"""
    names = set(VARIABLE.findall(text))
    # JSON 示例可合法包含相邻右花括号；只将双左花括号视为模板语法入口。
    if names - values.keys() or '{{' in VARIABLE.sub('', text):
        raise RuntimeError('提示词变量未声明或表达式无效')
    return VARIABLE.sub(lambda match: str(values[match[1]]), text)


def prompt_variables(directory, manifest):
    """仅从已登记工具 JSON 的顶层非秘密数值/布尔字段绑定变量；不展开连接引用。"""
    bindings = manifest.get('promptVariables', {})
    if not isinstance(bindings, dict):
        raise RuntimeError('提示词变量声明无效')
    values = {}
    for name, binding in bindings.items():
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name)
                or name in SLOTS or not isinstance(binding, dict)
                or set(binding) != {'toolRef', 'field'}):
            raise RuntimeError('提示词变量绑定无效')
        ref, field = binding['toolRef'], binding['field']
        if (not isinstance(ref, str) or ref not in manifest.get('toolConfig', {})
                or ref not in manifest.get('toolRefs', manifest.get('tools', []))
                or not isinstance(field, str) or not ENTRY_NAME.fullmatch(field)
                or re.search(r'token|secret|password|credential|connection|header|env|key|auth', field, re.I)):
            raise RuntimeError('提示词变量来源未登记')
        root = Path(directory).resolve()
        path = (root / manifest['toolConfig'][ref]).resolve()
        if (not path.is_relative_to(root) or path.suffix != '.json'
                or 'not_for_model' in path.relative_to(root).as_posix().lower().replace('-', '_')
                or not path.is_file() or path.stat().st_size > 128_000):
            raise RuntimeError('提示词变量文件无效')
        value = read_manifest(path.parent, path.name).get(field)
        if type(value) not in (bool, int, float) or (type(value) is float and not math.isfinite(value)):
            raise RuntimeError('提示词变量只允许非秘密数值或布尔字段')
        values[name] = value
    return values


def _skill(skills_root, ref):
    root = Path(skills_root).resolve()
    directory = (root / ref).resolve()
    if not directory.is_relative_to(root):
        raise RuntimeError('Skill 路径越界')
    return load_declared_asset(directory, 'skill.json', 'SKILL.md', ref,
                               required_fields=('description',), asset_root=root)


def shared_system_prompt():
    """持久 SDK 历史仅保存共同底座，逐轮业务正文由 Hook 更新。"""
    return read_documents(PROMPTS_ROOT, ['system.md'])[0]['text'].strip()


def validate_prompt_manifest(directory, manifest, skills_root):
    """发布和运行共用引用、变量及 Skill 依赖校验；声明不授予工具权限。"""
    documents = read_documents(directory, manifest.get('instructionRefs', []))
    if any((Path(directory) / doc['name']).resolve() == (Path(directory) / 'CAPABILITY.md').resolve()
           for doc in documents):
        raise RuntimeError('能力正文不能重复登记')
    skills = validate_refs(manifest.get('skillRefs', manifest.get('skill_refs', [])), 'skillRefs')
    required = validate_refs(manifest.get('requiredSkillRefs', []), 'requiredSkillRefs')
    if not set(required) <= set(skills):
        raise RuntimeError('必载 Skill 必须属于 skillRefs')
    if manifest.get('execution', {}).get('mode') == 'direct' and set(skills) - set(required):
        raise RuntimeError('direct 模式不能登记需要 Read 的按需 Skill，请显式声明为必载')
    tools = manifest.get('toolRefs', manifest.get('tools', []))
    for ref in skills:
        skill = _skill(skills_root, ref)
        needed = validate_refs(skill.get('toolRefs', []), 'Skill.toolRefs')
        if not set(needed) <= set(tools):
            raise RuntimeError('Skill 所需工具未在能力中声明')
    values = prompt_variables(directory, manifest)
    from runtime.asset_registry import read_asset_body
    for text in [read_asset_body(Path(directory), 'CAPABILITY.md'), *(doc['text'] for doc in documents)]:
        _render(text, values)
    return values


def load_prompt_assets(entry, *, template=None, catalog=None):
    """读取本轮所选规则；正文随现有 Run 装配保存，不建立持久化版本系统。"""
    catalog = catalog or TOOL_CATALOG
    sections, seen = [], set()
    values = dict(entry.get('_prompt_variables', {}))
    required = set(entry.get('requiredSkillRefs', []))

    def add(kind, directory, prefix, document, reason, *, tool=None, load='always', needs=()):
        root = Path(directory).resolve()
        path = (root / document['name']).resolve()
        if path in seen:
            raise RuntimeError('提示词来源重复加载')
        seen.add(path)
        source = prefix + path.relative_to(root).as_posix()
        text = document['text']
        _render(text, {**values, **{slot: '' for slot in SLOTS}})
        sections.append({'kind': kind, 'source': source, 'text': text.strip(),
                         'reason': reason, 'load': load, 'tool': tool, 'needs': list(needs)})

    for doc in read_documents(PROMPTS_ROOT, ['base.md', 'no-web.md', 'direct.md', 'date.md']):
        condition = {'no-web.md': 'no_web', 'direct.md': 'direct'}.get(doc['name'], 'always')
        add('runtime', PROMPTS_ROOT, 'prompts/', doc, '公共执行规则', load=condition)
    owner = 'capabilities/' + entry['name'] + '/'
    add('capability', entry['_directory'], owner,
        {'name': 'CAPABILITY.md', 'text': entry['_body']}, '本轮选择的业务能力')
    for doc in read_documents(entry['_directory'], entry.get('instructionRefs', [])):
        add('instruction', entry['_directory'], owner, doc, '能力显式声明的处理指引')
    if template:
        template_owner = owner + Path(template['_directory']).relative_to(entry['_directory']).as_posix() + '/'
        for doc in template['_documents']:
            add('template', template['_directory'], template_owner, doc, '本轮选择的模板指南')
        for doc in read_documents(PROMPTS_ROOT, ['template-reference.md']):
            add('runtime', PROMPTS_ROOT, 'prompts/', doc, '所选模板的运行时参考副本')
    for ref in entry.get('skill_refs', []):
        directory = Path(entry['_skill_root']) / ref
        skill = _skill(entry['_skill_root'], ref)
        needed = validate_refs(skill.get('toolRefs', []), 'Skill.toolRefs')
        is_required = ref in required
        text = ('- ' + ref + '：' + skill['description'] + '\n' + skill['_body'] if is_required else
                '- ' + ref + '：' + skill['description'] + '；适用时先用Read读取 {{skill_path}}')
        add('skill', entry['_skill_root'], 'skills/', {'name': ref + '/SKILL.md', 'text': text},
            '能力声明必载方法' if is_required else '能力声明按需方法，正文尚未注入',
            load='required' if is_required else 'on_demand', needs=needed)
        # 按需正文参与当前摘要，但不向模型或预览输出整篇正文。
        sections[-1]['bodyDigest'] = fingerprint(skill['_body'])
        if not is_required:
            sections[-1]['path'] = str((directory / 'SKILL.md').resolve())
    refs = list(entry.get('tools', []))
    if entry.get('supports_attachments') and 'attachments' not in refs:
        refs.append('attachments')
    for definition in catalog.resolve_many(refs):
        for doc in definition.instructions:
            add('tool', catalog.root / definition.ref, 'tools/' + definition.ref + '/', doc,
                '本轮实际挂载工具的使用说明', tool=definition.ref)
    if sum(len(item['text'].encode('utf-8')) for item in sections) > MAX_DOCUMENT_TOTAL_BYTES:
        raise RuntimeError('提示词资产总量超过限制')
    return {'sections': sections, 'variables': values, 'tools': refs,
            'requiredTools': entry.get('required_tools', []),
            'direct': entry.get('execution', {}).get('mode') == 'direct',
            'date': date.today().isoformat(), 'revision': fingerprint([sections, values])}


def assemble_prompt(assets, *, active_tools, runtime_values=None, preview=False, extra=''):
    """真实执行与管理预览使用同一过滤、渲染和来源说明；预览不推断工具可用性。"""
    active = set(validate_refs(active_tools, 'activeToolRefs'))
    if active - set(assets['tools']):
        raise RuntimeError('提示词工具组合超出能力声明')
    if set(assets['requiredTools']) - active:
        raise RuntimeError('能力必需工具未挂载')
    runtime_values = runtime_values or {}
    if set(runtime_values) - SLOTS:
        raise RuntimeError('提示词运行时变量未登记')
    values = {**assets['variables'], 'current_date': assets['date'], **runtime_values}
    sections, deferred, omitted = [], [], []
    for item in assets['sections']:
        reason = None
        if item['tool'] and item['tool'] not in active:
            reason = '本轮未挂载该工具'
        elif item['load'] == 'no_web' and 'web' in active:
            reason = '本轮已挂载联网工具'
        elif item['load'] == 'direct' and not assets['direct']:
            reason = '本轮不是 direct 模式'
        missing = set(item['needs']) - active
        if missing:
            if item['load'] == 'required':
                raise RuntimeError('必载 Skill 的工具未挂载')
            reason = '本轮缺少该方法所需工具'
        public = {key: item[key] for key in ('kind', 'source', 'reason', 'load')}
        if reason:
            omitted.append({**public, 'reason': reason})
            continue
        section_values = dict(values)
        if item.get('path') and not preview:
            section_values['skill_path'] = item['path']
        unresolved = set(VARIABLE.findall(item['text'])) - section_values.keys()
        if unresolved and not preview:
            raise RuntimeError('提示词缺少必要的运行时变量')
        text = _render(item['text'], {**section_values, **{name: '<运行时:' + name + '>' for name in unresolved}})
        sections.append({**public, 'text': text, 'runtimeSlots': sorted(unresolved)})
        if item['load'] == 'on_demand':
            deferred.append(item['source'])
    if extra:
        if not isinstance(extra, str):
            raise RuntimeError('运行时附加上下文无效')
        sections.append({'kind': 'runtime', 'source': 'runtime/extra-context',
                         'reason': '可信服务端本轮上下文，不属于资产预览', 'load': 'always',
                         'text': extra, 'runtimeSlots': []})
    text = '\n\n'.join(item['text'] for item in sections)
    if len(text.encode('utf-8')) > MAX_DOCUMENT_TOTAL_BYTES:
        raise RuntimeError('有效提示词超过大小限制')
    return {'text': text, 'sections': sections, 'omitted': omitted, 'deferredSkills': deferred,
            'activeToolRefs': sorted(active), 'revision': assets['revision']}
