"""Async process boundary for the Claude Agent SDK worker."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from runtime.config import worker_environment


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKER = PROJECT_ROOT / "python" / "agent_worker.py"


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    """接收 Worker 进程，终止其进程树并等待退出；无返回值，已退出时直接结束。"""
    if process.returncode is not None:
        return
    if os.name == "nt" and process.pid:
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(killer.wait(), timeout=5)
        except asyncio.TimeoutError:
            killer.kill()
            await killer.wait()
            if process.returncode is None:
                process.kill()
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


async def _spawn_worker_process(payload: dict[str, Any]) -> asyncio.subprocess.Process:
    """以受控环境启动 agent_worker.py，返回带标准输入、输出和错误管道的子进程。"""
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
        env=worker_environment(payload),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creation_flags,
        **kwargs,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    return process


async def stream_agent(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """将执行 payload 发送给一次性 Worker，逐条产出事件字典，结束或取消时回收进程。"""
    process = await _spawn_worker_process(payload)
    saw_done = False
    worker_error: str | None = None
    stderr_task: asyncio.Task[Any] | None = None

    async def relay_stderr() -> None:
        while line := await process.stderr.readline():
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                print(f"[python-agent] {message}", file=sys.stderr, flush=True)

    try:
        stderr_task = asyncio.create_task(relay_stderr())
        process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await process.stdin.drain()
        process.stdin.close()
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
        if stderr_task is not None and not stderr_task.done():
            stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)


class ClientWorkerError(RuntimeError):
    """Raised when a persistent Client worker exits or violates its protocol."""


class ClientWorkerProcess:
    """Persistent JSONL process boundary for one project-owned SDK Client.

    The parent never imports or owns a provider Client.  One reader task owns
    stdout, while the SessionActor owns all commands and decides when a new
    process must be created after a failure.
    """

    def __init__(
        self,
        *,
        start_timeout_ms: int = 60_000,
        send_timeout_ms: int = 5_000,
        close_timeout_ms: int = 5_000,
    ) -> None:
        for value, name in (
            (start_timeout_ms, "start_timeout_ms"),
            (send_timeout_ms, "send_timeout_ms"),
            (close_timeout_ms, "close_timeout_ms"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self.start_timeout_ms = start_timeout_ms
        self.send_timeout_ms = send_timeout_ms
        self.close_timeout_ms = close_timeout_ms
        self._process: asyncio.subprocess.Process | None = None
        self._events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task[Any] | None = None
        self._stderr_task: asyncio.Task[Any] | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False

    @property
    def process(self) -> asyncio.subprocess.Process | None:
        return self._process

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.returncode is None and not self._closed

    async def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        """接收初始执行配置并启动持久 Worker，等待连接就绪后返回 client_ready 事件。"""
        if self._process is not None:
            raise ClientWorkerError("Client worker 已经启动")
        self._closed = False
        self._process = await _spawn_worker_process(payload)
        self._reader_task = asyncio.create_task(self._read_stdout(), name="ccsdk-client-stdout")
        self._stderr_task = asyncio.create_task(self._relay_stderr(), name="ccsdk-client-stderr")
        try:
            initial = dict(payload)
            initial["mode"] = "client"
            await self.send(initial)
            deadline = time.monotonic() + self.start_timeout_ms / 1000
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                event = await asyncio.wait_for(self.next_event(), remaining)
                if event.get("type") == "client_ready":
                    return event
                if event.get("type") == "client_error":
                    raise ClientWorkerError("Client worker 连接失败")
        except asyncio.TimeoutError as error:
            await self.terminate()
            raise ClientWorkerError("Client worker 连接超时") from error
        except asyncio.CancelledError:
            await self.terminate()
            raise
        except Exception:
            await self.terminate()
            raise

    async def send(self, message: dict[str, Any]) -> None:
        """将命令字典以 UTF-8 JSONL 写入 Worker，串行保护写入；无返回值，通道故障时抛出异常。"""
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None or self._closed:
            raise ClientWorkerError("Client worker 不可用")
        if not isinstance(message, dict):
            raise ValueError("Client worker message must be an object")
        encoded = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        async with self._write_lock:
            try:
                process.stdin.write(encoded)
                await asyncio.wait_for(process.stdin.drain(), self.send_timeout_ms / 1000)
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError as error:
                raise ClientWorkerError("Client worker 写入超时") from error
            except (BrokenPipeError, ConnectionError) as error:
                raise ClientWorkerError("Client worker 通道已关闭") from error

    async def next_event(self) -> dict[str, Any]:
        """等待并返回队列中的下一条 Worker 事件，无额外输入；遇到进程退出标记时抛出异常。"""
        event = await self._events.get()
        if event.get("type") == "worker_exit":
            code = event.get("code")
            raise ClientWorkerError(f"Client worker 退出（code={code}）")
        return event

    async def terminate(self) -> None:
        """终止持久 Worker 并回收读写后台任务，无额外输入和返回值。"""
        process = self._process
        self._closed = True
        if process is not None:
            await _terminate_process_tree(process)
        tasks = [task for task in (self._reader_task, self._stderr_task) if task is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._reader_task = None
        self._stderr_task = None
        self._process = None

    async def close(self) -> None:
        """请求 Worker 正常关闭并限时等待确认，最后回收进程，无额外输入和返回值。"""
        if self._process is None:
            self._closed = True
            return
        try:
            if self.alive:
                await self.send({"type": "client_close"})
                deadline = time.monotonic() + self.close_timeout_ms / 1000
                while time.monotonic() < deadline:
                    try:
                        event = await asyncio.wait_for(self.next_event(), max(0.01, deadline - time.monotonic()))
                    except (ClientWorkerError, asyncio.TimeoutError):
                        break
                    if event.get("type") == "client_closed":
                        break
        finally:
            await self.terminate()

    async def _read_stdout(self) -> None:
        """持续读取 Worker 标准输出，将合法 JSON 事件和退出标记放入内部队列；无返回值。"""
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while line := await process.stdout.readline():
                try:
                    event = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(event, dict):
                    await self._events.put(event)
        finally:
            code = await process.wait()
            await self._events.put({"type": "worker_exit", "code": code})

    async def _relay_stderr(self) -> None:
        """读取 Worker 标准错误并添加来源前缀转发到父进程标准错误，无返回值。"""
        process = self._process
        if process is None or process.stderr is None:
            return
        while line := await process.stderr.readline():
            message = line.decode("utf-8", errors="replace").strip()
            if message:
                print(f"[python-client-agent] {message}", file=sys.stderr, flush=True)
