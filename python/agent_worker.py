#!/usr/bin/env python3
"""Run one Claude Agent SDK query and emit normalized events as JSON Lines.

The FastAPI service owns authentication, sessions, files, and browser SSE.
This process owns only the Python Agent SDK call. Keeping the boundary as JSONL
lets the two runtimes evolve independently while preserving the existing UI
event contract.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Any

from runtime.config import (
    build_options,
    create_run_services,
    isolated_sdk_environment,
    load_runtime_environment,
    missing_environment,
    prepare_workflow_assets,
)
from runtime.claude_sdk import (
    ClientState,
    ClaudeSDKClient,
    SDKError,
    SDKTimeoutError,
    normalize_message,
    stream_query,
)
from runtime.chart_delivery import ChartDelivery
DEFAULT_TIMEOUT_MS = 300_000

# 父进程以UTF-8收发JSONL；Windows默认GBK会使中文提示词乱码或解析失败。
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

TEXT_LIMIT = 2000
NOISE = {
    "status",
    "thinking_tokens",
    "session_state_changed",
    "background_tasks_changed",
    "commands_changed",
    "files_persisted",
}


def clip(value: Any) -> str:
    """将输入值转为文本并按 TEXT_LIMIT 截断，返回适合事件展示的字符串。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(value) <= TEXT_LIMIT else f"{value[:TEXT_LIMIT]}…"


def scope_of(message: Any) -> str:
    """接收 SDK 消息，根据父工具引用返回 main 或 sub:<工具调用标识> 作用域。"""
    normalized = normalize_message(message)
    parent = normalized.parent_tool_use_id
    return f"sub:{parent}" if parent else "main"


def emit(event: dict[str, Any]) -> None:
    """将事件字典写为一行 UTF-8 JSON 并立即刷新标准输出，无返回值。"""
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def event_from_stream(message: Any, streaming: dict[str, str]) -> list[dict[str, Any]]:
    """接收增量消息和流状态，更新各作用域的消息标识，返回文本或思考增量事件列表。"""
    normalized = normalize_message(message)
    if normalized.kind != "stream":
        return []
    raw = normalized.data.get("event") or {}
    event_type = raw.get("type")
    scope = f"sub:{normalized.parent_tool_use_id}" if normalized.parent_tool_use_id else "main"

    if event_type == "message_start":
        message_id = (raw.get("message") or {}).get("id")
        if message_id:
            streaming[scope] = message_id
        return []
    if event_type == "message_stop":
        streaming.pop(scope, None)
        return []

    if event_type == "content_block_delta":
        delta = raw.get("delta") or {}
        if delta.get("type") == "text_delta" and delta.get("text"):
            return [{"type": "text", "scope": scope, "text": delta["text"]}]
        if delta.get("type") == "thinking_delta" and delta.get("thinking"):
            return [{"type": "thinking", "scope": scope, "text": delta["thinking"]}]
    return []


def events_from_assistant(message: Any, streaming: dict[str, str]) -> list[dict[str, Any]]:
    """接收助手消息和流状态，返回文本、思考及工具调用事件，跳过已流式发送的同一消息文本。"""
    normalized = normalize_message(message)
    if normalized.kind != "assistant":
        return []
    events: list[dict[str, Any]] = []
    scope = scope_of(normalized)
    message_id = normalized.data.get("message_id")
    for block in normalized.data.get("content") or []:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and block.get("text") and streaming.get(scope) != message_id:
            events.append({"type": "text", "scope": scope, "text": block["text"]})
        elif block_type == "thinking" and block.get("thinking"):
            events.append({"type": "thinking", "scope": scope, "text": block["thinking"]})
        elif block_type == "tool_use":
            events.append({
                "type": "tool_use",
                "scope": scope,
                "id": block.get("id"),
                "name": block.get("name"),
                "input": clip(block.get("input")),
            })
    return events


