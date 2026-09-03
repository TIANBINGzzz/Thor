"""Strict, provider-neutral request models for the internal Agent Runtime.

The runtime receives a small, JSON-compatible envelope from the Java control
plane.  These models deliberately reject unknown keys: paths, MCP endpoints,
prompt overrides, API keys and other provider-specific escape hatches must be
compiled by the trusted control plane instead of arriving from a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping


PROTOCOL = "agent-run/v1"
DEFAULT_HARNESS = "claude-agent-sdk"
DEFAULT_PROVIDER = "qwen-compatible"
DEFAULT_TIMEOUT_MS = 120_000
DEFAULT_MAX_TURNS = 30
MAX_ID_LENGTH = 256
MAX_TEXT_LENGTH = 1_000_000
MAX_TOKEN_LENGTH = 16_384
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,255}$")


class ProtocolError(ValueError):
    """Raised when an internal request is malformed or contains unsafe keys."""


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{name} must be an object")
    return value


def _keys(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ProtocolError(f"{name} contains unsupported field(s): {', '.join(unknown)}")


def _string(value: Any, name: str, *, required: bool = True, max_length: int = MAX_ID_LENGTH) -> str | None:
    if value is None:
        if required:
            raise ProtocolError(f"{name} is required")
        return None
    if not isinstance(value, str):
        raise ProtocolError(f"{name} must be a string")
    if not value.strip():
        raise ProtocolError(f"{name} must not be empty")
    if "\x00" in value or ((name != "input.text") and ("\r" in value or "\n" in value)):
        raise ProtocolError(f"{name} contains control characters")
    if len(value) > max_length:
        raise ProtocolError(f"{name} is too long")
    return value.strip() if name != "input.text" else value


def _id(value: Any, name: str, *, required: bool = True) -> str | None:
    result = _string(value, name, required=required)
    if result is None:
        return None
    # IDs are later used as keys and (for Run) directory names. Keep the
    # wire-level contract deliberately narrower than an arbitrary string.
    if not SAFE_ID.fullmatch(result):
        raise ProtocolError(f"{name} must contain only letters, digits, '_' or '-'")
    return result


def _list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ProtocolError(f"{name} must be an array")
    return value


@dataclass(frozen=True)
class AgentRef:
    id: str

    @classmethod
    def from_dict(cls, value: Any, *, name: str = "agentRef") -> "AgentRef":
        data = _object(value, name)
        _keys(data, {"id"}, name)
        return cls(id=_id(data.get("id"), f"{name}.id") or "")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id}


@dataclass(frozen=True)
class WorkflowRef:
    id: str

    @classmethod
    def from_value(cls, value: Any, *, name: str = "workflowRef") -> "WorkflowRef | None":
        if value is None:
            return None
        if isinstance(value, str):
            return cls(id=_id(value, f"{name}.id") or "")
        data = _object(value, name)
        _keys(data, {"id"}, name)
        return cls(id=_id(data.get("id"), f"{name}.id") or "")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id}


@dataclass(frozen=True)
class SkillRef:
    id: str

    @classmethod
    def from_value(cls, value: Any, *, name: str = "skillRefs[]") -> "SkillRef":
        if isinstance(value, str):
            return cls(id=_id(value, f"{name}.id") or "")
        data = _object(value, name)
        _keys(data, {"id"}, name)
        return cls(id=_id(data.get("id"), f"{name}.id") or "")

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id}


@dataclass(frozen=True)
class Execution:
    kind: str = "conversation"
    workflow_ref: WorkflowRef | None = None
    skill_refs: tuple[SkillRef, ...] = ()

    @classmethod
    def from_dict(cls, value: Any = None) -> "Execution":
        if value is None:
            return cls()
        data = _object(value, "execution")
        _keys(data, {"kind", "workflowRef", "skillRefs"}, "execution")
        kind = _string(data.get("kind", "conversation"), "execution.kind")
        if kind not in {"conversation", "workflow"}:
            raise ProtocolError("execution.kind must be conversation or workflow")
        workflow_ref = WorkflowRef.from_value(data.get("workflowRef"))
        if kind == "workflow" and workflow_ref is None:
            raise ProtocolError("execution.workflowRef is required for workflow runs")
        if kind == "conversation" and workflow_ref is not None:
            raise ProtocolError("conversation runs cannot include execution.workflowRef")
        raw_skills = _list(data.get("skillRefs"), "execution.skillRefs")
        if len(raw_skills) > 32:
            raise ProtocolError("execution.skillRefs contains too many entries")
        return cls(
            kind=kind,
            workflow_ref=workflow_ref,
            skill_refs=tuple(SkillRef.from_value(item) for item in raw_skills),
        )

    @property
    def capability_ref(self) -> str | None:
        return self.workflow_ref.id if self.workflow_ref else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "workflowRef": self.workflow_ref.to_dict() if self.workflow_ref else None,
            "skillRefs": [item.to_dict() for item in self.skill_refs],
        }


@dataclass(frozen=True)
class AttachmentRef:
    file_id: str
    purpose: str = "input"

    @classmethod
    def from_dict(cls, value: Any, *, name: str = "input.attachmentRefs[]") -> "AttachmentRef":
        data = _object(value, name)
        _keys(data, {"fileId", "purpose"}, name)
        file_id = _id(data.get("fileId"), f"{name}.fileId") or ""
        purpose = _string(data.get("purpose", "input"), f"{name}.purpose")
        if purpose not in {"input", "reference"}:
            raise ProtocolError(f"{name}.purpose must be input or reference")
        return cls(file_id=file_id, purpose=purpose)

    def to_dict(self) -> dict[str, str]:
        return {"fileId": self.file_id, "purpose": self.purpose}


@dataclass(frozen=True)
class Input:
    text: str
    attachment_refs: tuple[AttachmentRef, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "Input":
        data = _object(value, "input")
        _keys(data, {"text", "attachmentRefs", "fileRefs"}, "input")
        if "attachmentRefs" in data and "fileRefs" in data:
            raise ProtocolError("input cannot contain both attachmentRefs and fileRefs")
        # An attachment-only request is valid.  Keep text validation strict,
        # but allow an omitted/empty value and let the runtime reject a run
        # only when both text and attachments are absent.
        raw_text = data.get("text", "")
        if raw_text is None:
            raw_text = ""
        if not isinstance(raw_text, str):
            raise ProtocolError("input.text must be a string")
        if "\x00" in raw_text or len(raw_text) > MAX_TEXT_LENGTH:
            raise ProtocolError("input.text is invalid or too long")
        raw_refs = data.get("attachmentRefs", data.get("fileRefs"))
        refs = _list(raw_refs, "input.attachmentRefs")
        if len(refs) > 64:
            raise ProtocolError("input.attachmentRefs contains too many entries")
        return cls(
            text=raw_text,
            attachment_refs=tuple(AttachmentRef.from_dict(item) for item in refs),
        )

    @property
    def file_refs(self) -> tuple[AttachmentRef, ...]:
        return self.attachment_refs

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "attachmentRefs": [item.to_dict() for item in self.attachment_refs],
        }


@dataclass(frozen=True)
class Runtime:
    harness: str = DEFAULT_HARNESS
    provider: str = DEFAULT_PROVIDER
    model: str | None = None
    session_ref: str | None = None
    continuity_policy: str = "new_with_summary"

    @classmethod
    def from_dict(cls, value: Any = None) -> "Runtime":
        if value is None:
            return cls()
        data = _object(value, "runtime")
        _keys(data, {"harness", "provider", "model", "sessionRef", "continuityPolicy"}, "runtime")
        harness = _string(data.get("harness", DEFAULT_HARNESS), "runtime.harness") or DEFAULT_HARNESS
        provider = _string(data.get("provider", DEFAULT_PROVIDER), "runtime.provider") or DEFAULT_PROVIDER
        model = _string(data.get("model"), "runtime.model", required=False)
        session_ref = _id(data.get("sessionRef"), "runtime.sessionRef", required=False)
        continuity = _string(
            data.get("continuityPolicy", "new_with_summary"),
            "runtime.continuityPolicy",
        ) or "new_with_summary"
        if continuity not in {"resume", "new_with_summary", "new_empty"}:
            raise ProtocolError("runtime.continuityPolicy is invalid")
        return cls(harness, provider, model, session_ref, continuity)

    def to_dict(self) -> dict[str, Any]:
        return {
            "harness": self.harness,
            "provider": self.provider,
            "model": self.model,
            "sessionRef": self.session_ref,
            "continuityPolicy": self.continuity_policy,
        }


@dataclass(frozen=True)
class Credentials:
    # repr=False prevents accidental token disclosure in debug logs.
    platform_bearer: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, value: Any = None) -> "Credentials":
        if value is None:
            return cls()
        data = _object(value, "credentials")
        _keys(data, {"platformBearer"}, "credentials")
        token = _string(
            data.get("platformBearer"),
            "credentials.platformBearer",
            required=False,
            max_length=MAX_TOKEN_LENGTH,
        )
        return cls(token)

    def to_dict(self, *, include_secret: bool = False) -> dict[str, Any]:
        if not include_secret or self.platform_bearer is None:
            return {}
        return {"platformBearer": self.platform_bearer}


@dataclass(frozen=True)
class Limits:
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_turns: int = DEFAULT_MAX_TURNS

    @classmethod
    def from_dict(cls, value: Any = None) -> "Limits":
        if value is None:
            return cls()
        data = _object(value, "limits")
        _keys(data, {"timeoutMs", "maxTurns"}, "limits")
        timeout = data.get("timeoutMs", DEFAULT_TIMEOUT_MS)
        turns = data.get("maxTurns", DEFAULT_MAX_TURNS)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3_600_000:
            raise ProtocolError("limits.timeoutMs must be an integer between 1 and 3600000")
        if isinstance(turns, bool) or not isinstance(turns, int) or not 1 <= turns <= 100:
            raise ProtocolError("limits.maxTurns must be an integer between 1 and 100")
        return cls(timeout, turns)

    def to_dict(self) -> dict[str, int]:
        return {"timeoutMs": self.timeout_ms, "maxTurns": self.max_turns}


@dataclass(frozen=True)
class Context:
    tenant_id: str | None = None
    user_id: str | None = None
    locale: str | None = None

    @classmethod
    def from_dict(cls, value: Any = None) -> "Context":
        if value is None:
            return cls()
        data = _object(value, "context")
        _keys(data, {"tenantId", "userId", "locale"}, "context")
        return cls(
            tenant_id=_id(data.get("tenantId"), "context.tenantId", required=False),
            user_id=_id(data.get("userId"), "context.userId", required=False),
            locale=_string(data.get("locale"), "context.locale", required=False, max_length=32),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "tenantId": self.tenant_id,
                "userId": self.user_id,
                "locale": self.locale,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class AgentRunRequest:
    protocol: str = PROTOCOL
    request_id: str | None = None
    run_id: str = ""
    message_id: str | None = None
    business_session_id: str | None = None
    turn_id: str | None = None
    agent_ref: AgentRef = field(default_factory=lambda: AgentRef("agent_default"))
    capability_ref: str | None = None
    execution: Execution = field(default_factory=Execution)
    input: Input = field(default_factory=lambda: Input(""))
    runtime: Runtime = field(default_factory=Runtime)
    credentials: Credentials = field(default_factory=Credentials)
    limits: Limits = field(default_factory=Limits)
    context: Context = field(default_factory=Context)
    trace_id: str | None = None

    def __post_init__(self) -> None:
        if self.protocol != PROTOCOL:
            raise ProtocolError(f"protocol must be {PROTOCOL}")
        _id(self.run_id, "runId")
        if self.request_id is not None:
            _id(self.request_id, "requestId")
        if self.business_session_id is not None:
            _id(self.business_session_id, "businessSessionId")
        if self.turn_id is not None:
            _id(self.turn_id, "turnId")
        if self.message_id is not None:
            _id(self.message_id, "messageId")
        if self.capability_ref is not None:
            _id(self.capability_ref, "capabilityRef")
        if self.trace_id is not None:
            _id(self.trace_id, "traceId")
        if self.execution.kind == "workflow":
            derived = self.execution.capability_ref
            if self.capability_ref not in {None, derived}:
                raise ProtocolError("capabilityRef must match execution.workflowRef.id")

    @classmethod
    def from_dict(cls, value: Any) -> "AgentRunRequest":
        data = _object(value, "request")
        _keys(
            data,
            {
                "protocol",
                "requestId",
                "runId",
                "messageId",
                "businessSessionId",
                "turnId",
                "agentRef",
                "capabilityRef",
                "execution",
                "input",
                "runtime",
                "credentials",
                "limits",
                "context",
                "traceId",
            },
            "request",
        )
        if "protocol" not in data:
            raise ProtocolError("protocol is required")
        protocol = data["protocol"]
        if protocol != PROTOCOL:
            raise ProtocolError(f"protocol must be {PROTOCOL}")
        run_id = _id(data.get("runId"), "runId") or ""
        execution = Execution.from_dict(data.get("execution"))
        explicit_capability = _id(data.get("capabilityRef"), "capabilityRef", required=False)
        if explicit_capability is None and execution.capability_ref:
            explicit_capability = execution.capability_ref
        return cls(
            protocol=protocol,
            request_id=_id(data.get("requestId"), "requestId", required=False),
            run_id=run_id,
            message_id=_id(data.get("messageId"), "messageId", required=False),
            business_session_id=_id(data.get("businessSessionId"), "businessSessionId", required=False),
            turn_id=_id(data.get("turnId"), "turnId", required=False),
            agent_ref=AgentRef.from_dict(data.get("agentRef", {"id": "agent_default"})),
            capability_ref=explicit_capability,
            execution=execution,
            input=Input.from_dict(data.get("input", {"text": ""})),
            runtime=Runtime.from_dict(data.get("runtime")),
            credentials=Credentials.from_dict(data.get("credentials")),
            limits=Limits.from_dict(data.get("limits")),
            context=Context.from_dict(data.get("context")),
            trace_id=_id(data.get("traceId"), "traceId", required=False),
        )

    @property
    def requestId(self) -> str | None:  # noqa: N802 - wire-format alias
        return self.request_id

    @property
    def runId(self) -> str:  # noqa: N802 - wire-format alias
        return self.run_id

    @property
    def capabilityRef(self) -> str | None:  # noqa: N802 - wire-format alias
        return self.capability_ref

    def to_dict(self, *, include_credentials: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "protocol": self.protocol,
            "requestId": self.request_id,
            "runId": self.run_id,
            "messageId": self.message_id,
            "businessSessionId": self.business_session_id,
            "turnId": self.turn_id,
            "agentRef": self.agent_ref.to_dict(),
            "capabilityRef": self.capability_ref,
            "execution": self.execution.to_dict(),
            "input": self.input.to_dict(),
            "runtime": self.runtime.to_dict(),
            "limits": self.limits.to_dict(),
            "context": self.context.to_dict(),
            "traceId": self.trace_id,
        }
        if include_credentials:
            result["credentials"] = self.credentials.to_dict(include_secret=True)
        return {key: value for key, value in result.items() if value is not None}

    def to_internal_dict(self) -> dict[str, Any]:
        """Serialize for the Java-to-Python boundary, including the token once."""
        return self.to_dict(include_credentials=True)
