"""FastAPI HTTP/SSE service for sessions, files, references, and Agent runs."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from starlette.datastructures import UploadFile

from local.references import is_source, list_sources, reference_prompt_context, search_source
from local.sessions import (
    MAX_FILE_BYTES,
    cleanup_session,
    create_session,
    decode_file_id,
    list_session_files,
    list_sessions,
    load_session,
    resolve_session_file,
    save_uploads,
    session_deliverables_directory,
    session_directory,
    session_prompt_context,
    session_stats,
    session_work_directory,
    update_session,
    update_session_model,
    upsert_session_turn,
    web_session,
)
from runtime.config import load_runtime_environment, load_workflow_config
from runtime.auth import JWTError, verify_run_jwt
from runtime.protocol import AgentRunRequest, ProtocolError
from runtime.process import prompt_without_workflow_prefix, stream_agent, workflow_name_from_prompt
from runtime.run_store import RunStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]


load_runtime_environment()
HOST = "127.0.0.1"
PORT = int(os.environ.get("SCRIBE_PORT", "4310"))
MAX_PROMPT_BYTES = 32 * 1024
MODELS = list(dict.fromkeys(
    model.strip()
    for model in (os.environ.get("SCRIBE_MODELS") or os.environ.get("ANTHROPIC_MODEL") or "").split(",")
    if model.strip()
))
TOKEN = os.environ.get("SCRIBE_TOKEN") or secrets.token_hex(24)
RUNTIME_JWT_SECRET = (
    os.environ.get("CCSDK_RUNTIME_JWT_SECRET")
    or os.environ.get("SCRIBE_RUNTIME_JWT_SECRET")
    or ""
).strip()
RUNTIME_JWT_AUDIENCE = os.environ.get("CCSDK_RUNTIME_JWT_AUDIENCE", "ccsdk-runtime").strip()
# Keep an explicit default so ``iss`` is always checked against the Java
# control-plane identity.  Deployments may override it, but an omitted issuer
# must not silently disable this binding check.
RUNTIME_JWT_ISSUER = os.environ.get(
    "CCSDK_RUNTIME_JWT_ISSUER", "string-ai-center-service"
).strip()
RUN_STORE = RunStore(os.environ.get("SCRIBE_RUN_DB", str(PROJECT_ROOT / ".scribe-runs" / "runs.sqlite3")))
active_runs: dict[str, asyncio.Task[Any] | None] = {}
active_runs_lock = asyncio.Lock()
internal_tasks: dict[str, asyncio.Task[Any]] = {}
internal_subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
internal_runs_lock = asyncio.Lock()
INTERNAL_BODY_BYTES = 2 * 1024 * 1024
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled"}
SSE_HEARTBEAT_SECONDS = max(1.0, float(os.environ.get("CCSDK_SSE_HEARTBEAT_SECONDS", "15")))


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    tasks = [task for task in active_runs.values() if task is not None]
    tasks.extend(internal_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def _plain(message: str, status: int) -> PlainTextResponse:
    return PlainTextResponse(
        message,
        status_code=status,
        headers={"cache-control": "no-store", "x-content-type-options": "nosniff"},
    )


@app.middleware("http")
async def secure_local_api(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    host = request.headers.get("host", "")
    if host not in {f"{HOST}:{PORT}", f"localhost:{PORT}"}:
        return _plain("Host 不被允许", 421)
    # Internal Runtime calls authenticate with a short-lived Run JWT at the
    # route, not with the browser's local x-scribe-token header.  Keep Origin
    # blocked because this endpoint is Java-to-Python server traffic.
    if request.url.path.startswith("/internal/v1/"):
        if request.headers.get("origin"):
            return _plain("校验失败", 403)
        return await call_next(request)
    if request.headers.get("origin") or request.headers.get("x-scribe-token") != TOKEN:
        return _plain("校验失败", 403)
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/models")
async def models() -> dict[str, list[str]]:
    return {"models": MODELS}


@app.get("/api/sources")
async def sources() -> dict[str, Any]:
    return {"sources": list_sources()}


@app.get("/api/options")
async def options(source: str = "", q: str = "", limit: str = "20", offset: str = "0"):
    if not is_source(source):
        return _plain("source 不在允许列表中", 400)
    return search_source(source, q, limit=limit, offset=offset)


@app.get("/api/sessions")
async def sessions() -> dict[str, Any]:
    return {"sessions": list_sessions()}


async def _small_json(request: Request, maximum: int = MAX_PROMPT_BYTES) -> dict[str, Any]:
    body = await request.body()
    if len(body) > maximum:
        raise ValueError("请求体过大")
    if not body:
        return {}
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("请求体不是合法 JSON") from error
    if not isinstance(value, dict):
        raise ValueError("请求体不是合法 JSON")
    return value


class _InternalAuthError(ValueError):
    """Authentication/authorization failure for the Java-to-Python API."""


def _bearer_from_request(request: Request) -> str:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _InternalAuthError("缺少 Runtime Bearer JWT")
    return token.strip()


def _claim_scope(claims: dict[str, Any]) -> set[str]:
    scope = claims.get("scope")
    if isinstance(scope, str):
        return {scope}
    if isinstance(scope, list) and all(isinstance(item, str) for item in scope):
        return set(scope)
    return set()


def _require_claim_identity(claims: dict[str, Any]) -> None:
    """Require the Java-issued principal on every internal Runtime call."""
    for name in ("sub", "tenant"):
        value = claims.get(name)
        if not isinstance(value, str) or not value.strip():
            raise _InternalAuthError(f"Runtime JWT 缺少 {name}")


def _authorize_internal(
    request: Request,
    run: dict[str, Any],
    *,
    allowed_scopes: set[str],
    consume_jti: bool,
) -> dict[str, Any]:
    if not RUNTIME_JWT_SECRET:
        raise _InternalAuthError("Runtime JWT 未配置")
    run_id = str(run.get("runId") or "")
    capability = str(run.get("capabilityRef") or "conversation")
    token = _bearer_from_request(request)
    try:
        claims = verify_run_jwt(
            token,
            RUNTIME_JWT_SECRET,
            run_id=run_id,
            capability_ref=capability,
            turn_id=run.get("turnId"),
            business_session_id=run.get("businessSessionId"),
            body={
                "runId": run_id,
                "capabilityRef": capability,
                "turnId": run.get("turnId"),
                "businessSessionId": run.get("businessSessionId"),
            },
            audience=RUNTIME_JWT_AUDIENCE,
            issuer=RUNTIME_JWT_ISSUER,
            expected_scope="",
            consume_jti=consume_jti,
        )
    except JWTError as error:
        raise _InternalAuthError(str(error)) from error
    _require_claim_identity(claims)
    if not (_claim_scope(claims) & allowed_scopes):
        raise _InternalAuthError("Runtime JWT scope 不允许此操作")
    if run.get("tenantId") is not None and claims.get("tenant") != run["tenantId"]:
        raise _InternalAuthError("租户不匹配")
    if run.get("userId") is not None and claims.get("sub") != run["userId"]:
        raise _InternalAuthError("用户不匹配")
    return claims


def _authorize_new_request(request: Request, run_request: AgentRunRequest) -> dict[str, Any]:
    if not RUNTIME_JWT_SECRET:
        raise _InternalAuthError("Runtime JWT 未配置")
    capability = run_request.capability_ref or "conversation"
    wire = run_request.to_dict()
    # Conversation requests intentionally omit capabilityRef in the public
    # model; bind them to the signed, fixed ``conversation`` capability.
    wire["capabilityRef"] = capability
    token = _bearer_from_request(request)
    try:
        claims = verify_run_jwt(
            token,
            RUNTIME_JWT_SECRET,
            body=wire,
            audience=RUNTIME_JWT_AUDIENCE,
            issuer=RUNTIME_JWT_ISSUER,
            expected_scope="run.execute",
        )
    except JWTError as error:
        raise _InternalAuthError(str(error)) from error
    _require_claim_identity(claims)
    context = run_request.context
    if context.tenant_id is not None and claims.get("tenant") != context.tenant_id:
        raise _InternalAuthError("租户不匹配")
    if context.user_id is not None and claims.get("sub") != context.user_id:
        raise _InternalAuthError("用户不匹配")
    return claims


def _public_internal_event(run_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Translate one SDK event to the small public event contract."""
    raw_type = str(raw.get("type") or "activity")
    if raw_type == "text":
        text = raw.get("text")
        if isinstance(text, str) and text:
            return {
                "runId": run_id,
                "type": "message.delta",
                "payload": {"textDelta": text},
            }
        return {"runId": run_id, "type": "phase", "payload": {"name": "response"}}
    if raw_type == "thinking":
        return {"runId": run_id, "type": "phase", "payload": {"name": "thinking"}}
    if raw_type in {"tool_use", "tool_progress", "tool_result"}:
        status = "finished" if raw_type == "tool_result" else "started"
        return {
            "runId": run_id,
            "type": "tool.finished" if raw_type == "tool_result" else "tool.started",
            "payload": {"status": status},
        }
    if raw_type == "init":
        return {"runId": run_id, "type": "phase", "payload": {"name": "started"}}
    if raw_type == "result":
        ok = raw.get("ok") is True
        usage = {
            key: int(raw[key])
            for key in ("inputTokens", "outputTokens", "turns")
            if isinstance(raw.get(key), (int, float)) and not isinstance(raw.get(key), bool)
        }
        return {
            "runId": run_id,
            "type": "run.completed" if ok else "run.failed",
            "payload": usage,
        }
    if raw_type == "error":
        return {"runId": run_id, "type": "run.failed", "payload": {"code": "runtime_error"}}
    return {"runId": run_id, "type": "phase", "payload": {"name": "working"}}


