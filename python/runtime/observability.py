"""独立观测出口：有界队列、持久游标和自动实例标识，不参与业务决策。"""
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
from runtime.private_trace import sanitize


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
        with self.lock:
            low,high=self.db.execute("SELECT MIN(seq),MAX(seq) FROM records").fetchone()
            rows=self.db.execute("SELECT seq,body FROM records WHERE seq>? ORDER BY seq LIMIT ?",(cursor,limit)).fetchall()
        return {"epoch":self.epoch,"records":[{**json.loads(b),"sequence":s} for s,b in rows],
                "nextCursor":rows[-1][0] if rows else cursor,"oldestCursor":low,"latestCursor":high,
                "gap":bool(low and cursor<low-1),"hasMore":bool(rows and rows[-1][0] < high)}

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
        self.browser_seen=set()
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
        # Phoenix 对 span_id 建全局唯一约束，阶段名必须带实例与 Run 命名空间。
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
                      identity=scope+"."+stage)
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
            self.tool_starts.setdefault(key,(time.perf_counter(),time.time_ns()/1000000,str(raw.get('name','tool'))))
        elif kind=='tool_result' and key in self.tool_starts:
            started,wall,name=self.tool_starts.pop(key)
            self.span(run_id,name,wall,(time.perf_counter()-started)*1000,parent=self.span_id(run_id,'run'),
                identity='tool:'+key[1],attributes={'openinference.span.kind':'TOOL','tool.call.id':key[1],
                    'measurement.boundary':'sdk_outer','tool.is_error':bool(raw.get('isError'))})
        elif kind=='result':
            # 数值用量与凭据字段分开命名，继续保持通用脱敏规则严格。
            usage={name:raw[key] for name,key in (('input','inputTokens'),('output','outputTokens'))
                   if type(raw.get(key)) in (int,float) and math.isfinite(raw[key])}
            self.emit('milestone',run_id,{'name':'sdk_result','usage':usage,**{k:v for k,v in raw.items() if k in {'turns','durationMs','costUsd','ok'} and type(v) in (int,float,bool)}})
            for k in [k for k in self.tool_starts if k[0]==run_id]: self.tool_starts.pop(k,None)

    def observe(self, name, value):
        count,total,buckets=self.histograms.setdefault(name,[0,0,{}])
        limits=(.05,.1,.25,.5,1,2.5,5,10,30,60,120,300)
        for bound in limits:
            if value<=bound: buckets[bound]=buckets.get(bound,0)+1
        self.histograms[name]=[count+1,total+value,buckets]

    def browser(self, run_id, data):
        if not self.enabled or not isinstance(data,dict): return False
        name=data.get("name")
        duration=data.get("elapsedMs")
        if (name not in {"request_started","response_headers","first_sse","first_body","first_render","artifact_received","artifact_displayed","subscription"}
            or type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=86400000):
            return False
        if name in {"first_body","first_render"}:
            key=(run_id,name)
            if data.get("replay") or not data.get("nonempty") or key in self.browser_seen: return False
            # 去重与数值持久化，重启或回放不会重新计首字。
            if self.store:
                with self.store.lock, self.store.db:
                    self.store.db.execute("CREATE TABLE IF NOT EXISTS browser_first(run TEXT,name TEXT,at REAL,PRIMARY KEY(run,name))")
                    try: self.store.db.execute("INSERT INTO browser_first VALUES(?,?,?)",(run_id,name,time.time()))
                    except sqlite3.IntegrityError: return False
                    self.store.db.execute("DELETE FROM browser_first WHERE at<?",(time.time()-self.store.retention_seconds,))
                    self.store.db.execute("DELETE FROM browser_first WHERE rowid NOT IN (SELECT rowid FROM browser_first ORDER BY at DESC LIMIT ?)",(self.store.max_records,))
            self.browser_seen.add(key)
            if len(self.browser_seen)>self.store.max_records: self.browser_seen.clear()
            if name=="first_body": self.observe("ccsdk_browser_ttft_seconds",duration/1000)
        origin=data.get('originUnixMs')
        anchor={'originUnixMs':origin} if type(origin) in (int,float) and math.isfinite(origin) and 0<origin<1e16 else {}
        self.emit("browser",run_id,{**anchor,"name":name,"elapsedMs":duration,"artifactId":str(data.get("artifactId",""))[:256],
                  "clock":"browser.performance.now","trust":"client_reported"})
        return True

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
    config={}
    try:
        for path in (root/"config"/"observability.yml",root/"config"/"observability.local.yml"):
            if path.exists():
                value=yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                if not isinstance(value,dict): raise ValueError('invalid observation configuration')
                config.update(value)
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
