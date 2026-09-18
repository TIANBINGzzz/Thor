"""MCP tools for publishing user-visible session artifacts."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _source_path(value: str | Path, roots: list[Path]) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        raise ValueError("source_path 不能为空")
    raw = Path(value).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    for root in roots:
        candidate = (root / raw).resolve()
        if candidate.is_file():
            return candidate
    return (roots[0] / raw).resolve()


def _inside(path: Path, roots: list[Path]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _safe_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("file_name 不能为空")
    normalized = value.replace("\\", "/")
    if Path(normalized).name != normalized or normalized in {".", ".."}:
        raise ValueError("file_name 不能包含目录路径")
    name = Path(normalized).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("file_name 无效")
    if name.startswith("."):
        raise ValueError("file_name 不能使用隐藏文件名")
    if any(ord(char) < 32 for char in name):
        raise ValueError("file_name 包含控制字符")
    return name


def publish_artifact(
    source_path: str,
    file_name: str,
    work_directory: str | Path,
    deliverables_directory: str | Path,
    session_directory: str | Path,
) -> dict[str, Any]:
    """把最终文件固化为独立 ID 的待上传快照；返回 pending，不代表远端已可下载。"""

    work = _resolved(work_directory)
    deliverables = _resolved(deliverables_directory)
    # ``session_directory`` is retained as an explicit boundary argument, but
    # the session root itself is never a readable/publishable tool root.  Only
    # the current session's work and deliverables directories are eligible;
    # this prevents historical Run inputs from becoming artifact sources.
    _ = _resolved(session_directory)
    source_roots = [_resolved(work_directory), _resolved(deliverables_directory)]
    source = _source_path(source_path, source_roots)
    target_name = _safe_name(file_name)
    if not _inside(source, [work, deliverables]):
        raise ValueError("只能发布当前会话目录中的工作或交付文件")
    if not source.is_file():
        raise FileNotFoundError(f"文件不存在：{source.name}")

    deliverables.mkdir(parents=True, exist_ok=True)
    artifact_id = 'artifact_' + uuid.uuid4().hex
    staging = deliverables / ('.' + artifact_id)
    staging.mkdir()
    try:
        digest = hashlib.sha256()
        size = 0
        with source.open('rb') as reader, (staging / 'content').open('xb') as writer:
            while chunk := reader.read(1024 * 1024):
                writer.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        record = {'artifactId': artifact_id, 'name': target_name, 'size': size,
                  'suffix': Path(target_name).suffix.lstrip('.'), 'sha256': digest.hexdigest()}
        (staging / 'manifest.json').write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        staging.replace(deliverables / artifact_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {'artifactId': artifact_id, 'name': target_name, 'size': size, 'status': 'pending'}


def _text_result(value: Any) -> dict[str, list[dict[str, str]]]:
    import json

    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


def create_artifact_server(
    session_directory: str | Path,
    work_directory: str | Path,
    deliverables_directory: str | Path,
    on_published=None,
):
    """接收会话、工作和交付目录，返回注册 publish_file 工具的进程内 MCP 服务配置。"""
    session = _resolved(session_directory)
    work = _resolved(work_directory)
    deliverables = _resolved(deliverables_directory)

    @sdk_tool(
        "publish_file",
        "提交最终文件供后台上传，返回 artifactId 和 pending 状态，不代表上传完成。中间文件不要发布。",
        {
            "type": "object",
            "properties": {
                "source_path": {"type": "string"},
                "file_name": {"type": "string"},
            },
            "required": ["source_path", "file_name"],
        },
    )
    async def publish_file(args: dict[str, Any]) -> dict[str, Any]:
        """接收 source_path 和 file_name 工具参数，发布文件并返回 MCP 文本结果。"""
        import asyncio
        # 等待快照线程收尾再处理取消，避免下一轮复用目录时仍在复制。
        task = asyncio.create_task(asyncio.to_thread(publish_artifact,
            args.get("source_path", ""),
            args.get("file_name", ""),
            work,
            deliverables,
            session,
        ))
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
        if on_published is not None:
            on_published({'type': 'artifact.published', 'artifactId': result['artifactId']})
        return _text_result(result)

    return create_sdk_mcp_server(
        "artifacts",
        version="0.1.0",
        tools=[publish_file],
    )
