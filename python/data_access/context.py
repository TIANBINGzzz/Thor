"""Trusted identities never come from model tool arguments."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json


class DataError(ValueError):
    def __init__(self, code: str):
        """保存可公开的数据错误码，避免携带底层敏感信息。"""
        self.code = code
        super().__init__(code)


def fingerprint(value) -> str:
    """对规范化 JSON 计算指纹，用于身份、策略和资产比对。"""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    default=str).encode()).hexdigest()


@dataclass(frozen=True)
class DataContext:
    run_id: str
    tenant_id: str
    user_id: str
    capability_ref: str
    run_directory: Path
    template_key: str | None = None

    @classmethod
    def from_payload(cls, payload):
        """从可信内部载荷构造本轮数据上下文，拒绝缺失身份或目录。"""
        identity = payload.get("_data_identity", {})
        values = [payload.get("run_id"), identity.get("tenant_id"),
                  identity.get("user_id"), payload.get("capability_ref")]
        if any(not isinstance(v, str) or not v.strip() for v in values):
            raise DataError("IDENTITY_REQUIRED")
        directory = payload.get("_data_run_directory")
        if not directory:
            raise DataError("RUN_DIRECTORY_REQUIRED")
        return cls(*values, Path(directory).resolve(), payload.get("_template_key"))

    @property
    def owner(self):
        """生成绑定 Run、租户、用户与能力的结果归属指纹。"""
        return fingerprint([self.run_id, self.tenant_id, self.user_id, self.capability_ref])
