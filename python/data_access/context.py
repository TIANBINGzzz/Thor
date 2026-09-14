"""Trusted identities never come from model tool arguments."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json


class DataError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def fingerprint(value) -> str:
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
        return fingerprint([self.run_id, self.tenant_id, self.user_id, self.capability_ref])
