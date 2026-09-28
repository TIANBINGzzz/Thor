import asyncio
import hashlib
import json
import socket
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.file_broker import (
    FileBroker,
    FileBrokerConfigurationError,
    FileBrokerError,
    FileBrokerUnavailableError,
    FileBrokerValidationError,
)
from runtime.protocol import AttachmentRef


class FileBrokerTests(unittest.TestCase):
    def test_explicit_broker_address_overrides_platform_download(self):
        with patch.dict('os.environ', {'CCSDK_FILE_BROKER_URL': 'https://override.test/broker'}):
            self.assertEqual(FileBroker().endpoint, 'https://override.test/broker')
            self.assertEqual(FileBroker('https://explicit.test/broker').endpoint, 'https://explicit.test/broker')

    def test_missing_file_service_config_keeps_broker_unconfigured(self):
        with patch.dict('os.environ', {'CCSDK_NACOS_URL': ''}, clear=True):
            self.assertFalse(FileBroker().configured)

    def ref(self, file_id="file-1", purpose="input"):
        return AttachmentRef(file_id=file_id, purpose=purpose)

    @staticmethod
    def public_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    def test_fetches_one_time_url_without_forwarding_run_bearer(self):
        content = b"%PDF-authorized"
        events = []
        requests = []

        def handler(request):
            requests.append(request)
            if request.method == "POST":
                self.assertEqual(request.headers["authorization"], "Bearer run-jwt")
                self.assertEqual(json.loads(request.content), {
                    "runId": "run-1",
                    "fileId": "file-1",
                    "purpose": "input",
                })
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "downloadUrl": "https://files.example.test/one-time/file-1",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(request.url.host, "93.184.216.34")
            self.assertEqual(request.headers["host"], "files.example.test")
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf", "content-length": str(len(content))},
                content=content,
            )

        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/internal/v1/file-access/grant",
                service_token="unused-because-run-token-wins",
                allowed_hosts={"files.example.test"},
                transport=httpx.MockTransport(handler),
                event_sink=lambda event_type, data: events.append((event_type, data)),
            )
            files = await broker.fetch_all(
                (self.ref(),),
                run_id="run-1",
                tenant_id="tenant-1",
                user_id="user-1",
                workspace=root,
                bearer_token="run-jwt",
            )
            return files

        with tempfile.TemporaryDirectory() as directory, patch(
            "runtime.file_broker.socket.getaddrinfo", side_effect=self.public_dns,
        ):
            files = asyncio.run(exercise(Path(directory)))
            self.assertEqual(files[0].safe_name, "report.pdf")
            self.assertEqual(files[0].path.read_bytes(), content)
            self.assertFalse(any("downloadUrl" in str(data) for _, data in events))
            self.assertEqual([event_type for event_type, _ in events], [
                "file.fetch.started", "file.fetch.transport.selected", "file.fetch.succeeded",
            ])
            self.assertEqual(events[1][1]["transferMode"], "one_time_url")
            self.assertEqual(events[2][1]["transferMode"], "one_time_url")
            self.assertEqual(len(requests), 2)

    def test_accepts_java_proxied_file_stream(self):
        content = b"spreadsheet"
        events = []

        def handler(request):
            self.assertEqual(request.method, "POST")
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/octet-stream",
                    "x-file-id": "file-1",
                    "x-file-name": "data.csv",
                    "x-file-mime-type": "text/csv",
                    "x-file-size": str(len(content)),
                    "x-file-sha256": hashlib.sha256(content).hexdigest(),
                },
                content=content,
            )

        async def exercise(root):
            return await FileBroker(
                "https://java.example.test/internal/v1/file-access/grant",
                service_token="broker-token",
                allowed_hosts={"files.example.test"},
                auth_mode="service",
                transport=httpx.MockTransport(handler),
                event_sink=lambda event_type, data: events.append((event_type, data)),
            ).fetch_all(
                (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
            )

        with tempfile.TemporaryDirectory() as directory:
            files = asyncio.run(exercise(Path(directory)))
            self.assertEqual(files[0].safe_name, "data.csv")
            self.assertEqual(files[0].mime_type, "text/csv")
            self.assertEqual(files[0].path.read_bytes(), content)
            self.assertEqual(files[0].transfer_mode, "proxy_stream")
            self.assertEqual(events[1][1]["transferMode"], "proxy_stream")

    def test_file_id_mismatch_fails_closed_and_cleanup(self):
        content = b"not-authorized"

        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "fileId": "other-file",
                    "name": "secret.txt",
                    "mimeType": "text/plain",
                    "size": len(content),
                    "sha256": "0" * 64,
                    "downloadUrl": "https://files.example.test/one-time/file-1",
                    "expiresAt": int((time.time() + 60) * 1000),
                    "oneTime": True,
                },
            )

        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="broker-token",
                allowed_hosts={"files.example.test"},
                auth_mode="service",
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(FileBrokerValidationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_digest_mismatch_removes_partial_output(self):
        content = b"authorized bytes"

        def handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.txt",
                        "mimeType": "text/plain",
                        "size": len(content),
                        "sha256": "0" * 64,
                        "downloadUrl": "https://files.example.test/one-time/file-1",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=content)

        async def exercise(root):
            with self.assertRaises(FileBrokerValidationError):
                await FileBroker(
                    "https://java.example.test/grant",
                    service_token="broker-token",
                    allowed_hosts={"files.example.test"},
                    auth_mode="service",
                    transport=httpx.MockTransport(handler),
                ).fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory, patch(
            "runtime.file_broker.socket.getaddrinfo", side_effect=self.public_dns,
        ):
            asyncio.run(exercise(Path(directory)))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_rejects_private_download_host(self):
        events = []

        def redirect_handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "downloadUrl": "https://127.0.0.1/secret",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            raise AssertionError("private host must be rejected before download")

        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="broker-token",
                allowed_hosts={"127.0.0.1"},
                auth_mode="service",
                transport=httpx.MockTransport(redirect_handler),
                event_sink=lambda event_type, data: events.append((event_type, data)),
            )
            with self.assertRaises(FileBrokerValidationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))
        self.assertEqual(events[-1][0], "file.fetch.failed")
        self.assertEqual(events[-1][1]["errorCode"], "file_validation_failed")

    def test_rejects_redirect_and_mime_mismatch(self):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "size": 4,
                        "sha256": hashlib.sha256(b"slow").hexdigest(),
                        "downloadUrl": "https://files.example.test/one-time/file-1",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            return httpx.Response(302, headers={"location": "https://files.example.test/next"})

        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="broker-token",
                allowed_hosts={"files.example.test"},
                auth_mode="service",
                transport=httpx.MockTransport(handler),
            )
            with self.assertRaises(FileBrokerValidationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory, patch(
            "runtime.file_broker.socket.getaddrinfo", side_effect=self.public_dns,
        ):
            asyncio.run(exercise(Path(directory)))

        def mime_handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "size": 4,
                        "sha256": hashlib.sha256(b"slow").hexdigest(),
                        "downloadUrl": "https://files.example.test/one-time/file-1",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")

        async def mime_exercise(root):
            with self.assertRaises(FileBrokerValidationError):
                await FileBroker(
                    "https://java.example.test/grant",
                    service_token="broker-token",
                    allowed_hosts={"files.example.test"},
                    auth_mode="service",
                    transport=httpx.MockTransport(mime_handler),
                ).fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory, patch(
            "runtime.file_broker.socket.getaddrinfo", side_effect=self.public_dns,
        ):
            asyncio.run(mime_exercise(Path(directory)))

    def test_enforces_total_fetch_timeout_and_size_limit(self):
        def slow_handler(request):
            if request.method == "POST":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/json"},
                    json={
                        "fileId": "file-1",
                        "name": "report.pdf",
                        "mimeType": "application/pdf",
                        "size": 4,
                        "sha256": hashlib.sha256(b"slow").hexdigest(),
                        "downloadUrl": "https://files.example.test/one-time/file-1",
                        "expiresAt": int((time.time() + 60) * 1000),
                        "oneTime": True,
                    },
                )
            raise httpx.ReadTimeout("slow", request=request)

        async def slow_exercise(root):
            with self.assertRaises(FileBrokerError) as caught:
                await FileBroker(
                    "https://java.example.test/grant",
                    service_token="broker-token",
                    allowed_hosts={"files.example.test"},
                    auth_mode="service",
                    transport=httpx.MockTransport(slow_handler),
                    timeout_ms=100,
                ).fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )
            self.assertEqual(caught.exception.code, "file_broker_timeout")

        with tempfile.TemporaryDirectory() as directory, patch(
            "runtime.file_broker.socket.getaddrinfo", side_effect=self.public_dns,
        ):
            asyncio.run(slow_exercise(Path(directory)))

        def oversized_handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/octet-stream",
                    "x-file-id": "file-1",
                    "x-file-name": "large.bin",
                    "x-file-size": "4",
                },
                content=b"1234",
            )

        async def oversized_exercise(root):
            with self.assertRaises(FileBrokerValidationError):
                await FileBroker(
                    "https://java.example.test/grant",
                    service_token="broker-token",
                    allowed_hosts={"files.example.test"},
                    max_bytes=3,
                    auth_mode="service",
                    transport=httpx.MockTransport(oversized_handler),
                ).fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(oversized_exercise(Path(directory)))

    def test_missing_broker_is_a_stable_failure(self):
        events = []

        async def exercise(root):
            broker = FileBroker(
                endpoint="",
                service_token="broker-token",
                auth_mode="service",
                event_sink=lambda event_type, data: events.append((event_type, data)),
            )
            with self.assertRaises(FileBrokerUnavailableError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))
        self.assertEqual(events[-1][1]["errorCode"], "file_broker_unavailable")
        self.assertNotIn("path", str(events))
        self.assertNotIn("token", str(events).lower())

    def test_run_jwt_mode_never_falls_back_to_service_token(self):
        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="service-token",
                auth_mode="run_jwt",
                transport=httpx.MockTransport(lambda _request: self.fail("请求不应发出")),
            )
            with self.assertRaises(FileBrokerUnavailableError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))

    def test_service_mode_uses_only_service_token(self):
        seen = []

        def handler(request):
            seen.append(request.headers.get("authorization"))
            content = b"ok"
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/octet-stream",
                    "x-file-id": "file-1",
                    "x-file-name": "data.txt",
                    "x-file-mime-type": "text/plain",
                    "x-file-size": str(len(content)),
                    "x-file-sha256": hashlib.sha256(content).hexdigest(),
                },
                content=content,
            )

        async def exercise(root):
            return await FileBroker(
                "https://java.example.test/grant",
                service_token="service-token",
                auth_mode="service",
                transport=httpx.MockTransport(handler),
            ).fetch_all(
                (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                bearer_token="run-jwt",
            )

        with tempfile.TemporaryDirectory() as directory:
            files = asyncio.run(exercise(Path(directory)))
            self.assertEqual(files[0].path.read_bytes(), b"ok")
        self.assertEqual(seen, ["Bearer service-token"])

    def test_rejects_invalid_limits_instead_of_using_defaults(self):
        with self.assertRaises(FileBrokerConfigurationError):
            FileBroker("https://java.example.test/grant", service_token="token", max_bytes=0)
        with self.assertRaises(FileBrokerConfigurationError):
            FileBroker("https://java.example.test/grant", service_token="token", timeout_ms=-1)

        async def exercise(root):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="token",
                auth_mode="service",
                transport=httpx.MockTransport(lambda _request: httpx.Response(
                    200,
                    headers={"content-type": "application/octet-stream", "x-file-id": "file-1"},
                    content=b"ok",
                )),
            )
            with self.assertRaises(FileBrokerConfigurationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                    timeout_ms=0,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))

    def test_url_grant_requires_short_one_time_expiry_and_allowlist(self):
        def grant(value):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "fileId": "file-1",
                    "name": "report.txt",
                    "mimeType": "text/plain",
                    "size": 2,
                    "sha256": hashlib.sha256(b"ok").hexdigest(),
                    "downloadUrl": "https://files.example.test/one-time/file-1",
                    **value,
                },
            )

        cases = [
            ({"oneTime": True}, FileBrokerValidationError),
            ({"expiresAt": int((time.time() + 60) * 1000), "oneTime": False}, FileBrokerValidationError),
            ({"expiresAt": int((time.time() - 1) * 1000), "oneTime": True}, FileBrokerError),
            ({"expiresAt": int((time.time() + 360) * 1000), "oneTime": True}, FileBrokerValidationError),
        ]

        for value, expected in cases:
            async def exercise(root, response=grant(value)):
                broker = FileBroker(
                    "https://java.example.test/grant",
                    service_token="token",
                    allowed_hosts={"files.example.test"},
                    auth_mode="service",
                    transport=httpx.MockTransport(lambda _request: response),
                )
                with self.assertRaises(expected):
                    await broker.fetch_all(
                        (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                    )

            with tempfile.TemporaryDirectory() as directory:
                asyncio.run(exercise(Path(directory)))

        async def missing_allowlist(root):
            response = grant({"expiresAt": int((time.time() + 60) * 1000), "oneTime": True})
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="token",
                auth_mode="service",
                transport=httpx.MockTransport(lambda _request: response),
            )
            with self.assertRaises(FileBrokerConfigurationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(missing_allowlist(Path(directory)))

    def test_url_mode_rejects_http_and_mixed_public_private_dns(self):
        def response_for(url):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "fileId": "file-1",
                    "name": "report.txt",
                    "mimeType": "text/plain",
                    "size": 2,
                    "sha256": hashlib.sha256(b"ok").hexdigest(),
                    "downloadUrl": url,
                    "expiresAt": int((time.time() + 60) * 1000),
                    "oneTime": True,
                },
            )

        async def exercise(root, url, dns=None):
            broker = FileBroker(
                "https://java.example.test/grant",
                service_token="token",
                allowed_hosts={"files.example.test"},
                auth_mode="service",
                transport=httpx.MockTransport(lambda _request: response_for(url)),
            )
            patches = (
                patch("runtime.file_broker.socket.getaddrinfo", return_value=dns)
                if dns is not None
                else patch("runtime.file_broker.socket.getaddrinfo", side_effect=AssertionError("DNS must not run"))
            )
            with patches, self.assertRaises(FileBrokerValidationError):
                await broker.fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asyncio.run(exercise(root, "http://files.example.test/file-1"))
            mixed_dns = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
            ]
            asyncio.run(exercise(root, "https://files.example.test/file-1", mixed_dns))

    def test_interrupted_proxy_stream_removes_partial_file(self):
        content = b"partial"

        class InterruptedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield content
                raise httpx.ReadError("interrupted")

            async def aclose(self):
                return None

        def handler(request):
            return httpx.Response(
                200,
                headers={
                    "content-type": "application/octet-stream",
                    "x-file-id": "file-1",
                    "x-file-name": "data.bin",
                    "x-file-mime-type": "application/octet-stream",
                    "x-file-size": str(len(content) + 1),
                    "x-file-sha256": "0" * 64,
                },
                stream=InterruptedStream(),
            )

        async def exercise(root):
            with self.assertRaises(FileBrokerError):
                await FileBroker(
                    "https://java.example.test/grant",
                    service_token="token",
                    auth_mode="service",
                    transport=httpx.MockTransport(handler),
                ).fetch_all(
                    (self.ref(),), run_id="run-1", tenant_id="tenant-1", user_id="user-1", workspace=root,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            asyncio.run(exercise(root))
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
