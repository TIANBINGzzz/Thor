import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import server
from runtime.auth import encode_hs256_jwt
from runtime.protocol import AgentRunRequest
from runtime.run_store import RunStore


class RuntimeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.store = RunStore(":memory:")
        self.addCleanup(self.store.close)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.body = {
            "protocol": "agent-run/v1", "runId": "run-test", "messageId": "msg-test",
            "businessSessionId": "session-test", "capabilityRef": "conversation",
            "input": {"text": "hello"},
            "credentials": {"platformBearer": "business-token"},
        }
        for name, value in {
            "RUN_STORE": self.store, "RUNTIME_JWT_SECRET": "test-runtime-secret",
            "SESSION_MANAGER": None, "internal_tasks": {}, "internal_subscribers": {},
            "PROJECT_ROOT": Path(self.temp.name),
        }.items():
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server.app, base_url=f"http://localhost:{server.PORT}")
        self.addCleanup(self.client.close)

    def headers(self, scope="run.read", **overrides):
        claims = {
            "iss": server.RUNTIME_JWT_ISSUER, "aud": server.RUNTIME_JWT_AUDIENCE,
            "iat": int(time.time()), "exp": int(time.time()) + 60, "jti": uuid.uuid4().hex,
            "sub": "user-test", "tenant": "tenant-test", "runId": "run-test",
            "capabilityRef": "conversation", "businessSessionId": "session-test",
            "messageId": "msg-test", "scope": scope,
        }
        claims.update(overrides)
        return {"Authorization": "Bearer " + encode_hs256_jwt(claims, "test-runtime-secret")}

    def seed(self, status="running"):
        self.store.create_run(
            "run-test", request=AgentRunRequest.from_dict(self.body), status=status,
            tenant_id="tenant-test", user_id="user-test",
            runtime_session_ref="provider-private", metadata={"messageId": "msg-test", "private": "internal-value"},
        )

    def test_catalog_is_public_and_does_not_grant_run_access(self):
        for secret in ("test-runtime-secret", ""):
            with self.subTest(secret_configured=bool(secret)), patch.object(server, "RUNTIME_JWT_SECRET", secret):
                response = self.client.get("/internal/v1/capabilities")
                self.assertEqual(response.status_code, 200, response.text)
                items = response.json()["capabilities"]
                self.assertEqual({item["capabilityRef"] for item in items}, set(server.CAPABILITIES))
                for item in items:
                    self.assertEqual(set(item), {"capabilityRef", "name", "description", "supportsAttachments"})
        self.assertEqual(self.client.post("/internal/v1/runs", json=self.body).status_code, 401)
        self.seed()
        self.assertEqual(self.client.get("/internal/v1/runs/run-test").status_code, 401)
        self.assertEqual(self.client.post("/internal/v1/runs/run-test/cancel").status_code, 401)

    def test_omitted_capability_binds_only_to_conversation_jwt(self):
        body={k:v for k,v in self.body.items() if k!='capabilityRef'}
        with patch.object(server, '_execute_internal_run', new_callable=AsyncMock):
            self.assertEqual(self.client.post('/internal/v1/runs',json=body,
                headers=self.headers('run.execute',capabilityRef='document-writing')).status_code,401)
            self.assert_public_run(self.client.post('/internal/v1/runs',json=body,
                headers=self.headers('run.execute')),202)

    def test_same_business_session_routes_capabilities_to_isolated_clients(self):
        claims={'tenant':'tenant-test','sub':'user-test'}
        keys=[]
        for capability in (None,'document-writing','national-excellence-data-qa'):
            request=AgentRunRequest.from_dict({**self.body,'capabilityRef':capability})
            keys.append(server._client_session_key(request,claims))
        self.assertEqual(len(set(keys)),3)

    def test_trusted_data_identity_does_not_enter_model_prompt(self):
        with patch.object(server, 'MODELS', ['test-model']):
            payload=server._internal_worker_payload(AgentRunRequest.from_dict(self.body),Path(self.temp.name),
                claims={'tenant':'trusted-secret-tenant','sub':'trusted-secret-user'})
        self.assertEqual(payload['_data_identity']['tenant_id'],'trusted-secret-tenant')
        self.assertNotIn('trusted-secret-tenant',payload['prompt'])
        self.assertNotIn('trusted-secret-user',payload['prompt'])

    def test_payload_reaches_query_and_client_prompt_and_binds_retry(self):
        body = {**self.body, "payload": {"reportTitle": "Annual report", "year": 2026,
                                       "sections": [{"name": "Budget", "amount": 120}]}}
        request = AgentRunRequest.from_dict(body)
        with patch.object(server, "MODELS", ["test-model"]):
            for mode in ("query", "client"):
                result = server._internal_worker_payload(request, Path(self.temp.name) / mode, runtime_mode=mode)
                self.assertIn(json.dumps(body["payload"], ensure_ascii=False), result["prompt"])
                self.assertEqual(result["model"], "test-model")
                self.assertIsNone(result["workflow_name"])
        with patch.object(server, "_execute_internal_run", new_callable=AsyncMock):
            self.assert_public_run(self.client.post("/internal/v1/runs", json=body,
                                                   headers=self.headers("run.execute")), 202)
            response = self.client.post("/internal/v1/runs", json={**body, "payload": {"year": 2027}},
                                        headers=self.headers("run.execute"))
            self.assertEqual(response.status_code, 409, response.text)

    def assert_public_run(self, response, status_code=200):
        self.assertEqual(response.status_code, status_code, response.text)
        run = response.json()["run"]
        self.assertEqual(set(run) - {"error"}, {"runId", "status", "lastSequence"})
        self.assertEqual(run["runId"], "run-test")
        return run

    def test_create_retry_and_query_hide_internal_record(self):
        with patch.object(server, "_execute_internal_run", new_callable=AsyncMock):
            created = self.client.post("/internal/v1/runs", json=self.body, headers=self.headers("run.execute"))
            self.assert_public_run(created, 202)
            self.assertEqual(created.json()["eventsUrl"], "/internal/v1/runs/run-test/events")
            retried = self.client.post("/internal/v1/runs", json=self.body, headers=self.headers("run.execute"))
            self.assert_public_run(retried)
        stored = self.store.get_run("run-test")
        self.assertEqual(stored["tenantId"], "tenant-test")
        self.assertEqual(stored["userId"], "user-test")
        self.assertEqual(stored["metadata"]["messageId"], "msg-test")
        self.assertNotIn("business-token", json.dumps(stored))
        self.store.update_status("run-test", "failed", error="timeout")
        result = self.assert_public_run(self.client.get("/internal/v1/runs/run-test", headers=self.headers()))
        self.assertEqual(result["error"], "timeout")

    def test_identity_still_checked_on_all_existing_run_routes(self):
        self.seed()
        for identity in ({"sub": "other-user"}, {"tenant": "other-tenant"}):
            for method, suffix, scope in (
                ("GET", "", "run.read"), ("GET", "/events", "run.read"),
                ("GET", "/artifacts", "run.read"), ("POST", "/control", "run.control"),
                ("POST", "/cancel", "run.cancel"),
            ):
                with self.subTest(identity=identity, suffix=suffix):
                    response = self.client.request(method, "/internal/v1/runs/run-test" + suffix,
                                                   headers=self.headers(scope, **identity), json={"option": "cancel"})
                    self.assertEqual(response.status_code, 401, response.text)

    def test_business_token_cannot_replace_runtime_header(self):
        response = self.client.post("/internal/v1/runs", json=self.body)
        self.assertEqual(response.status_code, 401)
        response = self.client.post("/internal/v1/runs", json=self.body,
                                    headers={"Authorization": "Bearer business-token"})
        self.assertEqual(response.status_code, 401)
        self.assertIsNone(self.store.get_run("run-test"))

    def test_jwt_identity_required_and_retry_cannot_change_owner(self):
        for identity in ({"sub": None}, {"tenant": None}):
            response = self.client.post("/internal/v1/runs", json=self.body,
                                        headers=self.headers("run.execute", **identity))
            self.assertEqual(response.status_code, 401, response.text)
        self.assertIsNone(self.store.get_run("run-test"))
        with patch.object(server, "_execute_internal_run", new_callable=AsyncMock):
            self.assert_public_run(self.client.post("/internal/v1/runs", json=self.body,
                                                   headers=self.headers("run.execute")), 202)
            for identity in ({"sub": "other-user"}, {"tenant": "other-tenant"}):
                response = self.client.post("/internal/v1/runs", json=self.body,
                                            headers=self.headers("run.execute", **identity))
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.store.get_run("run-test")["userId"], "user-test")

    def test_control_requires_explicit_option_field(self):
        self.seed()
        for body in ({"op": "cancel"}, {}, {"option": "pause"}, {"option": "cancel", "op": "cancel"}, {"option": 1}):
            with self.subTest(body=body):
                response = self.client.post("/internal/v1/runs/run-test/control", json=body,
                                            headers=self.headers("run.control"))
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.store.get_run("run-test")["status"], "running")

    def test_control_and_cancel_hide_internal_record_in_each_branch(self):
        self.seed()
        for mode in ("no-actor", "actor", "terminal"):
            for suffix, option in (("/control", "interrupt"), ("/control", "cancel"), ("/cancel", "cancel")):
                with self.subTest(mode=mode, suffix=suffix, option=option):
                    self.store.update_status("run-test", "succeeded" if mode == "terminal" else "running")
                    manager = SimpleNamespace(actor_for_run=lambda _: SimpleNamespace(active_run_id="run-test"),
                                              interrupt=AsyncMock(), cancel=AsyncMock()) if mode == "actor" else None
                    with patch.object(server, "SESSION_MANAGER", manager):
                        response = self.client.post("/internal/v1/runs/run-test" + suffix,
                                                    json={"option": option}, headers=self.headers("run.control"))
                    self.assert_public_run(response)

    def test_events_and_artifacts_expose_only_their_own_data(self):
        self.seed("succeeded")
        raw = {"type": "tool_use", "id": "call-1", "name": "tool-1", "sessionId": "provider-private",
               "input": {"secret": "business-token"}, "metadata": {"private": "internal-value"}}
        event = server._public_internal_event("run-test", raw)
        self.store.append_event("run-test", {"protocolVersion": "agent-events/v1", **event})
        events = self.client.get("/internal/v1/runs/run-test/events", headers=self.headers())
        self.assertEqual(events.status_code, 200)
        for private in ("provider-private", "business-token", "internal-value", "tenantId", "userId", "turnId"):
            self.assertNotIn(private, events.text)
        root = Path(self.temp.name) / ".scribe-runs" / "work" / "run-test" / ".deliverables"
        root.mkdir(parents=True)
        (root / "result.txt").write_text("result", encoding="utf-8")
        listing = self.client.get("/internal/v1/runs/run-test/artifacts", headers=self.headers())
        self.assertEqual(listing.json(), {"files": [{"name": "result.txt", "size": 6}]})
        download = self.client.get("/internal/v1/runs/run-test/artifacts?name=result.txt", headers=self.headers())
        self.assertEqual(download.content, b"result")
        self.assertNotIn(str(root), str(download.headers))
