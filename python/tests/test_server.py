import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from local import sessions as store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_root = store.SESSION_ROOT
        store.SESSION_ROOT = Path(self.temp.name) / ".scribe-sessions"
        store.reset_session_cache()
        server.active_runs.clear()
        server.TOKEN = "test-token"
        server.MODELS = ["qwen3.7-flash", "qwen3.7-plus"]
        self.client = TestClient(server.app, base_url="http://localhost:4310", headers={"x-scribe-token": "test-token"})

    def tearDown(self):
        self.client.close()
        server.active_runs.clear()
        store.reset_session_cache()
        store.SESSION_ROOT = self.original_root
        self.temp.cleanup()

    def test_health_does_not_require_token(self):
        response = self.client.get("/health", headers={"x-scribe-token": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

    def test_models_and_session_contract(self):
        self.assertEqual(self.client.get("/api/models").json()["models"], server.MODELS)
        created = self.client.post("/api/sessions", json={"modelId": "qwen3.7-plus"})
        self.assertEqual(created.status_code, 201)
        session_id = created.json()["session"]["id"]
        loaded = self.client.get(f"/api/sessions/{session_id}")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["session"]["modelId"], "qwen3.7-plus")

    def test_upload_and_download(self):
        session_id = self.client.post("/api/sessions", json={}).json()["session"]["id"]
        uploaded = self.client.post(
            f"/api/sessions/{session_id}/files",
            files={"files": ("中文资料.txt", "内容".encode(), "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        file = uploaded.json()["file"]
        self.assertEqual(file["name"], "中文资料.txt")
        downloaded = self.client.get(file["url"])
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.content, "内容".encode())

    def test_authentication_and_model_validation(self):
        unauthorized = self.client.get("/api/models", headers={"x-scribe-token": "wrong"})
        self.assertEqual(unauthorized.status_code, 403)
        invalid = self.client.post("/api/sessions", json={"modelId": "unknown"})
        self.assertEqual(invalid.status_code, 400)

    def test_chat_stream_persists_worker_events(self):
        session_id = self.client.post("/api/sessions", json={}).json()["session"]["id"]

        async def fake_stream(payload):
            self.assertEqual(payload["model"], "qwen3.7-flash")
            self.assertEqual(payload["workflow_name"], "database-qa")
            yield {"type": "init", "sessionId": "runtime-session"}
            yield {"type": "text", "text": "测试回复", "scope": "main"}
            yield {"type": "result", "sessionId": "runtime-session", "inputTokens": 2, "outputTokens": 3}

        with patch("server.stream_agent", fake_stream):
            response = self.client.post(
                f"/api/sessions/{session_id}/chat",
                json={"prompt": "测试请求", "modelId": "qwen3.7-flash", "workflow_name": "database-qa"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('"type": "done"', response.text)
        saved = self.client.get(f"/api/sessions/{session_id}").json()
        self.assertEqual(saved["messages"][-1]["content"], "测试回复")
        self.assertEqual(saved["messages"][-1]["tokens"], 5)
        self.assertEqual(store.load_session(session_id)["agentSessionId"], "runtime-session")


if __name__ == "__main__":
    unittest.main()
