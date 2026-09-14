import unittest
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
if __name__ == "__main__": unittest.main()
