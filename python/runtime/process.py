"""Async process boundary for the Claude Agent SDK worker."""

from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from runtime.config import worker_environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER = PROJECT_ROOT / "python" / "agent_worker.py"
WORKFLOW_PREFIX = re.compile(r"^/([A-Za-z0-9][A-Za-z0-9_-]*)(?:\s|$)")


def workflow_name_from_prompt(prompt: Any) -> str | None:
    if not isinstance(prompt, str):
        return None
    match = WORKFLOW_PREFIX.match(prompt.strip())
    return match.group(1) if match else None


def prompt_without_workflow_prefix(prompt: str) -> str:
    """Remove a leading workflow selector before the prompt reaches the SDK."""
    normalized = prompt.strip()
    match = WORKFLOW_PREFIX.match(normalized)
    return normalized[match.end():].strip() if match else normalized


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt" and process.pid:
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await killer.wait()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        if process.returncode is None:
            process.kill()
            await process.wait()


async def stream_agent(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    creation_flags = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creation_flags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(WORKER),
        cwd=str(PROJECT_ROOT),
        env=worker_environment(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creation_flags,
        **kwargs,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    saw_done = False
    worker_error: str | None = None

    async def relay_stderr() -> None:
        while line := await process.stderr.readline():
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                print(f"[python-agent] {message}", file=sys.stderr, flush=True)

    stderr_task = asyncio.create_task(relay_stderr())
    process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
    await process.stdin.drain()
    process.stdin.close()

    try:
        while line := await process.stdout.readline():
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if event.get("type") == "worker_done":
                saw_done = True
                continue
            if event.get("type") == "worker_error":
                worker_error = str(event.get("message") or "Python Agent 执行失败")
                continue
            yield event
        code = await process.wait()
        await stderr_task
        if worker_error:
            raise RuntimeError(worker_error)
        if code != 0 or not saw_done:
            raise RuntimeError(f"Python Agent worker 退出（code={code}）")
    except asyncio.CancelledError:
        await _terminate_process_tree(process)
        raise
    finally:
        if process.returncode is None:
            await _terminate_process_tree(process)
        if not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
