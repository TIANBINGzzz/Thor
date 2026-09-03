import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from runtime.auth import sign_hs256
from runtime.run_store import RunStore


class InternalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_store = server.RUN_STORE
        self.original_secret = server.RUNTIME_JWT_SECRET
        server.RUN_STORE = RunStore(Path(self.temp.name) / "runs.sqlite3")
        server.RUNTIME_JWT_SECRET = "runtime-secret"
        server.MODELS = ["test-model"]
        server.internal_tasks.clear()
        server.internal_subscribers.clear()
        self.client = TestClient(server.app, base_url="http://localhost:4310")
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        server.internal_tasks.clear()
        server.internal_subscribers.clear()
        server.RUN_STORE.close()
        server.RUN_STORE = self.original_store
        server.RUNTIME_JWT_SECRET = self.original_secret
        self.temp.cleanup()

    def token(self, run_id, *, capability="conversation", scope="run.execute", jti=None):
        now = int(time.time())
        return sign_hs256(
            {
                "aud": "ccsdk-runtime",
                "iss": "string-ai-center-service",
                "sub": "user-1",
                "tenant": "tenant-1",
                "runId": run_id,
                "capabilityRef": capability,
                "businessSessionId": "conversation-1",
                "turnId": "turn-1",
                "scope": scope,
                "jti": jti or f"jti-{run_id}-{scope}",
                "iat": now,
                "exp": now + 120,
            },
            server.RUNTIME_JWT_SECRET,
        )

    def payload(self, run_id="run-1"):
        return {
            "protocol": "agent-run/v1",
            "runId": run_id,
            "businessSessionId": "conversation-1",
            "turnId": "turn-1",
            "input": {"text": "你好"},
            "runtime": {"model": "test-model"},
            "context": {"tenantId": "tenant-1", "userId": "user-1"},
        }

    def auth_headers(self, token):
        return {"Authorization": f"Bearer {token}"}

    def test_create_run_persists_and_replays_sanitized_events(self):
        async def fake_stream(_payload):
            yield {"type": "init", "cwd": "C:\\secret"}
            yield {"type": "thinking", "text": "private reasoning"}
            yield {"type": "tool_use", "name": "private_tool", "input": "secret"}
            yield {"type": "text", "scope": "main", "text": "你好"}
            yield {"type": "result", "ok": True, "sessionId": "provider-session"}

        with patch("server.stream_agent", fake_stream):
            response = self.client.post(
                "/internal/v1/runs",
                json=self.payload(),
                headers=self.auth_headers(self.token("run-1")),
            )
            self.assertEqual(response.status_code, 202, response.text)
            run_id = response.json()["run"]["runId"]
            for _ in range(100):
                state = self.client.get(
                    f"/internal/v1/runs/{run_id}",
                    headers=self.auth_headers(self.token(run_id, scope="run.read", jti="poll-1")),
                )
                if state.json().get("run", {}).get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.01)

        events = self.client.get(
            "/internal/v1/runs/run-1/events?afterSequence=0",
            headers=self.auth_headers(self.token("run-1", scope="run.read", jti="read-1")),
        )
        self.assertEqual(events.status_code, 200, events.text)
        self.assertIn("event: message.delta", events.text)
        self.assertIn('"textDelta": "你好"', events.text)
        self.assertNotIn("private reasoning", events.text)
        self.assertNotIn("private_tool", events.text)
        self.assertNotIn("C:\\\\secret", events.text)
        self.assertEqual(self.client.get("/internal/v1/runs/run-1", headers=self.auth_headers(self.token("run-1", scope="run.read", jti="read-2"))).json()["run"]["status"], "succeeded")

    def test_sse_replay_uses_last_event_id_and_create_is_idempotent(self):
        async def empty_stream(_payload):
            if False:
                yield {}

        with patch("server.stream_agent", empty_stream):
            self.client.post(
                "/internal/v1/runs",
                json=self.payload(),
                headers=self.auth_headers(self.token("run-1", jti="start-1")),
            )
            for _ in range(100):
                if (server.RUN_STORE.get_run("run-1") or {}).get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.01)
        server.RUN_STORE.update_status("run-1", "succeeded")
        server.RUN_STORE.append_event("run-1", {"runId": "run-1", "type": "completed", "eventId": "done-1", "payload": {"status": "succeeded"}})
        duplicate = self.client.post(
            "/internal/v1/runs",
            json=self.payload(),
            headers=self.auth_headers(self.token("run-1", jti="start-2")),
        )
        self.assertEqual(duplicate.status_code, 200)
        response = self.client.get(
            "/internal/v1/runs/run-1/events",
            headers={**self.auth_headers(self.token("run-1", scope="run.read", jti="read-3")), "Last-Event-ID": "0"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: completed", response.text)

    def test_cancel_marks_run_and_requires_cancel_scope(self):
        async def hanging_stream(_payload):
            yield {"type": "init"}
            await asyncio.sleep(10)

        with patch("server.stream_agent", hanging_stream):
            created = self.client.post(
                "/internal/v1/runs",
                json=self.payload("run-cancel"),
                headers=self.auth_headers(self.token("run-cancel", jti="start-cancel")),
            )
            self.assertEqual(created.status_code, 202, created.text)
            forbidden = self.client.post(
                "/internal/v1/runs/run-cancel/cancel",
                headers=self.auth_headers(self.token("run-cancel", scope="run.execute", jti="wrong-scope")),
            )
            self.assertEqual(forbidden.status_code, 401)
            cancelled = self.client.post(
                "/internal/v1/runs/run-cancel/cancel",
                headers=self.auth_headers(self.token("run-cancel", scope="run.cancel", jti="cancel-1")),
            )
            self.assertEqual(cancelled.status_code, 200, cancelled.text)
            self.assertEqual(cancelled.json()["run"]["status"], "cancelled")

    def test_timeout_marks_run_failed_and_publishes_timeout_code(self):
        async def hanging_stream(_payload):
            await asyncio.sleep(10)
            yield {"type": "text", "text": "never"}

        payload = self.payload("run-timeout")
        payload["limits"] = {"timeoutMs": 20}
        with patch("server.stream_agent", hanging_stream):
            created = self.client.post(
                "/internal/v1/runs",
                json=payload,
                headers=self.auth_headers(self.token("run-timeout", jti="start-timeout")),
            )
            self.assertEqual(created.status_code, 202, created.text)
            for _ in range(100):
                state = server.RUN_STORE.get_run("run-timeout")
                if state and state.get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.01)
        self.assertEqual(state["status"], "failed")
        events = server.RUN_STORE.events_after("run-timeout")
        self.assertTrue(any(event.get("payload", {}).get("code") == "timeout" for event in events))


if __name__ == "__main__":
    unittest.main()
