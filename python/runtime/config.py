"""Shared runtime configuration for the Python Agent SDK worker.

Workflow-owned policy lives under ``.claude/workflows``. Secrets remain in the
process environment and are never copied into prompts or workflow files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tools.artifacts import create_artifact_server
from tools.docx import create_docx_server
from runtime.mcp_auth import inject_mcp_authentication
from runtime.claude_sdk import build_agent_options

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_ROOT = PROJECT_ROOT / ".claude" / "workflows"
DBHUB_ENTRYPOINT = PROJECT_ROOT / "node_modules" / "@bytebase" / "dbhub" / "dist" / "index.js"
TRUE_VALUES = {"1", "true", "yes"}
REQUIRED_ENV = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL")
WORKFLOW_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DATABASE_ENV_KEYS = {
    "DATABASE_URL",
    "DSN",
    "DB_TYPE",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
}
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
    "HTTP_PROXY",
    "NO_PROXY",
}
SDK_ENV_KEYS = {
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CONFIG_DIR",
}
WORKER_CONFIG_ENV_KEYS = {
    "BUSINESS_MCP_URL",
    "CCSDK_BUSINESS_MCP_CAPABILITIES",
    "CCSDK_CLIENT_CAPABILITIES",
    "DB_DEMO",
}
DEFAULT_WORKFLOW_ENV_FILE = "workflow.env"
MAX_WORKFLOW_DOCUMENT_BYTES = 24_000
MAX_WORKFLOW_DOCUMENT_TOTAL_BYTES = 80_000

DATABASE_APPEND = (
    "涉及数据库事实时必须使用 db MCP 工具，先检查结构，再执行必要的 SQL，并基于真实结果回答。"
    "默认只读；除非用户明确授权，不执行写入或结构变更。"
)
LANGUAGE_APPEND = (
    "始终使用简体中文回答，包括思考过程、进度说明、工具调用前的说明、待办事项和最终报告。"
    "代码、标识符、命令、文件路径、日志原文和引用的英文原文保持原样，不要翻译。"
    "即使用户使用英文提问，也用简体中文回答。"
)
NO_WEB_APPEND = (
    "当前运行环境没有可用的联网搜索能力：WebSearch 不可用，不要调用，也不要把它的返回当作搜索结果。"
    "WebFetch 只能抓取用户提供的确切 URL，不能用来搜索或发现网页。"
    "禁止猜测 URL、编造搜索结果、链接、引用或访问日期。"
)
DIRECT_WORKFLOW_APPEND = (
    "当前请求已经由应用后端确定性路由到本 workflow。直接使用已挂载的 MCP 工具完成用户问题，"
    "不要再次调用 Skill、Workflow、Task，不要启动子代理，也不要重复判断或转发 workflow。"
)


def load_runtime_environment(workflow_name: str | None = None) -> None:
    """Load root defaults, then the selected workflow's local environment."""
    runtime_db_demo = os.environ.get("DB_DEMO")
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    workflow_config = load_workflow_config(workflow_name)
    if workflow_config:
        env_path = workflow_environment_path(workflow_config)
        if env_path.is_file():
            load_dotenv(env_path, override=True)
    if runtime_db_demo is not None:
        os.environ["DB_DEMO"] = runtime_db_demo


def missing_environment() -> list[str]:
    return [
        name
        for name in REQUIRED_ENV
        if not os.environ.get(name, "").strip()
        or "YOUR_" in os.environ.get(name, "")
    ]


def agent_environment() -> dict[str, str]:
    """Return only environment values the Claude SDK actually needs.

    Runtime JWTs, the local UI token and database credentials are deliberately
    absent.  Database credentials are added to the DBHub child separately.
    """
    return _select_environment(BASE_PROCESS_ENV_KEYS | SDK_ENV_KEYS)


def database_environment() -> dict[str, str]:
    """Build the narrower environment for the DBHub MCP child process."""
    return _select_environment(BASE_PROCESS_ENV_KEYS | DATABASE_ENV_KEYS)


