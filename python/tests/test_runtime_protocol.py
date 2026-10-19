import unittest
from runtime.auth import JWTError, ReplayCache, encode_hs256_jwt, verify_run_jwt
from runtime.protocol import AgentRunRequest, ProtocolError

class RuntimeProtocolTests(unittest.TestCase):
    def payload(self):
        return {"protocol":"agent-run/v1","runId":"run-1","messageId":"msg-1","capabilityRef":"document-writing","input":{"text":"写文档"}}
    def test_capability_request(self):
        request=AgentRunRequest.from_dict(self.payload())
        self.assertEqual(request.capability_ref,"document-writing")
        self.assertNotIn("credentials",request.to_dict())
    def test_conversation_omits_capability_and_cannot_select_tools(self):
        from runtime.capabilities import resolve_capability
        body=self.payload()
        body.pop('capabilityRef')
        request=AgentRunRequest.from_dict(body)
        self.assertIsNone(request.capability_ref)
        self.assertNotIn('capabilityRef',request.to_dict())
        self.assertEqual(resolve_capability(request.capability_ref).ref,'conversation')
        with self.assertRaises(ProtocolError):
            AgentRunRequest.from_dict({**body,'capabilityRef':''})
    def test_execution_fields_rejected(self):
        payload=self.payload(); payload["workflowRef"]="writing-docx"
        with self.assertRaises(ProtocolError): AgentRunRequest.from_dict(payload)
    def test_body_identity_rejected(self):
        for field, value in (("context", {"tenantId": "t-1", "userId": "u-1"}), ("tenantId", "t-1"), ("userId", "u-1")):
            with self.subTest(field=field):
                payload = self.payload()
                payload[field] = value
                with self.assertRaises(ProtocolError):
                    AgentRunRequest.from_dict(payload)
        self.assertNotIn("context", AgentRunRequest.from_dict(self.payload()).to_dict())
    def test_attachment_only(self):
        payload=self.payload(); payload["input"]={"attachmentRefs":[{"fileId":"f-1"}]}
        self.assertEqual(len(AgentRunRequest.from_dict(payload).input.attachment_refs),1)
    def test_payload_json_validation(self):
        body = self.payload()
        body["input"] = {}
        body["payload"] = {"year": 2026, "sections": ["summary"], "draft": True}
        self.assertEqual(AgentRunRequest.from_dict(body).to_dict()["payload"], body["payload"])
        deep = {}
        for _ in range(18):
            deep = {"nested": deep}
        for value in (None, [], "text", {"x": float("nan")}, {"x": "x" * 65536}, deep,
                      {"nested": {"mcpServers": {}}}, {"credentials": {"platformBearer": "secret"}}):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ProtocolError):
                    AgentRunRequest.from_dict({**body, "payload": value})


class RuntimeJWTTests(unittest.TestCase):
    def token(self, jti, *, expires=140):
        return encode_hs256_jwt({
            'aud': 'ccsdk-runtime', 'iat': 99, 'exp': expires, 'jti': jti,
            'sub': 'user', 'tenant': 'tenant', 'scope': 'run.execute',
            'runId': 'run-1', 'capabilityRef': 'document-writing',
        }, 'test-secret')

    def test_full_replay_cache_preserves_unexpired_grants_until_expiry(self):
        cache = ReplayCache(max_entries=1)
        options = {'run_id': 'run-1', 'capability_ref': 'document-writing', 'replay_cache': cache}
        first = self.token('first', expires=110)
        second = self.token('second')
        verify_run_jwt(first, 'test-secret', now=100, **options)
        with self.assertRaisesRegex(JWTError, 'replay cache is full'):
            verify_run_jwt(second, 'test-secret', now=100, **options)
        with self.assertRaisesRegex(JWTError, 'already been used'):
            verify_run_jwt(first, 'test-secret', now=100, **options)
        self.assertEqual(verify_run_jwt(
            second, 'test-secret', now=100, consume_jti=False, **options)['jti'], 'second')
        self.assertEqual(verify_run_jwt(second, 'test-secret', now=116, **options)['jti'], 'second')
        with self.assertRaisesRegex(JWTError, 'already been used'):
            verify_run_jwt(second, 'test-secret', now=116, **options)

    def test_jwt_binding_requires_capability_instead_of_legacy_workflow(self):
        for workflow in ('document-writing', {'id': 'document-writing'}):
            with self.subTest(workflow=workflow):
                cache = ReplayCache()
                token = self.token('workflow')
                body = {'runId': 'run-1', 'execution': {'workflowRef': workflow}}
                with self.assertRaisesRegex(JWTError, 'capabilityRef mismatch'):
                    verify_run_jwt(token, 'test-secret', body=body, replay_cache=cache, now=100)
                claims = verify_run_jwt(token, 'test-secret', replay_cache=cache, now=100,
                                        body={'runId': 'run-1', 'capabilityRef': 'document-writing'})
                self.assertEqual(claims['capabilityRef'], 'document-writing')


if __name__ == "__main__": unittest.main()
