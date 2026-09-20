"""Minimal single-process SQLite Run and event store.

The store is intentionally thin: Java remains the production system of record
for business conversations, while this component provides enough local state
for a Runtime process to keep Run status and replayable events.  Credentials
are stripped from metadata and events before persistence.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")
STATUSES = {"queued", "running", "waiting", "succeeded", "failed", "cancelled"}
SECRET_KEYS = {
    "authorization",
    "apikey",
    "api_key",
    "password",
    "platformbearer",
    "platform_bearer",
    "secret",
    "token",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or not RUN_ID.fullmatch(value):
        raise ValueError("run_id must be a non-empty opaque identifier")
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _redact(item)
            for key, item in value.items()
            if str(key).lower().replace("-", "_") not in SECRET_KEYS
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_redact(value), ensure_ascii=False, separators=(",", ":"), default=str)


class RunStore:
    """SQLite-backed Run metadata and ordered event storage."""

    def __init__(self, path: str | Path = ".scribe-runs/runs.sqlite3") -> None:
        self.path = str(path)
        self._memory = self.path == ":memory:"
        if not self._memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    tenant_id TEXT,
                    user_id TEXT,
                    business_session_id TEXT,
                    turn_id TEXT,
                    capability_ref TEXT,
                    runtime_session_ref TEXT,
                    request_hash TEXT,
                    last_sequence INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence),
                    UNIQUE (run_id, event_id),
                    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_run_events_after
                    ON run_events(run_id, sequence);
                CREATE TABLE IF NOT EXISTS run_traces (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    event_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, sequence)
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    record_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
                CREATE INDEX IF NOT EXISTS idx_runs_session_created
                    ON runs(tenant_id, user_id, business_session_id, created_at DESC, run_id DESC);
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "runtime_session_ref" not in columns:
                self._connection.execute("ALTER TABLE runs ADD COLUMN runtime_session_ref TEXT")
            if "request_hash" not in columns:
                self._connection.execute("ALTER TABLE runs ADD COLUMN request_hash TEXT")
            if "last_sequence" not in columns:
                self._connection.execute("ALTER TABLE runs ADD COLUMN last_sequence INTEGER NOT NULL DEFAULT 0")
            self._connection.commit()
            self._connection.commit()

    def artifact(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute('SELECT record_json FROM artifacts WHERE artifact_id = ?',
                                           (artifact_id,)).fetchone()
            return json.loads(row['record_json']) if row else None

    def artifacts(self, run_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                'SELECT record_json FROM artifacts' + (' WHERE run_id = ?' if run_id is not None else '') + ' ORDER BY rowid',
                (run_id,) if run_id is not None else (),
            ).fetchall()
            return [json.loads(row['record_json']) for row in rows]

    def save_artifact(self, record: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
        """同一事务保存产物状态和对应事件；外部通知失败后仍可查询和回放。"""
        run_id = _validate_run_id(record['runId'])
        artifact_id = _validate_run_id(record['artifactId'])
        with self._lock:
            existing = self.artifact(artifact_id)
            if existing and existing['runId'] != run_id:
                raise ValueError('artifact owner mismatch')
            try:
                self._connection.execute(
                    'INSERT INTO artifacts VALUES (?,?,?,?) ON CONFLICT(artifact_id) DO UPDATE SET status=excluded.status, record_json=excluded.record_json',
                    (artifact_id, run_id, record['status'], _json(record)),
                )
                return self.append_event(run_id, event)
            except BaseException:
                self._connection.rollback()
                raise

    def list_runs_by_session(
        self, tenant_id: str, user_id: str, business_session_id: str, *,
        limit: int = 50, cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """按身份和业务会话倒序分页；游标只定位记录，不携带访问权限。"""
        if any(not isinstance(v, str) or not v.strip() for v in (tenant_id, user_id, business_session_id)):
            raise ValueError("session identity is required")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        scope = (tenant_id, user_id, business_session_id)
        condition = "tenant_id = ? AND user_id = ? AND business_session_id = ?"
        with self._lock:
            values: tuple = scope
            if cursor is not None:
                try:
                    if not re.fullmatch(r"v1\.[A-Za-z0-9_-]{1,342}", cursor):
                        raise ValueError()
                    encoded = cursor[3:]
                    run_id = _validate_run_id(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('ascii'))
                    if cursor != self._session_cursor(run_id):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise ValueError("invalid cursor") from None
                anchor = self._connection.execute(
                    f"SELECT created_at, run_id FROM runs WHERE {condition} AND run_id = ?",
                    (*scope, run_id),
                ).fetchone()
                if anchor is None:
                    raise ValueError("invalid cursor")
                condition += " AND (created_at, run_id) < (?, ?)"
                values += (anchor['created_at'], anchor['run_id'])
            rows = self._connection.execute(
                f"SELECT * FROM runs WHERE {condition} ORDER BY created_at DESC, run_id DESC LIMIT ?",
                (*values, limit + 1),
            ).fetchall()
        page = rows[:limit]
        next_cursor = self._session_cursor(page[-1]['run_id']) if len(rows) > limit else None
        return [self._run_row(row) for row in page], next_cursor

    @staticmethod
    def _session_cursor(run_id: str) -> str:
        return 'v1.' + base64.urlsafe_b64encode(run_id.encode('ascii')).rstrip(b'=').decode('ascii')

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None  # type: ignore[assignment]

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def create_run(
        self,
        run_id: str,
        metadata: Mapping[str, Any] | None = None,
        *,
        status: str = "queued",
        tenant_id: str | None = None,
        user_id: str | None = None,
        business_session_id: str | None = None,
        turn_id: str | None = None,
        capability_ref: str | None = None,
        runtime_session_ref: str | None = None,
        request: Any | None = None,
    ) -> dict[str, Any]:
        """接收 Run 标识、已验证身份及请求信息，返回新建或幂等复用的内部记录。

        重试的归属或非密钥请求内容不匹配时抛出异常。
        """
        run_id = _validate_run_id(run_id)
        if status not in STATUSES:
            raise ValueError(f"unsupported run status: {status}")
        if request is not None:
            metadata = metadata or {}
            business_session_id = business_session_id or getattr(request, "business_session_id", None)
            turn_id = turn_id or getattr(request, "turn_id", None)
            capability_ref = capability_ref or getattr(request, "capability_ref", None)
        request_hash = None
        if request is not None:
            try:
                # Credentials are transport-only.  Excluding them keeps an
                # idempotent retry valid when a short-lived bearer is
                # refreshed, while the request's non-secret shape still has
                # to match the original Run.
                wire = request.to_dict()
            except AttributeError:
                wire = request
            request_hash = hashlib.sha256(
                json.dumps(
                    _redact(wire),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        created = _now_ms()
        with self._lock:
            row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                self._connection.execute(
                    """INSERT INTO runs
                    (run_id,status,tenant_id,user_id,business_session_id,turn_id,capability_ref,runtime_session_ref,request_hash,last_sequence,error,metadata_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run_id,
                        status,
                        tenant_id,
                        user_id,
                        business_session_id,
                        turn_id,
                        capability_ref,
                        runtime_session_ref,
                        request_hash,
                        0,
                        None,
                        _json(metadata or {}),
                        created,
                        created,
                    ),
                )
                self._connection.commit()
                row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            else:
                # A retry is idempotent only for the same ownership context.
                # Do not return an existing Run to a different tenant/user.
                for field, supplied in (
                    ("tenant_id", tenant_id),
                    ("user_id", user_id),
                    ("business_session_id", business_session_id),
                    ("turn_id", turn_id),
                    ("capability_ref", capability_ref),
                ):
                    stored = row[field]
                    if (supplied is not None or stored is not None) and supplied != stored:
                        raise PermissionError(f"Run ownership mismatch: {run_id}")
                stored_hash = row["request_hash"]
                if request_hash is not None and stored_hash is not None and request_hash != stored_hash:
                    raise PermissionError(f"Run request mismatch: {run_id}")
            return self._run_row(row)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """按 Run 标识查询并返回内部记录字典，不存在时返回 None。"""
        run_id = _validate_run_id(run_id)
        with self._lock:
            row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._run_row(row) if row else None

    def update_status(self, run_id: str, status: str, *, error: str | None = None) -> dict[str, Any]:
        """按 Run 标识保存状态及可选错误信息，返回更新后的内部记录，不存在时抛出 KeyError。"""
        run_id = _validate_run_id(run_id)
        if status not in STATUSES:
            raise ValueError(f"unsupported run status: {status}")
        updated = _now_ms()
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE runs SET status = ?, error = ?, updated_at = ? WHERE run_id = ?",
                (status, str(error)[:2000] if error else None, updated, run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found: {run_id}")
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._run_row(row)

    set_status = update_status

    def update_runtime_session_ref(self, run_id: str, value: str | None) -> dict[str, Any]:
        """为指定 Run 保存或清空 SDK 会话引用，返回更新后的内部记录。"""
        run_id = _validate_run_id(run_id)
        if value is not None:
            value = str(value).strip()
            if not RUN_ID.fullmatch(value):
                raise ValueError("runtime_session_ref must be an opaque identifier")
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE runs SET runtime_session_ref = ?, updated_at = ? WHERE run_id = ?",
                (value, _now_ms(), run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found: {run_id}")
            self._connection.commit()
            row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return self._run_row(row)

    def append_event(self, run_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        """将输入事件按敏感字段规则过滤后追加到 Run，返回带序号的事件；相同 eventId 返回已有记录。"""
        run_id = _validate_run_id(run_id)
        if not isinstance(event, Mapping):
            raise ValueError("event must be an object")
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event.type is required")
        event_id = event.get("eventId", event.get("event_id"))
        if event_id is None:
            event_id = f"evt_{uuid.uuid4().hex}"
        event_id = _validate_run_id(str(event_id))
        occurred = event.get("occurredAt", event.get("occurred_at", _now_ms()))
        if isinstance(occurred, bool) or not isinstance(occurred, (int, float)):
            raise ValueError("event.occurredAt must be numeric")
        clean_event = _redact(dict(event))
        clean_event.pop("sequence", None)
        clean_event.pop("event_id", None)
        clean_event["eventId"] = event_id
        clean_event["occurredAt"] = int(occurred)
        with self._lock:
            run = self._connection.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            existing = self._connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND event_id = ?",
                (run_id, event_id),
            ).fetchone()
            if existing:
                return self._event_row(existing)
            sequence = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM run_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()["next_sequence"]
            self._connection.execute(
                "INSERT INTO run_events(run_id,sequence,event_id,occurred_at,event_json) VALUES (?,?,?,?,?)",
                (run_id, sequence, event_id, int(occurred), _json(clean_event)),
            )
            self._connection.execute(
                "UPDATE runs SET last_sequence = ?, updated_at = ? WHERE run_id = ?",
                (sequence, _now_ms(), run_id),
            )
            self._connection.commit()
            row = self._connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND sequence = ?", (run_id, sequence)
            ).fetchone()
            return self._event_row(row)

    def events_after(self, run_id: str, after_sequence: int = 0, *, limit: int = 500) -> list[dict[str, Any]]:
        """按 Run 标识、起始游标和条数上限查询，返回游标之后按序排列的事件列表。"""
        run_id = _validate_run_id(run_id)
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM run_events WHERE run_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
                (run_id, after_sequence, limit),
            ).fetchall()
            return [self._event_row(row) for row in rows]

    replay = events_after
    get_events = events_after

    def append_trace(self, run_id, raw):
        """私有调试事件独立编号，不进入公共事件回放或lastSequence。"""
        with self._lock:
            sequence = self._connection.execute(
                'SELECT COALESCE(MAX(sequence),0)+1 FROM run_traces WHERE run_id=?', (run_id,)).fetchone()[0]
            event = {'runId': run_id, 'sequence': sequence, 'occurredAt': _now_ms(), 'event': raw}
            self._connection.execute('INSERT INTO run_traces VALUES (?,?,?)', (run_id, sequence, _json(event)))
            self._connection.commit()
            return event

    def traces_after(self, run_id, after_sequence=0, limit=100):
        with self._lock:
            rows = self._connection.execute(
                'SELECT event_json FROM run_traces WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?',
                (run_id, after_sequence, limit)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def last_sequence(self, run_id: str) -> int:
        """接收 Run 标识，返回已存事件的最大序号，无事件时返回 0。"""
        run_id = _validate_run_id(run_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM run_events WHERE run_id = ?", (run_id,)
            ).fetchone()
            return int(row["sequence"])

    def delete_run(self, run_id: str) -> bool:
        """删除指定 Run 及关联事件，返回是否实际删除了 Run 记录。"""
        run_id = _validate_run_id(run_id)
        with self._lock:
            cursor = self._connection.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
            self._connection.commit()
            return cursor.rowcount == 1

    @staticmethod
    def _run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        try:
            metadata = json.loads(row["metadata_json"])
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        result = {
            "runId": row["run_id"],
            "status": row["status"],
            "tenantId": row["tenant_id"],
            "userId": row["user_id"],
            "businessSessionId": row["business_session_id"],
            "turnId": row["turn_id"],
            "capabilityRef": row["capability_ref"],
            "runtimeSessionRef": row["runtime_session_ref"],
            "lastSequence": int(row["last_sequence"] or 0),
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "metadata": metadata,
        }
        if row["error"]:
            result["error"] = row["error"]
        return result

    @staticmethod
    def _event_row(row: sqlite3.Row) -> dict[str, Any]:
        try:
            event = json.loads(row["event_json"])
        except (TypeError, json.JSONDecodeError):
            event = {"type": "unknown"}
        if not isinstance(event, dict):
            event = {"type": "unknown", "payload": event}
        event["eventId"] = row["event_id"]
        event["sequence"] = row["sequence"]
        event["occurredAt"] = row["occurred_at"]
        return event


__all__ = ["RunStore", "STATUSES"]
