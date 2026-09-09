"""Strict business request models for the internal Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


PROTOCOL = "agent-run/v1"
MAX_TEXT_LENGTH = 1_000_000
MAX_TOKEN_LENGTH = 16_384
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")


class ProtocolError(ValueError):
    """Raised when an internal request has an invalid business shape."""


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
        data = _object(value, "input.attachmentRefs[]")
        _keys(data, {"fileId", "purpose"}, "input.attachmentRefs[]")
        purpose = data.get("purpose", "input")
        if purpose not in {"input", "reference"}:
            raise ProtocolError("input.attachmentRefs[].purpose must be input or reference")
        return cls(_id(data.get("fileId"), "input.attachmentRefs[].fileId") or "", purpose)

    def to_dict(self) -> dict[str, str]:
        return {"fileId": self.file_id, "purpose": self.purpose}


@dataclass(frozen=True)
class Input:
    text: str = ""
    attachment_refs: tuple[AttachmentRef, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "Input":
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
        return {"text": self.text, "attachmentRefs": [item.to_dict() for item in self.attachment_refs]}


@dataclass(frozen=True)
class Credentials:
    platform_bearer: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, value: Any = None) -> "Credentials":
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
        return {"platformBearer": self.platform_bearer} if include_secret and self.platform_bearer else {}


@dataclass(frozen=True)
class AgentRunRequest:
    protocol: str
    run_id: str
    message_id: str
    capability_ref: str
    input: Input
    business_session_id: str | None = None
    credentials: Credentials = field(default_factory=Credentials)

    @classmethod
    def from_dict(cls, value: Any) -> "AgentRunRequest":
        data = _object(value, "request")
        _keys(
            data,
            {"protocol", "runId", "messageId", "businessSessionId", "capabilityRef", "input", "credentials"},
            "request",
        )
        if data.get("protocol") != PROTOCOL:
            raise ProtocolError(f"protocol must be {PROTOCOL}")
        request = cls(
            protocol=PROTOCOL,
            run_id=_id(data.get("runId"), "runId") or "",
            message_id=_id(data.get("messageId"), "messageId") or "",
            business_session_id=_id(data.get("businessSessionId"), "businessSessionId", required=False),
            capability_ref=_id(data.get("capabilityRef"), "capabilityRef") or "",
            input=Input.from_dict(data.get("input")),
            credentials=Credentials.from_dict(data.get("credentials")),
        )
        if not request.input.text.strip() and not request.input.attachment_refs:
            raise ProtocolError("input must include text or attachmentRefs")
        return request

    def to_dict(self, *, include_credentials: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol": self.protocol,
            "runId": self.run_id,
            "messageId": self.message_id,
            "businessSessionId": self.business_session_id,
            "capabilityRef": self.capability_ref,
            "input": self.input.to_dict(),
        }
        if include_credentials:
            result["credentials"] = self.credentials.to_dict(include_secret=True)
        return {key: value for key, value in result.items() if value not in (None, {})}

    def to_internal_dict(self) -> dict[str, Any]:
        return self.to_dict(include_credentials=True)


__all__ = ["AgentRunRequest", "AttachmentRef", "Credentials", "Input", "PROTOCOL", "ProtocolError"]
