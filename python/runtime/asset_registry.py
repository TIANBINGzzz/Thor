"""读取部署资产声明并校验资源引用。"""

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


def validate_refs(values, label: str) -> tuple[str, ...]:
    """校验声明中的资源引用，返回去重前的不可变引用集合。"""
    if not isinstance(values, list) or any(not isinstance(value, str) or not ENTRY_NAME.fullmatch(value) for value in values):
        raise RuntimeError(f"{label}配置无效")
    if len(set(values)) != len(values):
        raise RuntimeError(f"{label}不能重复")
    return tuple(values)