def _public_legacy_event(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep the old local UI event names while removing sensitive details."""
    kind = str(raw.get("type") or "activity")
    if kind == "text":
        return {"type": "text", "scope": raw.get("scope", "main"), "text": str(raw.get("text") or "")}
    if kind == "thinking":
        return {"type": "thinking", "scope": raw.get("scope", "main")}
    if kind == "tool_use":
        return {
            "type": "tool_use",
            "scope": raw.get("scope", "main"),
            "id": raw.get("id"),
            "name": str(raw.get("name") or "tool")[:160],
        }
    if kind == "tool_result":
        return {"type": "tool_result", "scope": raw.get("scope", "main"), "id": raw.get("id"), "isError": raw.get("isError") is True}
    if kind == "init":
        return {
            "type": "init",
            "model": raw.get("model"),
            "tools": raw.get("tools", 0),
            "skills": [],
            "agents": [],
            "commands": [],
        }
    if kind == "result":
        return {
            "type": "result",
            "ok": raw.get("ok") is True,
            "durationMs": raw.get("durationMs"),
            "turns": raw.get("turns"),
            "inputTokens": raw.get("inputTokens", 0),
            "outputTokens": raw.get("outputTokens", 0),
        }
    if kind == "activity":
        return {"type": "activity", "scope": raw.get("scope", "main"), "label": str(raw.get("label") or "working")[:160]}
    if kind == "tool_progress":
        return {"type": "tool_progress", "scope": raw.get("scope", "main")}
    if kind == "error":
        # Provider errors may contain URLs, command lines or credential
        # fragments.  The local compatibility API has the same public
        # boundary as the Java bridge, so expose only a stable message.
        return {"type": "error", "message": "Agent 执行失败"}
    return {"type": "activity", "scope": "main", "label": "working"}


async def _publish_internal_event(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    clean = {"protocolVersion": "agent-events/v1", **event}
    stored = RUN_STORE.append_event(run_id, clean)
    async with internal_runs_lock:
        queues = list(internal_subscribers.get(run_id, set()))
    for queue in queues:
        queue.put_nowait(stored)
    return stored


def _internal_worker_payload(run_request: AgentRunRequest, run_directory: Path) -> dict[str, Any]:
    model = run_request.runtime.model or (MODELS[0] if MODELS else "")
    if not model or model not in MODELS:
        raise ValueError("model 不在允许列表中")
    work_directory = run_directory / ".work"
    deliverables_directory = run_directory / ".deliverables"
    work_directory.mkdir(parents=True, exist_ok=True)
    deliverables_directory.mkdir(parents=True, exist_ok=True)
    prompt = run_request.input.text.strip()
    if not prompt and run_request.input.attachment_refs:
        prompt = "请处理本次请求中已授权的附件。"
    if not prompt:
        raise ValueError("input.text 不能为空")
    workflow_name = (
        run_request.execution.workflow_ref.id
        if run_request.execution.kind == "workflow" and run_request.execution.workflow_ref
        else None
    )
    if workflow_name and load_workflow_config(workflow_name) is None:
        raise ValueError(f"workflow 暂不支持 Python Runtime：{workflow_name}")
    payload: dict[str, Any] = {
        "prompt": prompt,
        "workflow_name": workflow_name,
        # Keep the Java capability binding available to the worker even when
        # the capability is not backed by a directory workflow.  MCP auth and
        # other runtime policy are keyed by this stable reference.
        "capability_ref": run_request.capability_ref or "conversation",
        "model": model,
        "resume": run_request.runtime.session_ref if run_request.runtime.continuity_policy == "resume" else None,
        "max_turns": run_request.limits.max_turns,
        "include_partial_messages": True,
        "cwd": str(PROJECT_ROOT),
        "additional_directories": [str(run_directory), str(work_directory), str(deliverables_directory)],
        "session_directory": str(run_directory),
        "work_directory": str(work_directory),
        "deliverables_directory": str(deliverables_directory),
        "skill_refs": [item.id for item in run_request.execution.skill_refs],
    }
    credentials = run_request.credentials.to_dict(include_secret=True)
    if credentials:
        # This value remains in the worker's transient stdin payload.  The
        # worker/config boundary consumes it for request-scoped MCP injection;
        # it is never copied to RunStore or public events.
        payload["credentials"] = credentials
    return payload


async def _execute_internal_run(run_request: AgentRunRequest) -> None:
    run_id = run_request.run_id
    run_directory = (PROJECT_ROOT / ".scribe-runs" / "work" / run_id).resolve()
    run_directory.mkdir(parents=True, exist_ok=True)
    try:
        RUN_STORE.update_status(run_id, "running")
        await _publish_internal_event(run_id, {"runId": run_id, "type": "run.started", "payload": {"status": "running"}})
        worker_payload = _internal_worker_payload(run_request, run_directory)
        saw_terminal = False

        async def consume_agent() -> None:
            nonlocal saw_terminal
            async for raw in stream_agent(worker_payload):
                provider_session = raw.get("sessionId")
                if provider_session:
                    try:
                        RUN_STORE.update_runtime_session_ref(run_id, str(provider_session))
                    except (KeyError, ValueError):
                        pass
                public = _public_internal_event(run_id, raw)
                await _publish_internal_event(run_id, public)
                if public["type"] == "run.completed":
                    saw_terminal = True
                    RUN_STORE.update_status(run_id, "succeeded")
                elif public["type"] == "run.failed":
                    saw_terminal = True
                    RUN_STORE.update_status(run_id, "failed")

        # Cancelling this wait propagates through stream_agent and terminates
        # the child worker process tree.
        await asyncio.wait_for(consume_agent(), timeout=run_request.limits.timeout_ms / 1000)
        if not saw_terminal:
            await _publish_internal_event(run_id, {"runId": run_id, "type": "run.completed", "payload": {}})
            RUN_STORE.update_status(run_id, "succeeded")
    except asyncio.TimeoutError:
        current = RUN_STORE.get_run(run_id)
        if current and current.get("status") not in TERMINAL_RUN_STATUSES:
            await _publish_internal_event(run_id, {"runId": run_id, "type": "run.failed", "payload": {"code": "timeout"}})
            RUN_STORE.update_status(run_id, "failed", error="timeout")
    except asyncio.CancelledError:
        current = RUN_STORE.get_run(run_id)
        if current and current.get("status") not in TERMINAL_RUN_STATUSES:
            await _publish_internal_event(run_id, {"runId": run_id, "type": "run.cancelled", "payload": {}})
            RUN_STORE.update_status(run_id, "cancelled")
        raise
    except Exception:
        current = RUN_STORE.get_run(run_id)
        if current and current.get("status") not in TERMINAL_RUN_STATUSES:
            await _publish_internal_event(run_id, {"runId": run_id, "type": "run.failed", "payload": {"code": "runtime_error"}})
            RUN_STORE.update_status(run_id, "failed", error="runtime_error")
    finally:
        async with internal_runs_lock:
            internal_tasks.pop(run_id, None)


@app.post("/internal/v1/runs")
async def internal_create_run(request: Request):
    try:
        payload = await _small_json(request, INTERNAL_BODY_BYTES)
        run_request = AgentRunRequest.from_dict(payload)
        claims = _authorize_new_request(request, run_request)
    except (ValueError, ProtocolError, _InternalAuthError) as error:
        status = 401 if isinstance(error, _InternalAuthError) else 400
        if isinstance(error, _InternalAuthError) and str(error) == "Runtime JWT 未配置":
            status = 503
        return _plain(str(error), status)

    capability = run_request.capability_ref or "conversation"
    try:
        async with internal_runs_lock:
            existing = RUN_STORE.get_run(run_request.run_id)
            run = RUN_STORE.create_run(
                run_request.run_id,
                request=run_request,
                tenant_id=(run_request.context.tenant_id or claims.get("tenant")),
                user_id=(run_request.context.user_id or claims.get("sub")),
                business_session_id=(run_request.business_session_id or claims.get("businessSessionId")),
                turn_id=(run_request.turn_id or claims.get("turnId")),
                capability_ref=capability,
                metadata={
                    "requestId": run_request.request_id,
                    "agentRef": run_request.agent_ref.id,
                    "executionKind": run_request.execution.kind,
                },
            )
            # A process restart leaves a persisted queued/running record but
            # no asyncio task. Re-posting the same run from Java is the MVP
            # recovery handshake; it must not create a second task in-process.
            if run.get("status") not in TERMINAL_RUN_STATUSES and run_request.run_id not in internal_tasks:
                internal_tasks[run_request.run_id] = asyncio.create_task(_execute_internal_run(run_request))
    except (KeyError, PermissionError, ValueError) as error:
        return _plain(str(error), 409 if isinstance(error, PermissionError) else 400)
    return JSONResponse(
        {
            "run": run,
            "eventsUrl": f"/internal/v1/runs/{run_request.run_id}/events",
        },
        status_code=202 if existing is None else 200,
    )


@app.get("/internal/v1/runs/{run_id}")
async def internal_get_run(run_id: str, request: Request):
    run = RUN_STORE.get_run(run_id)
    if run is None:
        return _plain("Run 不存在", 404)
    try:
        _authorize_internal(request, run, allowed_scopes={"run.read", "run.execute"}, consume_jti=False)
    except _InternalAuthError as error:
        return _plain(str(error), 503 if str(error) == "Runtime JWT 未配置" else 401)
    return {"run": run}


@app.get("/internal/v1/runs/{run_id}/events")
async def internal_run_events(
    run_id: str,
    request: Request,
    afterSequence: int | None = Query(default=None, ge=0),
):
    run = RUN_STORE.get_run(run_id)
    if run is None:
        return _plain("Run 不存在", 404)
    try:
        _authorize_internal(request, run, allowed_scopes={"run.read", "run.execute"}, consume_jti=False)
    except _InternalAuthError as error:
        return _plain(str(error), 503 if str(error) == "Runtime JWT 未配置" else 401)
    last_header = request.headers.get("last-event-id")
    if afterSequence is None and last_header:
        try:
            afterSequence = max(0, int(last_header))
        except ValueError:
            return _plain("Last-Event-ID 无效", 400)
    cursor = afterSequence or 0

    async def event_stream():
        nonlocal cursor

        def format_event(event: dict[str, Any]) -> str:
            lines = [f"id: {event['sequence']}", f"event: {event['type']}"]
            lines.append(f"data: {json.dumps(event, ensure_ascii=False)}")
            return "\n".join(lines) + "\n\n"

        for event in RUN_STORE.events_after(run_id, cursor):
            cursor = event["sequence"]
            yield format_event(event)
        current = RUN_STORE.get_run(run_id)
        if current is None or current.get("status") in TERMINAL_RUN_STATUSES:
            return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with internal_runs_lock:
            internal_subscribers.setdefault(run_id, set()).add(queue)
            # Fill the gap between the initial replay and registration.
            gap = RUN_STORE.events_after(run_id, cursor)
        for event in gap:
            cursor = event["sequence"]
            yield format_event(event)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    # Comment frames keep proxies/browser connections alive
                    # without adding a persisted event or sequence number.
                    yield ": heartbeat\n\n"
                    continue
                if event["sequence"] <= cursor:
                    continue
                cursor = event["sequence"]
                yield format_event(event)
                if event["type"] in {"run.completed", "run.failed", "run.cancelled"}:
                    return
        finally:
            async with internal_runs_lock:
                subscribers = internal_subscribers.get(run_id)
                if subscribers is not None:
                    subscribers.discard(queue)
                    if not subscribers:
                        internal_subscribers.pop(run_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


@app.post("/internal/v1/runs/{run_id}/cancel")
async def internal_cancel_run(run_id: str, request: Request):
    run = RUN_STORE.get_run(run_id)
    if run is None:
        return _plain("Run 不存在", 404)
    try:
        _authorize_internal(request, run, allowed_scopes={"run.cancel"}, consume_jti=True)
    except _InternalAuthError as error:
        return _plain(str(error), 503 if str(error) == "Runtime JWT 未配置" else 401)
    if run.get("status") in TERMINAL_RUN_STATUSES:
        return {"run": run}
    async with internal_runs_lock:
        task = internal_tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    else:
        RUN_STORE.update_status(run_id, "cancelled")
        await _publish_internal_event(run_id, {"runId": run_id, "type": "run.cancelled", "payload": {}})
    return {"run": RUN_STORE.get_run(run_id)}


@app.post("/api/sessions")
async def create_session_route(request: Request):
    try:
        payload = await _small_json(request, 1024)
        model = str(payload.get("modelId") or "").strip()
        if model and model not in MODELS:
            return _plain("模型未配置", 400)
        created = create_session(model=model or (MODELS[0] if MODELS else None))
        return JSONResponse({"session": {
            "id": created["id"],
            "title": created["title"],
            "modelId": created["modelId"],
            "createdAt": created["createdAt"],
            "updatedAt": created["updatedAt"],
        }}, status_code=201)
    except (ValueError, RuntimeError) as error:
        return _plain(str(error), 400)


@app.get("/api/sessions/{session_id}")
async def session_route(session_id: str):
    try:
        return web_session(session_id)
    except RuntimeError as error:
        return _plain(str(error), 404)


@app.patch("/api/sessions/{session_id}")
async def update_session_route(session_id: str, request: Request):
    try:
        payload = await _small_json(request)
        model = str(payload.get("modelId") or "").strip()
        if model and model not in MODELS:
            return _plain("模型未配置", 400)
        update_session(session_id, title=payload.get("title"), model=model or None)
        return {"ok": True}
    except ValueError as error:
        return _plain(str(error), 400)
    except RuntimeError as error:
        return _plain(str(error), 404)


@app.delete("/api/sessions/{session_id}")
async def delete_session_route(session_id: str):
    removed = cleanup_session(session_id)
    return JSONResponse({"ok": True} if removed else {"error": "会话不存在"}, status_code=200 if removed else 404)


@app.post("/api/sessions/{session_id}/files")
async def upload_route(session_id: str, request: Request):
    try:
        form = await request.form()
        upload_files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
        if not upload_files:
            return _plain("没有可上传的文件", 400)
        uploads = []
        for upload in upload_files:
            try:
                chunks = []
                size = 0
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_FILE_BYTES:
                        raise RuntimeError(f"文件 {upload.filename or '未命名文件'} 超过 {MAX_FILE_BYTES // 1024 // 1024} MB 限制")
                    chunks.append(chunk)
                uploads.append((upload.filename or "未命名文件", upload.content_type, b"".join(chunks)))
            finally:
                await upload.close()
        saved = save_uploads(session_id, uploads)
        data = web_session(session_id)
        uploaded_names = set(saved.get("uploaded", []))
        file = next((item for item in data["files"] if (decoded := decode_file_id(item["id"])) and decoded["name"] in uploaded_names), None)
        if file is None:
            return _plain("上传完成但文件记录不存在", 500)
        return JSONResponse({"file": file}, status_code=201)
    except RuntimeError as error:
        return _plain(str(error), 400)


@app.get("/api/files/{file_id}")
async def download_route(file_id: str):
    decoded = decode_file_id(file_id)
    if decoded is None:
        return _plain("文件不存在", 404)
    try:
        file = resolve_session_file(decoded["sessionId"], decoded["name"])
    except RuntimeError as error:
        return _plain(str(error), 404)
    return FileResponse(
        file["path"],
        media_type=file["mimeType"],
        filename=file["downloadName"],
        headers={
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "content-security-policy": "sandbox",
        },
    )


@app.get("/api/stats")
async def stats_route():
    return session_stats()


@app.post("/api/sessions/{session_id}/chat")
async def chat_route(session_id: str, request: Request):
    try:
        payload = await _small_json(request)
    except ValueError as error:
        return _plain(str(error), 400)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return _plain("prompt 不能为空", 400)
    requested_workflow = str(payload.get("workflow_name") or payload.get("workflowName") or "").strip()
    prefixed_workflow = workflow_name_from_prompt(prompt)
    if requested_workflow and prefixed_workflow and requested_workflow != prefixed_workflow:
        return _plain("workflow_name 与 prompt 前缀不一致", 400)
    workflow_name = requested_workflow or prefixed_workflow
    agent_prompt = prompt_without_workflow_prefix(prompt) if prefixed_workflow else prompt
    if not agent_prompt:
        return _plain("workflow 前缀后缺少问题", 400)
    try:
        files_context = session_prompt_context(session_id)
        upload_directory = session_directory(session_id)
        work_directory = session_work_directory(session_id)
        deliverables_directory = session_deliverables_directory(session_id)
        session = load_session(session_id)
    except RuntimeError as error:
        return _plain(str(error), 404)
    requested_model = str(payload.get("modelId") or payload.get("model") or "").strip()
    model = requested_model or session.get("model") or (MODELS[0] if MODELS else "")
    if not model or model not in MODELS:
        return _plain("model 不在允许列表中", 400)
    async with active_runs_lock:
        if session_id in active_runs:
            return JSONResponse({"error": "该会话正在执行中，请等待当前任务结束", "code": "run_in_progress"}, status_code=409)
        active_runs[session_id] = None
    if requested_model and requested_model != session.get("model"):
        update_session_model(session_id, requested_model)

    resume = session.get("agentSessionId") or None
    turn_started_at = int(time.time() * 1000)
    files_before = {
        file["name"]: f"{file['bytes']}:{file['createdAt']}"
        for file in list_session_files(session_id)["files"]
    }
    associated = {
        name
        for turn in session["history"] if isinstance(turn, dict)
        for field in ("files", "inputFiles")
        for name in (turn.get(field) if isinstance(turn.get(field), list) else [])
    }
    last_created_at = int(session["history"][-1].get("createdAt") or 0) if session["history"] else 0
    input_files = [
        file["name"] for file in session["files"]
        if file.get("source") != "generated"
        and file["name"] not in associated
        and (not session["history"] or int(file.get("createdAt") or 0) >= last_created_at)
    ]

    async def event_stream():
        events: list[dict[str, Any]] = []
        agent_session_id = resume
        turn_id = secrets.token_hex(12)
        turn_files: list[str] = []
        last_persisted_count = 0
        last_persisted_at = 0.0
        current_task = asyncio.current_task()
        active_runs[session_id] = current_task

        def persist(force: bool = False) -> None:
            nonlocal last_persisted_count, last_persisted_at
            timestamp = time.monotonic()
            if not force and len(events) != 1 and len(events) - last_persisted_count < 24 and timestamp - last_persisted_at < 0.75:
                return
            last_persisted_count = len(events)
            last_persisted_at = timestamp
            upsert_session_turn(
                session_id,
                turn_id=turn_id,
                prompt=prompt,
                events=events[-500:],
                agent_session_id=agent_session_id,
                model=model,
                files=turn_files,
                input_files=input_files,
            )

        try:
            upsert_session_turn(
                session_id,
                turn_id=turn_id,
                prompt=prompt,
                events=[],
                agent_session_id=agent_session_id,
                model=model,
                input_files=input_files,
            )
            references_context = reference_prompt_context(agent_prompt)
            full_prompt = "\n\n".join(filter(None, [files_context, references_context, f"用户请求：\n{agent_prompt}"]))
            worker_payload = {
                "prompt": full_prompt,
                "workflow_name": workflow_name,
                "model": model,
                "resume": resume,
                "include_partial_messages": True,
                "cwd": str(Path.cwd()),
                "additional_directories": [upload_directory, work_directory, deliverables_directory],
                "session_directory": upload_directory,
                "work_directory": work_directory,
                "deliverables_directory": deliverables_directory,
            }
            async for event in stream_agent(worker_payload):
                # Keep provider session bookkeeping private, but persist and
                # stream only the redacted compatibility event.  In
                # particular, thinking text and tool input/result must never
                # enter the session history.
                if event.get("type") in {"init", "result"} and event.get("sessionId"):
                    agent_session_id = str(event["sessionId"])
                public_event = _public_legacy_event(event)
                events.append(public_event)
                persist()
                yield f"data: {json.dumps(public_event, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as error:
            event = _public_legacy_event({"type": "error", "message": str(error)})
            events.append(event)
            persist()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            try:
                for file in list_session_files(session_id)["files"]:
                    if file["source"] != "generated":
                        continue
                    before = files_before.get(file["name"])
                    current = f"{file['bytes']}:{file['createdAt']}"
                    if before is None or before != current or file["createdAt"] >= turn_started_at:
                        turn_files.append(file["name"])
                persist(force=True)
            except RuntimeError:
                pass
            async with active_runs_lock:
                active_runs.pop(session_id, None)
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


if __name__ == "__main__":
    print(f"Agent API: http://{HOST}:{PORT}")
    print(f"模型: {os.environ.get('ANTHROPIC_MODEL', '')}")
    if not os.environ.get("SCRIBE_TOKEN"):
        print("当前使用随机后端 token；请通过 npm run ui 启动完整界面。")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