def worker_environment() -> dict[str, str]:
    """Environment passed to the trusted JSONL worker process.

    The worker still needs database values to construct DBHub and the public
    business-MCP allow-list, but the Java Runtime secret and local API token
    are intentionally excluded before a provider process is started.
    """
    return _select_environment(BASE_PROCESS_ENV_KEYS | SDK_ENV_KEYS
                               | DATABASE_ENV_KEYS | WORKER_CONFIG_ENV_KEYS)


@contextmanager
def isolated_sdk_environment() -> Iterator[None]:
    """Run the provider SDK with only its explicit, non-MCP environment.

    ``ClaudeAgentOptions.env`` is merged with ``os.environ`` by the SDK.  A
    filtered options dict alone therefore does not prevent workflow database
    credentials (or a Runtime/JWT secret loaded from ``.env``) from reaching
    the Claude CLI.  Build MCP configs first, then temporarily replace the
    worker environment while the SDK is alive; DBHub receives its own explicit
    ``database_environment()`` map.
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


def _select_environment(allowed: set[str]) -> dict[str, str]:
    allowed_upper = {item.upper() for item in allowed}
    # Windows preserves the spelling used by the parent process (for example
    # ``SystemRoot``), so compare names case-insensitively.
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed_upper
    }


def _safe_workflow_name(value: Any) -> str | None:
    if value is None:
        return None
    name = str(value).strip()
    if not name:
        return None
    if not WORKFLOW_NAME.fullmatch(name):
        raise RuntimeError(f"workflow 名称不合法：{name}")
    return name


def workflow_environment_path(workflow_config: dict[str, Any]) -> Path:
    directory = Path(str(workflow_config["_directory"])).resolve()
    env_value = workflow_config.get("env_file", DEFAULT_WORKFLOW_ENV_FILE)
    if not isinstance(env_value, str) or not env_value.strip():
        raise RuntimeError("workflow env_file 配置无效")
    env_path = (directory / env_value.strip()).resolve()
    try:
        env_path.relative_to(directory)
    except ValueError as error:
        raise RuntimeError("workflow 环境文件路径越界") from error
    return env_path


def load_workflow_config(workflow_name: str | None) -> dict[str, Any] | None:
    """Load optional JSON config colocated with a workflow script."""
    safe_name = _safe_workflow_name(workflow_name)
    if safe_name is None:
        return None
    directory = (WORKFLOWS_ROOT / safe_name).resolve()
    try:
        directory.relative_to(WORKFLOWS_ROOT.resolve())
    except ValueError as error:
        raise RuntimeError("workflow 配置路径越界") from error
    # Workflows such as professional-report are valid flat SDK scripts and do
    # not need a colocated runtime config directory.
    if not directory.is_dir():
        script_path = (WORKFLOWS_ROOT / f"{safe_name}.js").resolve()
        try:
            script_path.relative_to(WORKFLOWS_ROOT.resolve())
        except ValueError as error:
            raise RuntimeError("workflow 脚本路径越界") from error
        if not script_path.is_file():
            raise RuntimeError(f"workflow 不存在：{safe_name}")
        return None
    config_path = directory / "workflow.json"
    if not config_path.is_file():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"workflow 配置无法读取：{config_path}") from error
    if not isinstance(config, dict):
        raise RuntimeError(f"workflow 配置必须是对象：{config_path}")
    if config.get("name") not in (None, safe_name):
        raise RuntimeError(f"workflow 配置名称不匹配：{config_path}")
    execution = config.get("execution", {})
    if not isinstance(execution, dict):
        raise RuntimeError(f"workflow execution 配置必须是对象：{config_path}")
    if execution.get("mode", "agent") not in {"agent", "direct"}:
        raise RuntimeError(f"workflow execution.mode 配置无效：{config_path}")
    runtime = config.get("runtime", {})
    if not isinstance(runtime, dict):
        raise RuntimeError(f"workflow runtime 配置必须是对象：{config_path}")
    if runtime.get("mode", "query") not in {"query", "client"}:
        raise RuntimeError(f"workflow runtime.mode 配置无效：{config_path}")
    database = config.get("database")
    if database is not None:
        if not isinstance(database, dict):
            raise RuntimeError(f"workflow database 配置必须是对象：{config_path}")
        tables = database.get("allowed_tables", [])
        if not isinstance(tables, list) or any(not isinstance(table, str) or not table.strip() for table in tables):
            raise RuntimeError(f"workflow allowed_tables 配置无效：{config_path}")
        if database.get("read_only") is not True:
            raise RuntimeError(f"database-qa 只允许 read_only=true：{config_path}")
    documents = config.get("documents", {})
    if not isinstance(documents, dict):
        raise RuntimeError(f"workflow documents 配置必须是对象：{config_path}")
    for category in ("constraints", "semantics"):
        paths = documents.get(category, [])
        if not isinstance(paths, list) or any(not isinstance(path, str) or not path.strip() for path in paths):
            raise RuntimeError(f"workflow documents.{category} 配置无效：{config_path}")
    config["_directory"] = str(directory)
    return config


def is_direct_workflow(workflow_config: dict[str, Any] | None) -> bool:
    execution = workflow_config.get("execution") if workflow_config else None
    return isinstance(execution, dict) and execution.get("mode") == "direct"


def runtime_mode_for(capability_ref: str | None, workflow_config: dict[str, Any] | None = None) -> str:
    """Resolve the SDK lifetime from trusted profile configuration.

    The browser and legacy Java callers do not need to send a new mode field.
    A workflow may declare its mode in ``workflow.json``; capability-only
    profiles can use the deployment-owned allow-list.  Unknown capabilities
    remain one-shot Query runs by default.
    """

    capability = str(capability_ref or "conversation").strip()
    runtime = workflow_config.get("runtime") if workflow_config else None
    if isinstance(runtime, dict) and runtime.get("mode") is not None:
        mode = str(runtime.get("mode")).strip()
        if mode in {"query", "client"}:
            return mode
        raise RuntimeError("workflow runtime.mode 配置无效")
    return "client" if capability in _csv_environment("CCSDK_CLIENT_CAPABILITIES") else "query"


def _workflow_database(workflow_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not workflow_config:
        return None
    database = workflow_config.get("database")
    return database if isinstance(database, dict) else None


def _provider_config_path(workflow_config: dict[str, Any]) -> Path | None:
    database = _workflow_database(workflow_config)
    if not database:
        return None
    provider_value = database.get("provider_config")
    if not provider_value:
        return None
    directory = Path(str(workflow_config["_directory"])).resolve()
    provider_path = (directory / str(provider_value)).resolve()
    try:
        provider_path.relative_to(directory)
    except ValueError as error:
        raise RuntimeError("workflow DBHub 配置路径越界") from error
    if not provider_path.is_file():
        raise RuntimeError(f"DBHub 配置文件不存在：{provider_path}")
    return provider_path


def configured_database_tables(workflow_config: dict[str, Any] | None = None) -> list[str]:
    database = _workflow_database(workflow_config)
    if not database:
        return []
    return [table.strip() for table in database.get("allowed_tables", []) if table.strip()]


def _csv_environment(name: str) -> set[str]:
    """Read a deployment-owned comma-separated allow-list."""
    return {
        item.strip()
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    }


def _platform_bearer_present(credentials: Any) -> bool:
    if not isinstance(credentials, dict):
        return False
    value = credentials.get("platformBearer")
    return isinstance(value, str) and bool(value.strip())


def workflow_prompt_documents(workflow_config: dict[str, Any] | None = None) -> str:
    """Load explicitly listed Markdown constraints and semantic hints."""
    if not workflow_config:
        return ""
    documents = workflow_config.get("documents") or {}
    directory = Path(str(workflow_config["_directory"])).resolve()
    sections: list[str] = []
    total_bytes = 0
    for category, title in (("constraints", "Workflow 约束"), ("semantics", "Workflow 语义层")):
        for relative_value in documents.get(category, []):
            relative_path = Path(relative_value)
            if relative_path.suffix.lower() != ".md":
                raise RuntimeError(f"workflow 文档必须是 Markdown：{relative_value}")
            path = (directory / relative_path).resolve()
            try:
                path.relative_to(directory)
            except ValueError as error:
                raise RuntimeError(f"workflow 文档路径越界：{relative_value}") from error
            if not path.is_file():
                raise RuntimeError(f"workflow 文档不存在：{path}")
            content = path.read_text(encoding="utf-8")
            size = len(content.encode("utf-8"))
            if size > MAX_WORKFLOW_DOCUMENT_BYTES:
                raise RuntimeError(f"workflow 文档过大：{path}")
            total_bytes += size
            if total_bytes > MAX_WORKFLOW_DOCUMENT_TOTAL_BYTES:
                raise RuntimeError("workflow 文档总量超过限制")
            sections.append(f"### {title}: {relative_value}\n{content.strip()}")
    return "\n\n".join(sections)


def create_database_mcp_server(workflow_config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build DBHub MCP config from workflow policy and secret environment values."""
    demo = os.environ.get("DB_DEMO", "").lower() in TRUE_VALUES
    database = _workflow_database(workflow_config)
    database_url = os.environ.get("DATABASE_URL", "").strip()
    database_name = str(database.get("name", "")).strip() if database else ""
    db_type = str(database.get("type", "")).strip() if database else os.environ.get("DB_TYPE", "").strip()
    individual = all(os.environ.get(name, "").strip() for name in ("DB_HOST", "DB_USER", "DB_PASSWORD")) and bool(db_type and (database_name or os.environ.get("DB_NAME", "").strip()))
    if database and not demo:
        missing_db_values = [
            name for name in ("DB_HOST", "DB_USER", "DB_PASSWORD")
            if not os.environ.get(name, "").strip()
        ]
        if missing_db_values:
            raise RuntimeError(
                "workflow 数据库配置缺少环境变量：" + ", ".join(missing_db_values)
            )
    if not demo and not database_url and not individual:
        return None
    if not DBHUB_ENTRYPOINT.is_file():
        raise RuntimeError(f"DBHub MCP 入口不存在：{DBHUB_ENTRYPOINT}")

    env = database_environment()
    if database_name:
        env["DB_NAME"] = database_name
    if db_type:
        env["DB_TYPE"] = db_type
    args = [str(DBHUB_ENTRYPOINT), "--transport", "stdio"]
    provider_path = _provider_config_path(workflow_config or {})
    if provider_path:
        env.pop("DSN", None)
        args.extend(["--config", str(provider_path)])
    elif database_url:
        env["DSN"] = database_url
    if demo:
        args.append("--demo")
    return {
        "type": "stdio",
        "command": os.environ.get("NODE_BIN") or shutil.which("node") or "node",
        "args": args,
        "env": env,
    }


