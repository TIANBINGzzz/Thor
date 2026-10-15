"""身份绑定、并发领取及跨能力的 Runtime/Actor 集成回归。"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import httpx

import server
from runtime.auth import encode_hs256_jwt
from runtime.run_store import RunStore
from runtime.session_actor import SessionManager
from tests.test_session_actor import FakeClientWorker, complete_script


class WorkspaceBindingTests(unittest.TestCase):
    def test_binding_is_immutable_persistent_and_scoped_by_all_identity_parts(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'runs.sqlite3'
            with RunStore(db) as store:
                first = store.get_or_create_workspace('t', 'u', 'session', 's')
                self.assertRegex(first, r'^[0-9a-f]{32}$')
                self.assertEqual(first, store.get_or_create_workspace('t', 'u', 'session', 's',
                                                                     workspace_id=uuid.uuid4().hex))
                others = [store.get_or_create_workspace(*scope) for scope in (
                    ('other', 'u', 'session', 's'), ('t', 'other', 'session', 's'),
                    ('t', 'u', 'session', 'other'), ('t', 'u', 'run', 's'))]
                self.assertEqual(len(set([first, *others])), 5)
                with self.assertRaises(sqlite3.IntegrityError):
                    store.get_or_create_workspace('t', 'other', 'session', 'new', workspace_id=first)
            with RunStore(db) as store:
                self.assertEqual(first, store.get_or_create_workspace('t', 'u', 'session', 's'))

    def test_concurrent_first_claims_across_connections_return_one_workspace(self):
        with tempfile.TemporaryDirectory() as folder:
            db = Path(folder) / 'runs.sqlite3'
            with RunStore(db):
                pass

            def claim(_):
                with RunStore(db) as store:
                    return store.get_or_create_workspace('t', 'u', 'session', 'same')

            with ThreadPoolExecutor(max_workers=6) as executor:
                workspaces = list(executor.map(claim, range(18)))
            self.assertEqual(len(set(workspaces)), 1)

    def test_invalid_identity_or_directory_is_rejected(self):
        with RunStore(':memory:') as store:
            for scope in (('', 'u', 'session', 's'), ('t', None, 'session', 's'),
                          ('t', 'u', 'invalid', 's'), ('t', 'u', 'run', ' ')):
                with self.subTest(scope=scope), self.assertRaises(ValueError):
                    store.get_or_create_workspace(*scope)
            for directory in ('../outside', '/absolute', '', 'not-hex'):
                with self.subTest(directory=directory), self.assertRaises(ValueError):
                    store.get_or_create_workspace('t', 'u', 'session', 's', workspace_id=directory)

    def test_server_uses_random_binding_and_preserves_existing_work_files(self):
        with tempfile.TemporaryDirectory() as folder, RunStore(':memory:') as store:
            root = Path(folder)
            old_key = json.dumps(['t', 'u', 'session', 'old'], separators=(',', ':'))
            digest = hashlib.sha256(old_key.encode()).hexdigest()[:32]
            legacy = root / digest
            legacy.mkdir()
            (legacy / 'draft.txt').write_text('keep', encoding='utf-8')
            with patch.multiple(server, RUN_STORE=store, CLIENT_SESSION_ROOT=root):
                self.assertEqual(server._client_session_directory(old_key), legacy)
                self.assertEqual((legacy / 'draft.txt').read_text(), 'keep')
                new_key = json.dumps(['t', 'u', 'session', 'new'])
                created = server._client_session_directory(new_key)
                self.assertNotEqual(created.name, hashlib.sha256(new_key.encode()).hexdigest()[:32])
                self.assertEqual(created, server._client_session_directory(new_key))


class WorkspaceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_artifact_resolves_persisted_workspace_after_reopen(self):
        from runtime.artifact_delivery import ArtifactDelivery
        from tools.artifacts import publish_artifact

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = json.dumps(['t', 'u', 'session', 'same'])
            with RunStore(root / 'runs.sqlite3') as store, patch.multiple(
                    server, RUN_STORE=store, CLIENT_SESSION_ROOT=root / 'sessions'):
                workspace = server._client_session_directory(key)
                work = workspace / '.work'
                work.mkdir()
                (work / 'draft.txt').write_bytes(b'hello')
                artifact = publish_artifact('draft.txt', 'draft.txt', work,
                                            workspace / '.deliverables', workspace)
                store.create_run('artifact-run', {'sessionKey': key}, tenant_id='t',
                                 user_id='u', business_session_id='same')

            events, requests = [], []

            async def notify(event):
                events.append(event)

            def upload(request):
                requests.append(request)
                return httpx.Response(200, json={'state': 200, 'success': True, 'data': {
                    'id': 'fixture-file', 'fileName': 'draft.txt', 'fileSize': 5,
                    'fileSuffix': 'txt', 'url': 'private-object'}})

            with RunStore(root / 'runs.sqlite3') as store:
                delivery = ArtifactDelivery(store, root / 'archive', notify,
                    env={}, transport=httpx.MockTransport(upload))
                with patch.multiple(server, RUN_STORE=store, CLIENT_SESSION_ROOT=root / 'sessions',
                                    ARTIFACT_DELIVERY=delivery, RUN_TIMINGS={}), \
                     patch('runtime.nacos_config.fetch_config', return_value={'fileService': {
                         'baseUrl': 'https://files.example.test', 'domainName': 'routing.example.test',
                         'remoteUrl': 'https://public.example.test'}}):
                    try:
                        await server._handle_agent_event('artifact-run', {
                            'type': 'artifact.published', 'artifactId': artifact['artifactId']})
                        await delivery.wait('artifact-run')
                        self.assertEqual(len(requests), 1)
                        self.assertIn(b'hello', requests[0].content)
                        self.assertEqual(events[-1]['type'], 'artifact.ready')
                        self.assertEqual(delivery.list('artifact-run')[0]['fileId'], 'fixture-file')
                        self.assertEqual(delivery.path('artifact-run', artifact['artifactId']).read_bytes(), b'hello')
                        self.assertIsNone(delivery.path('other-run', artifact['artifactId']))
                    finally:
                        await delivery.close()

    async def test_http_capability_switch_token_refresh_and_restart_keep_workspace_and_history(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RunStore(root / 'runs.sqlite3')
            workers = []

            def factory(**_):
                worker = FakeClientWorker([complete_script('sdk-history')] * 10, worker_id=len(workers))
                workers.append(worker)
                return worker

            def manager():
                return SessionManager(worker_factory=factory, on_public_event=server._handle_client_public_event)

            current_manager = manager()
            settings = dict(RUN_STORE=store, PROJECT_ROOT=root, CLIENT_SESSION_ROOT=root / 'sessions',
                DEFAULT_MODEL='test', RUNTIME_JWT_SECRET='workspace-test', SESSION_MANAGER=current_manager,
                internal_tasks={}, internal_subscribers={}, pending_terminals={}, RUN_TIMINGS={}, TRACE_SECRETS={})
            # 此处验证会话生命周期；部署配置使用固定数据，禁止依赖真实外部服务。
            with patch.multiple(server, **settings), \
                 patch('runtime.nacos_config.fetch_config', return_value={'campusMcp': {
                     'url': 'https://campus.example.test/string_campus_brain_service/mcp',
                     'domainName': 'campus.example.test'}}), \
                 patch.object(httpx.Client, 'send', side_effect=AssertionError('unexpected external HTTP request')):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://runtime') as client:
                    async def execute(index, capability='conversation', tenant='t', user='u', token='token-a'):
                        run_id = f'run-{index}'
                        body = {'protocol': 'agent-run/v1', 'runId': run_id, 'messageId': f'message-{index}',
                            'businessSessionId': 'same', 'capabilityRef': capability,
                            'input': {'text': 'test'}, 'credentials': {'platformBearer': token}}
                        claims = {'iss': server.RUNTIME_JWT_ISSUER, 'aud': server.RUNTIME_JWT_AUDIENCE,
                            'iat': int(time.time()), 'exp': int(time.time()) + 120, 'jti': uuid.uuid4().hex,
                            'tenant': tenant, 'sub': user, 'scope': 'run.execute',
                            **{k: body[k] for k in ('runId', 'messageId', 'businessSessionId', 'capabilityRef')}}
                        headers = {'Authorization': 'Bearer ' + encode_hs256_jwt(claims, 'workspace-test')}
                        response = await client.post('/internal/v1/runs', json=body, headers=headers)
                        self.assertEqual(response.status_code, 202, response.text)
                        self.assertNotIn(str(root), response.text)
                        await asyncio.wait_for(server.internal_tasks[run_id], 5)
                        run = server.RUN_STORE.get_run(run_id)
                        self.assertEqual(run['status'], 'succeeded', run)
                        self.assertEqual(run['runtimeSessionRef'], 'sdk-history')
                        self.assertNotIn(token, json.dumps(server.RUN_STORE.events_after(run_id, 0)))
                        return Path(workers[-1].start_payload['session_directory'])

                    try:
                        original = await execute(0)
                        self.assertEqual(original, await execute('same-config'))
                        self.assertEqual(len(workers), 1)
                        for index, capability in enumerate(('chart-generation', 'image-generation', 'document-writing',
                                                           'national-excellence-data-qa', 'campus-brain-query', 'conversation'), 1):
                            self.assertEqual(original, await execute(index, capability, token=f'token-{index}'))
                            self.assertEqual(workers[-1].sent[-1]['credentials']['platformBearer'], f'token-{index}')
                            self.assertEqual(workers[-1].sent[-1]['capability_ref'], capability)
                        self.assertNotEqual(original, await execute('tenant', tenant='other'))
                        self.assertIsNone(workers[-1].start_payload['resume'])
                        self.assertNotEqual(original, await execute('user', user='other'))
                        self.assertIsNone(workers[-1].start_payload['resume'])
                        await current_manager.close_all()
                        store.close()
                        store = RunStore(root / 'runs.sqlite3')
                        server.RUN_STORE = store
                        current_manager = manager()
                        server.SESSION_MANAGER = current_manager
                        self.assertEqual(original, await execute('restarted'))
                        self.assertEqual(workers[-1].start_payload['resume'], 'sdk-history')
                    finally:
                        await current_manager.close_all()
                        store.close()


if __name__ == '__main__':
    unittest.main()
