import asyncio
import hashlib
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx

import server
from runtime.file_broker import FileBroker, FileBrokerTimeoutError, FileBrokerValidationError
from runtime.protocol import AgentRunRequest, AttachmentRef
from runtime.run_store import RunStore
from runtime.session_actor import SessionManager
from runtime.auth import encode_hs256_jwt
from tests.test_session_actor import FakeClientWorker, complete_script


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunk, count, gate=None, started=None):
        self.chunk, self.count, self.gate, self.started = chunk, count, gate, started

    async def __aiter__(self):
        for index in range(self.count):
            yield self.chunk
            if index == 0 and self.started is not None:
                self.started.set()
                await self.gate.wait()


def file_response(chunk, count, *, gate=None, started=None, valid=True):
    digest = hashlib.sha256()
    for _ in range(count):
        digest.update(chunk)
    return httpx.Response(200, headers={
        "content-type": "application/octet-stream", "x-file-id": "file-1",
        "x-file-name": "template.docx", "x-file-mime-type": "application/octet-stream",
        "x-file-size": str(len(chunk) * count),
        "x-file-sha256": digest.hexdigest() if valid else "0" * 64,
    }, stream=Chunks(chunk, count, gate, started))


class FilePreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_progress_arrives_before_download_finishes(self):
        chunk = b"x" * 262144
        gate, reported = asyncio.Event(), asyncio.Event()
        events = []

        class SlowStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield chunk
                await asyncio.sleep(0.55)
                yield chunk
                await gate.wait()
                yield chunk

        async def progress(event):
            events.append(event)
            if event["name"] == "downloading_file" and event["receivedBytes"] == len(chunk) * 2:
                reported.set()

        response = file_response(chunk, 3)
        response.stream = SlowStream()
        with tempfile.TemporaryDirectory() as folder:
            broker = FileBroker("https://java.test/files", progress_sink=progress,
                                transport=httpx.MockTransport(lambda _: response))
            task = asyncio.create_task(broker.fetch_all([AttachmentRef("file-1")], run_id="r",
                                       tenant_id="t", user_id="u", workspace=folder, bearer_token="jwt"))
            try:
                await asyncio.wait_for(reported.wait(), 2)
                self.assertFalse(task.done())
                self.assertEqual(events[-1]["totalBytes"], len(chunk) * 3)
                gate.set()
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_large_stream_progress_and_atomic_visibility(self):
        chunk = b"x" * (1024 * 1024)
        events = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            async def progress(event):
                events.append(event)
                if event["name"] in {"downloading_file", "validating_file"}:
                    self.assertFalse((root / "template.docx").exists())

            broker = FileBroker("https://java.test/files", progress_sink=progress,
                                transport=httpx.MockTransport(lambda _: file_response(chunk, 104)))
            files = await broker.fetch_all([AttachmentRef("file-1")], run_id="run-1",
                tenant_id="t", user_id="u", workspace=root, bearer_token="jwt")
            self.assertEqual(files[0].path.stat().st_size, 104 * 1024 * 1024)
            self.assertTrue(any(e["name"] == "downloading_file" and e["receivedBytes"] > 0 for e in events))
            self.assertEqual(events[-2]["name"], "validating_file")
            self.assertEqual(events[-1]["name"], "file_ready")
            self.assertEqual(events[-1]["receivedBytes"], 104 * 1024 * 1024)
            self.assertFalse(list(root.glob("*.part")))

    async def test_cancel_timeout_and_invalid_digest_remove_partial_files(self):
        for outcome in ("cancel", "timeout", "invalid"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as folder:
                gate, started = asyncio.Event(), asyncio.Event()
                broker = FileBroker("https://java.test/files", transport=httpx.MockTransport(
                    lambda _: file_response(b"x" * 262144, 2, gate=gate,
                                            started=started if outcome != "invalid" else None,
                                            valid=outcome != "invalid")))
                task = asyncio.create_task(broker.fetch_all([AttachmentRef("file-1")],
                    run_id="r", tenant_id="t", user_id="u", workspace=folder,
                    bearer_token="jwt", timeout_ms=30 if outcome == "timeout" else 1000))
                if outcome == "cancel":
                    await started.wait()
                    task.cancel()
                expected = {"cancel": asyncio.CancelledError, "timeout": FileBrokerTimeoutError,
                            "invalid": FileBrokerValidationError}[outcome]
                with self.assertRaises(expected):
                    await task
                self.assertEqual(list(Path(folder).iterdir()), [])

    async def test_run_waits_for_files_then_queries_with_fresh_budget_and_replays_progress(self):
        for mode in ("query", "client"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                store = RunStore(":memory:")
                request = AgentRunRequest.from_dict({"protocol": "agent-run/v1", "runId": "run-1",
                    "messageId": "msg-1", "capabilityRef": "conversation", "businessSessionId": "session-1",
                    "input": {"text": "read", "attachmentRefs": [{"fileId": "file-1"}]}})
                store.create_run("run-1", request=request, tenant_id="t", user_id="u")
                gate, started = asyncio.Event(), asyncio.Event()
                sdk_calls = []

                def assert_ready(payload):
                    self.assertIn("template.docx", payload["prompt"])
                    self.assertTrue(list(root.rglob("template.docx")))
                    self.assertEqual(payload["timeout_ms"], 500)
                    sdk_calls.append(payload)

                async def query(payload):
                    assert_ready(payload)
                    yield {"type": "result", "ok": True}

                class Worker(FakeClientWorker):
                    async def send(worker, message):
                        if message["type"] == "client_query":
                            assert_ready(message)
                        await super().send(message)

                manager = SessionManager(worker_factory=lambda **_: Worker([complete_script()], worker_id=0))
                def broker(**kwargs):
                    return FileBroker("https://java.test/files", **kwargs, transport=httpx.MockTransport(
                        lambda _: file_response(b"x" * 262144, 2, gate=gate, started=started)))

                with patch.multiple(server, RUN_STORE=store, PROJECT_ROOT=root, CLIENT_SESSION_ROOT=root / "sessions",
                                    MODELS=["test"], SESSION_MANAGER=manager, RUN_EXECUTION_TIMEOUT_MS=500,
                                    FILE_PREPARE_TIMEOUT_MS=3000, internal_tasks={}, internal_subscribers={}), \
                     patch.object(server, "_runtime_mode_for_request", return_value=mode), \
                     patch.object(server, "FileBroker", side_effect=broker), patch.object(server, "stream_agent", query):
                    task = asyncio.create_task(server._execute_internal_run(request, {"tenant": "t", "sub": "u"}, runtime_bearer="jwt"))
                    await asyncio.wait_for(started.wait(), 1)
                    # Preparation must outlast the SDK budget, with enough scheduling headroom on CI.
                    await asyncio.sleep(0.7)
                    self.assertFalse(task.done())
                    self.assertEqual(sdk_calls, [])
                    gate.set()
                    await asyncio.wait_for(task, 2)
                    self.assertEqual(store.get_run("run-1")["status"], "succeeded", store.get_run("run-1"))
                    events = store.events_after("run-1", 0)
                    phases = [e["payload"]["name"] for e in events if e["type"] == "phase"]
                    self.assertLess(phases.index("files_ready"), phases.index("model_starting"))
                    cursor = next(e["sequence"] for e in events if e.get("payload", {}).get("name") == "downloading_file")
                    self.assertTrue(all(e["sequence"] > cursor for e in store.events_after("run-1", cursor)))
                    serialized = json.dumps(events)
                    self.assertNotIn("jwt", serialized)
                    self.assertNotIn("java.test", serialized)
                    self.assertNotIn(str(root), serialized)
                    self.assertFalse(list(root.rglob("template.docx")))
                    await manager.close_all()
                store.close()

    async def test_preparation_failure_or_no_attachments(self):
        for attachments in ([], [{"fileId": "file-1"}]):
            with tempfile.TemporaryDirectory() as folder:
                store = RunStore(":memory:")
                request = AgentRunRequest.from_dict({"protocol": "agent-run/v1", "runId": "run-1",
                    "messageId": "msg-1", "capabilityRef": "conversation",
                    "input": {"text": "hello", "attachmentRefs": attachments}})
                store.create_run("run-1", request=request, tenant_id="t", user_id="u")
                calls = []
                async def query(payload):
                    calls.append(payload)
                    yield {"type": "result", "ok": True}
                with patch.multiple(server, RUN_STORE=store, PROJECT_ROOT=Path(folder), MODELS=["test"],
                                    internal_tasks={}, internal_subscribers={}), \
                     patch.object(server, "_runtime_mode_for_request", return_value="query"), \
                     patch.object(server, "FileBroker", side_effect=FileBrokerValidationError("bad")) as broker, \
                     patch.object(server, "stream_agent", query):
                    await server._execute_internal_run(request, {"tenant": "t", "sub": "u"}, runtime_bearer="jwt")
                    self.assertEqual(len(calls), 0 if attachments else 1)
                    if not attachments:
                        broker.assert_not_called()
                    self.assertEqual(store.get_run("run-1")["status"], "failed" if attachments else "succeeded")
                store.close()

    async def test_http_accepts_then_cancels_preparation_and_replays_sse(self):
        for mode in ("query", "client"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                store = RunStore(":memory:")
                root = Path(folder)
                gate, started = asyncio.Event(), asyncio.Event()
                workers = []
                def worker_factory(**kwargs):
                    workers.append(True)
                    return FakeClientWorker([complete_script()], worker_id=0)
                manager = SessionManager(worker_factory=worker_factory)
                def broker(**kwargs):
                    return FileBroker("https://java.test/files", **kwargs, transport=httpx.MockTransport(
                        lambda _: file_response(b"x" * 262144, 2, gate=gate, started=started)))
                def headers(scope):
                    claims = {"iss": server.RUNTIME_JWT_ISSUER, "aud": server.RUNTIME_JWT_AUDIENCE,
                              "iat": int(time.time()), "exp": int(time.time()) + 60, "jti": uuid.uuid4().hex,
                              "sub": "u", "tenant": "t", "runId": "run-1", "messageId": "msg-1",
                              "capabilityRef": "conversation", "scope": scope}
                    return {"Authorization": "Bearer " + encode_hs256_jwt(claims, "test-secret")}
                body = {"protocol": "agent-run/v1", "runId": "run-1", "messageId": "msg-1",
                        "capabilityRef": "conversation", "input": {"text": "read",
                        "attachmentRefs": [{"fileId": "file-1"}]}}
                with patch.multiple(server, RUN_STORE=store, PROJECT_ROOT=root, CLIENT_SESSION_ROOT=root / "sessions",
                                    MODELS=["test"], SESSION_MANAGER=manager, RUNTIME_JWT_SECRET="test-secret",
                                    internal_tasks={}, internal_subscribers={}), \
                     patch.object(server, "_runtime_mode_for_request", return_value=mode), \
                     patch.object(server, "FileBroker", side_effect=broker), \
                     patch.object(server, "stream_agent", side_effect=AssertionError("SDK must not start")):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://runtime") as client:
                        response = await client.post("/internal/v1/runs", json=body, headers=headers("run.execute"))
                        self.assertEqual(response.status_code, 202)
                        await asyncio.wait_for(started.wait(), 1)
                        task = server.internal_tasks["run-1"]
                        self.assertFalse(task.done())
                        response = await client.post("/internal/v1/runs/run-1/control", json={"option": "cancel"}, headers=headers("run.cancel"))
                        self.assertEqual(response.status_code, 200, response.text)
                        await asyncio.gather(task, return_exceptions=True)
                        self.assertEqual(store.get_run("run-1")["status"], "cancelled")
                        response = await client.get("/internal/v1/runs/run-1/events", headers=headers("run.read"))
                        self.assertIn("downloading_file", response.text)
                        self.assertIn("run.cancelled", response.text)
                        self.assertNotIn("model_starting", response.text)
                        self.assertEqual(workers, [])
                        self.assertFalse(list(root.rglob("*.part")))
                        await manager.close_all()
                store.close()
