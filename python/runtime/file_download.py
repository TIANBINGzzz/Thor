"""按本轮授权 fileId 下载平台文件，模型启动前原子写入隔离的输入目录。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from email.message import Message
import hashlib
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib.parse import unquote_plus
import uuid

import httpx

from runtime.file_service import FileServiceError, file_service_config, with_run_domain
from runtime.protocol import SAFE_ID
from runtime.runtime_settings import RUNTIME_SETTINGS


LOGGER = logging.getLogger("ccsdk.file_download")
DEFAULT_MAX_FILE_BYTES = RUNTIME_SETTINGS.limits.file_max_bytes
DOWNLOAD_CHUNK_BYTES = 256 * 1024
SAFE_MIME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+/[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
SAFE_FILENAME = re.compile(r'^[^\\/\x00\r\n<>:"|?*]+$')
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
EventSink = Callable[[str, dict[str, Any]], None]
ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]


class FileDownloadError(RuntimeError):
    """文件下载稳定错误，不包含上游地址或凭据。"""

    def __init__(self, message: str, *, code: str = "file_download_failed") -> None:
        super().__init__(message)
        self.code = code


class FileDownloadUnavailableError(FileDownloadError):
    def __init__(self, message: str = "文件下载服务未配置或不可用") -> None:
        super().__init__(message, code="file_download_unavailable")


class FileDownloadConfigurationError(FileDownloadError):
    def __init__(self, message: str = "文件下载配置无效") -> None:
        super().__init__(message, code="file_download_configuration_error")


class FileDownloadTimeoutError(FileDownloadError):
    def __init__(self, message: str = "文件下载超时") -> None:
        super().__init__(message, code="file_download_timeout")


class FileDownloadValidationError(FileDownloadError):
    def __init__(self, message: str = "文件校验失败") -> None:
        super().__init__(message, code="file_validation_failed")


@dataclass(frozen=True)
class FetchedFile:
    """已下载文件的本轮元数据；对外元数据不含源地址和本地路径。"""

    file_id: str
    purpose: str
    safe_name: str
    mime_type: str
    size: int
    sha256: str
    path: Path
    transfer_mode: str = "file_service"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "fileId": self.file_id,
            "purpose": self.purpose,
            "safeName": self.safe_name,
            "mimeType": self.mime_type,
            "bytes": self.size,
            "sha256": self.sha256,
            "source": "file-service",
            "transferMode": self.transfer_mode,
        }


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FileDownloadConfigurationError(f"{name} 必须是正整数")
    return value


def _safe_filename(value: Any) -> str:
    """拒绝路径字符、控制字符和 Windows 保留名，不替换不安全的来源文件名。"""
    if not isinstance(value, str) or not value.strip():
        raise FileDownloadValidationError("文件服务器未返回文件名")
    name = value.strip()
    if (len(name) > 255 or not SAFE_FILENAME.fullmatch(name) or name in {".", ".."}
            or name.endswith((".", " ")) or any(ord(char) < 32 for char in name)
            or name.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES):
        raise FileDownloadValidationError("文件名不安全")
    return name


def _content_type(headers: httpx.Headers) -> str:
    value = headers.get("content-type")
    if not value:
        return "application/octet-stream"
    mime = value.split(";", 1)[0].strip().lower()
    if not SAFE_MIME.fullmatch(mime):
        raise FileDownloadValidationError("文件 MIME 类型无效")
    return mime


def _content_length(headers: httpx.Headers, max_bytes: int) -> int | None:
    value = headers.get("content-length")
    if value is None:
        return None
    try:
        size = int(value)
    except ValueError:
        raise FileDownloadValidationError("文件大小无效") from None
    if size < 0 or size > max_bytes:
        raise FileDownloadValidationError("文件大小无效或超过限制")
    return size


def _filename(headers: httpx.Headers) -> str:
    disposition = headers.get("content-disposition", "")
    message = Message()
    message["Content-Disposition"] = disposition
    name = message.get_filename()
    if name and not re.search(r"(?:^|;)\s*filename\*\s*=", disposition, re.I):
        # 平台普通 filename 使用 Java URL 编码；RFC 5987 由 email 库解码，避免重复处理。
        try:
            name = unquote_plus(name, encoding="utf-8", errors="strict")
        except UnicodeError:
            raise FileDownloadValidationError("文件名编码无效") from None
    return _safe_filename(name)


class FileDownloader:
    """只下载可信 Java 本轮提交的附件引用；文件 ACL 由 Java 提交前校验。"""

    def __init__(self, *, domain_name: str,
                 max_bytes: int | None = None, timeout_ms: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 event_sink: EventSink | None = None,
                 progress_sink: ProgressSink | None = None) -> None:
        try:
            self.file_service = with_run_domain(file_service_config(download=True), domain_name)
        except FileServiceError as error:
            if error.code != "file_service_not_configured":
                raise FileDownloadConfigurationError() from None
            self.file_service = None
        self.max_bytes = _positive_int(
            max_bytes if max_bytes is not None else RUNTIME_SETTINGS.limits.file_max_bytes,
            "max_bytes")
        self.timeout_ms = _positive_int(
            timeout_ms if timeout_ms is not None else RUNTIME_SETTINGS.timeouts.file_download_ms,
            "timeout_ms")
        if self.file_service:
            self.max_bytes = min(self.max_bytes, self.file_service["maxFileBytes"])
            self.timeout_ms = min(self.timeout_ms, self.file_service["timeoutSeconds"] * 1000)
        self.transport, self.event_sink, self.progress_sink = transport, event_sink, progress_sink

    @property
    def configured(self) -> bool:
        return bool(self.file_service)

    async def fetch_all(self, attachment_refs: Any, *, workspace: str | Path) -> tuple[FetchedFile, ...]:
        """顺序准备附件；任一失败、超时或取消均清理本次已完成文件和临时片段。"""
        refs = tuple(attachment_refs or ())
        if not refs:
            return ()
        if not self.configured:
            for reference in refs:
                self._emit("file.fetch.started", self._start_data(reference))
                self._emit("file.fetch.failed", self._failure_data(
                    reference, "file_download_unavailable", 0))
            raise FileDownloadUnavailableError()

        root = Path(workspace).resolve()
        root.mkdir(parents=True, exist_ok=True)
        results: list[FetchedFile] = []
        used_names: set[str] = set()
        prepare_ms = min(RUNTIME_SETTINGS.timeouts.file_prepare_ms,
                         self.file_service["timeoutSeconds"] * 1000)
        deadline = time.monotonic() + prepare_ms / 1000
        active_reference, active_started = None, None
        try:
            async with asyncio.timeout(prepare_ms / 1000):
                async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_ms / 1000),
                        follow_redirects=False, trust_env=False, transport=self.transport) as client:
                    for reference in refs:
                        active_reference, active_started = reference, time.monotonic()
                        data = self._start_data(reference)
                        self._emit("file.fetch.started", data)
                        try:
                            await self._progress("preparing_file", fileId=data["fileId"])
                            fetched = await self._fetch_one(client, reference, root, used_names)
                            results.append(fetched)
                            used_names.add(fetched.safe_name.lower())
                            await self._progress("file_ready", fileId=fetched.file_id,
                                                 receivedBytes=fetched.size, totalBytes=fetched.size)
                            self._emit("file.fetch.succeeded", {
                                **fetched.to_metadata(), "durationMs": self._duration(active_started)})
                        except asyncio.CancelledError:
                            code = "file_download_timeout" if time.monotonic() >= deadline else "cancelled"
                            self._emit("file.fetch.failed", self._failure_data(
                                reference, code, self._duration(active_started)))
                            active_reference = None
                            raise
                        except FileDownloadError as error:
                            self._emit("file.fetch.failed", self._failure_data(
                                reference, error.code, self._duration(active_started)))
                            raise
                        except (httpx.TimeoutException, TimeoutError) as error:
                            failure = FileDownloadTimeoutError()
                            self._emit("file.fetch.failed", self._failure_data(
                                reference, failure.code, self._duration(active_started)))
                            raise failure from error
                        except (httpx.HTTPError, OSError, ValueError) as error:
                            failure = FileDownloadError("文件下载失败")
                            self._emit("file.fetch.failed", self._failure_data(
                                reference, failure.code, self._duration(active_started)))
                            raise failure from error
                        active_reference, active_started = None, None
        except asyncio.TimeoutError as error:
            self._remove_files(results)
            if active_reference is not None:
                self._emit("file.fetch.failed", self._failure_data(active_reference,
                    "file_download_timeout", self._duration(active_started or time.monotonic())))
            raise FileDownloadTimeoutError() from error
        except BaseException:
            self._remove_files(results)
            raise
        return tuple(results)

    async def _fetch_one(self, client: httpx.AsyncClient, reference: Any,
                         root: Path, used_names: set[str]) -> FetchedFile:
        file_id = str(getattr(reference, "file_id", "") or "")
        purpose = str(getattr(reference, "purpose", "input") or "input")
        if not SAFE_ID.fullmatch(file_id):
            raise FileDownloadValidationError("文件标识无效")
        config = self.file_service
        url = config["baseUrl"] + config["downloadPath"].replace("{fileId}", file_id)
        headers = {"domain-name": config["domainName"], "remote-url": config["remoteUrl"],
                   "accept": "application/octet-stream", "accept-encoding": "identity"}
        # 同批次响应可能设置 Cookie；仅发送受控路由头，不复用隐式身份。
        client.cookies.clear()
        async with client.stream("GET", url, headers=headers) as response:
            if response.is_redirect:
                raise FileDownloadValidationError("文件下载不允许重定向")
            if response.status_code in {401, 403, 404, 409, 410, 424}:
                raise FileDownloadError("文件未授权或不可用", code="file_access_denied")
            if response.status_code != 200:
                raise FileDownloadError("文件下载失败")
            name = self._unique_name(_filename(response.headers), file_id, used_names)
            mime = _content_type(response.headers)
            expected_size = _content_length(response.headers, self.max_bytes)
            self._emit("file.fetch.transport.selected", {
                "fileId": file_id, "purpose": purpose, "transferMode": "file_service"})
            return await self._download_response(response, file_id=file_id, purpose=purpose,
                name=name, mime_type=mime, expected_size=expected_size, root=root)

    async def _download_response(self, response: httpx.Response, *, file_id: str, purpose: str,
            name: str, mime_type: str, expected_size: int | None, root: Path) -> FetchedFile:
        """按响应长度和限额核验流；本地摘要仅记录实际输入，不冒充远端权威摘要。"""
        target = (root / name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise FileDownloadValidationError("文件路径越界") from None
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        digest, total, progress_at = hashlib.sha256(), 0, time.monotonic()
        await self._progress("downloading_file", fileId=file_id,
                             receivedBytes=0, totalBytes=expected_size)
        try:
            with temporary.open("xb") as stream:
                async for chunk in response.aiter_bytes(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_bytes or (expected_size is not None and total > expected_size):
                        raise FileDownloadValidationError("文件超过大小限制")
                    stream.write(chunk)
                    digest.update(chunk)
                    now = time.monotonic()
                    if now - progress_at >= 0.5:
                        await self._progress("downloading_file", fileId=file_id,
                                             receivedBytes=total, totalBytes=expected_size)
                        progress_at = now
                    # 已缓冲的传输也须让出执行权，使取消及时生效。
                    await asyncio.sleep(0)
                await self._progress("downloading_file", fileId=file_id,
                                     receivedBytes=total, totalBytes=expected_size)
                await self._progress("validating_file", fileId=file_id,
                                     receivedBytes=total, totalBytes=expected_size)
                stream.flush()
                os.fsync(stream.fileno())
            if expected_size is not None and total != expected_size:
                raise FileDownloadValidationError("文件大小与响应长度不匹配")
            os.replace(temporary, target)
            return FetchedFile(file_id, purpose, name, mime_type, total, digest.hexdigest(), target)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as error:
                LOGGER.warning("文件下载临时片段清理失败: %s", type(error).__name__)
            raise

    @staticmethod
    def _unique_name(name: str, file_id: str, used_names: set[str]) -> str:
        if name.lower() not in used_names:
            return name
        stem, dot, suffix = name.rpartition(".")
        if not dot:
            stem, suffix = name, ""
        short_id = re.sub(r"[^A-Za-z0-9_-]", "_", file_id)[:24] or "file"
        candidate = f"{stem}__{short_id}" + (f".{suffix}" if suffix else "")
        if candidate.lower() in used_names:
            candidate = f"{stem}__{short_id}_{uuid.uuid4().hex[:8]}" + (f".{suffix}" if suffix else "")
        return _safe_filename(candidate)

    @staticmethod
    def _duration(started: float) -> int:
        return max(0, int((time.monotonic() - started) * 1000))

    @staticmethod
    def _start_data(reference: Any) -> dict[str, Any]:
        return {"fileId": str(getattr(reference, "file_id", "") or ""),
                "purpose": str(getattr(reference, "purpose", "input") or "input")}

    @staticmethod
    def _failure_data(reference: Any, code: str, duration_ms: int) -> dict[str, Any]:
        return {**FileDownloader._start_data(reference), "errorCode": code, "durationMs": duration_ms}

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(event_type, data)
            except Exception as error:
                # 观测故障不得改变文件准备结果，只记录异常类型。
                LOGGER.warning("文件下载事件回调失败: %s", type(error).__name__)

    async def _progress(self, name: str, **fields: Any) -> None:
        if self.progress_sink is not None:
            await self.progress_sink({"name": name, **fields})

    @staticmethod
    def _remove_files(files: list[FetchedFile]) -> None:
        for item in files:
            try:
                item.path.unlink(missing_ok=True)
            except OSError as error:
                LOGGER.warning("文件下载已完成输入清理失败: %s", type(error).__name__)


__all__ = ["DEFAULT_MAX_FILE_BYTES", "FileDownloader", "FileDownloadError",
           "FileDownloadUnavailableError", "FileDownloadConfigurationError",
           "FileDownloadTimeoutError", "FileDownloadValidationError", "FetchedFile"]
