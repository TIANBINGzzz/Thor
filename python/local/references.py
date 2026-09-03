"""Server-owned reference parsing, search, and prompt expansion."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRECTORIES = {"node_modules", ".git", ".idea", ".tmp", ".scribe-sessions", ".next", "__pycache__"}
REFERENCE_TERMINATORS = "，。、；：！？“”‘’（）《》【】…—～"
REFERENCE_PATTERN = re.compile(rf"@([a-z][a-z0-9_]*):([^\s@{re.escape(REFERENCE_TERMINATORS)}]+)")
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
CACHE_TTL_SECONDS = 30


def encode_reference_value(value: str) -> str:
    return re.sub(r"[%\s@]", lambda match: f"%{ord(match.group(0)):02X}", value)


def decode_reference_value(value: str) -> str:
    return re.sub(r"%([0-9a-fA-F]{2})", lambda match: chr(int(match.group(1), 16)), value)


def parse_references(prompt: Any) -> list[dict[str, str]]:
    found = []
    seen = set()
    for match in REFERENCE_PATTERN.finditer(str(prompt or "")):
        source_type = match.group(1)
        value = decode_reference_value(match.group(2))
        key = (source_type, value)
        if key in seen:
            continue
        seen.add(key)
        found.append({"type": source_type, "value": value, "raw": match.group(0)})
    return found


class _Cache:
    def __init__(self, loader: Callable[[], list[dict[str, str]]]):
        self.loader = loader
        self.loaded_at = 0.0
        self.value: list[dict[str, str]] = []

    def get(self) -> list[dict[str, str]]:
        if not self.value or time.monotonic() - self.loaded_at >= CACHE_TTL_SECONDS:
            self.value = self.loader()
            self.loaded_at = time.monotonic()
        return self.value

def _load_project_files() -> list[dict[str, str]]:
    files = []
    for path in PROJECT_ROOT.rglob("*"):
        try:
            relative = path.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        if len(relative.parts) > 9 or not path.is_file():
            continue
        value = relative.as_posix()
        files.append({"value": value, "label": value})
    return sorted(files, key=lambda item: item["value"])


def _load_packages() -> list[dict[str, str]]:
    modules = PROJECT_ROOT / "node_modules"
    if not modules.is_dir():
        return []
    names = []
    for path in modules.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        if path.name.startswith("@"):
            names.extend(f"{path.name}/{child.name}" for child in path.iterdir() if child.is_dir())
        else:
            names.append(path.name)
    return [{"value": name, "label": name} for name in sorted(names)]


def _load_skills() -> list[dict[str, str]]:
    skills_root = PROJECT_ROOT / ".claude" / "skills"
    if not skills_root.is_dir():
        return []
    skills = []
    frontmatter = re.compile(r"^---\s*\nname:\s*(.+?)\s*\ndescription:\s*(.+?)\s*\n---", re.DOTALL)
    for path in skills_root.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        try:
            content = (path / "SKILL.md").read_text(encoding="utf-8")
        except OSError:
            continue
        match = frontmatter.match(content)
        skills.append({
            "value": path.name,
            "label": match.group(1).strip() if match else path.name,
            "description": match.group(2).strip() if match else "",
        })
    return sorted(skills, key=lambda item: item["label"].casefold())


_files = _Cache(_load_project_files)
_packages = _Cache(_load_packages)
_skills = _Cache(_load_skills)

SOURCES = {
    "file": {"label": "项目文件", "hint": "按路径搜索项目中的文件", "cache": _files},
    "skill": {"label": "技能", "hint": "按名称搜索可用的 Skill", "cache": _skills},
    "pkg": {"label": "已安装依赖", "hint": "按包名搜索 node_modules 里的依赖", "cache": _packages},
}


def list_sources() -> list[dict[str, str]]:
    return [
        {"type": source_type, "label": SOURCES[source_type]["label"], "hint": SOURCES[source_type]["hint"]}
        for source_type in ("skill", "pkg", "file")
    ]


def is_source(source_type: str) -> bool:
    return source_type in SOURCES


def search_source(source_type: str, query: str = "", *, limit: Any = DEFAULT_LIMIT, offset: Any = 0) -> dict[str, Any] | None:
    source = SOURCES.get(source_type)
    if source is None:
        return None
    try:
        size = min(max(int(limit or DEFAULT_LIMIT), 1), MAX_LIMIT)
    except (TypeError, ValueError):
        size = DEFAULT_LIMIT
    try:
        start = max(int(offset or 0), 0)
    except (TypeError, ValueError):
        start = 0
    needle = str(query or "").strip().casefold()
    all_items = source["cache"].get()
    matched = [item for item in all_items if needle in item["label"].casefold()] if needle else list(all_items)
    if needle:
        matched.sort(key=lambda item: (
            not item["label"].casefold().startswith(needle),
            len(item["label"]),
            item["label"].casefold(),
        ))
    return {
        "type": source_type,
        "total": len(matched),
        "offset": start,
        "items": [
            {
                "value": item["value"],
                "label": item["label"],
                "reference": f"@{source_type}:{encode_reference_value(item['value'])}",
            }
            for item in matched[start:start + size]
        ],
    }


def _resolve(source_type: str, value: str) -> dict[str, str] | None:
    source = SOURCES[source_type]
    item = next((entry for entry in source["cache"].get() if entry["value"] == value), None)
    if item is None:
        return None
    if source_type == "file":
        path = (PROJECT_ROOT / value).resolve()
        try:
            path.relative_to(PROJECT_ROOT.resolve())
        except ValueError:
            return None
        if not path.is_file():
            return None
        return {"label": item["label"], "detail": f"路径：{path}；{path.stat().st_size} 字节"}
    if source_type == "skill":
        return {"label": item["label"], "detail": item.get("description") or "无描述"}
    manifest = PROJECT_ROOT / "node_modules" / value / "package.json"
    try:
        parsed = json.loads(manifest.read_text(encoding="utf-8"))
        detail = " · ".join(part for part in (
            f"v{parsed.get('version')}" if parsed.get("version") else "",
            str(parsed.get("description") or ""),
        ) if part)
    except (OSError, json.JSONDecodeError):
        detail = ""
    return {"label": value, "detail": detail}


def reference_prompt_context(prompt: str) -> str:
    references = parse_references(prompt)
    if not references:
        return ""
    lines = []
    for reference in references:
        source = SOURCES.get(reference["type"])
        if source is None:
            lines.append(f"- {reference['raw']}：未知引用类型，忽略。")
            continue
        resolved = _resolve(reference["type"], reference["value"])
        if resolved is None:
            lines.append(f"- {reference['raw']}：在{source['label']}中不存在，不要凭猜测使用。")
            continue
        detail = f"（{resolved['detail']}）" if resolved["detail"] else ""
        lines.append(f"- {reference['raw']} → {source['label']}：{resolved['label']}{detail}")
    return "\n".join([
        "用户在提问中使用了引用标记，对应的真实对象如下（由服务端解析，可信）：",
        *lines,
        "引用 @skill: 时遵循该 Skill 的工作流程和规则。",
    ])