def build_system_prompt(
    extra: str = "",
    database_enabled: bool = False,
    workflow_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    parts = [
        "你是师创智能体（AI 师创智能体），代表师创智能体为用户提供可靠、清晰、可执行的帮助。",
        DATABASE_APPEND if database_enabled else "遵循项目 CLAUDE.md 和已加载的项目 Skills；没有可靠证据时明确说明不确定性。",
    ]
    tables = configured_database_tables(workflow_config)
    if database_enabled and tables:
        parts.append(f"本次问数允许的业务表仅限：{', '.join(tables)}。超出范围时明确说明，不要猜测或访问其他表。")
    documents = workflow_prompt_documents(workflow_config)
    if documents:
        parts.append(documents)
    if is_direct_workflow(workflow_config):
        parts.append(DIRECT_WORKFLOW_APPEND)
    parts.extend([LANGUAGE_APPEND, NO_WEB_APPEND])
    if extra.strip():
        parts.append(extra.strip())
    return {"type": "preset", "preset": "claude_code", "append": "\n\n".join(parts)}


def build_options(payload: dict[str, Any]) -> ClaudeAgentOptions:
    workflow_config = load_workflow_config(payload.get("workflow_name"))
    direct_workflow = is_direct_workflow(workflow_config)
    capability_ref = str(
        payload.get("capability_ref") or payload.get("workflow_name") or "conversation"
    ).strip()
    database_server = create_database_mcp_server(workflow_config)
    database_enabled = database_server is not None
    mcp_servers: dict[str, Any] = {}
    if database_server:
        mcp_servers["db"] = database_server
    session_directory = payload.get("session_directory")
    work_directory = payload.get("work_directory")
    deliverables_directory = payload.get("deliverables_directory")
    artifact_enabled = bool(session_directory and work_directory and deliverables_directory)
    if artifact_enabled and not direct_workflow:
        mcp_servers["artifacts"] = create_artifact_server(
            session_directory,
            work_directory,
            deliverables_directory,
        )
    business_mcp_url = os.environ.get("BUSINESS_MCP_URL", "").strip()
    business_capabilities = _csv_environment("CCSDK_BUSINESS_MCP_CAPABILITIES")
    credentials = payload.get("credentials")
    # A business MCP is never mounted merely because its URL exists.  An
    # operator may explicitly allow capabilities through the environment; in
    # the small MVP, the presence of the Java-supplied bearer is the fallback
    # signal for a capability that has no separate allow-list yet.
    # Fail closed when the operator has not declared which capabilities may
    # mount the business MCP.  A bearer's mere presence must never expand the
    # tool set for an otherwise ordinary conversation.
    business_allowed = capability_ref in business_capabilities
    if business_mcp_url and business_allowed:
        mcp_servers["business"] = {"type": "http", "url": business_mcp_url}
    if not direct_workflow:
        docx_server = create_docx_server(
            payload.get("cwd") or Path.cwd(),
            [
                *(payload.get("additional_directories") or []),
                *(item for item in [work_directory, deliverables_directory] if item),
            ],
        )
        mcp_servers["docx"] = docx_server
    # Credentials are request-scoped. Rules decide which registered MCP may
    # receive the bearer; no process-global environment is changed.
    mcp_servers = inject_mcp_authentication(mcp_servers, credentials)
    allowed_tools = [] if direct_workflow else ["mcp__docx__*"]
    if database_enabled:
        allowed_tools.append("mcp__db__*")
    if artifact_enabled and not direct_workflow:
        allowed_tools.append("mcp__artifacts__*")
    requested_skills = (workflow_config or {}).get("skills", payload.get("skill_refs") or [])
    if not isinstance(requested_skills, list) or any(not isinstance(item, str) or not WORKFLOW_NAME.fullmatch(item) for item in requested_skills):
        raise RuntimeError("skill_refs 配置无效")
    if requested_skills:
        for skill in requested_skills:
            skill_directory = (PROJECT_ROOT / ".claude" / "skills" / skill).resolve()
            try:
                skill_directory.relative_to((PROJECT_ROOT / ".claude" / "skills").resolve())
            except ValueError as error:
                raise RuntimeError("skill 路径越界") from error
            if not (skill_directory / "SKILL.md").is_file():
                raise RuntimeError(f"skill 不存在：{skill}")
        skills = [] if direct_workflow else requested_skills
    else:
        skills = [] if direct_workflow else None
    return build_agent_options(
        model=payload.get("model") or os.environ.get("ANTHROPIC_MODEL"),
        cwd=payload.get("cwd") or Path.cwd(),
        resume=payload.get("resume"),
        max_turns=payload.get("max_turns") or int(os.environ.get("SCRIBE_MAX_TURNS", "30")),
        include_partial_messages=bool(payload.get("include_partial_messages")),
        setting_sources=[] if direct_workflow else ["project", "local"],
        system_prompt=build_system_prompt(
            payload.get("system_prompt_append") or "",
            database_enabled,
            workflow_config,
        ),
        tools=[] if direct_workflow else {"type": "preset", "preset": "claude_code"},
        disallowed_tools=["WebSearch"],
        allowed_tools=allowed_tools,
        skills=skills,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        strict_mcp_config=direct_workflow,
        add_dirs=payload.get("additional_directories") or [],
        env=agent_environment(),
    )
