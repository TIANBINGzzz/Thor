"""SDK Worker 的通用配置；能力规则归执行资产，秘密仅从部署快照按需注入。"""

from __future__ import annotations

import json
import hashlib
import os
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any


from data_access.context import fingerprint, DataError
from runtime.mcp_auth import inject_mcp_authentication, validate_capability_credentials
from runtime.claude_sdk import build_agent_options, CLIENT_HOT_ENV_KEYS, AGENT_BUILTIN_TOOLS
from runtime.capabilities import capability_entry, resolve_capability
from runtime.deployment_config import (ConfigSnapshot, deployment_section, worker_configuration,
                                       WORKER_CONFIGURATION_ENV, configuration_scope)
from runtime.runtime_settings import RUNTIME_SETTINGS, load_model_settings
from runtime.prompt_assembly import assemble_prompt, load_prompt_assets, shared_system_prompt
from runtime.tool_services import ToolServices, load_tool_assets
from runtime.tool_registry import build_registered_tools
from runtime.mcp_providers import load_mcp_connections

PROJECT_ROOT = Path(__file__).resolve().parents[2]
class _ModelSettings:
    def __getattr__(self, name):
        return getattr(load_model_settings(), name)

MODEL_SETTINGS = _ModelSettings()
REQUIRED_ENV = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
BASE_PROCESS_ENV_KEYS = {
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PYTHONPATH",
    "NODE_BIN",
    "LANG",
    "LC_ALL",
    "TZ",
    "TERM",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
}
SDK_ENV_KEYS = {
    # 渲染回调在 SDK 环境内执行，保留非秘密的引擎位置配置。
    "CCSDK_LIBREOFFICE_PATH",
    "CCSDK_UNO_PYTHON",
    "CCSDK_RENDER_IMAGE",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CONFIG_DIR",
}
WORKER_CONFIG_ENV_KEYS = {
    "CCSDK_OFFICECLI_PATH",
    "CCSDK_LIBREOFFICE_PATH",
    "CCSDK_UNO_PYTHON",
    "CCSDK_RENDER_IMAGE",
    "CCSDK_ENABLE_TIMING",
    "CCSDK_OBSERVABILITY_ENABLED",
}
def missing_environment() -> list[str]:
    """检查当前进程中的必需模型配置，返回缺失的环境变量名称列表。"""
    model = deployment_section('model', {})
    return [name for name, field in (('ANTHROPIC_AUTH_TOKEN', 'apiKey'), ('ANTHROPIC_BASE_URL', 'baseUrl'))
            if not model.get(field)]


def agent_environment(environ=None) -> dict[str, str]:
    """从当前进程环境返回 SDK 所需变量的白名单字典，不包含 Runtime、UI 和数据库凭据。

    数据库凭据仅由受保护配置提供给进程内 data 执行器。
    """
    environ = os.environ if environ is None else environ
    environment = _select_environment(BASE_PROCESS_ENV_KEYS | SDK_ENV_KEYS, environ)
    model = deployment_section('model', {})
    environment.pop('ANTHROPIC_AUTH_TOKEN', None)
    environment.pop('ANTHROPIC_BASE_URL', None)
    if model:
        environment.update(ANTHROPIC_AUTH_TOKEN=model['apiKey'], ANTHROPIC_BASE_URL=model['baseUrl'])
    environment.update(MODEL_SETTINGS.environment())
    # 禁用 CLI 的自动后台化；Hook 同时拒绝模型显式申请后台 Shell。
    environment['CLAUDE_CODE_DISABLE_BACKGROUND_TASKS'] = '1'
    # Runtime 已按轮选择 MCP；CLI 延迟发现缓存会在撤销后保留旧工具定义。
    environment['ENABLE_TOOL_SEARCH'] = 'false'
    office = environ.get('CCSDK_OFFICECLI_PATH')
    if office and Path(office).is_file():
        # Bash与原生MCP使用同一工具版本，避免系统PATH上的旧版本读取同一文件。
        path_key = next((key for key in environment if key.upper() == 'PATH'), 'PATH')
        environment[path_key] = str(Path(office).resolve().parent) + os.pathsep + environment.get(path_key, '')
    return environment


