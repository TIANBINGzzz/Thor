#!/usr/bin/env python3
"""Run one Claude Agent SDK query and emit normalized events as JSON Lines.

The Node HTTP server owns authentication, sessions, files, and browser SSE.
This process owns only the Python Agent SDK call. Keeping the boundary as JSONL
lets the two runtimes evolve independently while preserving the existing UI
event contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)

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
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(value) <= TEXT_LIMIT else f"{value[:TEXT_LIMIT]}…"


def scope_of(message: Any) -> str:
    parent = getattr(message, "parent_tool_use_id", None)
    return f"sub:{parent}" if parent else "main"


def emit(event: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def event_from_stream(message: StreamEvent, streaming: dict[str, str]) -> list[dict[str, Any]]:
    raw = message.event or {}
    event_type = raw.get("type")
    scope = f"sub:{message.parent_tool_use_id}" if message.parent_tool_use_id else "main"

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


def events_from_assistant(message: AssistantMessage, streaming: dict[str, str]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    scope = scope_of(message)
    for block in message.content:
        if isinstance(block, TextBlock) and block.text and streaming.get(scope) != message.message_id:
            events.append({"type": "text", "scope": scope, "text": block.text})
        elif isinstance(block, ThinkingBlock) and block.thinking:
            events.append({"type": "thinking", "scope": scope, "text": block.thinking})
        elif isinstance(block, ToolUseBlock):
            events.append({
                "type": "tool_use",
                "scope": scope,
                "id": block.id,
                "name": block.name,
                "input": clip(block.input),
            })
    return events


def events_from_user(message: UserMessage) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    scope = scope_of(message)
    if not isinstance(message.content, list):
        return events
    for block in message.content:
        if isinstance(block, ToolResultBlock):
            events.append({
                "type": "tool_result",
                "scope": scope,
                "id": block.tool_use_id,
                "isError": block.is_error is True,
                "text": clip(block.content),
            })
    return events


def events_from_system(message: SystemMessage) -> list[dict[str, Any]]:
    subtype = message.subtype
    data = message.data or {}
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
            "detail": data.get("description") or data.get("workflow_name") or "",
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


def events_from_result(message: ResultMessage) -> list[dict[str, Any]]:
    usage = message.model_usage or {}
    input_tokens = sum(int(item.get("inputTokens", 0)) for item in usage.values())
    output_tokens = sum(int(item.get("outputTokens", 0)) for item in usage.values())
    ok = message.subtype == "success" and not message.is_error
    return [{
        "type": "result",
        "ok": ok,
        "subtype": message.subtype,
        "sessionId": message.session_id,
        "durationMs": message.duration_ms,
        "turns": message.num_turns,
        "costUsd": message.total_cost_usd,
        "inputTokens": input_tokens,
        "outputTokens": output_tokens,
        "message": "" if ok else "; ".join(message.errors or []) or message.result or f"执行结束：{message.subtype}",
    }]


def message_events(message: Any, streaming: dict[str, str]) -> list[dict[str, Any]]:
    if isinstance(message, StreamEvent):
        return event_from_stream(message, streaming)
    if isinstance(message, AssistantMessage):
        return events_from_assistant(message, streaming)
    if isinstance(message, UserMessage):
        return events_from_user(message)
    if isinstance(message, SystemMessage):
        return events_from_system(message)
    if isinstance(message, ResultMessage):
        return events_from_result(message)
    return []


def build_options(payload: dict[str, Any]) -> ClaudeAgentOptions:
    append = payload.get("system_prompt_append") or ""
    system_prompt: dict[str, str] = {
        "type": "preset",
        "preset": "claude_code",
        "append": append,
    }
    mcp_servers = payload.get("mcp_servers") or {}
    allowed_tools = payload.get("allowed_tools") or []
    return ClaudeAgentOptions(
        model=payload.get("model"),
        cwd=payload.get("cwd") or Path.cwd(),
        resume=payload.get("resume"),
        max_turns=payload.get("max_turns", 30),
        include_partial_messages=bool(payload.get("include_partial_messages")),
        setting_sources=["project", "local"],
        system_prompt=system_prompt,
        tools={"type": "preset", "preset": "claude_code"},
        disallowed_tools=["WebSearch"],
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        mcp_servers=mcp_servers,
        add_dirs=payload.get("additional_directories") or [],
        env=dict(os.environ),
    )


async def run(payload: dict[str, Any]) -> None:
    options = build_options(payload)
    streaming: dict[str, str] = {}
    async for message in query(prompt=payload["prompt"], options=options):
        for event in message_events(message, streaming):
            emit(event)


async def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            await run(json.loads(line))
            emit({"type": "worker_done"})
        except Exception as error:  # the parent turns this into the UI error event
            emit({"type": "worker_error", "message": str(error)})


if __name__ == "__main__":
    asyncio.run(main())
