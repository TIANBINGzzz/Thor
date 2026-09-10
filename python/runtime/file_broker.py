"""Request-scoped attachment fetching through the Java File Broker.

Fixed attachments are runtime inputs, not model tools.  This module exchanges
an attachment id for a one-time URL or a proxied response, validates the
response, and atomically writes it below the current Run workspace.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import Message
import hashlib
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import re
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit
import uuid

import httpx


LOGGER = logging.getLogger("ccsdk.file_broker")
DEFAULT_GRANT_TIMEOUT_MS = 15_000
DEFAULT_MAX_FILE_BYTES = 256 * 1024 * 1024
DEFAULT_PREPARE_TIMEOUT_MS = 600_000
DOWNLOAD_CHUNK_BYTES = 256 * 1024
MAX_GRANT_BYTES = 256 * 1024
MAX_GRANT_TTL_MS = 5 * 60 * 1000
SAFE_MIME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+/[A-Za-z0-9!#$%&'*+.^_`|~-]+$")
SAFE_FILENAME = re.compile(r"^[^\\/\x00\r\n<>:\"|?*]+$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


class FileBrokerError(RuntimeError):
    """Stable, non-sensitive error from the File Broker exchange."""

    def __init__(self, message: str, *, code: str = "file_broker_error") -> None:
        super().__init__(message)
        self.code = code


class FileBrokerUnavailableError(FileBrokerError):
    def __init__(self, message: str = "File Broker 未配置或不可用") -> None:
        super().__init__(message, code="file_broker_unavailable")


class FileBrokerConfigurationError(FileBrokerError):
    def __init__(self, message: str = "File Broker 配置无效") -> None:
        super().__init__(message, code="file_broker_configuration_error")


class FileBrokerTimeoutError(FileBrokerError):
    def __init__(self, message: str = "File Broker 请求超时") -> None:
        super().__init__(message, code="file_broker_timeout")


class FileBrokerValidationError(FileBrokerError):
    def __init__(self, message: str = "File Broker 文件校验失败") -> None:
        super().__init__(message, code="file_validation_failed")


@dataclass(frozen=True)
class FetchedFile:
    """Safe file metadata returned to the Runtime, without a source URL."""

    file_id: str
    purpose: str
    safe_name: str
    mime_type: str
    size: int
    sha256: str
    path: Path
    transfer_mode: str = "proxy_stream"

    def to_metadata(self) -> dict[str, Any]:
        """将当前下载文件转换为元数据字典，不包含源下载地址、本地路径或凭据。"""
        return {
            "fileId": self.file_id,
            "purpose": self.purpose,
            "safeName": self.safe_name,
            "mimeType": self.mime_type,
            "bytes": self.size,
            "sha256": self.sha256,
            "source": "java-file-broker",
            "transferMode": self.transfer_mode,
        }


@dataclass(frozen=True)
class _Grant:
    file_id: str
    name: str
    mime_type: str
    expected_size: int | None
    expected_sha256: str | None
    download_url: str | None
    expires_at: int | None
    one_time: bool


EventSink = Callable[[str, dict[str, Any]], None]
ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise FileBrokerConfigurationError(f"{name} 必须是正整数")
    return value


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise FileBrokerConfigurationError(f"{name} 必须是正整数")
    return _positive_int(parsed, name)


def _split_csv(name: str) -> set[str]:
    return {item.strip().lower() for item in os.environ.get(name, "").split(",") if item.strip()}


def _safe_filename(value: Any, *, fallback: str | None = None) -> str:
    name = value if isinstance(value, str) else fallback
    if not isinstance(name, str) or not name.strip():
        raise FileBrokerValidationError("File Broker 未返回文件名")
    name = name.strip()
    if (
        len(name) > 255
        or not SAFE_FILENAME.fullmatch(name)
        or name in {".", ".."}
        or name.endswith((".", " "))
        or any(ord(char) < 32 for char in name)
    ):
        raise FileBrokerValidationError("File Broker 文件名不安全")
    stem = name.rsplit(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        raise FileBrokerValidationError("File Broker 文件名不安全")
    return name


def _safe_mime(value: Any, *, required: bool = True) -> str:
    if value is None and not required:
        return "application/octet-stream"
    if not isinstance(value, str) or not SAFE_MIME.fullmatch(value.strip()):
        raise FileBrokerValidationError("File Broker MIME 类型无效")
    return value.strip().lower()


def _safe_sha256(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not SHA256.fullmatch(value.strip()):
        raise FileBrokerValidationError("File Broker 摘要无效")
    return value.strip().lower()


def _header_int(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = int(value)
    except ValueError as error:
        raise FileBrokerValidationError(f"File Broker {name} 无效") from error
    if parsed < 0:
        raise FileBrokerValidationError(f"File Broker {name} 无效")
    return parsed


def _content_type(headers: httpx.Headers) -> str | None:
    value = headers.get("content-type")
    if not value:
        return None
    mime = value.split(";", 1)[0].strip().lower()
    return _safe_mime(mime)


def _is_json_response(headers: httpx.Headers) -> bool:
    value = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return value == "application/json" or value.endswith("+json")


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    message = Message()
    message["Content-Disposition"] = value
    return message.get_filename()


def _validate_download_url(value: Any, *, allowed_hosts: set[str]) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise FileBrokerValidationError("File Broker 下载地址无效")
    if any(char.isspace() for char in value):
        raise FileBrokerValidationError("File Broker 下载地址无效")
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise FileBrokerValidationError("File Broker 下载地址无效")
    if parsed.username or parsed.password or parsed.fragment:
        raise FileBrokerValidationError("File Broker 下载地址无效")
    try:
        port = parsed.port
    except ValueError as error:
        raise FileBrokerValidationError("File Broker 下载地址端口不允许") from error
    if port not in {None, 443}:
        raise FileBrokerValidationError("File Broker 下载地址端口不允许")
    host = parsed.hostname.rstrip(".").lower()
    if allowed_hosts and host not in allowed_hosts:
        raise FileBrokerValidationError("File Broker 下载地址不在允许范围")
    return value


def _resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    try:
        resolved = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise FileBrokerValidationError("File Broker 下载地址无法解析") from error
    addresses: list[str] = []
    for item in resolved:
        raw = item[4][0]
        try:
            address = ipaddress.ip_address(raw)
        except ValueError as error:
            raise FileBrokerValidationError("File Broker 下载地址无效") from error
        if (
            not address.is_global
            or
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise FileBrokerValidationError("File Broker 下载地址不允许访问私网")
        normalized = address.compressed
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise FileBrokerValidationError("File Broker 下载地址无法解析")
    return tuple(addresses)


def _pinned_download_target(value: str) -> tuple[str, str, str]:
    """Resolve once, reject mixed/private answers, then pin the actual TCP peer.

    The original hostname remains in the HTTP Host header and TLS SNI so
    virtual hosting, signed URLs, and certificate validation keep their normal
    semantics.  Replacing only the connection authority removes the DNS lookup
    between validation and connect that would otherwise permit rebinding.
    """

    parsed = urlsplit(value)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    address = _resolve_public_addresses(host, port)[0]
    authority = f"[{address}]" if ":" in address else address
    if parsed.port is not None:
        authority = f"{authority}:{parsed.port}"
    pinned_url = urlunsplit((parsed.scheme, authority, parsed.path, parsed.query, ""))
    return pinned_url, parsed.netloc, host


def _validate_expected_size(value: Any, max_bytes: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > max_bytes:
        raise FileBrokerValidationError("File Broker 文件大小无效")
    return value


class FileBroker:
    """Fetch fixed Run attachments via an authenticated Java service call."""

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        max_bytes: int | None = None,
        timeout_ms: int | None = None,
        allowed_hosts: set[str] | None = None,
        service_token: str | None = None,
        auth_mode: str | None = None,
        verify: str | bool | None = None,
        client_cert: str | tuple[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        event_sink: EventSink | None = None,
        progress_sink: ProgressSink | None = None,
    ) -> None:
        raw_endpoint = (endpoint if endpoint is not None else os.environ.get("CCSDK_FILE_BROKER_URL", "")).strip()
        if raw_endpoint:
            parsed = urlsplit(raw_endpoint)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError("CCSDK_FILE_BROKER_URL 必须是无查询参数的 HTTPS 地址")
            self.endpoint = raw_endpoint
        else:
            self.endpoint = ""
        self.max_bytes = (
            _positive_int(max_bytes, "max_bytes")
            if max_bytes is not None
            else _env_int("CCSDK_FILE_MAX_BYTES", DEFAULT_MAX_FILE_BYTES)
        )
        self.timeout_ms = (
            _positive_int(timeout_ms, "timeout_ms")
            if timeout_ms is not None
            else _env_int("CCSDK_FILE_BROKER_TIMEOUT_MS", DEFAULT_GRANT_TIMEOUT_MS)
        )
        self.allowed_hosts = {
            host.lower().rstrip(".")
            for host in (allowed_hosts if allowed_hosts is not None else _split_csv("CCSDK_FILE_BROKER_ALLOWED_HOSTS"))
        }
        self.service_token = service_token if service_token is not None else os.environ.get("CCSDK_FILE_BROKER_SERVICE_TOKEN", "").strip()
        self.auth_mode = (auth_mode if auth_mode is not None else os.environ.get("CCSDK_FILE_BROKER_AUTH_MODE", "run_jwt")).strip().lower()
        if self.auth_mode not in {"run_jwt", "service"}:
            raise ValueError("CCSDK_FILE_BROKER_AUTH_MODE 必须是 run_jwt 或 service")
        self.verify = verify if verify is not None else os.environ.get("CCSDK_FILE_BROKER_CA", "").strip() or True
        configured_cert = client_cert if client_cert is not None else os.environ.get("CCSDK_FILE_BROKER_CLIENT_CERT", "").strip()
        configured_key = os.environ.get("CCSDK_FILE_BROKER_CLIENT_KEY", "").strip()
        if configured_cert and configured_key:
            self.client_cert: str | tuple[str, str] | None = (configured_cert, configured_key)
        elif configured_cert or configured_key:
            raise ValueError("File Broker mTLS 必须同时配置客户端证书和私钥")
        else:
            self.client_cert = configured_cert or client_cert
        self.transport = transport
        self.event_sink = event_sink
        self.progress_sink = progress_sink

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    async def fetch_all(
        self,
        attachment_refs: Any,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        workspace: str | Path,
        bearer_token: str | None = None,
        timeout_ms: int | None = None,
    ) -> tuple[FetchedFile, ...]:
        """接收附件引用、Run 上下文、工作目录和访问凭据，顺序下载并返回已校验的 FetchedFile 元组。

        访问授权交由 Java File Broker 校验；失败、超时或取消时清理本次已下载文件。
        """
        _ = tenant_id, user_id
        refs = tuple(attachment_refs or ())
        if not refs:
            return ()
        if not self.configured:
            for reference in refs:
                self._emit("file.fetch.started", self._start_data(reference))
                self._emit("file.fetch.failed", self._failure_data(reference, "file_broker_unavailable", 0))
            raise FileBrokerUnavailableError()
        selected_token = self._selected_token(bearer_token)
        if not selected_token:
            for reference in refs:
                self._emit("file.fetch.started", self._start_data(reference))
                self._emit("file.fetch.failed", self._failure_data(reference, "file_broker_unavailable", 0))
            raise FileBrokerUnavailableError("File Broker 缺少服务间鉴权")

        root = Path(workspace).resolve()
        root.mkdir(parents=True, exist_ok=True)
        results: list[FetchedFile] = []
        used_names: set[str] = set()
        effective_timeout_ms = (
            _positive_int(timeout_ms, "timeout_ms")
            if timeout_ms is not None
            else _env_int("CCSDK_FILE_PREPARE_TIMEOUT_MS", DEFAULT_PREPARE_TIMEOUT_MS)
        )
        deadline = time.monotonic() + effective_timeout_ms / 1000
        active_reference: Any | None = None
        active_started: float | None = None
        try:
            async with asyncio.timeout(effective_timeout_ms / 1000):
                async with httpx.AsyncClient(
                    timeout=self._timeout(None),
                    follow_redirects=False,
                    trust_env=False,
                    transport=self.transport,
                    verify=self.verify,
                    cert=self.client_cert,
                ) as client:
                    for reference in refs:
                        active_reference = reference
                        file_id = str(getattr(reference, "file_id", "") or "")
                        purpose = str(getattr(reference, "purpose", "input") or "input")
                        started = time.monotonic()
                        active_started = started
                        self._emit("file.fetch.started", {"fileId": file_id, "purpose": purpose})
                        await self._progress("preparing_file", fileId=file_id)
                        try:
                            fetched = await self._fetch_one(
                                client,
                                reference,
                                run_id=run_id,
                                root=root,
                                used_names=used_names,
                                auth_token=selected_token,
                            )
                            results.append(fetched)
                            used_names.add(fetched.safe_name.lower())
                            await self._progress("file_ready", fileId=file_id,
                                                 receivedBytes=fetched.size, totalBytes=fetched.size)
                            self._emit(
                                "file.fetch.succeeded",
                                {**fetched.to_metadata(), "durationMs": self._duration(started)},
                            )
                            active_reference = None
                            active_started = None
                        except asyncio.CancelledError:
                            code = "file_broker_timeout" if time.monotonic() >= deadline else "cancelled"
                            self._emit(
                                "file.fetch.failed",
                                self._failure_data(reference, code, self._duration(started)),
                            )
                            active_reference = None
                            active_started = None
                            raise
                        except FileBrokerError as error:
                            self._emit(
                                "file.fetch.failed",
                                self._failure_data(reference, error.code, self._duration(started)),
                            )
                            raise
                        except (httpx.TimeoutException, TimeoutError) as error:
                            _ = error
                            failure = FileBrokerTimeoutError()
                            self._emit(
                                "file.fetch.failed",
                                self._failure_data(reference, failure.code, self._duration(started)),
                            )
                            raise failure from error
                        except (httpx.HTTPError, OSError, ValueError) as error:
                            _ = error
                            failure = FileBrokerError("File Broker 请求失败", code="file_broker_request_failed")
                            self._emit(
                                "file.fetch.failed",
                                self._failure_data(reference, failure.code, self._duration(started)),
                            )
                            raise failure from error
        except asyncio.TimeoutError as error:
            self._remove_files(results)
            if active_reference is not None:
                self._emit(
                    "file.fetch.failed",
                    self._failure_data(
                        active_reference,
                        "file_broker_timeout",
                        self._duration(active_started or time.monotonic()),
                    ),
                )
            raise FileBrokerTimeoutError() from error
        except asyncio.CancelledError:
            self._remove_files(results)
            raise
        except Exception:
            self._remove_files(results)
            raise
        return tuple(results)

    def _timeout(self, timeout_ms: int | None) -> httpx.Timeout:
        effective_timeout_ms = (
            _positive_int(timeout_ms, "timeout_ms")
            if timeout_ms is not None
            else self.timeout_ms
        )
        value = effective_timeout_ms / 1000
        return httpx.Timeout(value, connect=value, read=value, write=value, pool=value)

    def _selected_token(self, bearer_token: str | None) -> str | None:
        if self.auth_mode == "service":
            return self.service_token or None
        return bearer_token or None

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        reference: Any,
        *,
        run_id: str,
        root: Path,
        used_names: set[str],
        auth_token: str | None,
    ) -> FetchedFile:
        """按附件引用和 Run 标识向 Java 获取授权，处理代理流或一次性下载地址，返回校验后的文件。"""
        file_id = str(getattr(reference, "file_id", "") or "")
        purpose = str(getattr(reference, "purpose", "input") or "input")
        headers = {"accept": "application/json, application/octet-stream"}
        if auth_token:
            headers["authorization"] = f"Bearer {auth_token}"
        try:
            async with client.stream(
                "POST",
                self.endpoint,
                headers=headers,
                json={"runId": run_id, "fileId": file_id, "purpose": purpose},
            ) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    raise FileBrokerValidationError("File Broker 不允许重定向")
                if response.status_code in {401, 403, 404, 409, 410, 424}:
                    raise FileBrokerError("File Broker 未授权或文件不可用", code="file_access_denied")
                if response.status_code < 200 or response.status_code >= 300:
                    raise FileBrokerError("File Broker 请求失败", code="file_broker_request_failed")
                if _is_json_response(response.headers):
                    self._emit(
                        "file.fetch.transport.selected",
                        {"fileId": file_id, "purpose": purpose, "transferMode": "one_time_url"},
                    )
                    grant = await self._read_grant(response)
                    if grant.file_id != file_id:
                        raise FileBrokerValidationError("File Broker 文件标识不匹配")
                    name = self._unique_name(_safe_filename(grant.name), file_id, used_names)
                    if grant.download_url:
                        if not self.allowed_hosts:
                            raise FileBrokerConfigurationError(
                                "URL 下载模式必须配置 CCSDK_FILE_BROKER_ALLOWED_HOSTS"
                            )
                        url = _validate_download_url(grant.download_url, allowed_hosts=self.allowed_hosts)
                        pinned_url, host_header, sni_hostname = _pinned_download_target(url)
                        async with client.stream(
                            "GET",
                            pinned_url,
                            headers={"accept": "*/*", "host": host_header},
                            extensions={"sni_hostname": sni_hostname},
                        ) as download:
                            return await self._download_response(
                                download,
                                file_id=file_id,
                                purpose=purpose,
                                name=name,
                                mime_type=grant.mime_type,
                                expected_size=grant.expected_size,
                                expected_sha256=grant.expected_sha256,
                                root=root,
                                transfer_mode="one_time_url",
                            )
                    raise FileBrokerValidationError("File Broker 授权响应缺少下载地址")

                self._emit(
                    "file.fetch.transport.selected",
                    {"fileId": file_id, "purpose": purpose, "transferMode": "proxy_stream"},
                )
                response_file_id = response.headers.get("x-file-id")
                if response_file_id != file_id:
                    raise FileBrokerValidationError("File Broker 文件标识不匹配")
                name = _safe_filename(
                    response.headers.get("x-file-name")
                    or _filename_from_content_disposition(response.headers.get("content-disposition")),
                )
                name = self._unique_name(name, file_id, used_names)
                mime_type = _safe_mime(response.headers.get("x-file-mime-type"))
                expected_size = _validate_expected_size(_header_int(response.headers, "x-file-size"), self.max_bytes)
                expected_sha256 = _safe_sha256(response.headers.get("x-file-sha256"))
                if expected_size is None or expected_sha256 is None:
                    raise FileBrokerValidationError("File Broker 代理流缺少完整性元数据")
                return await self._download_response(
                    response,
                    file_id=file_id,
                    purpose=purpose,
                    name=name,
                    mime_type=mime_type,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    root=root,
                    transfer_mode="proxy_stream",
                )
        except FileBrokerError:
            raise
        except httpx.TimeoutException as error:
            raise FileBrokerTimeoutError() from error

    async def _read_grant(self, response: httpx.Response) -> _Grant:
        """读取 Java 授权响应，校验文件元数据、下载地址及时效，返回内部授权对象。"""
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_GRANT_BYTES:
                raise FileBrokerValidationError("File Broker 授权响应过大")
        try:
            value = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FileBrokerValidationError("File Broker 授权响应无效") from error
        if not isinstance(value, Mapping):
            raise FileBrokerValidationError("File Broker 授权响应无效")
        file_id = value.get("fileId")
        if not isinstance(file_id, str) or not file_id.strip():
            raise FileBrokerValidationError("File Broker 响应缺少 fileId")
        name = _safe_filename(value.get("name"))
        mime_type = _safe_mime(value.get("mimeType"))
        expected_size = _validate_expected_size(value.get("size"), self.max_bytes)
        expected_sha256 = _safe_sha256(value.get("sha256"))
        if expected_size is None or expected_sha256 is None:
            raise FileBrokerValidationError("File Broker 授权响应缺少完整性元数据")
        download_url = value.get("downloadUrl")
        if download_url is not None and not isinstance(download_url, str):
            raise FileBrokerValidationError("File Broker 下载地址无效")
        expires_at = value.get("expiresAt")
        if expires_at is not None:
            if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
                raise FileBrokerValidationError("File Broker 授权过期时间无效")
            expiry_ms = float(expires_at)
            if not math.isfinite(expiry_ms) or expiry_ms <= 0:
                raise FileBrokerValidationError("File Broker 授权过期时间无效")
            if expiry_ms < 10_000_000_000:
                expiry_ms *= 1000
            now_ms = time.time() * 1000
            if expiry_ms <= now_ms:
                raise FileBrokerError("File Broker 授权已过期", code="file_access_expired")
            if expiry_ms - now_ms > MAX_GRANT_TTL_MS:
                raise FileBrokerValidationError("File Broker 临时地址有效期过长")
        one_time = value.get("oneTime") is True
        if download_url:
            if expires_at is None:
                raise FileBrokerValidationError("临时下载地址缺少 expiresAt")
            if not one_time:
                raise FileBrokerValidationError("临时下载地址必须是一次性的")
        if not download_url:
            raise FileBrokerValidationError("File Broker 授权响应缺少下载地址")
        return _Grant(
            file_id=file_id,
            name=name,
            mime_type=mime_type,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
            download_url=download_url,
            expires_at=(
                int(expiry_ms)
                if expires_at is not None
                else None
            ),
            one_time=one_time,
        )

    async def _download_response(
        self,
        response: httpx.Response,
        *,
        file_id: str,
        purpose: str,
        name: str,
        mime_type: str,
        expected_size: int | None,
        expected_sha256: str | None,
        root: Path,
        transfer_mode: str,
    ) -> FetchedFile:
        """接收下载响应及预期元数据，流式写入目标目录并校验大小和摘要，返回 FetchedFile。"""
        if response.status_code in {301, 302, 303, 307, 308}:
            raise FileBrokerValidationError("文件下载不允许重定向")
        if response.status_code < 200 or response.status_code >= 300:
            raise FileBrokerError("文件下载失败", code="file_download_failed")
        actual_mime = _content_type(response.headers)
        if actual_mime and actual_mime not in {"application/octet-stream", mime_type}:
            raise FileBrokerValidationError("文件 MIME 类型与授权不匹配")
        content_length = _header_int(response.headers, "content-length")
        if content_length is not None and content_length > self.max_bytes:
            raise FileBrokerValidationError("文件超过大小限制")
        if expected_size is not None and content_length is not None and expected_size != content_length:
            raise FileBrokerValidationError("文件大小与授权不匹配")

        target = (root / name).resolve()
        try:
            target.relative_to(root)
        except ValueError as error:
            raise FileBrokerValidationError("文件路径越界") from error
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        digest = hashlib.sha256()
        total = 0
        progress_at = time.monotonic()
        await self._progress("downloading_file", fileId=file_id,
                             receivedBytes=0, totalBytes=expected_size)
        try:
            with temporary.open("xb") as stream:
                async for chunk in response.aiter_bytes(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self.max_bytes or (expected_size is not None and total > expected_size):
                        raise FileBrokerValidationError("文件超过大小限制")
                    stream.write(chunk)
                    digest.update(chunk)
                    now = time.monotonic()
                    if now - progress_at >= 0.5:
                        await self._progress("downloading_file", fileId=file_id,
                                             receivedBytes=total, totalBytes=expected_size)
                        progress_at = now
                    # Bounded writes and a scheduling point keep cancellation responsive
                    # even when the HTTP transport already has buffered data.
                    await asyncio.sleep(0)
                await self._progress("downloading_file", fileId=file_id,
                                     receivedBytes=total, totalBytes=expected_size)
                await self._progress("validating_file", fileId=file_id,
                                     receivedBytes=total, totalBytes=expected_size)
                stream.flush()
                os.fsync(stream.fileno())
            actual_sha256 = digest.hexdigest()
            if expected_size is not None and total != expected_size:
                raise FileBrokerValidationError("文件大小与授权不匹配")
            if expected_sha256 is not None and actual_sha256 != expected_sha256:
                raise FileBrokerValidationError("文件摘要与授权不匹配")
            os.replace(temporary, target)
            return FetchedFile(
                file_id,
                purpose,
                name,
                mime_type,
                total,
                actual_sha256,
                target,
                transfer_mode,
            )
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup_error:
                LOGGER.warning(
                    "File Broker partial-file cleanup failed: %s",
                    type(cleanup_error).__name__,
                )
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
        return {
            "fileId": str(getattr(reference, "file_id", "") or ""),
            "purpose": str(getattr(reference, "purpose", "input") or "input"),
        }

    @staticmethod
    def _failure_data(reference: Any, code: str, duration_ms: int) -> dict[str, Any]:
        return {**FileBroker._start_data(reference), "errorCode": code, "durationMs": duration_ms}

    def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        if self.event_sink is not None:
            try:
                self.event_sink(event_type, data)
            except Exception as error:
                # Event sink. A broken sink must not
                # turn a valid file fetch into a failed user Run.
                LOGGER.warning("File Broker event sink failed: %s", type(error).__name__)

    async def _progress(self, name: str, **fields: Any) -> None:
        if self.progress_sink is not None:
            await self.progress_sink({"name": name, **fields})

    @staticmethod
    def _remove_files(files: list[FetchedFile]) -> None:
        for item in files:
            try:
                item.path.unlink(missing_ok=True)
            except OSError as error:
                LOGGER.warning("File Broker fetched-file cleanup failed: %s", type(error).__name__)


__all__ = [
    "DEFAULT_MAX_FILE_BYTES",
    "FileBroker",
    "FileBrokerConfigurationError",
    "FileBrokerError",
    "FileBrokerTimeoutError",
    "FileBrokerUnavailableError",
    "FileBrokerValidationError",
    "FetchedFile",
]