def events_from_user(message: Any) -> list[dict[str, Any]]:
    """接收 SDK 用户消息，提取其中的工具结果并返回事件列表；无工具结果时返回空列表。"""
    normalized = normalize_message(message)
    if normalized.kind != "user":
        return []
    events: list[dict[str, Any]] = []
    scope = scope_of(normalized)
    content = normalized.data.get("content")
    if not isinstance(content, list):
        return events
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            events.append({
                "type": "tool_result",
                "scope": scope,
                "id": block.get("tool_use_id"),
                "isError": block.get("is_error") is True,
                "text": clip(block.get("content")),
            })
    return events


def events_from_system(message: Any) -> list[dict[str, Any]]:
    """接收系统消息，过滤高频状态通知，返回初始化、任务进展或上下文压缩等事件列表。"""
    normalized = normalize_message(message)
    if normalized.kind != "system":
        return []
    subtype = normalized.data.get("subtype")
    data = normalized.data.get("data") or {}
    scope = f"sub:{data['parent_tool_use_id']}" if data.get("parent_tool_use_id") else "main"

    if subtype in NOISE:
        return []
    if subtype == "init":
        return [{
            "type": "init",
            "sessionId": data.get("session_id"),
            "model": data.get("model"),
            "cwd": data.get("cwd"),
            "permissionMode": data.get("permissionMode") or data.get("permission_mode"),
            "tools": len(data.get("tools") or []),
            "skills": data.get("skills") or [],
            "agents": data.get("agents") or [],
            "commands": data.get("slash_commands") or [],
            "mcpServers": data.get("mcp_servers") or [],
        }]
    if subtype == "task_started":
        return [{
            "type": "activity",
            "scope": scope,
            "label": f"子代理启动 {data.get('subagent_type')}" if data.get("subagent_type") else "任务启动",
            "detail": data.get("description") or data.get("capability_ref") or "",
        }]
    if subtype == "task_progress":
        usage = data.get("usage") or {}
        return [{
            "type": "tool_progress",
            "scope": scope,
            "id": data.get("tool_use_id") or data.get("task_id"),
            "seconds": round(float(usage.get("duration_ms", 0)) / 1000),
        }]
    if subtype == "compact_boundary":
        return [{"type": "activity", "scope": scope, "label": "上下文压缩", "detail": ""}]
    return [{"type": "activity", "scope": scope, "label": f"system/{subtype}", "detail": ""}]


def events_from_result(message: Any) -> list[dict[str, Any]]:
    """接收 SDK 结果消息，返回包含成功状态、耗时及用量的结果事件列表。"""
    normalized = normalize_message(message)
    if normalized.kind != "result":
        return []
    data = normalized.data
    usage = data.get("model_usage") or {}
    input_tokens = sum(int(item.get("inputTokens", item.get("input_tokens", 0))) for item in usage.values() if isinstance(item, dict))
    output_tokens = sum(int(item.get("outputTokens", item.get("output_tokens", 0))) for item in usage.values() if isinstance(item, dict))
    ok = data.get("subtype") == "success" and not data.get("is_error")
    return [{
        "type": "result",
        "ok": ok,
        "subtype": data.get("subtype"),
        "sessionId": data.get("session_id"),
        "durationMs": data.get("duration_ms"),
        "turns": data.get("num_turns"),
        "costUsd": data.get("total_cost_usd"),
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "message": "" if ok else "; ".join(data.get("errors") or []) or data.get("result") or f"执行结束：{data.get('subtype')}",
    }]


def message_events(message: Any, streaming: dict[str, str]) -> list[dict[str, Any]]:
    """按输入 SDK 消息类型分派转换器，返回 Worker 事件列表，并按需更新传入的流状态。"""
    normalized = normalize_message(message)
    if normalized.kind == "stream":
        return event_from_stream(normalized, streaming)
    if normalized.kind == "assistant":
        return events_from_assistant(normalized, streaming)
    if normalized.kind == "user":
        return events_from_user(normalized)
    if normalized.kind == "system":
        return events_from_system(normalized)
    if normalized.kind == "result":
        return events_from_result(normalized)
    return []