def worker_environment() -> dict[str, str]:
    """从当前进程环境返回可信 JSONL Worker 所需的变量字典。

    可信 Worker 接收必要的部署快照；SDK 环境另按白名单筛选。
    """
    environment = _select_environment(BASE_PROCESS_ENV_KEYS | SDK_ENV_KEYS
                                      | WORKER_CONFIG_ENV_KEYS)
    environment.update(MODEL_SETTINGS.environment())
    configuration = worker_configuration()
    if configuration is not None:
        environment[WORKER_CONFIGURATION_ENV] = json.dumps(configuration, ensure_ascii=True, separators=(',', ':'))
    return environment


@contextmanager
def isolated_sdk_environment() -> Iterator[None]:
    """提供无参数上下文管理器，临时将当前 Worker 环境替换为 SDK 白名单，退出时恢复原环境。

    SDK 会合并 os.environ，因此须先装配 MCP 配置；data服务持有独立配置快照。
    """
    original = dict(os.environ)
    safe = agent_environment()
    os.environ.clear()
    os.environ.update(safe)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def _select_environment(allowed: set[str], environ=None) -> dict[str, str]:
    """大小写无关地筛选跨平台进程变量，避免扩散凭据。"""
    allowed_upper = {item.upper() for item in allowed}
    # Windows preserves the spelling used by the parent process (for example
    # ``SystemRoot``), so compare names case-insensitively.
    return {
        key: value
        for key, value in (os.environ if environ is None else environ).items()
        if key.upper() in allowed_upper
    }


def is_direct_capability(capability_config: dict[str, Any] | None) -> bool:
    """检查输入配置的 execution.mode，返回是否采用 direct 执行模式。"""
    execution = capability_config.get("execution") if capability_config else None
    return isinstance(execution, dict) and execution.get("mode") == "direct"


def runtime_mode_for(capability_ref: str | None, *, capability_config=None) -> str:
    """运行方式只由可信能力声明，未声明时使用 query。"""
    capability = str(capability_ref or 'conversation').strip()
    entry = capability_config if capability_config is not None else capability_entry(resolve_capability(capability).directory)
    runtime = entry.get('runtime', {})
    if runtime.get('mode') is not None:
        return runtime['mode']
    return 'query'


def load_execution_entry(capability_ref):
    from runtime.configuration import execution_entry
    return execution_entry(capability_ref)

def prepare_capability_assets(payload):
    assets = payload.get('_capability_assets')
    if assets is not None and ('selection' not in assets or assets['selection'] == [payload.get('capability_ref'), payload.get('_template_key')]):
        return assets
    local = payload.get('_execution_entry') or load_execution_entry(payload.get('capability_ref'))
    payload['_execution_entry'] = local
    with configuration_scope(local.get('_configuration')):
        return _prepare_capability_assets(payload)


def with_payload_configuration(function):
    from functools import wraps
    @wraps(function)
    def call(payload, *args, **kwargs):
        assets = prepare_capability_assets(payload)
        with configuration_scope(assets.get('_configuration')):
            return function(payload, *args, **kwargs)
    return call

def _prepare_capability_assets(payload):
    """保留本轮已解析配置与资产摘要，不新增持久化快照或版本仓库。"""
    selection = [payload.get('capability_ref'), payload.get('_template_key')]
    if (payload.get('_capability_assets') or {}).get('selection') != selection:
        from runtime.template_assets import load_template
        local = payload.get('_execution_entry') or load_execution_entry(payload.get('capability_ref'))
        entry = local['capability']
        template_key = payload.get('_template_key')
        template = load_template(template_key, payload.get('capability_ref'), entry=entry) if template_key is not None else None
        environment = dict(os.environ)
        settings = ConfigSnapshot()
        tool_assets = load_tool_assets(entry, settings)
        mcp_connections = load_mcp_connections(entry, settings, environment=environment)
        prompt_assets = load_prompt_assets(entry, template=template)
        content = assemble_prompt(prompt_assets, active_tools=entry['tools'], preview=True)['text']
        runtime = entry.get('runtime', {})
        revisions = {name: value['revision'] for name, value in tool_assets.items()}
        sources = sorted(set(template['source_roles'].values())) if template else None
        revision = template['_revision'] if template else None
        config_values = settings.export()
        payload['_capability_assets'] = {'selection': selection, 'capability': entry, 'prompt': content, 'prompt_assets': prompt_assets,
            'tool_revisions': revisions, 'runtime': runtime, 'config_values': config_values,
            'mcp_connections': mcp_connections,
            'template_revision': revision, 'template_sources': sources,
            'revision': fingerprint([entry, content, revision, revisions, runtime, config_values, mcp_connections, prompt_assets['revision']]),
            '_configuration': worker_configuration()}
    return payload['_capability_assets']

