import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.auth import JWTError, ReplayCache, sign_hs256, verify_run_jwt
from runtime.mcp_auth import MCPAuthError, inject_mcp_auth
from runtime.protocol import AgentRunRequest, ProtocolError
from runtime.run_store import RunStore


class RuntimeProtocolTests(unittest.TestCase):
    def request_payload(self):
        return {
            "protocol": "agent-run/v1",
            "requestId": "req-1",
            "runId": "run-1",
            "businessSessionId": "conv-1",
            "turnId": "turn-1",
            "capabilityRef": "writing-docx",
            "execution": {
                "kind": "workflow",
                "workflowRef": {"id": "writing-docx"},
                "skillRefs": [{"id": "writing-documents"}],
            },
            "input": {
                "text": "第一行\n第二行",
                "attachmentRefs": [{"fileId": "file-1", "purpose": "input"}],
            },
            "runtime": {"continuityPolicy": "new_with_summary"},
            "limits": {"timeoutMs": 10_000, "maxTurns": 5},
            "context": {"tenantId": "tenant-1", "userId": "user-1", "locale": "zh-CN"},
        }

    def test_protocol_parses_minimal_request_and_hides_credentials(self):
        payload = self.request_payload()
        payload["credentials"] = {"platformBearer": "secret-token"}
        request = AgentRunRequest.from_dict(payload)
        self.assertEqual(request.run_id, "run-1")
        self.assertEqual(request.execution.workflow_ref.id, "writing-docx")
        self.assertEqual(request.input.text, "第一行\n第二行")
        self.assertNotIn("credentials", request.to_dict())
        self.assertEqual(request.to_internal_dict()["credentials"]["platformBearer"], "secret-token")

    def test_protocol_rejects_unknown_and_path_like_fields(self):
        payload = self.request_payload()
        payload["cwd"] = "C:\\secret"
        with self.assertRaises(ProtocolError):
            AgentRunRequest.from_dict(payload)
        payload = self.request_payload()
        payload.pop("protocol")
        with self.assertRaisesRegex(ProtocolError, "protocol"):
            AgentRunRequest.from_dict(payload)
        payload = self.request_payload()
        payload["runId"] = "../other-run"
        with self.assertRaises(ProtocolError):
            AgentRunRequest.from_dict(payload)

    def test_protocol_requires_workflow_reference_and_matching_capability(self):
        payload = self.request_payload()
        payload["execution"] = {"kind": "workflow"}
        with self.assertRaisesRegex(ProtocolError, "workflowRef"):
            AgentRunRequest.from_dict(payload)
        payload = self.request_payload()
        payload["capabilityRef"] = "other"
        with self.assertRaisesRegex(ProtocolError, "capabilityRef"):
            AgentRunRequest.from_dict(payload)

    def test_protocol_rejects_invalid_limits_and_file_purpose(self):
        payload = self.request_payload()
        payload["limits"] = {"timeoutMs": 0}
        with self.assertRaises(ProtocolError):
            AgentRunRequest.from_dict(payload)
        payload = self.request_payload()
        payload["input"]["attachmentRefs"][0]["purpose"] = "path"
        with self.assertRaises(ProtocolError):
            AgentRunRequest.from_dict(payload)

    def test_protocol_allows_attachment_only_input(self):
        payload = self.request_payload()
        payload["input"] = {
            "text": "",
            "attachmentRefs": [{"fileId": "file-1", "purpose": "input"}],
        }
        request = AgentRunRequest.from_dict(payload)
        self.assertEqual(request.input.text, "")
        self.assertEqual(request.input.file_refs[0].file_id, "file-1")


class RuntimeAuthTests(unittest.TestCase):
    def claims(self, **overrides):
        now = int(time.time())
        result = {
            "aud": "ccsdk-runtime",
            "sub": "user-1",
            "tenant": "tenant-1",
            "runId": "run-1",
            "capabilityRef": "writing-docx",
            "scope": "run.execute",
            "jti": "jti-1",
            "iat": now,
            "exp": now + 120,
        }
        result.update(overrides)
        return result

    def test_verify_hs256_binds_run_and_capability(self):
        token = sign_hs256(self.claims(), "test-secret")
        claims = verify_run_jwt(
            token,
            "test-secret",
            body={"runId": "run-1", "capabilityRef": "writing-docx"},
            replay_cache=ReplayCache(),
        )
        self.assertEqual(claims["sub"], "user-1")

    def test_verify_rejects_tampering_expiry_scope_and_binding(self):
        cache = ReplayCache()
        token = sign_hs256(self.claims(), "test-secret")
        with self.assertRaises(JWTError):
            verify_run_jwt(token, "wrong-secret", replay_cache=cache)
        with self.assertRaises(JWTError):
            verify_run_jwt(token, "test-secret", body={"runId": "other", "capabilityRef": "writing-docx"}, replay_cache=cache)
        with self.assertRaises(JWTError):
            verify_run_jwt(sign_hs256(self.claims(scope="run.cancel"), "test-secret"), "test-secret", replay_cache=cache)
        with self.assertRaises(JWTError):
            verify_run_jwt(sign_hs256(self.claims(exp=int(time.time()) - 1), "test-secret"), "test-secret", replay_cache=cache)
        missing_capability = self.claims()
        missing_capability.pop("capabilityRef")
        with self.assertRaises(JWTError):
            verify_run_jwt(sign_hs256(missing_capability, "test-secret"), "test-secret", replay_cache=cache)

        for field in ("sub", "tenant"):
            missing_identity = self.claims()
            missing_identity.pop(field)
            with self.assertRaisesRegex(JWTError, field):
                verify_run_jwt(sign_hs256(missing_identity, "test-secret"), "test-secret", replay_cache=ReplayCache())

    def test_jti_is_marked_only_after_binding_and_replay_is_rejected(self):
        cache = ReplayCache()
        token = sign_hs256(self.claims(), "test-secret")
        with self.assertRaises(JWTError):
            verify_run_jwt(token, "test-secret", body={"runId": "wrong", "capabilityRef": "writing-docx"}, replay_cache=cache)
        verify_run_jwt(token, "test-secret", body={"runId": "run-1", "capabilityRef": "writing-docx"}, replay_cache=cache)
        with self.assertRaisesRegex(JWTError, "already"):
            verify_run_jwt(token, "test-secret", body={"runId": "run-1", "capabilityRef": "writing-docx"}, replay_cache=cache)


