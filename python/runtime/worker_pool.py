"""预连接未绑定身份的 Client；领取后归 Actor 独占，永不跨会话归还。"""
import asyncio
from collections import deque
import inspect
import logging
from pathlib import Path
import time
import weakref
import uuid

import psutil

from runtime.process import ClientWorkerProcess, ClientWorkerError
from runtime.telemetry import exception_event

LOGGER = logging.getLogger('ccsdk.worker_pool')
LOCAL_WORKER_START = 'local-worker-start'


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
            raw_limit = Path(limit_file).read_text().strip()
        except FileNotFoundError:
            continue
        except OSError:
            return 0
        if raw_limit == 'max':
            continue
        try:
            available = min(available, max(0, int(raw_limit) - int(Path(usage_file).read_text())))
        except (OSError, ValueError):
            return 0
    return available / 1048576


class WorkerPool:
    def __init__(self, *, max_idle, max_starting, min_available_memory_mib=0,
                 payload_factory=None, profile_payloads=None,
                 worker_factory=ClientWorkerProcess, observer=None, on_change=None, business_waiting=None):
        """管理预热库存与新启动许可；已绑定连接由 Actor 管理。"""
        for value, minimum in ((max_idle, 0), (max_starting, 1), (min_available_memory_mib, 0)):
            if type(value) is not int or value < minimum:
                raise ValueError('Worker pool limits must be nonnegative integers; max_starting must be positive')
        self.max_idle = max_idle
        self.max_starting = max_starting
        self.min_available_memory_mib = min_available_memory_mib
        self._factory = worker_factory
        self._payload_factory = payload_factory
        self._ready = deque()
        self._ready_profiles = {}
        self._idle_at = weakref.WeakKeyDictionary()
        self._starting = set()
        self._starting_profiles = {}
        self._business_starting = 0
        self._start_slots_used = 0
        self._profiles = {}
        for payload in profile_payloads or []:
            self.register_profile(payload)
        self._retiring = set()
        self._retiring_workers = set()
        self._leased = weakref.WeakSet()
        self._task = None
        self._wake = asyncio.Event()
        self._closed = False
        self._hits = self._misses = self._failures = 0
        self._backoff = 1.0
        self._retry_at = 0.0
        self._memory_paused = False
        self._memory_resume_at = 0.0
        self._observer = observer
        self._on_change = on_change
        self._business_waiting = business_waiting or (lambda: False)

    def notify(self):
        self._wake.set()
        if self._on_change is not None:
            self._on_change()

    def register_profile(self, payload):
        """分组仅保留启动信息；未知新配置按需进入共享预算，不保留身份及凭据。"""
        key = payload.get('_client_connection_fingerprint')
        if key is not None:
            self._profiles.pop(key, None)
            self._profiles[key] = {name: payload[name] for name in (
                'cwd', 'capability_ref', 'max_turns', '_client_runtime', '_client_connection_fingerprint') if name in payload}
            if hasattr(self, '_wake'):
                self._wake.set()

    def _profile_targets(self):
        # 配置种类超过空白池容量时，保留最近需求的分组；不允许每组各扩出 max_idle。
        keys = list(self._profiles)[-self.max_idle:] if self.max_idle else []
        if not keys:
            return {None: self.max_idle}
        share, remainder = divmod(self.max_idle, len(keys))
        return {key: share + int(index < remainder) for index, key in enumerate(keys)}

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
        if self._task is None:
            self._task = asyncio.create_task(self._maintain(), name='ccsdk-worker-pool')

    def _live_count(self):
        # 关闭中的进程在确认退出前仍计入观测。
        return (sum(w.alive or w.awaiting_connection or w.process is not None for w in self._leased)
                + len(self._ready) + self._start_slots_used - self._business_starting + len(self._retiring_workers))

    def _memory_allows_start(self):
        return not self.min_available_memory_mib or available_memory_mib() >= self.min_available_memory_mib

    def _pause_prewarm(self):
        if not self._memory_paused:
            self._memory_paused = True
            self._memory_resume_at = time.monotonic() + 30
            self._wake.set()

    def try_start(self, *, background=False):
        """在事件循环内紧邻启动检查余量并取得名额，返回幂等释放函数。"""
        if self._closed:
            raise ClientWorkerError('Runtime 正在关闭', code='runtime_stopping')
        if background and (self._memory_paused or self._business_waiting()):
            return None
        if not self._memory_allows_start():
            self._pause_prewarm()
            return None
        if self._start_slots_used >= self.max_starting:
            return None
        self._start_slots_used += 1
        self._business_starting += not background
        released = False

        def release():
            nonlocal released
            if not released:
                released = True
                self._start_slots_used -= 1
                self._business_starting -= not background
                self.notify()

        return release

    def _try_ready(self, initial_payload):
        if self._closed:
            raise RuntimeError('Worker pool is closed')
        payload = initial_payload or {}
        if self._payload_factory is not None and payload.get('resume'):
            return None
        for _ in range(len(self._ready)):
            candidate = self._ready.popleft()
            if not candidate.alive:
                self._retire(candidate)
            elif (self._payload_factory is None or self._ready_profiles[candidate]
                  == payload.get('_client_connection_fingerprint')):
                self._ready_profiles.pop(candidate)
                self._idle_at.pop(candidate, None)
                return candidate
            else:
                self._ready.append(candidate)
        return None

    async def acquire(self, initial_payload=None, *, queued_run=None, **kwargs):
        """空白连接按固定配置领取；只有需要新进程才参与启动顺序。"""
        started = time.perf_counter()
        if queued_run is not None:
            claim = await queued_run.wait_for(self.try_start, resource=LOCAL_WORKER_START,
                                              try_reuse=lambda: self._try_ready(initial_payload))
            release, worker = (claim, None) if callable(claim) else (None, claim)
        elif (worker := self._try_ready(initial_payload)) is None:
            release = self.try_start()
            if release is None:
                raise ClientWorkerError('Worker 当前不能启动', code='worker_memory_pressure')
        else:
            release = None
        if release is not None:
            try:
                worker = self._factory(**kwargs)
                worker._ccsdk_release_start_slot = release
                start = getattr(worker, 'start', None)
                if callable(start):
                    async def managed_start(*args, **options):
                        try:
                            result = start(*args, **options)
                            return await result if inspect.isawaitable(result) else result
                        finally:
                            release()
                    worker.start = managed_start
            except BaseException:
                release()
                raise
            self._misses += 1
            source = 'cold'
        else:
            self._hits += 1
            source = 'prewarmed'
            for key, value in kwargs.items():
                setattr(worker, key, value)
        self._leased.add(worker)
        reason = 'history_restore' if (initial_payload or {}).get('resume') else 'no_matching_client'
        worker.observation_acquisition={'source':source,'missReason':reason if source=='cold' else None,
            'elapsedMs':round((time.perf_counter()-started)*1000,3),
            'warmRunId':getattr(worker,'observation_warm_id',None)}
        self._observe(worker,'acquired',**worker.observation_acquisition)
        LOGGER.info('Worker acquired: source=%s pool=%s', source, self.snapshot())
        self.notify()
        return worker

    def snapshot(self):
        """仅返回非秘密计数，命中率分母是需要新 Worker 的次数。"""
        return {'ready': sum(w.alive for w in self._ready), 'starting': self._start_slots_used - self._business_starting,
                'live': self._live_count(), 'retiring': len(self._retiring_workers),
                'businessStarting': self._business_starting,
                'groups': {str(key): sum(self._ready_profiles[w] == key and w.alive
                    for w in self._ready) for key in self._profiles},
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
        self._idle_at.pop(worker, None)
        self._ready_profiles.pop(worker, None)
        self._retiring_workers.add(worker)
        task = asyncio.create_task(self._terminate(worker), name='ccsdk-pool-retire')
        self._retiring.add(task)
        task.add_done_callback(self._retired)
        return task

    def _retired(self, task):
        self._retiring.discard(task)
        self.notify()

    async def _terminate(self, worker):
        terminated = False
        try:
            self._observe(worker,'retiring')
            await worker.terminate()
            terminated = True
        except Exception as error:
            LOGGER.warning('Worker pool cleanup failed: %s', type(error).__name__)
            self._retry_at = time.monotonic() + self._backoff
            self._backoff = min(30.0, self._backoff * 2)
        finally:
            if terminated:
                self._retiring_workers.discard(worker)
                self.notify()
            else:
                # 终止异常或被取消仍保留强引用和容量，下次领取、补池或关闭时重试。
                self._retiring_workers.add(worker)

    def _prepared(self, task):
        # 即使协程尚未执行第一行就被取消，也必须归还创建名额。
        self._starting.discard(task)
        self._starting_profiles.pop(task, None)
        self.notify()

    async def _prepare(self, profile=None):
        worker = None
        release = None
        warm_id = 'warm:' + uuid.uuid4().hex
        started=time.perf_counter()
        wall=time.time_ns()/1000000
        outcome='failed'
        try:
            release = self.try_start(background=True)
            if release is None:
                return
            worker = self._factory()
            worker.observation_warm_id = warm_id
            if self._observer and hasattr(worker, 'set_observation_callback'):
                try:
                    worker.set_observation_callback(self._observe_startup, run_id=warm_id)
                except Exception:
                    pass
            self._observe(worker,'prewarm_started')
            fingerprint = None
            if self._payload_factory is None:
                await worker.prewarm()
            else:
                payload = self._payload_factory(profile) if profile is not None else self._payload_factory()
                fingerprint = payload.get('_client_connection_fingerprint')
                await worker.preconnect(payload)
            if self._closed:
                await self._terminate(worker)
            else:
                self._ready.append(worker)
                self._ready_profiles[worker] = fingerprint
                self._idle_at[worker] = time.monotonic()
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
            if release is not None:
                release()
            if worker is not None and self._observer:
                try:
                    self._observer.span(worker.observation_warm_id,'prewarm',wall,(time.perf_counter()-started)*1000,
                        attributes={'pool.outcome':outcome},identity='prewarm')
                    for event in getattr(worker, 'startup_traces', ()):
                        self._observer.performance(worker.observation_warm_id,event,parent=self._observer.span_id(worker.observation_warm_id,'prewarm'))
                except Exception:
                    pass
            self._starting.discard(asyncio.current_task())
            self._starting_profiles.pop(asyncio.current_task(), None)
            self.notify()

    async def _maintain(self):
        next_sample = time.monotonic() + 15
        while not self._closed:
            self._wake.clear()
            if self._retiring_workers and not self._retiring and time.monotonic() >= self._retry_at:
                for worker in tuple(self._retiring_workers):
                    self._retire(worker)
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
            targets = self._profile_targets()
            counts = {key: sum(value == key for value in self._starting_profiles.values()) for key in targets}
            while self._ready:
                worker = self._ready.popleft()
                profile = self._ready_profiles[worker]
                if (not worker.alive
                        or (self._profiles and counts.get(profile, 0) >= targets.get(profile, 0))):
                    self._retire(worker)
                else:
                    kept.append(worker)
                    counts[profile] = counts.get(profile, 0) + 1
            self._ready = kept
            if self._memory_paused:
                if not self._memory_allows_start():
                    for task in tuple(self._starting):
                        if not task.cancelling():
                            task.cancel()
                    if not self._retiring and not self._retiring_workers:
                        self._retire_oldest_ready()
            elif (time.monotonic() >= self._retry_at and not self._retiring
                  and not self._business_waiting() and not self._business_starting
                  and not any(w.awaiting_connection for w in self._leased)):
                count = min(self.max_idle - len(self._ready) - len(self._starting),
                            self.max_starting - len(self._starting))
                for _ in range(max(0, count)):
                    key = max(targets, key=lambda key: targets[key] - counts[key])
                    task = asyncio.create_task(self._prepare(self._profiles.get(key)), name='ccsdk-worker-prewarm')
                    self._starting.add(task)
                    self._starting_profiles[task] = key
                    counts[key] += 1
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
                if self._business_waiting() and self._on_change is not None:
                    self._on_change()

    async def close(self):
        """停止补充并回收池内进程；已领取进程仍由 Actor 关闭。"""
        self._closed = True
        self.notify()
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
        await asyncio.gather(*tuple(self._retiring), return_exceptions=True)
        workers = set(self._ready) | self._retiring_workers
        self._ready.clear()
        self._ready_profiles.clear()
        await asyncio.gather(*(self._terminate(w) for w in workers), return_exceptions=True)

    def _retire_oldest_ready(self):
        """仅认领空白 Client；关闭由池负责，退出后通知等待者。"""
        candidates = [worker for worker in self._ready if worker.alive]
        if not candidates:
            return None
        worker = min(candidates, key=lambda item: self._idle_at.get(item, 0))
        self._ready.remove(worker)
        return self._retire(worker)
