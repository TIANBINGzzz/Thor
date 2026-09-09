import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import server
from runtime.protocol import AgentRunRequest


class RuntimeBoundaryTests(unittest.TestCase):
    def test_payload_file_id_does_not_authorize_fetch(self):
        request = AgentRunRequest.from_dict({
            "protocol": "agent-run/v1", "runId": "run-file", "messageId": "msg-file",
            "capabilityRef": "conversation", "input": {}, "payload": {"fileId": "file-id"},
        })
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "FileBroker") as broker:
            result = asyncio.run(server._fetch_run_files(request, {"tenant": "t", "sub": "u"},
                                 Path(folder), "runtime-jwt", time.monotonic() + 5))
            self.assertEqual(result, ())
            broker.assert_not_called()

    def test_only_runtime_and_health_routes_are_exposed(self):
        paths = {route.path for route in server.app.routes}
        self.assertTrue(all(path == "/health" or path.startswith("/internal/v1/") for path in paths), paths)
        with TestClient(server.app, base_url="http://runtime.internal:4310") as client:
            self.assertEqual(client.get("/health").status_code, 200)
            for path in ("/api/sessions", "/api/capabilities", "/api/models", "/api/files/test"):
                self.assertEqual(client.get(path).status_code, 404)
            response = client.post("/internal/v1/runs", headers={"Origin": "http://browser.example"})
            self.assertEqual(response.status_code, 403)
            response = client.post("/internal/v1/runs", json={
                "protocol": "agent-run/v1", "runId": "run-auth", "messageId": "msg-auth",
                "businessSessionId": "session-auth", "capabilityRef": "conversation", "input": {"text": "hello"}})
            self.assertIn(response.status_code, (401, 503))

    def test_local_identity_uses_the_same_file_broker(self):
        request = AgentRunRequest.from_dict({
            "protocol": "agent-run/v1", "runId": "run-file", "messageId": "msg-file",
            "businessSessionId": "session-file", "capabilityRef": "conversation",
            "input": {"text": "read", "attachmentRefs": [{"fileId": "file-id", "purpose": "input"}]},
        })
        with tempfile.TemporaryDirectory() as folder, patch.object(server, "FileBroker") as broker:
            broker.return_value.fetch_all = AsyncMock(return_value=())
            asyncio.run(server._fetch_run_files(request, {"tenant": "local-tenant", "sub": "local-user"},
                Path(folder), "runtime-jwt", time.monotonic() + 5))
            kwargs = broker.return_value.fetch_all.call_args.kwargs
            self.assertEqual(kwargs["bearer_token"], "runtime-jwt")
            self.assertEqual(kwargs["tenant_id"], "local-tenant")
            broker.return_value.fetch_all.assert_awaited_once()
