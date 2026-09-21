"""会话执行索引的HTTP授权、稳定分页与公开字段契约。"""

import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from runtime.auth import encode_hs256_jwt
from runtime.run_store import RunStore


class SessionRunTests(unittest.TestCase):
    path = '/internal/v1/sessions/session-a/runs'

    def setUp(self):
        self.store = RunStore(':memory:')
        self.addCleanup(self.store.close)
        for name, value in {'RUN_STORE': self.store, 'RUNTIME_JWT_SECRET': 'session-test-secret'}.items():
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)

    def headers(self, **overrides):
        claims = {'iss': server.RUNTIME_JWT_ISSUER, 'aud': server.RUNTIME_JWT_AUDIENCE,
                  'iat': int(time.time()), 'exp': int(time.time()) + 60, 'jti': 'read-pages',
                  'tenant': 'tenant-a', 'sub': 'user-a', 'businessSessionId': 'session-a',
                  'scope': 'session.read'}
        claims.update(overrides)
        return {'Authorization': 'Bearer ' + encode_hs256_jwt(claims, 'session-test-secret')}

    def seed(self, run_id, *, timestamp=100, tenant='tenant-a', user='user-a', session='session-a', capability='conversation'):
        with patch('runtime.run_store._now_ms', return_value=timestamp):
            return self.store.create_run(run_id, tenant_id=tenant, user_id=user,
                business_session_id=session, capability_ref=capability,
                runtime_session_ref='private-sdk-session',
                metadata={'messageId': 'message-a', 'sessionKey': 'private-key'})

    def test_pages_are_stable_across_ties_inserts_status_updates_and_retries(self):
        for run_id in ('run-a', 'run-b', 'run-c'):
            self.seed(run_id)
        self.seed('run-d', timestamp=200, capability='document-writing')
        self.seed('run-d', timestamp=300, capability='document-writing')  # 幂等重试不是新Run。
        headers = self.headers()
        first = self.client.get(self.path, headers=headers, params={'limit': 2})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual([r['runId'] for r in first.json()['runs']], ['run-d', 'run-c'])
        cursor = first.json()['nextCursor']
        self.seed('run-new', timestamp=400)
        self.store.update_status('run-b', 'succeeded')
        second = self.client.get(self.path, headers=headers, params={'limit': 2, 'cursor': cursor})
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual([r['runId'] for r in second.json()['runs']], ['run-b', 'run-a'])
        self.assertEqual(second.json()['runs'][0]['status'], 'succeeded')
        self.assertIsNone(second.json()['nextCursor'])
        self.assertEqual(first.headers['cache-control'], 'no-store')
        for item in first.json()['runs']:
            self.assertEqual(set(item), {'runId', 'messageId', 'capabilityRef', 'status', 'createdAt', 'updatedAt'})
        self.assertNotIn('private-', first.text)

    def test_scope_is_always_filtered_by_tenant_user_and_session(self):
        self.seed('run-own')
        self.seed('run-tenant', tenant='tenant-b')
        self.seed('run-user', user='user-b')
        self.seed('run-session', session='session-b')
        self.seed('run-stateless', session=None)
        result = self.client.get(self.path, headers=self.headers()).json()
        self.assertEqual([r['runId'] for r in result['runs']], ['run-own'])
        self.assertEqual(self.client.get(self.path, headers=self.headers(sub='absent')).json(),
                         {'runs': [], 'nextCursor': None})
        self.assertEqual(self.client.get('/internal/v1/sessions/empty/runs',
                         headers=self.headers(businessSessionId='empty')).json(), {'runs': [], 'nextCursor': None})

    def test_run_tokens_and_invalid_session_claims_are_rejected(self):
        self.seed('run-own')
        self.assertEqual(self.client.get(self.path).status_code, 401)
        invalid = [{'scope': 'run.read', 'runId': 'run-own', 'capabilityRef': 'conversation'},
                   {'scope': 'run.execute'}, {'businessSessionId': 'session-b'},
                   {'businessSessionId': None}, {'tenant': ''}, {'sub': None}, {'jti': None},
                   {'iss': 'wrong'}, {'aud': 'wrong'}, {'iat': 1, 'exp': 2}]
        for claims in invalid:
            with self.subTest(claims=claims):
                self.assertEqual(self.client.get(self.path, headers=self.headers(**claims)).status_code, 401)
        headers = self.headers()
        token = headers['Authorization'].split(' ')[1]
        header, claims, signature = token.split('.')
        headers['Authorization'] = 'Bearer ' + '.'.join((header, claims, ('A' if signature[0] != 'A' else 'B') + signature[1:]))
        self.assertEqual(self.client.get(self.path, headers=headers).status_code, 401)
        with patch.object(server, 'RUNTIME_JWT_SECRET', ''):
            self.assertEqual(self.client.get(self.path, headers=self.headers()).status_code, 503)

    def test_session_read_token_does_not_grant_run_control_or_run_read(self):
        self.seed('run-own')
        self.assertEqual(self.client.get('/internal/v1/runs/run-own', headers=self.headers()).status_code, 401)
        self.assertEqual(self.client.post('/internal/v1/runs/run-own/cancel', headers=self.headers()).status_code, 401)

    def test_cursor_validation_and_page_size_limits(self):
        self.seed('run-own')
        self.seed('run-foreign', user='user-b')
        for cursor in ('', 'not-a-cursor', 'v1.A', 'v1.__8',
                       self.store._session_cursor('missing'), self.store._session_cursor('run-foreign')):
            with self.subTest(cursor=cursor):
                response = self.client.get(self.path, headers=self.headers(), params={'cursor': cursor})
                self.assertEqual(response.status_code, 400, response.text)
        for limit in (0, -1, 101, 'abc'):
            self.assertEqual(self.client.get(self.path, headers=self.headers(), params={'limit': limit}).status_code, 422)
        self.assertEqual(self.client.get(self.path, headers=self.headers(), params={'cursor': 'a' * 346}).status_code, 422)

    def test_cursor_survives_store_restart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'runs.sqlite3'
            with RunStore(path) as store:
                for run_id in ('a', 'b', 'c'):
                    with patch('runtime.run_store._now_ms', return_value=100):
                        store.create_run(run_id, tenant_id='t', user_id='u', business_session_id='s')
                first, cursor = store.list_runs_by_session('t', 'u', 's', limit=1)
                self.assertEqual(first[0]['runId'], 'c')
            with RunStore(path) as store:
                rest, cursor = store.list_runs_by_session('t', 'u', 's', cursor=cursor)
                self.assertEqual([r['runId'] for r in rest], ['b', 'a'])
                self.assertIsNone(cursor)

    def test_latest_provider_session_survives_restart_and_respects_identity(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.sqlite3'
            with RunStore(path) as store:
                for run, tenant, user, session, ref in (
                    ('first', 't', 'u', 's', 'sdk-first'),
                    ('second', 't', 'u', 's', 'sdk-second'),
                    ('foreign-tenant', 'other', 'u', 's', 'wrong'),
                    ('foreign-user', 't', 'other', 's', 'wrong'),
                    ('foreign-session', 't', 'u', 'other', 'wrong'),
                    ('queued', 't', 'u', 's', None),
                ):
                    with patch('runtime.run_store._now_ms', return_value=100):
                        store.create_run(run, tenant_id=tenant, user_id=user,
                                         business_session_id=session, runtime_session_ref=ref)
                store.update_status('first', 'succeeded')
            with RunStore(path) as store:
                self.assertEqual(store.latest_runtime_session('t', 'u', 's'), 'sdk-second')
                self.assertIsNone(store.latest_runtime_session('t', 'u', 'unknown'))
