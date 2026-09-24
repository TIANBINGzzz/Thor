"""声明式 Capability、Workflow 与 Skill 资产注册表。"""

from __future__ import annotations

import json
from pathlib import Path
import re


ENTRY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def read_manifest(directory: Path, filename: str) -> dict:
    """读取目录内的 JSON manifest，并拒绝非法对象或未知内部字段。"""
    path = (directory / filename).resolve()
    if not path.is_file() or not path.is_relative_to(directory.resolve()):
        raise RuntimeError(f"声明文件不存在：{path}")
    try:
        def unique_pairs(pairs):
            """JSON 对象拒绝重复键，避免静默覆盖安全配置。"""
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = item
            return result

        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"声明文件无效：{path}") from error
    if not isinstance(value, dict) or any(key.startswith("_") for key in value):
        raise RuntimeError(f"声明文件必须是对象：{path}")
    return value


def read_asset_body(directory: Path, filename: str) -> str:
    """读取资产 Markdown 正文。"""
    path = directory / filename
    if not path.is_file():
        raise RuntimeError(f"资产正文不存在：{path}")
    try:
        body = path.read_text(encoding="utf-8").strip()
        if not body or len(body.encode("utf-8")) > 24_000:
            raise RuntimeError("资产正文为空或超限")
        return body
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"资产正文无法读取：{path}") from error


def load_declared_asset(
    directory: Path,
    manifest_filename: str,
    body_filename: str,
    expected_ref: str,
    *,
    required_fields: tuple[str, ...] = (),
) -> dict:
    """统一读取并校验带 JSON 声明和 Markdown 正文的执行资产。"""
    directory = Path(directory).resolve()
    manifest = read_manifest(directory, manifest_filename)
    if manifest.get("ref") != expected_ref:
        raise RuntimeError(f"资产引用不匹配：{directory / manifest_filename}")
    for field in required_fields:
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise RuntimeError(f"资产元数据无效：{directory / manifest_filename}")
    return {
        **manifest,
        "_body": read_asset_body(directory, body_filename),
        "_directory": str(directory),
    }


def validate_refs(values, label: str) -> tuple[str, ...]:
    """校验声明中的资源引用，返回去重前的不可变引用集合。"""
    if not isinstance(values, list) or any(not isinstance(value, str) or not ENTRY_NAME.fullmatch(value) for value in values):
        raise RuntimeError(f"{label}配置无效")
    if len(set(values)) != len(values):
        raise RuntimeError(f"{label}不能重复")
    return tuple(values)