class MCPAuthTests(unittest.TestCase):
    def test_http_injection_copies_server_and_does_not_touch_environment(self):
        server = {"type": "http", "url": "https://mcp.internal", "headers": {"X-Trace": "1"}}
        with patch.dict("os.environ", {}, clear=True):
            result = inject_mcp_auth("business", server, {"platformBearer": "token-1"})
            self.assertNotIn("Authorization", server["headers"])
            self.assertEqual(result["headers"]["Authorization"], "Bearer token-1")
            self.assertNotIn("PLATFORM_BEARER", __import__("os").environ)

    def test_optional_mcp_does_not_require_or_consume_token(self):
        server = {"type": "stdio", "command": "node", "env": {"A": "B"}}
        result = inject_mcp_auth("db", server)
        self.assertEqual(result, server)

    def test_required_mcp_missing_token_and_unregistered_mcp_fail(self):
        with self.assertRaises(MCPAuthError):
            inject_mcp_auth("business", {"type": "http"})
        with self.assertRaises(MCPAuthError):
            inject_mcp_auth("unknown", {"type": "http"}, {"platformBearer": "token"})

    def test_stdio_injection_uses_rule_env_without_mutation(self):
        from runtime import mcp_auth

        server = {"type": "stdio", "command": "node", "env": {"A": "B"}}
        with patch.dict(mcp_auth.MCP_AUTH_RULES, {"internal": {"required": True, "transport": "stdio", "env": "BUSINESS_TOKEN"}}):
            result = inject_mcp_auth("internal", server, {"platformBearer": "token-1"})
        self.assertEqual(result["env"]["BUSINESS_TOKEN"], "token-1")
        self.assertNotIn("BUSINESS_TOKEN", server["env"])


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self.temp.name) / "runs.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_create_is_idempotent_and_metadata_is_redacted(self):
        first = self.store.create_run("run-1", {"label": "test", "platformBearer": "do-not-save"})
        second = self.store.create_run("run-1", {"label": "changed"}, status="running")
        self.assertEqual(first["createdAt"], second["createdAt"])
        self.assertEqual(second["status"], "queued")
        self.assertNotIn("platformBearer", second["metadata"])

    def test_idempotency_hash_ignores_transient_credentials(self):
        from runtime.protocol import AgentRunRequest

        first_request = AgentRunRequest.from_dict({
            "protocol": "agent-run/v1",
            "runId": "run-credential-refresh",
            "input": {"text": "same request"},
            "credentials": {"platformBearer": "token-one"},
        })
        second_request = AgentRunRequest.from_dict({
            "protocol": "agent-run/v1",
            "runId": "run-credential-refresh",
            "input": {"text": "same request"},
            "credentials": {"platformBearer": "token-two"},
        })
        self.store.create_run("run-credential-refresh", request=first_request)
        replay = self.store.create_run("run-credential-refresh", request=second_request)
        self.assertEqual(replay["runId"], "run-credential-refresh")

    def test_idempotent_create_rejects_different_owner(self):
        self.store.create_run("run-1", tenant_id="tenant-1", user_id="user-1")
        with self.assertRaises(PermissionError):
            self.store.create_run("run-1", tenant_id="tenant-2", user_id="user-1")
        with self.assertRaises(PermissionError):
            self.store.create_run("run-1")

    def test_event_sequence_replay_and_event_id_idempotency(self):
        self.store.create_run("run-1")
        event = self.store.append_event("run-1", {"type": "activity", "eventId": "evt-1", "payload": {"token": "secret", "phase": "tool"}})
        duplicate = self.store.append_event("run-1", {"type": "activity", "eventId": "evt-1", "payload": {"phase": "other"}})
        self.assertEqual(event["sequence"], 1)
        self.assertEqual(duplicate["sequence"], 1)
        self.store.append_event("run-1", {"type": "completed", "eventId": "evt-2"})
        replayed = self.store.events_after("run-1", after_sequence=1)
        self.assertEqual([item["sequence"] for item in replayed], [2])
        self.assertNotIn("token", replayed[0])

    def test_status_and_delete(self):
        self.store.create_run("run-1")
        updated = self.store.update_status("run-1", "failed", error="boom")
        self.assertEqual(updated["status"], "failed")
        self.assertEqual(updated["error"], "boom")
        self.assertTrue(self.store.delete_run("run-1"))
        self.assertIsNone(self.store.get_run("run-1"))


if __name__ == "__main__":
    unittest.main()