@with_payload_configuration
def data_source_keys(payload):
    """按能力和模板缩小已授权来源，不由连接存在与否扩大权限。"""
    assets = prepare_capability_assets(payload)
    data = assets['capability'].get('data', {})
    mode = data.get('access')
    if mode is None:
        return []
    sources = list(data.get('sourceRefs', []))
    if assets['template_sources'] is not None:
        selected = assets['template_sources']
        if not selected or not set(selected) <= set(sources):
            raise DataError('SOURCE_FORBIDDEN')
        return selected
    if mode == 'optional' and not payload.get('_template_key'):
        from data_access.connections import load_config
        configured = load_config(os.environ, optional=True)
        return [source for source in sources if source in configured]
    if not sources:
        raise RuntimeError('本轮能力没有已登记的数据源')
    return sources


@with_payload_configuration
def create_run_services(payload):
    """仅为声明数据需求且具有绑定来源的执行创建数据服务。"""
    entry = prepare_capability_assets(payload)['capability']
    # 能力凭据每轮检查；共享 data 工具不因此改变其他能力的要求。
    validate_capability_credentials(entry, payload.get('credentials'))
    sources = data_source_keys(payload)
    if not sources:
        return None
    # 执行器会加载 SQLAlchemy/SQL 解析器，只在本轮确实绑定数据来源时导入。
    from runtime.data_services import RunServices
    return RunServices(sources, context_topics=entry.get('data', {}).get('contextTopics'))


def _shared_system_prompt(runtime):
    return {'type': 'custom',
            'prompt': shared_system_prompt(),
            'snapshot': runtime.get('system_prompt_snapshot', True)}


def _merge_mcp_servers(registered_servers, client_servers):
    """合并本轮与 Client 工具时拒绝同名遮蔽，避免复用连接指向错误处理器。"""
    collisions = set(registered_servers) & set(client_servers)
    if collisions:
        raise RuntimeError('MCP 服务名称冲突')
    return {**registered_servers, **client_servers}


def resolve_model(runtime: dict, default: str | None = None) -> str:
    """能力只选择部署已开放的模型；空字符串沿用部署默认或可信内部默认。"""
    selected = runtime.get('model')
    return selected or default or MODEL_SETTINGS.default


