"""预连接未绑定身份的 Client；领取后归 Actor 独占，永不跨会话归还。"""
import asyncio
from collections import deque
import logging
from pathlib import Path
import time
import weakref
import uuid

import psutil

from runtime.process import ClientWorkerProcess, ClientWorkerError
from runtime.telemetry import exception_event

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
                 max_live=0, payload_factory=None, cleanup_workspace=None, worker_factory=ClientWorkerProcess, observer=None):
        """空闲数与总存活数分开；创建中及已保留的连接也占容量。"""
        for value, minimum in ((max_idle, 0), (max_starting, 1), (min_available_memory_mib, 0), (max_live, 0)):
            if type(value) is not int or value < minimum:
                raise ValueError('Worker pool limits must be nonnegative integers; max_starting must be positive')
        self.max_idle = max_idle
        self.max_starting = max_starting
        self.min_available_memory_mib = min_available_memory_mib
        self._factory = worker_factory
        self.max_live = max_live
        self._payload_factory = payload_factory
        self._cleanup_workspace = cleanup_workspace
        self._reserved = {}
        self._payloads = weakref.WeakKeyDictionary()
        self._ready = deque()
        self._starting = set()
        self._retiring = set()
        self._retiring_workers = set()
        self._leased = weakref.WeakSet()
        self._task = None
        self._wake = asyncio.Event()
        self._acquire_lock = asyncio.Lock()
        self._closed = False
        self._hits = self._misses = self._failures = 0
        self._backoff = 1.0
        self._retry_at = 0.0
        self._memory_paused = False
        self._memory_resume_at = 0.0
        self._observer = observer

    def _observe(self, worker, name, **values):
        if self._observer:
            try:
                self._observer.emit('pool',getattr(worker,'observation_warm_id','pool'),{'name':name,**values})
            except Exception:
                pass

    def _observe_startup(self, warm_id, event):
        """预热只有自身关联标识；连接证据不得归入尚不存在的业务 Run。"""
        if self._observer:
            try:
                if event.get('type') == 'diagnostic':
                    self._observer.emit('evidence', warm_id, event)
                elif event.get('type') == 'performance':
                    self._observer.emit('milestone', warm_id, event)
            except Exception:
                pass

    def start(self):
        """后台预热，不让模型服务或预热失败阻塞 HTTP 启动。"""
        if self._closed:
            raise RuntimeError('Worker pool is closed')
        if self._task is None and self.max_idle:
            self._task = asyncio.create_task(self._maintain(), name='ccsdk-worker-pool')

    def reserve_workspace(self):
        """仅为新业务会话保留空白 Client；数据库完成归属绑定后按目录领取。"""
        if self._closed or self._payload_factory is None:
            return None
        while self._ready:
            worker = self._ready.popleft()
            if not worker.alive:
                self._retire(worker)
                continue
            directory = self._payloads[worker]['session_directory']
            self._reserved[directory] = worker
            self._wake.set()
            return directory
        return None

    def release_workspace(self, directory):
        """准备失败或尚未领取时销毁连接；已绑定目录不删除、不跨身份回池。"""
        worker = self._reserved.pop(str(directory), None)
        if worker is not None:
            self._retire(worker)
            self._wake.set()

    def _live_count(self):
        # 关闭标记先于进程树回收；释放进程引用前仍占容量，避免新旧 Client 重叠超限。
        return (sum(w.alive or w.awaiting_connection or w.process is not None for w in self._leased)
                + len(self._ready) + len(self._reserved) + len(self._starting) + len(self._retiring_workers))

    async def acquire(self, initial_payload=None, **kwargs):
        """事件循环内原子领取；耗尽走现有冷启动，调用方立即拥有清理责任。"""
        async with self._acquire_lock:
            return await self._acquire(initial_payload, **kwargs)

    async def _acquire(self, initial_payload, **kwargs):
        if self._closed:
            raise RuntimeError('Worker pool is closed')
        worker = None
        started=time.perf_counter()
        reason='history_restore' if (initial_payload or {}).get('resume') else 'no_reserved_client'
        if self._payload_factory is not None and initial_payload:
            candidate = self._reserved.pop(initial_payload.get('session_directory'), None)
            if candidate is not None:
                expected = self._payloads[candidate]
                if (candidate.alive and not initial_payload.get('resume')
                        and expected.get('_client_connection_fingerprint') == initial_payload.get('_client_connection_fingerprint')):
                    worker = candidate
                else:
                    reason='dead_client' if not candidate.alive else 'binding_changed'
                    self._retire(candidate)
        while self._payload_factory is None and self._ready:
            candidate = self._ready.popleft()
            if candidate.alive:
                worker = candidate
                break
            self._retire(candidate)
        if worker is None:
            # 空白预热不能挤占历史恢复或固定配置变化后的业务连接。
            if self.max_live and self._live_count() >= self.max_live and self._ready:
                # 请求取消只结束等待；退出任务仍归池管理并继续占用容量。
                await asyncio.shield(self._retire(self._ready.popleft()))
            if self.max_live and self._live_count() >= self.max_live and self._starting:
                task = next(iter(self._starting))
                task.cancel()
                await asyncio.shield(asyncio.gather(task, return_exceptions=True))
            if self.max_live and self._live_count() >= self.max_live and self._retiring:
                await asyncio.shield(asyncio.gather(*tuple(self._retiring), return_exceptions=True))
            if self.max_live and self._live_count() >= self.max_live:
                raise ClientWorkerError('Client 容量已满，请稍后重试')
            self._misses += 1
            worker = self._factory(**kwargs)
            source = 'cold'
        else:
            self._hits += 1
            source = 'prewarmed'
            for key, value in kwargs.items():
                setattr(worker, key, value)
        self._leased.add(worker)
        worker.observation_acquisition={'source':source,'missReason':reason if source=='cold' else None,
            'elapsedMs':round((time.perf_counter()-started)*1000,3),
            'warmRunId':getattr(worker,'observation_warm_id',None)}
        self._observe(worker,'acquired',**worker.observation_acquisition)
        LOGGER.info('Worker acquired: source=%s pool=%s', source, self.snapshot())
        self._wake.set()
        return worker

    def snapshot(self):
        """仅返回非秘密计数，命中率分母是需要新 Worker 的次数。"""
        return {'ready': sum(w.alive for w in self._ready), 'starting': len(self._starting),
                'reserved': len(self._reserved), 'max_live': self.max_live,
                'leased_alive': sum(w.alive for w in self._leased),
                'leased_connecting': sum(w.awaiting_connection for w in self._leased),
                'hits': self._hits, 'misses': self._misses, 'failures': self._failures,
                'memory_paused': self._memory_paused}

    def memory_snapshot(self):
        """按 PID 采样进程树 RSS/PSS；不读取身份、命令行或凭据。"""
        roots = [(w.process.pid, 'idle') for w in self._ready if w.alive and w.process]
        roots += [(w.process.pid, 'leased') for w in self._leased if w.alive and w.process]
        roots += [(w.process.pid, 'reserved') for w in self._reserved.values() if w.alive and w.process]
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
        self._retiring_workers.add(worker)
        task = asyncio.create_task(self._terminate(worker), name='ccsdk-pool-retire')
        self._retiring.add(task)
        task.add_done_callback(self._retiring.discard)
        return task

    async def _terminate(self, worker):
        try:
            self._observe(worker,'retiring')
            await worker.terminate()
            payload = self._payloads.pop(worker, None)
            if payload and self._cleanup_workspace:
                self._cleanup_workspace(payload['session_directory'])
        except Exception as error:
            LOGGER.warning('Worker pool cleanup failed: %s', type(error).__name__)
        finally:
            self._retiring_workers.discard(worker)

    def _prepared(self, task):
        # 即使协程尚未执行第一行就被取消，也必须归还创建名额。
        self._starting.discard(task)
        self._wake.set()

    async def _prepare(self):
        worker = None
        warm_id = 'warm:' + uuid.uuid4().hex
        started=time.perf_counter()
        wall=time.time_ns()/1000000
        outcome='failed'
        try:
            worker = self._factory()
            worker.observation_warm_id = warm_id
            if self._observer and hasattr(worker, 'set_observation_callback'):
                try:
                    worker.set_observation_callback(self._observe_startup, run_id=warm_id)
                except Exception:
                    pass
            self._observe(worker,'prewarm_started')
            if self._payload_factory is None:
                await worker.prewarm()
            else:
                payload = self._payload_factory()
                self._payloads[worker] = payload
                await worker.preconnect(payload)
            if self._closed:
                await self._terminate(worker)
            else:
                self._ready.append(worker)
                self._backoff = 1.0
                outcome='ready'
                self._observe(worker,'prewarm_ready')
        except asyncio.CancelledError:
            if worker is not None:
                await self._terminate(worker)
            raise
        except Exception as error:
            if self._observer:
                try:
                    self._observe_startup(warm_id, exception_event(error, scope='pool_prewarm'))
                except Exception:
                    pass
            if worker is not None:
                await self._terminate(worker)
            self._failures += 1
            self._retry_at = time.monotonic() + self._backoff
            self._backoff = min(30.0, self._backoff * 2)
            LOGGER.warning('Worker prewarm failed: %s', type(error).__name__)
        finally:
            if worker is not None and self._observer:
                try:
                    self._observer.span(worker.observation_warm_id,'prewarm',wall,(time.perf_counter()-started)*1000,
                        attributes={'pool.outcome':outcome},identity='prewarm')
                    for event in getattr(worker, 'startup_traces', ()):
                        self._observer.performance(worker.observation_warm_id,event,parent=self._observer.span_id(worker.observation_warm_id,'prewarm'))
                except Exception:
                    pass
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
                  and not self._acquire_lock.locked()
                  and not any(w.awaiting_connection for w in self._leased)):
                # SDK 初始化会创建 CLI/MCP 进程；业务连接期间不再发起后台导入争抢 CPU/I/O。
                count = min(self.max_idle - len(self._ready) - len(self._starting),
                            self.max_starting - len(self._starting))
                if self.max_live:
                    count = min(count, self.max_live - self._live_count())
                for _ in range(max(0, count)):
                    task = asyncio.create_task(self._prepare(), name='ccsdk-worker-prewarm')
                    self._starting.add(task)
                    task.add_done_callback(self._prepared)
            if time.monotonic() >= next_sample:
                # 先在事件循环捕获根 PID，避免在线程中遍历变化的队列。
                roots = [(w.process.pid, 'idle') for w in self._ready if w.alive and w.process]
                roots += [(w.process.pid, 'leased') for w in self._leased if w.alive and w.process]
                roots += [(w.process.pid, 'reserved') for w in self._reserved.values() if w.alive and w.process]
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
        workers.extend(self._reserved.values())
        self._reserved.clear()
        self._ready.clear()
        await asyncio.gather(*(self._terminate(w) for w in workers), *self._retiring, return_exceptions=True)
