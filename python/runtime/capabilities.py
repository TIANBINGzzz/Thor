"""Trusted business Capability catalog for the Python SDK runtime."""

from __future__ import annotations

from dataclasses import dataclass


class CapabilityError(ValueError):
    """Raised when a business capability is not available to the runtime."""


@dataclass(frozen=True)
class Capability:
    ref: str
    workflow_ref: str | None
    supports_attachments: bool = False
    name: str = ""
    description: str = ""

    def to_public_dict(self) -> dict:
        """将当前能力转换为公开目录字典，包含业务标识、说明和附件支持状态。"""
        return {"capabilityRef": self.ref, "name": self.name,
                "description": self.description, "supportsAttachments": self.supports_attachments}


# These names are business entry points. Workflow names remain implementation
# details and may be reused by several capabilities.
CAPABILITIES: dict[str, Capability] = {
    "conversation": Capability("conversation", None, True, "通用对话", "日常交流、内容总结与问题解答"),
    "document-writing": Capability("document-writing", "writing-docx", True, "文档撰写", "起草、修改与生成 Word 文档"),
    "national-excellence-data-qa": Capability("national-excellence-data-qa", "double-high-qa", False, "双高问数", "查询国双高项目、任务、资金与绩效"),
}


def resolve_capability(ref: str | None) -> Capability:
    """根据业务能力标识返回登记的 Capability，未登记时抛出 CapabilityError。"""
    try:
        return CAPABILITIES["conversation" if ref is None else ref]
    except KeyError as error:
        raise CapabilityError("capability_not_found") from error


__all__ = ["CAPABILITIES", "Capability", "CapabilityError", "resolve_capability"]