@with_payload_configuration
def build_options(payload: dict[str, Any], data_services=None, artifact_sink=None, chart_sink=None, tool_services=None, mcp_error_sink=None, turn_policy=None):
    """接收内部执行 payload，装配模型、目录、提示词、Skill 和 MCP，返回 ClaudeAgentOptions。

    按流程策略限制工具，并仅向指定 MCP 的配置副本注入本次请求凭据。
    """
    assets = prepare_capability_assets(payload)
    capability_config = assets['capability']
    validate_capability_credentials(capability_config, payload.get('credentials'))
    direct_capability = is_direct_capability(capability_config)
    capability_ref = str(
        payload.get("capability_ref") or "conversation"
    ).strip()
    model = resolve_model(assets['runtime'], payload.get('model'))
    data_services = data_services or create_run_services(payload)
    registered_template = assets['template_revision'] is not None
    entry = assets['capability']
    restricted_tools = direct_capability
    session_directory = payload.get("session_directory")
    work_directory = payload.get("work_directory")
    deliverables_directory = payload.get("deliverables_directory")
    artifact_enabled = bool(session_directory and work_directory and deliverables_directory)
    runtime_values = {}
    if registered_template:
        from runtime.template_assets import load_template, stage_template
        if not artifact_enabled:
            raise DataError('TEMPLATE_WORKSPACE_REQUIRED')
        template = load_template(payload['_template_key'], payload.get('capability_ref'), entry=entry)
        if template['_revision'] != assets['template_revision']:
            raise DataError('TEMPLATE_MISMATCH')
        template_path = stage_template(template, work_directory)
        runtime_values.update(template_path=str(template_path), template_file_name=template['file_name'])
    credentials = payload.get("credentials")
    tool_services = tool_services or ToolServices(assets, credentials)
    registered = build_registered_tools(entry, {
        'model': model, 'restricted': restricted_tools, 'data_services': data_services,
        'chart_sink': chart_sink, 'artifact_sink': artifact_sink,
        'artifact_enabled': artifact_enabled, 'session_directory': session_directory,
        'work_directory': work_directory, 'deliverables_directory': deliverables_directory,
        'run_id': payload.get('run_id'),
        'capability_ref': capability_ref,
        'mcp_connections': assets['mcp_connections'],
        'input_directory': payload.get('input_directory'), 'cwd': payload.get('cwd'),
        'additional_directories': payload.get('additional_directories'),
        'provided_tools': tool_services.tool_refs & tool_services.services.keys(),
        'operation_services': tool_services,
        'mcp_error_sink': mcp_error_sink,
    })
    mcp_servers = _merge_mcp_servers(
        registered.servers, tool_services.servers(on_error=mcp_error_sink))
    # 只有静态 Tool Catalog 中登记的 MCP 才有凭据规则；能力 Operation
    # 使用独立 namespace，不能借用另一个 MCP 的 Token 接收配置。
    auth_refs = registered.auth_refs
    secured = inject_mcp_authentication(
        {ref: mcp_servers[ref] for ref in auth_refs}, credentials,
        allowed_refs=sorted(auth_refs))
    mcp_servers.update(secured)
    if artifact_enabled:
        runtime_values.update(work_directory=str(work_directory), deliverables_directory=str(deliverables_directory))
    prompt_tool_refs = set(assets['prompt_assets']['tools'])
    active_prompt_tools = [name for name in mcp_servers if name in prompt_tool_refs]
    stage_skill_files(assets['prompt_assets'], work_directory)
    effective_prompt = assemble_prompt(assets['prompt_assets'], active_tools=active_prompt_tools,
        runtime_values=runtime_values, extra=payload.get('system_prompt_append') or '')
    exact_tools = registered.exact_tools
    exact_tools.update({name: tool_services.services[name].tool_names()
                        for name in tool_services.tool_refs & tool_services.services.keys()})
    allowed_tools = ['mcp__' + name + '__' + tool
                     for name in mcp_servers for tool in entry.get('_mcp_allowlists', {}).get(name, exact_tools.get(name, ['*']))]
    # Skill以受控引用按需读取，禁用SDK未登记的自动发现。
    skills = []
    runtime = {**assets["runtime"], **payload.get('_client_runtime', {})}
    sdk_env = agent_environment(dict(os.environ))
    extra_body = dict(deployment_section('model', {}).get('parameters', {}))
    if runtime.get('max_output_tokens'):
        extra_body['max_tokens'] = runtime['max_output_tokens']
    if extra_body:
        sdk_env['CLAUDE_CODE_EXTRA_BODY'] = json.dumps(extra_body)
    if (runtime.get('thinking') or {}).get('type') == 'disabled':
        # SDK 的 disabled 会省略请求字段；兼容端可能默认开启思考，须显式关闭。
        sdk_env['CLAUDE_CODE_EXTRA_BODY'] = json.dumps({**extra_body, 'thinking': {'type': 'disabled'}})
    options = build_agent_options(
        model=model,
        thinking=runtime.get("thinking"),
        effort=runtime.get("effort"),
        cwd=payload.get("cwd") or Path.cwd(),
        resume=payload.get("resume"),
        max_turns=payload.get("max_turns") or runtime.get("max_turns") or RUNTIME_SETTINGS.limits.max_turns,
        include_partial_messages=bool(payload.get("include_partial_messages")),
        # 文档核验读取页面图片会产生较大的JSONL消息，默认1MiB会在发布前中断。
        max_buffer_size=RUNTIME_SETTINGS.limits.sdk_buffer_bytes,
        setting_sources=[] if restricted_tools else ["project", "local"],
        verbatim_prompts=True,
        system_prompt=({'type': 'custom', 'prompt': effective_prompt['text'],
                        'snapshot': runtime.get('system_prompt_snapshot', True)}
                       if runtime.get('prompt_mode') == 'custom' else
                       {'type': 'preset', 'preset': 'claude_code', 'append': effective_prompt['text'],
                        'snapshot': runtime.get('system_prompt_snapshot', True)}),
        tools=list(AGENT_BUILTIN_TOOLS),
        disallowed_tools=['WebSearch'],
        allowed_tools=allowed_tools,
        skills=skills,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        strict_mcp_config=restricted_tools,
        add_dirs=payload.get("additional_directories") or [],
        env=sdk_env,
    )
    if turn_policy is not None:
        # query 的历史也可被 Client 恢复，首轮快照只能保存共同底座。
        turn_policy.bind(options)
        options.system_prompt = _shared_system_prompt(runtime)
        options.hooks = turn_policy.hooks()
    return options