class ClientRunCancelled(Exception):
    """Internal signal used to retire a Client after an explicit cancellation."""


async def _read_client_commands(queue: asyncio.Queue[dict[str, Any]]) -> None:
    """异步读取标准输入中的 JSONL 命令并放入指定队列；无返回值，输入结束时发送关闭标记。"""

    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            await queue.put({"type": "worker_stdin_closed"})
            return
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            await queue.put({"type": "invalid_command"})
            continue
        if isinstance(value, dict):
            await queue.put(value)
        else:
            await queue.put({"type": "invalid_command"})


def _client_command_run_id(command: dict[str, Any]) -> str:
    """从命令字典提取 run_id 或 runId，返回字符串，缺失时返回空串。"""
    value = command.get("run_id") or command.get("runId") or ""
    return str(value)


def _client_error_code(error: BaseException) -> str:
    """接收执行异常，返回稳定的 Client 错误码，不包含异常详情。"""
    if isinstance(error, SDKError):
        return error.code
    if isinstance(error, asyncio.TimeoutError):
        return "sdk_timeout"
    return "sdk_execution_error"


async def _receive_client_response(
    client: ClaudeSDKClient,
    command: dict[str, Any],
    streaming: dict[str, str],
    command_queue: asyncio.Queue[dict[str, Any]],
    direct_workflow: bool,
    deadline: float | None,
    chart_delivery: ChartDelivery | None = None,
    mcp_errors: list | None = None,
) -> str | None:
    """接收 Client、当前命令、流状态、控制队列及执行策略，输出回复事件并返回最后的 SDK 会话标识。

    子 Task 仅读取下一条回复；interrupt 等生命周期操作始终由本协程的所属 Task 执行。
    """

    iterator = client.receive_response(timeout_ms=None if deadline is None else max(1, int((deadline - time.monotonic()) * 1000)))
    next_task: asyncio.Task[Any] | None = None
    command_task: asyncio.Task[Any] | None = None
    completed = False
    last_session_id: str | None = None
    try:
        next_task = asyncio.create_task(iterator.__anext__(), name="ccsdk-client-response")
        command_task = asyncio.create_task(command_queue.get(), name="ccsdk-client-control")
        while True:
            wait_set = {next_task, command_task}
            done, _ = await asyncio.wait(wait_set, return_when=asyncio.FIRST_COMPLETED)
            if next_task in done:
                command_task.cancel()
                await asyncio.gather(command_task, return_exceptions=True)
                command_task = asyncio.create_task(command_queue.get(), name="ccsdk-client-control")
                try:
                    message = next_task.result()
                except StopAsyncIteration as error:
                    raise SDKError("Claude SDK response stream 提前结束") from error
                normalized = normalize_message(message)
                if normalized.session_id:
                    last_session_id = normalized.session_id
                for event in message_events(normalized, streaming):
                    event = mcp_result_event(event, mcp_errors)
                    (chart_delivery.emit if chart_delivery else emit)(direct_workflow_event(event) if direct_workflow else event)
                if normalized.kind == "result":
                    completed = True
                    return last_session_id
                next_task = asyncio.create_task(iterator.__anext__(), name="ccsdk-client-response")
                continue

            command_value = command_task.result()
            command_task = asyncio.create_task(command_queue.get(), name="ccsdk-client-control")
            command_type = command_value.get("type")
            if command_type == "client_interrupt" and _client_command_run_id(command_value) == _client_command_run_id(command):
                await client.interrupt()
                emit({"type": "client_control_ack", "run_id": _client_command_run_id(command), "op": "interrupt"})
            elif command_type == "client_cancel" and _client_command_run_id(command_value) == _client_command_run_id(command):
                await client.interrupt()
                raise ClientRunCancelled
            elif command_type == "client_close":
                await client.interrupt()
                raise ClientRunCancelled
            elif command_type in {"client_query", "client_interrupt", "client_cancel"}:
                emit({
                    "type": "client_error",
                    "run_id": _client_command_run_id(command_value),
                    "code": "client_busy",
                })
    finally:
        if command_task is not None and not command_task.done():
            command_task.cancel()
        if next_task is not None and not next_task.done():
            next_task.cancel()
        pending = [task for task in (command_task, next_task) if task is not None]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await iterator.aclose()
        except asyncio.CancelledError:
            raise
        except Exception:
            if completed:
                raise


