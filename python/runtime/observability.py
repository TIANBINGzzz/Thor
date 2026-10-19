"""通用拉取出口：有界待采日志、持久游标和自动实例标识，不依赖观测平台。"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
import uuid
import yaml
from runtime.telemetry import sanitize


def trace_id(instance, run):
    return hashlib.sha256((instance + ":" + run).encode()).hexdigest()[:32]


class ObservationStore:
    def __init__(self, path, *, max_records=20000, retention_seconds=86400):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db=sqlite3.connect(str(path), check_same_thread=False, timeout=1)
        self.lock=threading.RLock()
        self.max_records, self.retention_seconds=max_records, retention_seconds
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("CREATE TABLE IF NOT EXISTS records(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, body TEXT)")
            self.db.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('epoch',?)",(uuid.uuid4().hex,))
        self.epoch=self.db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0]

    def append(self, record):
        with self.lock, self.db:
            self.db.execute("INSERT INTO records(at,body) VALUES(?,?)",(time.time(),json.dumps(record,ensure_ascii=False)))
            high=self.db.execute("SELECT MAX(seq) FROM records").fetchone()[0]
            self.db.execute("DELETE FROM records WHERE seq<=? OR at<?",(high-self.max_records,time.time()-self.retention_seconds))

    def read(self, cursor, limit):
        with self.lock, self.db:
            # 空闲期读取也执行保留策略；全部过期后仍保留单调水位，明确报告缺口。
            self.db.execute("DELETE FROM records WHERE at<?", (time.time()-self.retention_seconds,))
            row=self.db.execute("SELECT seq FROM sqlite_sequence WHERE name='records'").fetchone()
            high=row[0] if row else 0
            low=self.db.execute("SELECT MIN(seq) FROM records").fetchone()[0]
            rows=self.db.execute("SELECT seq,body FROM records WHERE seq>? ORDER BY seq LIMIT ?",(cursor,limit)).fetchall()
        return {"epoch":self.epoch,"records":[{**json.loads(b),"sequence":s} for s,b in rows],
                "nextCursor":rows[-1][0] if rows else max(cursor,high),"oldestCursor":low,"latestCursor":high,
                "gap":cursor < (low-1 if low is not None else high),"hasMore":bool(rows and rows[-1][0] < high)}

    def close(self):
        self.db.close()


class Observer:
    def __init__(self, path, *, enabled=False, max_records=20000,
                 retention_seconds=86400, queue_size=2048):
        self.enabled=enabled
        self.store=ObservationStore(path,max_records=max_records,retention_seconds=retention_seconds) if enabled else None
        # 标识随观测库持久化；新库使用新标识，避免地址复用或游标重置时混入旧实例。
        self.instance_id=self.store.epoch if self.store else ""
        self.queue=queue.Queue(maxsize=queue_size)
        self.dropped=0
        self.counters={(name,''):0 for name in ('ccsdk_runs_created_total','ccsdk_artifact_ready_total','ccsdk_artifact_failed_total')}
        self.counters[('ccsdk_runs_completed_total','{status="failed"}')]=0
        self.histograms={}
        self.tool_starts={}
        self.thread=None
        if enabled:
            self.thread=threading.Thread(target=self._write,daemon=True,name="observation-spool")
            self.thread.start()

    def emit(self, kind, run_id, data, *, secrets=()):
        if not self.enabled:
            return
        try:
            value=sanitize(data, secrets)
            record={"kind":kind,"runId":run_id,"traceId":trace_id(self.instance_id,run_id),
                    "timestamp":time.time_ns()//1000000,"data":value}
            # 限制单条记录；丢弃只影响观测完整度。
            if len(json.dumps(record))>131072:
                self.dropped+=1
                return
            self.queue.put_nowait(record)
        except Exception:
            self.dropped+=1

    def _write(self):
        while True:
            record=self.queue.get()
            try:
                if record is None: return
                self.store.append(record)
            except Exception:
                self.dropped+=1
            finally:
                self.queue.task_done()

    def span_id(self, run_id, identity):
        # 阶段名带实例与 Run 命名空间，保证跨 Trace 导出时也不碰撞。
        return hashlib.sha256((self.instance_id+':'+run_id+':'+identity).encode()).hexdigest()[:16]

    def span(self, run_id, name, start_ms, duration_ms, *, parent=None, attributes=None, links=(), identity=None):
        if not self.enabled: return
        try:
            self.emit("span",run_id,{"traceId":trace_id(self.instance_id,run_id),
                "spanId":self.span_id(run_id,identity or name),
                "parentSpanId":parent,"name":name,"startTimeUnixNano":str(int(start_ms*1000000)),
                "endTimeUnixNano":str(int((start_ms+max(0,duration_ms))*1000000)),
                "attributes":attributes or {},"links":list(links)})
        except Exception:
            self.dropped+=1

    def timing_mark(self, run_id, timing, stage):
        """Timing 只回调首次 mark；运行中只发快照，终态再转换为 Span。"""
        if not self.enabled: return
        self.emit('milestone',run_id,timing.event())
        if timing.scope == 'runtime' and stage == 'first_text':
            self.observe('ccsdk_runtime_first_text_seconds',timing.elapsed[stage]/1000)

    def performance(self, run_id, event, *, parent=None):
        self.emit("milestone",run_id,event)
        elapsed=event.get("elapsedMs",{})
        if not elapsed: return
        # 不跨进程计算差值；无墙钟锚点时只保留原始 Timing，不能伪造 Trace 时间。
        origin=event.get("originUnixMs")
        if origin is None: return
        scope=event["scope"]
        root=parent or self.span_id(run_id,"run")
        previous=0
        for stage, end in sorted(elapsed.items(),key=lambda item:item[1]):
            self.span(run_id,scope+".until_"+stage,origin+previous,end-previous,parent=root,
                      attributes={"timing.scope":scope,"timing.local_duration_ms":end-previous,"timing.clock_id":event.get("clockId",""),"timing.cumulative_ms":end},
                      identity=scope+"."+str(event.get('clockId',''))+"."+str(origin)+"."+stage)
            previous=end

    def count(self, name, labels="", amount=1):
        key=(name,labels)
        self.counters[key]=self.counters.get(key,0)+amount

    def sdk(self, run_id, raw):
        """SDK 外层调用区间，不伪装成 MCP 服务内部或模型 HTTP 耗时。"""
        kind=raw.get('type')
        key=(run_id,str(raw.get('id','')))
        if kind=='tool_use' and key[1]:
            if len(self.tool_starts)>=self.queue.maxsize: self.tool_starts.pop(next(iter(self.tool_starts)))
            if key not in self.tool_starts:
                self.tool_starts[key]=(time.perf_counter(),time.time_ns()/1000000,str(raw.get('name','tool')))
                self.emit('milestone',run_id,{'name':'tool.started','callId':key[1],
                    'toolName':self.tool_starts[key][2], 'originUnixMs':self.tool_starts[key][1],
                    'measurement.boundary':'sdk_outer'})
        elif kind=='tool_result' and key in self.tool_starts:
            started,wall,name=self.tool_starts.pop(key)
            duration=(time.perf_counter()-started)*1000
            self.span(run_id,name,wall,duration,parent=self.span_id(run_id,'run'),
                identity='tool:'+key[1],attributes={'openinference.span.kind':'TOOL','tool.call.id':key[1],
                    'timing.local_duration_ms':duration,
                    'measurement.boundary':'sdk_outer','tool.is_error':bool(raw.get('isError'))})
        elif kind=='result':
            # 数值用量与凭据字段分开命名，继续保持通用脱敏规则严格。
            usage={name:raw[key] for name,key in (('input','inputTokens'),('output','outputTokens'))
                   if type(raw.get(key)) in (int,float) and math.isfinite(raw[key])}
            self.emit('milestone',run_id,{'name':'sdk_result','usage':usage,**{k:v for k,v in raw.items() if k in {'turns','durationMs','costUsd','ok'} and type(v) in (int,float,bool)}})

    def finish_run(self, run_id, status):
        """未收到结果的调用只标记不完整，不能把 Run 终点冒充工具完成时间。"""
        for key in [key for key in self.tool_starts if key[0] == run_id]:
            _, wall, name = self.tool_starts.pop(key)
            self.emit('milestone', run_id, {'name': 'tool.incomplete', 'callId': key[1],
                'toolName': name, 'originUnixMs': wall, 'runStatus': status,
                'measurement.boundary': 'sdk_outer', 'reason': 'run_ended_without_tool_result'})

    def observe(self, name, value):
        count,total,buckets=self.histograms.setdefault(name,[0,0,{}])
        limits=(.05,.1,.25,.5,1,2.5,5,10,30,60,120,300)
        for bound in limits:
            if value<=bound: buckets[bound]=buckets.get(bound,0)+1
        self.histograms[name]=[count+1,total+value,buckets]

    def metrics(self):
        lines=["# TYPE ccsdk_observation_dropped_total counter",f"ccsdk_observation_dropped_total {self.dropped}"]
        for (name,labels),value in self.counters.items(): lines.append(f"{name}{labels} {value}")
        for name,(count,total,buckets) in self.histograms.items():
            lines.append(f"# TYPE {name} histogram")
            for bound in (.05,.1,.25,.5,1,2.5,5,10,30,60,120,300):
                lines.append(f'{name}_bucket{{le="{bound}"}} {buckets.get(bound,0)}')
            lines.extend([f'{name}_bucket{{le="+Inf"}} {count}',f"{name}_sum {total}",f"{name}_count {count}"])
        return "\n".join(lines)+"\n"

    def flush(self):
        self.queue.join()

    def read(self,cursor,limit):
        return self.store.read(cursor,limit) if self.store else {"records":[],"nextCursor":cursor}

    def close(self):
        if self.thread:
            self.queue.put(None)
            self.thread.join(timeout=5)
            if not self.thread.is_alive():
                self.thread=None
                self.store.close()


def create_observer(root):
    """观测总开关与缓冲预算来自主配置，不读取平台地址或独立配置文件。"""
    root=Path(root)
    config={}
    try:
        for path in (root/"config"/"application.yml",root/"config"/"application.local.yml"):
            if path.exists():
                value=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(value,dict): raise ValueError('invalid observation configuration')
                runtime=value.get('runtime',{})
                if not isinstance(runtime,dict): raise ValueError('invalid runtime configuration')
                section=runtime.get('observability',{})
                if not isinstance(section,dict) or set(section)-{'enabled','storage','max-records','retention-seconds','queue-size'}:
                    raise ValueError('invalid observation configuration')
                config.update(section)
        enabled=config.get("enabled",False)
        if type(enabled) is not bool: raise ValueError('invalid enabled')
        if os.environ.get('CCSDK_OBSERVABILITY_ENABLED') in {'0','1'}:
            enabled=os.environ['CCSDK_OBSERVABILITY_ENABLED']=='1'
        for key,default in [('max-records',20000),('retention-seconds',86400),('queue-size',2048)]:
            if type(config.get(key,default)) is not int or config.get(key,default)<=0:
                raise ValueError('invalid observation limit')
        return Observer(root/config.get("storage",".scribe-runs/observation.sqlite"),
            enabled=enabled,
            max_records=config.get("max-records",20000),retention_seconds=config.get("retention-seconds",86400),
            queue_size=config.get("queue-size",2048))
    except (OSError,sqlite3.Error,ValueError,TypeError,yaml.YAMLError):
        # 配置损坏或观测磁盘不可用时停采，业务进程仍能启动。
        return Observer(root/'unused')