def _client_connection_values(payload):
    """仅包含 SDK 连接后无法可靠热更新的选项。秘密值只参与内存哈希。"""
    runtime = payload['_client_runtime'] if '_client_runtime' in payload else prepare_capability_assets(payload)['runtime']
    entry = ((payload.get('_execution_entry') or {}).get('capability')
             or (payload.get('_capability_assets') or {}).get('capability')
             or capability_entry(resolve_capability(payload.get('capability_ref')).directory))
    effective = dict(os.environ)
    environment = agent_environment(effective)
    environment = {key: value for key, value in environment.items() if key not in CLIENT_HOT_ENV_KEYS}
    return dict(cwd=str(Path(payload.get('cwd') or Path.cwd()).resolve()), env=environment,
                tools=list(AGENT_BUILTIN_TOOLS),
                max_turns=payload.get('max_turns') or runtime.get('max_turns') or RUNTIME_SETTINGS.limits.max_turns,
                system_prompt=_shared_system_prompt(runtime),
                include_partial_messages=True,
                extra_args={'replay-user-messages': None})


@with_payload_configuration
def client_connection_fingerprint(payload):
    values = _client_connection_values(payload)
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@with_payload_configuration
def inherit_client_runtime(payload, previous=None):
    """逐轮使用当前配置，不让上一能力的推理参数和预算覆盖数据库。"""
    assets = prepare_capability_assets(payload)
    declared = assets['runtime']
    fields = ('thinking', 'effort', 'max_turns', 'system_prompt_snapshot')
    runtime = {name: declared[name] for name in fields if name in declared}
    if runtime.get('max_turns') is None:
        runtime['max_turns'] = RUNTIME_SETTINGS.limits.max_turns
    runtime.setdefault('system_prompt_snapshot', True)
    payload['_client_runtime'] = runtime
    payload['_client_connection_fingerprint'] = client_connection_fingerprint(payload)
    return runtime


@with_payload_configuration
def build_client_options(payload, policy):
    """空白 Client 不加载业务 MCP、数据连接或凭据，领取后的首轮才装配。"""
    values = _client_connection_values(payload)
    values['env'] = agent_environment()
    return build_agent_options(**values, thinking=None, effort=None, add_dirs=[],
        model=payload.get('model') or MODEL_SETTINGS.default, resume=payload.get('resume'),
        verbatim_prompts=True,
        skills=[], setting_sources=[],
        strict_mcp_config=True, mcp_servers={}, disallowed_tools=['WebSearch'],
        permission_mode='bypassPermissions', hooks=policy.hooks(), max_buffer_size=RUNTIME_SETTINGS.limits.sdk_buffer_bytes)


def stage_skill_files(prompt_assets, work_directory):
    """按需方法只写入本轮工作目录；执行中读取的正文不随管理端编辑改变。"""
    if work_directory:
        import shutil
        directory = Path(work_directory) / '.skills'
        if directory.exists(): shutil.rmtree(directory)
    for section in prompt_assets['sections']:
        if section['load'] != 'on_demand' or 'body' not in section:
            continue
        if not work_directory:
            raise ValueError('skill_workspace_required')
        ref = section['source'].split('/')[1]
        directory = Path(work_directory) / '.skills' / ref
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'SKILL.md').write_text(section['body'], encoding='utf-8')
        for name, content in section.get('resources', {}).items():
            path = (directory/name).resolve()
            if not path.is_relative_to(directory.resolve()) or path.suffix.lower() not in {'.md','.txt','.json','.csv'}:
                raise ValueError('skill_resource_invalid')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(content,encoding='utf-8')
        section['path'] = str((directory/'SKILL.md').resolve())