async def run_client(initial: dict[str, Any]) -> None:
    """接收初始配置并持有一个 SDK Client，串行处理标准输入命令，将回复和控制结果写入 JSONL；无返回值。"""

    load_runtime_environment(initial.get("workflow_name"))
    missing = missing_environment()
    if missing:
        emit({"type": "client_error", "code": "configuration_error"})
        return
    data_services = create_run_services(initial)
    campus_service = None
    if initial.get('capability_ref') == 'campus-brain-query':
        from tools.campus import CampusQuery, load_campus_assets
        from runtime.deployment_config import ConfigSnapshot
        settings = ConfigSnapshot(values=prepare_workflow_assets(initial)['config_values'])
        campus_service = CampusQuery(load_campus_assets(settings), initial.get('credentials'))
    chart_delivery = ChartDelivery(emit)
    mcp_errors = []
    options = build_options(initial, data_services=data_services, artifact_sink=emit, chart_sink=chart_delivery.record,
                            mcp_error_sink=lambda: mcp_errors.append(True),
                            **({'campus_service': campus_service} if campus_service else {}))
    direct_workflow = options.tools == [] and options.strict_mcp_config
    client = ClaudeSDKClient(
        options,
        connect_timeout_ms=initial.get("connect_timeout_ms", 60_000),
        query_timeout_ms=initial.get("query_timeout_ms", DEFAULT_TIMEOUT_MS),
        receive_timeout_ms=initial.get("receive_timeout_ms", DEFAULT_TIMEOUT_MS),
        disconnect_timeout_ms=initial.get("disconnect_timeout_ms", 5_000),
    )
    command_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    reader_task = asyncio.create_task(_read_client_commands(command_queue), name="ccsdk-client-stdin")
    client_closed = False
    with isolated_sdk_environment():
        try:
            await client.connect()
            emit({"type": "client_ready", "state": client.state.value})
            while True:
                command = await command_queue.get()
                command_type = command.get("type")
                if command_type == "client_close" or command_type == "worker_stdin_closed":
                    if client.state not in {ClientState.CLOSED, ClientState.NEW, ClientState.FAILED}:
                        await client.disconnect()
                    client_closed = True
                    emit({"type": "client_closed", "state": client.state.value})
                    return
                if command_type != "client_query":
                    emit({"type": "client_error", "run_id": _client_command_run_id(command), "code": "invalid_command"})
                    continue

                run_id = _client_command_run_id(command)
                chart_delivery.reset()
                mcp_errors.clear()
                prompt = command.get("prompt")
                streaming: dict[str, str] = {}
                timeout_value = command.get("timeout_ms", command.get("timeoutMs", DEFAULT_TIMEOUT_MS))
                if isinstance(timeout_value, bool) or not isinstance(timeout_value, int) or timeout_value <= 0:
                    emit({"type": "client_error", "run_id": run_id, "code": "configuration_error"})
                    continue
                try:
                    deadline = time.monotonic() + timeout_value / 1000
                    async with asyncio.timeout(timeout_value / 1000):
                        if campus_service:
                            campus_service.bind(command.get('credentials'))
                        if data_services:
                            await data_services.bind(command)
                            prompt = data_services.prepare_prompt(str(prompt or ""))
                        await client.query(str(prompt or ""), session_id=str(command.get("session_id") or "default"))
                        session_id = await _receive_client_response(
                            client, command, streaming, command_queue, direct_workflow, deadline, chart_delivery, mcp_errors,
                        )
                    emit({"type": "client_run_completed", "run_id": run_id, "session_id": session_id})
                except ClientRunCancelled:
                    emit({"type": "client_run_cancelled", "run_id": run_id})
                    return
                except (asyncio.TimeoutError, SDKTimeoutError):
                    emit({"type": "client_error", "run_id": run_id, "code": "sdk_timeout"})
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    emit({"type": "client_error", "run_id": run_id, "code": _client_error_code(error)})
                    return
                finally:
                    if campus_service:
                        campus_service.clear()
                    if data_services:
                        await data_services.close()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            emit({"type": "client_error", "code": _client_error_code(error)})
        finally:
            if not client_closed and client.state not in {ClientState.CLOSED, ClientState.NEW, ClientState.FAILED}:
                try:
                    await client.disconnect()
                except Exception:
                    emit({"type": "client_error", "code": "sdk_cleanup_error"})
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)


