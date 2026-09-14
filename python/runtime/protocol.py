"""Strict business request models for the internal Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
from typing import Any, Mapping


PROTOCOL = "agent-run/v1"
MAX_TEXT_LENGTH = 1_000_000
MAX_TOKEN_LENGTH = 16_384
MAX_PAYLOAD_BYTES = 65_536
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")


class ProtocolError(ValueError):
    """Raised when an internal request has an invalid business shape."""


def _payload(value: Any) -> dict[str, Any]:
    """校验业务 payload 的保留字段、层级、类型和大小，返回 JSON 深拷贝，非法输入抛出 ProtocolError。"""
    data = _object(value, "payload")
    reserved = {"credentials", "platformbearer", "authorization", "token", "apikey", "secret",
                "tenantid", "userid", "workflowref", "skill", "skills", "agent", "agents",
                "model", "tools", "mcp", "mcpservers", "mcps", "cwd", "workspace", "permissions"}

    def check(item: Any, depth: int) -> None:
        if depth > 16:
            raise ProtocolError("payload nesting exceeds 16 levels")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or key.lower().replace("_", "").replace("-", "") in reserved:
                    raise ProtocolError("payload contains a reserved or invalid key")
                check(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                check(child, depth + 1)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ProtocolError("payload must contain JSON values")
        elif isinstance(item, float) and not math.isfinite(item):
            raise ProtocolError("payload numbers must be finite")

    check(dict(data), 0)
    encoded = json.dumps(dict(data), ensure_ascii=False, allow_nan=False)
    try:
        size = len(encoded.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProtocolError("payload must contain valid UTF-8 text") from error
    if size > MAX_PAYLOAD_BYTES:
        raise ProtocolError("payload exceeds 65536 bytes")
    return json.loads(encoded)


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{name} must be an object")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProtocolError(f"{name} contains unsupported field(s): {', '.join(unknown)}")


def _id(value: Any, name: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ProtocolError(f"{name} is required")
        return None
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ProtocolError(f"{name} must contain only letters, digits, '_' or '-'")
    return value


@dataclass(frozen=True)
class AttachmentRef:
    file_id: str
    purpose: str = "input"

    @classmethod
    def from_dict(cls, value: Any) -> "AttachmentRef":
        """校验输入的文件标识和用途，返回附件引用对象，不执行文件获取或授权。"""
        data = _object(value, "input.attachmentRefs[]")
        _keys(data, {"fileId", "purpose"}, "input.attachmentRefs[]")
        purpose = data.get("purpose", "input")
        if purpose not in {"input", "reference"}:
            raise ProtocolError("input.attachmentRefs[].purpose must be input or reference")
        return cls(_id(data.get("fileId"), "input.attachmentRefs[].fileId") or "", purpose)

    def to_dict(self) -> dict[str, str]:
        """将当前附件引用转换为包含 fileId 和 purpose 的协议字典。"""
        return {"fileId": self.file_id, "purpose": self.purpose}


@dataclass(frozen=True)
class Input:
    text: str = ""
    attachment_refs: tuple[AttachmentRef, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "Input":
        """校验输入文本和附件引用列表，返回 Input 对象。"""
        data = _object(value, "input")
        _keys(data, {"text", "attachmentRefs"}, "input")
        text = data.get("text", "")
        if not isinstance(text, str) or "\x00" in text or len(text) > MAX_TEXT_LENGTH:
            raise ProtocolError("input.text is invalid or too long")
        refs = data.get("attachmentRefs", [])
        if not isinstance(refs, list) or len(refs) > 64:
            raise ProtocolError("input.attachmentRefs must be an array with at most 64 entries")
        return cls(text=text, attachment_refs=tuple(AttachmentRef.from_dict(item) for item in refs))

    def to_dict(self) -> dict[str, Any]:
        """将当前输入转换为含 text 和 attachmentRefs 的协议字典。"""
        return {"text": self.text, "attachmentRefs": [item.to_dict() for item in self.attachment_refs]}


@dataclass(frozen=True)
class Credentials:
    platform_bearer: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, value: Any = None) -> "Credentials":
        """校验凭据字典的结构并返回 Credentials，未提供输入时返回空凭据；不验证 Token 的业务有效性。"""
        if value is None:
            return cls()
        data = _object(value, "credentials")
        _keys(data, {"platformBearer"}, "credentials")
        token = data.get("platformBearer")
        if token is not None and (
            not isinstance(token, str) or not token.strip() or len(token) > MAX_TOKEN_LENGTH or "\x00" in token
        ):
            raise ProtocolError("credentials.platformBearer is invalid")
        return cls(token)

    def to_dict(self, *, include_secret: bool = False) -> dict[str, str]:
        """将当前凭据转为字典，默认返回空字典，仅显式启用 include_secret 时包含业务 Token。"""
        return {"platformBearer": self.platform_bearer} if include_secret and self.platform_bearer else {}


@dataclass(frozen=True)
class AgentRunRequest:
    protocol: str
    run_id: str
    message_id: str
    capability_ref: str | None
    input: Input
    business_session_id: str | None = None
    credentials: Credentials = field(default_factory=Credentials)
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> "AgentRunRequest":
        """校验请求字典的协议版本、标识和业务输入，返回 AgentRunRequest，非法字段抛出 ProtocolError。"""
        data = _object(value, "request")
        _keys(
            data,
            {"protocol", "runId", "messageId", "businessSessionId", "capabilityRef", "input", "credentials", "payload"},
            "request",
        )
        if data.get("protocol") != PROTOCOL:
            raise ProtocolError(f"protocol must be {PROTOCOL}")
        request = cls(
            protocol=PROTOCOL,
            run_id=_id(data.get("runId"), "runId") or "",
            message_id=_id(data.get("messageId"), "messageId") or "",
            business_session_id=_id(data.get("businessSessionId"), "businessSessionId", required=False),
            capability_ref=_id(data.get("capabilityRef"), "capabilityRef", required=False),
            input=Input.from_dict(data.get("input")),
            credentials=Credentials.from_dict(data.get("credentials")),
            payload=_payload(data.get("payload", {})),
        )
        if not request.input.text.strip() and not request.input.attachment_refs and not request.payload:
            raise ProtocolError("request must include text, attachmentRefs or payload")
        return request

    def to_dict(self, *, include_credentials: bool = False) -> dict[str, Any]:
        """将当前 Run 请求序列化为协议字典，默认省略凭据，并移除值为 None 或空字典的字段。"""
        result: dict[str, Any] = {
            "protocol": self.protocol,
            "runId": self.run_id,
            "messageId": self.message_id,
            "businessSessionId": self.business_session_id,
            "capabilityRef": self.capability_ref,
            "input": self.input.to_dict(),
            "payload": self.payload,
        }
        if include_credentials:
            result["credentials"] = self.credentials.to_dict(include_secret=True)
        return {key: value for key, value in result.items() if value not in (None, {})}

    def to_internal_dict(self) -> dict[str, Any]:
        """返回包含凭据的内部请求字典，仅供需要传递本次请求 Token 的内部调用使用。"""
        return self.to_dict(include_credentials=True)


__all__ = ["AgentRunRequest", "AttachmentRef", "Credentials", "Input", "PROTOCOL", "ProtocolError"]
