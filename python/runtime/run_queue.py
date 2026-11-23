"""已授权 Run 的排队顺序、等待预算和执行交接。"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import TypeVar

_T = TypeVar('_T')


class RunQueueError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RunQueue:
    def __init__(self, *, max_pending: int):
        self._limit = max_pending
        self._pending = 0
        self._sessions: dict[str, deque[QueuedRun]] = {}
        self._waiting: dict[str, dict[QueuedRun, None]] = {}
        self._changes: set[asyncio.Future] = set()
        self._closed = False

    def enqueue(self, session_key: str, *, timeout_ms: int) -> QueuedRun:
        if self._closed:
            raise RunQueueError('runtime_stopping')
        if self._pending >= self._limit:
            raise RunQueueError('worker_capacity_exceeded')
        run = QueuedRun(self, session_key, timeout_ms / 1000)
        self._sessions.setdefault(session_key, deque()).append(run)
        self._pending += 1
        return run

    @property
    def pending(self) -> int:
        return self._pending

    def waiting_for(self, resource: str) -> bool:
        return bool(self._waiting.get(resource))

    def notify(self) -> None:
        for changed in self._changes:
            if not changed.done():
                changed.set_result(None)
        self._changes.clear()

    def close(self) -> None:
        self._closed = True
        self.notify()


class QueuedRun:
    def __init__(self, queue: RunQueue, session_key: str, seconds: float):
        self._queue = queue
        self._key = session_key
        self._remaining = seconds
        self._enqueued_at = time.monotonic()
        self._dispatched = False
        self._released = False

    async def wait_turn(self) -> None:
        """等本会话上一轮收尾；扣除等待，暂不计随后的附件准备时间。"""
        await self._wait(lambda: self._queue._sessions[self._key][0] is self,
                         started=self._enqueued_at)

    async def wait_for(self, try_take: Callable[[], _T | None], *, resource: str,
                       try_reuse: Callable[[], _T | None] | None = None) -> _T:
        """只在相同资源的等待者之间按序领取；资源检查不持锁、不跨 await。"""
        waiting = self._queue._waiting.setdefault(resource, {})
        waiting[self] = None

        def probe():
            # 现成资源不和新启动竞争，队首暂时启动不了也不妨碍其他会话命中。
            value = try_reuse() if try_reuse is not None else None
            if value is None and next(iter(waiting)) is self:
                value = try_take()
            return (True, value) if value is not None else None

        try:
            _, value = await self._wait(probe, started=time.monotonic())
            return value
        finally:
            waiting.pop(self, None)
            if not waiting:
                self._queue._waiting.pop(resource)
            self._queue.notify()

    async def _wait(self, probe, *, started):
        queue = self._queue
        deadline = started + self._remaining
        try:
            while True:
                if queue._closed:
                    raise RunQueueError('runtime_stopping')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RunQueueError('run_queue_timeout')
                if result := probe():
                    return result
                changed = asyncio.get_running_loop().create_future()
                queue._changes.add(changed)
                try:
                    await asyncio.wait_for(changed, remaining)
                except TimeoutError:
                    raise RunQueueError('run_queue_timeout') from None
                finally:
                    queue._changes.discard(changed)
        finally:
            self._remaining = max(0, deadline - time.monotonic())

    def dispatch(self) -> None:
        """出队后继续持有会话顺序，直到执行和收尾完毕。"""
        if not self._dispatched:
            self._dispatched = True
            self._queue._pending -= 1

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if not self._dispatched:
            self._queue._pending -= 1
        session = self._queue._sessions[self._key]
        session.remove(self)
        if not session:
            del self._queue._sessions[self._key]
        self._queue.notify()
