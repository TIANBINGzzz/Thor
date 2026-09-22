"""Private materialized results and opaque, owner-bound paging handles."""

from datetime import date, datetime
from decimal import Decimal
import json
from secrets import token_urlsafe

from .context import DataError


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        raise DataError("BINARY_RESULT_UNSUPPORTED")
    raise TypeError(type(value).__name__)


class Results:
    def __init__(self, context, *, max_bytes=20_000_000):
        self.context = context
        self.directory = context.run_directory / "data"
        self.records = {}
        self.cursors = {}
        self.max_bytes = max_bytes
        self.bytes = 0

    def save(self, rows, metadata, output):
        reference = "result_" + token_urlsafe(18)
        record = {"result_ref": reference, "owner": self.context.owner,
                  "rows": rows, "metadata": metadata, "output": output}
        content = json.dumps(record, ensure_ascii=False, default=json_value, allow_nan=False)
        size = len(content.encode())
        if self.bytes + size > self.max_bytes:
            raise DataError("RESULT_LIMIT")
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{reference}.json").write_text(content, encoding="utf-8")
        self.bytes += size
        self.records[reference] = record
        return reference

    def get(self, reference):
        record = self.records.get(reference)
        if record is None or record["owner"] != self.context.owner:
            raise DataError("RESULT_FORBIDDEN")
        return record

    def page(self, reference, cursor=None):
        record = self.get(reference)
        offset = 0
        if cursor is not None:
            if cursor not in self.cursors or self.cursors[cursor][0] != reference:
                raise DataError("CURSOR_INVALID")
            offset = self.cursors[cursor][1]
        hidden = {f["name"] for f in record["output"] if f.get("visibility") == "internal_only"}
        rows = [{k: v for k, v in row.items() if k not in hidden} for row in record["rows"][offset:offset+100]]
        next_cursor = None
        if offset + 100 < len(record["rows"]):
            next_cursor = "cursor_" + token_urlsafe(18)
            self.cursors[next_cursor] = (reference, offset + 100)
        return {"result_ref": reference, "rows": rows, "row_count": len(record["rows"]),
                "complete": record["metadata"]["complete"], "cursor": next_cursor,
                "status": "no_data" if not record["rows"] else "available",
                # 从本轮冻结的指标定义继承口径；分页也携带，避免数值脱离适用范围。
                "semantics": list(record["metadata"].get("semantics", [])),
                "provenance": {k: v for k, v in record["metadata"].items() if k in {
                    "source_key", "domain", "query_id", "query_version", "asset_revision",
                    "source_version", "scope_ref", "parameters", "collected_at", "dynamic",
                    "sql_fingerprint"}},
                "columns": [f for f in record["output"] if f["name"] not in hidden]}
