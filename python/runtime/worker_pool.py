"""预热未绑定的 Python 进程；领取后归 Actor 独占，永不跨会话归还。"""
import asyncio
from collections import deque
import logging
from pathlib import Path
import time
import weakref

import psutil

from runtime.process import ClientWorkerProcess

LOGGER = logging.getLogger('ccsdk.worker_pool')


def configure_worker_logging():
    """独立开启数值观测，不打开 SDK/httpx 等库的详细日志。"""
    for name in ('ccsdk.worker_pool', 'ccsdk.session_actor'):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


def available_memory_mib():
    """同时考虑宿主机与容器 cgroup 剩余量；不读取进程参数或环境。"""
    available = psutil.virtual_memory().available
    for limit_file, usage_file in (
        ('/sys/fs/cgroup/memory.max', '/sys/fs/cgroup/memory.current'),
        ('/sys/fs/cgroup/memory/memory.limit_in_bytes', '/sys/fs/cgroup/memory/memory.usage_in_bytes'),
    ):
        try:
            limit = int(Path(limit_file).read_text())
            usage = int(Path(usage_file).read_text())
            available = min(available, max(0, limit - usage))
        except (OSError, ValueError):
            pass
    return available / 1048576


class WorkerPool:
    def __init__(self, *, max_idle, max_starting, min_available_memory_mib=0,
                 worker_factory=ClientWorkerProcess):
        """容量只含未绑定进程；创建中的进程也占容量。"""
        for value, minimum in ((max_idle, 0), (max_starting, 1), (min_available_memory_mib, 0)):
            if type(value) is not int or value < minimum:
                raise ValueError('Worker pool limits must be nonnegative integers; max_starting must be positive')
        self.max_idle = max_idle
        self.max_starting = max_starting
        self.min_available_memory_mib = min_available_memory_mib
        self._factory = worker_factory
        self._ready = deque()
        self._starting = set()
        self._retiring = set()
        self._leased = weakref.WeakSet()
        self._task = None
        self._wake = asyncio.Event()
        self._closed = False
        self._hits = self._misses = self._failures = 0
        self._backoff = 1.0
        self._retry_at = 0.0
        self._memory_paused = False
        self._memory_resume_at = 0.0

    def start(self):
        """后台预热，不让模型服务或预热失败阻塞 HTTP 启动。"""
        if self._closed:
            raise RuntimeError('Worker pool is closed')
        if self._task is None and self.max_idle:
            self._task = asyncio.create_task(self._maintain(), name='ccsdk-worker-pool')

    def acquire(self, **kwargs):
        """事件循环内原子领取；耗尽走现有冷启动，调用方立即拥有清理责任。"""
        if self._closed:
            raise RuntimeError('Worker pool is closed')
        worker = None
        while self._ready:
            candidate = self._ready.popleft()
            if candidate.alive:
                worker = candidate
                break
            self._retire(candidate)
        if worker is None:
            self._misses += 1
            worker = self._factory(**kwargs)
            source = 'cold'
        else:
            self._hits += 1
            source = 'prewarmed'
            for key, value in kwargs.items():
                setattr(worker, key, value)
        self._leased.add(worker)
        LOGGER.info('Worker acquired: source=%s pool=%s', source, self.snapshot())
        self._wake.set()
        return worker

    def snapshot(self):
        """仅返回非秘密计数，命中率分母是需要新 Worker 的次数。"""
        return {'ready': sum(w.alive for w in self._ready), 'starting': len(self._starting),
                'leased_alive': sum(w.alive for w in self._leased),
                'leased_connecting': sum(w.awaiting_connection for w in self._leased),
                'hits': self._hits, 'misses': self._misses, 'failures': self._failures,
                'memory_paused': self._memory_paused}

    def memory_snapshot(self):
        """按 PID 采样进程树 RSS/PSS；不读取身份、命令行或凭据。"""
        roots = [(w.process.pid, 'idle') for w in self._ready if w.alive and w.process]
        roots += [(w.process.pid, 'leased') for w in self._leased if w.alive and w.process]
        return self._measure_memory(roots)

    @staticmethod
    def _measure_memory(roots):
        records = []
        seen = set()
        for pid, state in roots:
            try:
                root = psutil.Process(pid)
                processes = [root, *root.children(recursive=True)]
            except psutil.Error:
                continue
            for process in processes:
                if process.pid in seen:
                    continue
                seen.add(process.pid)
                try:
                    info = process.memory_full_info()
                    records.append({'pid': process.pid, 'worker_pid': pid, 'state': state,
                        'rss_mib': round(info.rss / 1048576, 1),
                        'pss_mib': round(info.pss / 1048576, 1) if hasattr(info, 'pss') else None})
                except psutil.Error:
                    pass
        return records

    def _retire(self, worker):
        task = asyncio.create_task(self._terminate(worker), name='ccsdk-pool-retire')
        self._retiring.add(task)
        task.add_done_callback(self._retiring.discard)

    async def _terminate(self, worker):
        try:
            await worker.terminate()
        except Exception as error:
            LOGGER.warning('Worker pool cleanup failed: %s', type(error).__name__)

    def _prepared(self, task):
        # 即使协程尚未执行第一行就被取消，也必须归还创建名额。
        self._starting.discard(task)
        self._wake.set()

    async def _prepare(self):
        worker = None
        try:
            worker = self._factory()
            await worker.prewarm()
            if self._closed:
                await worker.terminate()
            else:
                self._ready.append(worker)
                self._backoff = 1.0
        except asyncio.CancelledError:
            if worker is not None:
                await self._terminate(worker)
            raise
        except Exception as error:
            if worker is not None:
                await self._terminate(worker)
            self._failures += 1
            self._retry_at = time.monotonic() + self._backoff
            self._backoff = min(30.0, self._backoff * 2)
            LOGGER.warning('Worker prewarm failed: %s', type(error).__name__)
        finally:
            self._starting.discard(asyncio.current_task())
            self._wake.set()

    async def _maintain(self):
        next_sample = time.monotonic() + 15
        while not self._closed:
            self._wake.clear()
            if self.min_available_memory_mib:
                available = available_memory_mib()
                if self._memory_paused:
                    # 释放池本身会增加可用内存；需额外余量和冷却才恢复，避免反复导入。
                    if (available >= 2 * self.min_available_memory_mib
                            and time.monotonic() >= self._memory_resume_at):
                        self._memory_paused = False
                elif available < self.min_available_memory_mib:
                    self._memory_paused = True
                    self._memory_resume_at = time.monotonic() + 30
            kept = deque()
            while self._ready:
                worker = self._ready.popleft()
                if not worker.alive or self._memory_paused:
                    self._retire(worker)
                else:
                    kept.append(worker)
            self._ready = kept
            if self._memory_paused:
                for task in tuple(self._starting):
                    if not task.cancelling():
                        task.cancel()
            elif (time.monotonic() >= self._retry_at and not self._retiring
                  and not any(w.awaiting_connection for w in self._leased)):
                # SDK 初始化会创建 CLI/MCP 进程；业务连接期间不再发起后台导入争抢 CPU/I/O。
                count = min(self.max_idle - len(self._ready) - len(self._starting),
                            self.max_starting - len(self._starting))
                for _ in range(max(0, count)):
                    task = asyncio.create_task(self._prepare(), name='ccsdk-worker-prewarm')
                    self._starting.add(task)
                    task.add_done_callback(self._prepared)
            if time.monotonic() >= next_sample:
                # 先在事件循环捕获根 PID，避免在线程中遍历变化的队列。
                roots = [(w.process.pid, 'idle') for w in self._ready if w.alive and w.process]
                roots += [(w.process.pid, 'leased') for w in self._leased if w.alive and w.process]
                records = await asyncio.to_thread(self._measure_memory, roots)
                LOGGER.info('Worker pool: %s processes=%s', self.snapshot(), records)
                next_sample = time.monotonic() + 15
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=.5)
            except asyncio.TimeoutError:
                pass

    async def close(self):
        """停止补充并回收池内进程；已领取进程仍由 Actor 关闭。"""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        tasks = list(self._starting)
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._starting.clear()
        workers = list(self._ready)
        self._ready.clear()
        await asyncio.gather(*(w.terminate() for w in workers), *self._retiring, return_exceptions=True)