def direct_workflow_event(event: dict[str, Any]) -> dict[str, Any]:
    """接收 Worker 事件，清空 direct 模式初始化事件中的 Skill、Agent 和命令列表，返回处理后的事件。"""
    if event.get("type") != "init":
        return event
    return {**event, "skills": [], "agents": [], "commands": []}


def mcp_result_event(event, failures):
    """上游失败即使被模型解释为正常文本，本轮终态仍沿用SDK执行失败协议。"""
    if event.get('type') == 'result' and failures:
        return {**event, 'ok': False, 'message': '上游服务调用失败'}
    return event


async def run(payload: dict[str, Any]) -> None:
    """接收包含提示词和执行配置的 payload，执行一次 SDK query，并向标准输出写入事件；无返回值。"""
    load_runtime_environment(payload.get("workflow_name"))
    missing = missing_environment()
    if missing:
        raise RuntimeError(f"请先在项目根目录的 .env 中配置：{', '.join(missing)}")
    data_services = create_run_services(payload)
    streaming: dict[str, str] = {}
    # The SDK merges ``options.env`` with the worker process environment.  Keep
    # secrets loaded for configuration construction out of the provider CLI.
    timeout_ms = payload.get("timeout_ms", payload.get("timeoutMs", DEFAULT_TIMEOUT_MS))
    try:
        prompt = payload['prompt']
        if data_services:
            await data_services.bind(payload)
            prompt = data_services.prepare_prompt(prompt)
        chart_delivery = ChartDelivery(emit)
        mcp_errors = []
        options = build_options(payload, data_services=data_services, artifact_sink=emit, chart_sink=chart_delivery.record,
                                mcp_error_sink=lambda: mcp_errors.append(True))
        direct_workflow = options.tools == [] and options.strict_mcp_config
        with isolated_sdk_environment():
            async for message in stream_query(prompt, options, timeout_ms=timeout_ms):
                normalized = normalize_message(message)
                for event in message_events(message, streaming):
                    event = mcp_result_event(event, mcp_errors)
                    chart_delivery.emit(direct_workflow_event(event) if direct_workflow else event)
    finally:
        if data_services:
            await data_services.close()


async def main() -> None:
    """从标准输入读取 JSONL，按首条消息选择 Query 或 Client 模式，输出执行事件及完成或错误标记。"""
    first_line = await asyncio.to_thread(sys.stdin.readline)
    if not first_line.strip():
        return
    try:
        first_payload = json.loads(first_line)
        if isinstance(first_payload, dict) and first_payload.get("mode") == "client":
            await run_client(first_payload)
            return
        await run(first_payload)
        emit({"type": "worker_done"})
        for line in sys.stdin:
            if not line.strip():
                continue
            await run(json.loads(line))
            emit({"type": "worker_done"})
    except asyncio.CancelledError:
        raise
    except Exception:
        # Never forward raw provider paths, command lines or credential-shaped
        # details through the worker protocol.
        emit({"type": "worker_error", "message": "Python Agent worker 执行失败"})


if __name__ == "__main__":
    asyncio.run(main())
