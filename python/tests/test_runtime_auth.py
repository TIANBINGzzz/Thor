import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from runtime import auth
from runtime.protocol import AgentRunRequest
from runtime.run_store import RunStore


class RuntimeAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.request = AgentRunRequest.from_dict({
            'protocol': 'agent-run/v1', 'runId': 'auth-run', 'messageId': 'auth-message',
            'businessSessionId': 'auth-session', 'capabilityRef': 'conversation',
            'input': {'text': 'hello'},
        })
        self.store = RunStore(':memory:')
        self.addCleanup(self.store.close)
        self.run = self.store.create_run(
            'auth-run', request=self.request, tenant_id='tenant', user_id='user',
            capability_ref='conversation', status='succeeded',
        )
        for target, name, value in (
            (auth, '_DEFAULT_REPLAY_CACHE', auth.ReplayCache()),
            (server, 'RUN_STORE', self.store),
            (server, 'RUNTIME_JWT_SECRET', 'test-auth-secret'),
            (server, 'RUNTIME_JWT_ISSUER', 'test-java'),
            (server, 'RUNTIME_JWT_AUDIENCE', 'ccsdk-runtime'),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def headers(self, scope):
        now = time.time()
        token = auth.encode_hs256_jwt({
            'iss': 'test-java', 'aud': 'ccsdk-runtime', 'iat': now, 'exp': now + 60,
            'jti': uuid.uuid4().hex, 'sub': 'user', 'tenant': 'tenant', 'scope': scope,
            'runId': 'auth-run', 'capabilityRef': 'conversation',
            'businessSessionId': 'auth-session', 'messageId': 'auth-message',
        }, 'test-auth-secret')
        return {'authorization': 'Bearer ' + token}

    def test_scope_denial_preserves_jti_for_authorized_creation(self):
        request = SimpleNamespace(headers=self.headers('run.execute'))
        with self.assertRaises(server._InternalAuthError):
            server._authorize_internal(request, self.run, allowed_scopes={'run.read'}, consume_jti=True)
        claims, _ = server._authorize_new_request(request, self.request)
        self.assertEqual(claims['runId'], 'auth-run')
        with self.assertRaisesRegex(server._InternalAuthError, 'already been used'):
            server._authorize_new_request(request, self.request)

    def test_identity_denial_preserves_jti_for_the_authorized_run(self):
        for identity in ({'tenantId': 'other-tenant'}, {'userId': 'other-user'}):
            with self.subTest(identity=identity):
                request = SimpleNamespace(headers=self.headers('run.execute'))
                with self.assertRaises(server._InternalAuthError):
                    server._authorize_internal(request, {**self.run, **identity},
                                               allowed_scopes={'run.execute'}, consume_jti=True)
                claims = server._authorize_internal(request, self.run,
                                                     allowed_scopes={'run.execute'}, consume_jti=True)
                self.assertEqual((claims['tenant'], claims['sub']), ('tenant', 'user'))
                with self.assertRaisesRegex(server._InternalAuthError, 'already been used'):
                    server._authorize_internal(request, self.run,
                                               allowed_scopes={'run.execute'}, consume_jti=True)

    def test_invalid_control_option_preserves_jti_for_interrupt(self):
        headers = self.headers('run.execute')
        route = '/internal/v1/runs/auth-run/control'
        self.assertEqual(self.client.post(route, headers=headers, json={'option': 'invalid'}).status_code, 400)
        self.assertEqual(self.client.post(route, headers=headers, json={'option': 'interrupt'}).status_code, 200)
        self.assertEqual(self.client.post(route, headers=headers, json={'option': 'interrupt'}).status_code, 401)

    def test_reads_and_cancellation_can_reuse_a_consumed_creation_grant(self):
        headers = self.headers('run.execute')
        server._authorize_new_request(SimpleNamespace(headers=headers), self.request)
        for _ in range(2):
            self.assertEqual(self.client.get('/internal/v1/runs/auth-run', headers=headers).status_code, 200)
            self.assertEqual(self.client.post('/internal/v1/runs/auth-run/cancel', headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/internal/v1/runs/auth-run/control', headers=headers,
                                          json={'option': 'interrupt'}).status_code, 401)


if __name__ == '__main__':
    unittest.main()
