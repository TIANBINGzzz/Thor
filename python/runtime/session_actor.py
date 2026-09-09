"""Single-owner session actors for the persistent Claude SDK Client mode."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import Enum
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from runtime.process import ClientWorkerError, ClientWorkerProcess


LOGGER = logging.getLogger("ccsdk.session_actor")


class ActorState(str, Enum):
    NEW = "new"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class SessionActorError(RuntimeError):
    """Project-owned error for actor routing and Client worker failures."""

    def __init__(self, message: str, *, code: str = "session_actor_error") -> None:
        super().__init__(message)
        self.code = code


PublicEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
StateCallback = Callable[[dict[str, Any]], Awaitable[None]]
RunPreparation = Callable[[], Awaitable[Mapping[str, Any]]]
RunCleanup = Callable[[], Awaitable[None]]


async def _noop_public(_: str, __: dict[str, Any]) -> None:
    return


async def _noop_state(_: dict[str, Any]) -> None:
    return


@dataclass
class _Command:
    kind: str
    run_id: str | None
    payload: dict[str, Any] | None
    future: asyncio.Future[Any]
    prepare: RunPreparation | None = None
    cleanup: RunCleanup | None = None


@dataclass(frozen=True)
class _RunOutcome:
    status: str
    session_id: str | None = None


class SessionActor:
    """Own one persistent Client worker and serialize all session commands."""

    def __init__(
        self,
        session_key: str,
        initial_payload: Mapping[str, Any],
        *,
        on_public_event: PublicEventCallback | None = None,
        on_state: StateCallback | None = None,
        idle_ttl_ms: int = 300_000,
        worker_start_timeout_ms: int = 60_000,
        worker_send_timeout_ms: int = 5_000,
        worker_close_timeout_ms: int = 5_000,
        control_timeout_ms: int = 5_000,
        worker_factory: Callable[..., ClientWorkerProcess] | None = None,
    ) -> None:
        if not isinstance(session_key, str) or not session_key.strip():
            raise ValueError("session_key is required")
        if isinstance(idle_ttl_ms, bool) or not isinstance(idle_ttl_ms, int) or idle_ttl_ms <= 0:
            raise ValueError("idle_ttl_ms must be a positive integer")
        self.session_key = session_key
        self._initial_payload = dict(initial_payload)
        self._on_public_event = on_public_event or _noop_public
        self._on_state = on_state or _noop_state
        self._idle_ttl_ms = idle_ttl_ms
        self._worker_start_timeout_ms = worker_start_timeout_ms
        self._worker_send_timeout_ms = worker_send_timeout_ms
        self._worker_close_timeout_ms = worker_close_timeout_ms
        if isinstance(control_timeout_ms, bool) or not isinstance(control_timeout_ms, int) or control_timeout_ms <= 0:
            raise ValueError("control_timeout_ms must be a positive integer")
        self._control_timeout_ms = control_timeout_ms
        self._worker_factory = worker_factory or ClientWorkerProcess
        self._commands: asyncio.Queue[_Command] = asyncio.Queue()
        self._pending_runs: deque[_Command] = deque()
        self._run_commands: dict[str, _Command] = {}
        self._cancel_requested: set[str] = set()
        self._task: asyncio.Task[Any] | None = None
        self._worker: ClientWorkerProcess | None = None
        self._state = ActorState.NEW
        self._active_run_id: str | None = None
        self._last_session_id: str | None = self._initial_payload.get("resume")
        self._last_event_at: int | None = None
        self._created_at = int(time.time() * 1000)
        self._updated_at = self._created_at
        self._idle_deadline: int | None = None
        self._idle_handle: asyncio.TimerHandle | None = None
        self._close_requested = False
        self._streaming_state = "idle"
        self._active_run_started_at: int | None = None
        self._last_run_duration_ms: int | None = None
        self._last_error_code: str | None = None

    @property
    def config_fingerprint(self) -> str | None:
        value = self._initial_payload.get("_credential_binding")
        return str(value) if value is not None else None

    @property
    def state(self) -> ActorState:
        return self._state

    @property
    def active_run_id(self) -> str | None:
        return self._active_run_id

    @property
    def worker_pid(self) -> int | None:
        process = self._worker.process if self._worker else None
        return process.pid if process and process.returncode is None else None

    def snapshot(self) -> dict[str, Any]:
        return {
            "sessionKey": self.session_key,
            "state": self._state.value,
            "clientState": self._state.value,
            "activeRunId": self._active_run_id,
            "runtimeSessionRef": self._last_session_id,
            "workerPid": self.worker_pid,
            "lastEventAt": self._last_event_at,
            "createdAt": self._created_at,
            "updatedAt": self._updated_at,
            "idleDeadline": self._idle_deadline,
            "streamingState": self._streaming_state,
            "pendingRuns": len(self._pending_runs),
            "commandQueueDepth": self._commands.qsize(),
            "activeRunStartedAt": self._active_run_started_at,
            "lastRunDurationMs": self._last_run_duration_ms,
            "lastErrorCode": self._last_error_code,
        }

    async def submit(
        self,
        run_id: str,
        payload: Mapping[str, Any],
        *,
        prepare: RunPreparation | None = None,
        cleanup: RunCleanup | None = None,
    ) -> dict[str, Any]:
        self._cancel_idle_timer()
        command = await self._enqueue("run", run_id, dict(payload), prepare=prepare, cleanup=cleanup)
        try:
            result = await command.future
            return result
        except asyncio.CancelledError:
            # A cancelled HTTP/task waiter must not leave its command running
            # invisibly in the actor mailbox.
            cleanup_task = asyncio.create_task(self.cancel(run_id), name=f"ccsdk-cancel:{run_id}")
            try:
                await asyncio.shield(asyncio.wait_for(cleanup_task, self._control_timeout_ms / 1000))
            except (SessionActorError, ClientWorkerError, asyncio.TimeoutError) as cleanup_error:
                # Preserve the caller's cancellation while retaining the
                # original cancellation as the authoritative outcome.
                _ = cleanup_error
                if not cleanup_task.done():
                    cleanup_task.cancel()
                    await asyncio.gather(cleanup_task, return_exceptions=True)
            raise

    async def interrupt(self, run_id: str) -> None:
        command = await self._enqueue("interrupt", run_id, None)
        await command.future

    async def cancel(self, run_id: str) -> None:
        if run_id not in self._run_commands:
            raise SessionActorError("Run 不存在或已结束", code="run_not_active")
        # Set this before enqueuing the control command. If the Run is still in
        # the mailbox, the actor can skip it without starting preparation or a
        # provider query even though FIFO puts the cancel command after it.
        self._cancel_requested.add(run_id)
        if self._active_run_id != run_id:
            return
        command = await self._enqueue("cancel", run_id, None)
        await command.future

    async def close(self) -> None:
        task = self._task
        if task is None or task.done():
            if self._worker is not None:
                await self._worker.close()
            await self._reject_queued_commands()
            self._state = ActorState.CLOSED
            await self._notify_state()
            return
        command = await self._enqueue("close", None, None)
        await command.future
        await task

    async def _enqueue(
        self,
        kind: str,
        run_id: str | None,
        payload: dict[str, Any] | None,
        *,
        prepare: RunPreparation | None = None,
        cleanup: RunCleanup | None = None,
    ) -> _Command:
        if self._state in {ActorState.CLOSING, ActorState.CLOSED} and kind != "close":
            raise SessionActorError("SessionActor 已关闭", code="session_actor_closed")
        loop = asyncio.get_running_loop()
        command = _Command(kind, run_id, payload, loop.create_future(), prepare, cleanup)
        if kind == "run" and run_id is not None:
            if run_id in self._run_commands:
                raise SessionActorError("Run 已提交", code="run_already_submitted")
            self._run_commands[run_id] = command
        self._ensure_task()
        await self._commands.put(command)
        return command

    def _ensure_task(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name=f"ccsdk-session-actor:{self.session_key}")

    async def _loop(self) -> None:
        try:
            while self._state not in {ActorState.CLOSING, ActorState.CLOSED}:
                command = self._pending_runs.popleft() if self._pending_runs else await self._commands.get()
                if command.kind == "run":
                    if command.run_id in self._cancel_requested:
                        self._cancel_requested.discard(command.run_id or "")
                        self._resolve_run(command, {
                            "status": "cancelled",
                            "runtimeSessionRef": self._last_session_id,
                        })
                        continue
                    await self._execute_run(command)
                elif command.kind == "close":
                    await self._close_worker()
                    self._resolve(command, None)
                    break
                elif command.kind in {"interrupt", "cancel"}:
                    self._resolve_error(command, SessionActorError("当前没有活动 Run", code="no_active_run"))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._state = ActorState.FAILED
            await self._notify_state()
            await self._reject_queued_commands(
                SessionActorError("SessionActor 已失败", code="session_actor_failed")
            )
            raise error
        finally:
            if self._worker is not None:
                await self._close_worker()

    async def _execute_run(self, command: _Command) -> None:
        assert command.run_id is not None
        self._cancel_idle_timer()
        self._active_run_id = command.run_id
        self._active_run_started_at = int(time.time() * 1000)
        self._streaming_state = "waiting"
        self._last_error_code = None
        try:
            payload = dict(command.payload or {})
            if command.prepare is not None:
                prepared = await command.prepare()
                if not isinstance(prepared, Mapping):
                    raise SessionActorError("Run 准备结果无效", code="run_preparation_failed")
                payload.update(prepared)
            await self._ensure_worker()
            self._state = ActorState.RUNNING
            await self._notify_state()
            outcome = await self._run_worker_command(command.run_id, payload)
            if outcome.session_id:
                self._last_session_id = outcome.session_id
            if self._close_requested:
                await self._close_worker()
            elif outcome.status == "cancelled":
                await self._discard_worker()
                self._state = ActorState.FAILED
                self._streaming_state = "cancelled"
                self._last_error_code = "cancelled"
            else:
                self._state = ActorState.READY
                self._streaming_state = "idle"
            result = {
                "status": outcome.status,
                "runtimeSessionRef": self._last_session_id,
            }
            await self._cleanup_run(command)
            self._resolve_run(command, result)
        except asyncio.CancelledError:
            await self._cleanup_run(command)
            self._resolve_run_error(command, SessionActorError("SessionActor 被取消", code="cancelled"))
            raise
        except (SessionActorError, ClientWorkerError) as error:
            self._last_error_code = getattr(error, "code", None) or "worker_error"
            await self._discard_worker()
            self._state = ActorState.FAILED
            self._streaming_state = "failed"
            await self._cleanup_run(command)
            self._resolve_run_error(command, self._as_actor_error(error))
        except Exception as error:
            self._last_error_code = getattr(error, "code", None) or "session_actor_error"
            await self._discard_worker()
            self._state = ActorState.FAILED
            self._streaming_state = "failed"
            await self._cleanup_run(command)
            self._resolve_run_error(command, SessionActorError("SessionActor 执行失败", code=self._last_error_code))
        finally:
            if self._active_run_started_at is not None:
                self._last_run_duration_ms = max(0, int(time.time() * 1000) - self._active_run_started_at)
            self._active_run_id = None
            self._active_run_started_at = None
            await self._notify_state()
            if self._state == ActorState.READY and not self._pending_runs and self._commands.empty():
                self._schedule_idle_close()

    async def _cleanup_run(self, command: _Command) -> None:
        if command.cleanup is None:
            return
        try:
            # Resolve the submit Future only after cleanup.  The next queued
            # Run and the outer Runtime task therefore cannot race with the
            # previous Run's current-input cleanup.
            await command.cleanup()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._last_error_code = self._last_error_code or "run_cleanup_error"
            LOGGER.warning("SessionActor Run cleanup failed: %s", type(error).__name__)

    async def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.alive and self._state == ActorState.READY:
            return
        if self._worker is not None:
            await self._worker.terminate()
        payload = dict(self._initial_payload)
        if self._last_session_id:
            payload["resume"] = self._last_session_id
        self._state = ActorState.STARTING
        await self._notify_state()
        self._worker = self._worker_factory(
            start_timeout_ms=self._worker_start_timeout_ms,
            send_timeout_ms=self._worker_send_timeout_ms,
            close_timeout_ms=self._worker_close_timeout_ms,
        )
        try:
            await self._worker.start(payload)
        except (ClientWorkerError, asyncio.TimeoutError) as error:
            self._worker = None
            self._state = ActorState.FAILED
            await self._notify_state()
            raise self._as_actor_error(error, code="sdk_connection_error") from error
        self._state = ActorState.READY
        await self._notify_state()

    async def _run_worker_command(self, run_id: str, payload: dict[str, Any]) -> _RunOutcome:
        worker = self._worker
        if worker is None or not worker.alive:
            raise SessionActorError("Client worker 不可用", code="sdk_connection_error")
        command = {"type": "client_query", "run_id": run_id, **payload}
        await worker.send(command)
        timeout_value = payload.get("timeout_ms", payload.get("timeoutMs"))
        deadline = (
            time.monotonic() + timeout_value / 1000
            if isinstance(timeout_value, int) and not isinstance(timeout_value, bool) and timeout_value > 0
            else None
        )
        next_task: asyncio.Task[Any] | None = asyncio.create_task(worker.next_event(), name="ccsdk-actor-event")
        command_task: asyncio.Task[Any] | None = asyncio.create_task(self._commands.get(), name="ccsdk-actor-command")
        try:
            while True:
                assert next_task is not None and command_task is not None
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise SessionActorError("Claude Client 执行超时", code="sdk_timeout")
                done, _ = await asyncio.wait(
                    {next_task, command_task},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    raise SessionActorError("Claude Client 执行超时", code="sdk_timeout")
                if next_task in done:
                    event = next_task.result()
                    next_task = asyncio.create_task(worker.next_event(), name="ccsdk-actor-event")
                    simultaneous_command: _Command | None = None
                    if command_task in done:
                        simultaneous_command = command_task.result()
                        command_task = asyncio.create_task(self._commands.get(), name="ccsdk-actor-command")
                    else:
                        command_task.cancel()
                        await asyncio.gather(command_task, return_exceptions=True)
                        command_task = asyncio.create_task(self._commands.get(), name="ccsdk-actor-command")
                    event_type = event.get("type")
                    self._last_event_at = int(time.time() * 1000)
                    self._updated_at = self._last_event_at
                    if event_type in {"client_ready", "client_control_ack"}:
                        if simultaneous_command is not None:
                            await self._handle_active_command(simultaneous_command, run_id, worker)
                        continue
                    if event_type in {"client_run_completed", "client_run_cancelled", "client_error"}:
                        session_id = event.get("session_id") or event.get("sessionId")
                        if session_id:
                            self._last_session_id = str(session_id)
                        if simultaneous_command is not None and simultaneous_command.kind == "run":
                            self._pending_runs.append(simultaneous_command)
                        elif simultaneous_command is not None:
                            self._resolve_error(
                                simultaneous_command,
                                SessionActorError("当前 Run 已结束", code="run_not_active"),
                            )
                        if event_type == "client_run_completed":
                            return _RunOutcome("succeeded", self._last_session_id)
                        if event_type == "client_run_cancelled":
                            return _RunOutcome("cancelled", self._last_session_id)
                        raise SessionActorError("Claude Client 执行失败", code=str(event.get("code") or "sdk_execution_error"))
                    if event_type == "worker_exit":
                        raise ClientWorkerError("Client worker 已退出")
                    if event_type in {"init", "text", "thinking", "tool_use", "tool_result", "activity", "tool_progress", "result", "error"}:
                        session_id = event.get("sessionId")
                        if session_id:
                            self._last_session_id = str(session_id)
                        await self._on_public_event(run_id, event)
                        if event_type in {"text", "thinking", "tool_use", "tool_progress", "activity"}:
                            self._streaming_state = "streaming"
                        elif event_type in {"result", "error"}:
                            self._streaming_state = "idle" if event_type == "result" else "failed"
                    if simultaneous_command is not None:
                        await self._handle_active_command(simultaneous_command, run_id, worker)
                    continue

                command_value = command_task.result()
                command_task = asyncio.create_task(self._commands.get(), name="ccsdk-actor-command")
                await self._handle_active_command(command_value, run_id, worker)
        finally:
            for task in (next_task, command_task):
                if task is not None and not task.done():
                    task.cancel()
            pending = [task for task in (next_task, command_task) if task is not None]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _close_worker(self) -> None:
        self._cancel_idle_timer()
        self._state = ActorState.CLOSING
        await self._notify_state()
        worker = self._worker
        self._worker = None
        if worker is not None:
            try:
                await worker.close()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._last_error_code = self._last_error_code or "worker_cleanup_error"
        await self._reject_queued_commands(
            SessionActorError("SessionActor 已关闭", code="session_actor_closed")
        )
        self._state = ActorState.CLOSED
        self._streaming_state = "closed"
        await self._notify_state()

    async def _discard_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        try:
            await worker.terminate()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._last_error_code = self._last_error_code or "worker_cleanup_error"

    async def _handle_active_command(
        self,
        command_value: _Command,
        run_id: str,
        worker: ClientWorkerProcess,
    ) -> None:
        command_type = command_value.kind
        if command_type == "run":
            self._pending_runs.append(command_value)
            return
        if command_type == "interrupt":
            if command_value.run_id == run_id:
                await worker.send({"type": "client_interrupt", "run_id": run_id})
                self._resolve(command_value, None)
            else:
                self._resolve_error(command_value, SessionActorError("Run 不属于当前活动 Client", code="run_not_active"))
            return
        if command_type == "cancel":
            if command_value.run_id == run_id:
                self._cancel_requested.discard(run_id)
                await worker.send({"type": "client_cancel", "run_id": run_id})
                self._resolve(command_value, None)
            else:
                self._resolve_error(command_value, SessionActorError("Run 不属于当前活动 Client", code="run_not_active"))
            return
        if command_type == "close":
            self._close_requested = True
            await worker.send({"type": "client_close"})
            self._resolve(command_value, None)
            return
        self._resolve_error(
            command_value,
            SessionActorError("未知的 SessionActor 命令", code="invalid_command"),
        )

    def _schedule_idle_close(self) -> None:
        self._cancel_idle_timer()
        loop = asyncio.get_running_loop()
        self._idle_deadline = int(time.time() * 1000) + self._idle_ttl_ms
        self._idle_handle = loop.call_later(self._idle_ttl_ms / 1000, self._idle_close_callback)

    def _idle_close_callback(self) -> None:
        self._idle_handle = None
        asyncio.create_task(self.close(), name=f"ccsdk-idle-close:{self.session_key}")

    def _cancel_idle_timer(self) -> None:
        if self._idle_handle is not None:
            self._idle_handle.cancel()
            self._idle_handle = None
        self._idle_deadline = None

    async def _notify_state(self) -> None:
        self._updated_at = int(time.time() * 1000)
        await self._on_state(self.snapshot())

    async def _reject_queued_commands(self, error: SessionActorError | None = None) -> None:
        """Resolve every command that can no longer be consumed by the actor."""

        failure = error or SessionActorError("SessionActor 已关闭", code="session_actor_closed")
        while self._pending_runs:
            self._resolve_run_error(self._pending_runs.popleft(), failure)
        while True:
            try:
                command = self._commands.get_nowait()
            except asyncio.QueueEmpty:
                break
            if command.kind == "close":
                self._resolve(command, None)
            elif command.kind == "run":
                self._resolve_run_error(command, failure)
            else:
                self._resolve_error(command, failure)
        self._cancel_requested.clear()

    @staticmethod
    def _resolve(command: _Command, value: Any) -> None:
        if not command.future.done():
            command.future.set_result(value)

    @staticmethod
    def _resolve_error(command: _Command, error: BaseException) -> None:
        if not command.future.done():
            command.future.set_exception(error)

    def _resolve_run(self, command: _Command, value: Any) -> None:
        if command.run_id is not None:
            self._run_commands.pop(command.run_id, None)
            self._cancel_requested.discard(command.run_id)
        self._resolve(command, value)

    def _resolve_run_error(self, command: _Command, error: BaseException) -> None:
        if command.run_id is not None:
            self._run_commands.pop(command.run_id, None)
            self._cancel_requested.discard(command.run_id)
        self._resolve_error(command, error)

    @staticmethod
    def _as_actor_error(error: BaseException, *, code: str | None = None) -> SessionActorError:
        if isinstance(error, SessionActorError):
            return error
        return SessionActorError(str(error) or "SessionActor 执行失败", code=code or "session_actor_error")


class SessionManager:
    """Route one session key to one actor and map active Runs to that actor."""

    def __init__(
        self,
        *,
        on_public_event: PublicEventCallback | None = None,
        on_state: StateCallback | None = None,
        idle_ttl_ms: int = 300_000,
        worker_factory: Callable[..., ClientWorkerProcess] | None = None,
    ) -> None:
        self._on_public_event = on_public_event
        self._on_state = on_state
        self._idle_ttl_ms = idle_ttl_ms
        self._worker_factory = worker_factory
        self._actors: dict[str, SessionActor] = {}
        self._run_actors: dict[str, SessionActor] = {}
        self._lock = asyncio.Lock()

    async def submit(
        self,
        session_key: str,
        initial_payload: Mapping[str, Any],
        run_id: str,
        payload: Mapping[str, Any],
        *,
        prepare: RunPreparation | None = None,
        cleanup: RunCleanup | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            actor = self._actors.get(session_key)
            incoming_fingerprint = initial_payload.get("_credential_binding")
            if actor is not None and actor.config_fingerprint != (
                str(incoming_fingerprint) if incoming_fingerprint is not None else None
            ):
                if actor.active_run_id is not None:
                    raise SessionActorError("Client 凭据正在使用，不能在活动 Run 中切换", code="credential_binding_busy")
                await actor.close()
                actor = None
            if actor is None or actor.state == ActorState.CLOSED:
                actor = SessionActor(
                    session_key,
                    initial_payload,
                    on_public_event=self._on_public_event,
                    on_state=self._on_state,
                    idle_ttl_ms=self._idle_ttl_ms,
                    worker_factory=self._worker_factory,
                )
                self._actors[session_key] = actor
            self._run_actors[run_id] = actor
        try:
            return await actor.submit(run_id, payload, prepare=prepare, cleanup=cleanup)
        finally:
            async with self._lock:
                self._run_actors.pop(run_id, None)

    async def interrupt(self, run_id: str) -> None:
        actor = self._run_actors.get(run_id)
        if actor is None:
            raise SessionActorError("Run 不存在或已结束", code="run_not_active")
        await actor.interrupt(run_id)

    async def cancel(self, run_id: str) -> None:
        actor = self._run_actors.get(run_id)
        if actor is None:
            raise SessionActorError("Run 不存在或已结束", code="run_not_active")
        await actor.cancel(run_id)

    def actor_for_run(self, run_id: str) -> SessionActor | None:
        return self._run_actors.get(run_id)

    def snapshots(self) -> list[dict[str, Any]]:
        return [actor.snapshot() for actor in self._actors.values()]

    async def close_all(self) -> None:
        actors = list(self._actors.values())
        if actors:
            await asyncio.gather(*(actor.close() for actor in actors), return_exceptions=True)
        self._actors.clear()
        self._run_actors.clear()


__all__ = ["ActorState", "SessionActor", "SessionActorError", "SessionManager"]
