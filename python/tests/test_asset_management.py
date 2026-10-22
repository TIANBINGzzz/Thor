"""管理端可创建组合能力；执行端 JWT 和浏览器输入不能发布执行资产。"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from runtime.auth import encode_hs256_jwt


class AssetManagementTests(unittest.TestCase):
    def setUp(self):
        from runtime.asset_management import create_asset_router
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'capabilities'
        self.root.mkdir()
        app = FastAPI()
        app.include_router(create_asset_router(root=self.root))
        self.client = TestClient(app)
        self.enterContext(patch.dict('os.environ', {
            'CCSDK_ASSET_JWT_SECRET': 'asset-secret', 'CCSDK_RUNTIME_JWT_SECRET': 'run-secret',
            'CCSDK_OBSERVATION_JWT_SECRET': 'observation-secret'}))

    def headers(self, *, secret='asset-secret', **overrides):
        now = time.time()
        claims = {'iss': 'string-ai-center-service', 'aud': 'ccsdk-runtime-assets',
                  'iat': now, 'exp': now + 60, 'jti': 'grant', 'sub': 'operator',
                  'scope': 'assets.manage', **overrides}
        return {'Authorization': 'Bearer ' + encode_hs256_jwt(claims, secret)}

    def body(self):
        return {'manifest': {'ref': 'business-report', 'title': '业务报告', 'description': '撰写业务报告',
                'toolRefs': ['data', 'documents', 'office', 'artifacts'],
                'data': {'access': 'required', 'sourceRefs': ['schoolDoubleHigh']}},
                'prompt': '根据获准资料撰写；不得编造业务事实。'}

    def test_validate_create_discover_and_no_overwrite(self):
        from runtime.capabilities import load_capabilities
        body = self.body()
        validation = self.client.post('/internal/v1/assets/capabilities/validate', json=body, headers=self.headers())
        self.assertEqual(validation.status_code, 200, validation.text)
        self.assertEqual(list(self.root.iterdir()), [])
        result = self.client.post('/internal/v1/assets/capabilities', json=body, headers=self.headers())
        self.assertEqual(result.status_code, 201, result.text)
        self.assertIn('business-report', load_capabilities(self.root))
        self.assertEqual(self.client.post('/internal/v1/assets/capabilities', json=body,
                         headers=self.headers()).status_code, 409)
        catalog = self.client.get('/internal/v1/assets/catalog', headers=self.headers()).json()
        self.assertIn('office', {tool['ref'] for tool in catalog['tools']})
        self.assertIn('schoolDoubleHigh', {source['ref'] for source in catalog['dataSources']})
        self.assertNotIn('connection', json.dumps(catalog))
        self.assertNotIn('auth', json.dumps(catalog))

    def test_run_credentials_cannot_manage_assets_and_disabled_fails_closed(self):
        for headers in ({}, self.headers(secret='run-secret'), self.headers(scope='run.execute'),
                        self.headers(aud='ccsdk-runtime'), self.headers(exp=time.time() + 600)):
            with self.subTest(headers=bool(headers)):
                self.assertEqual(self.client.post('/internal/v1/assets/capabilities', json=self.body(),
                                 headers=headers).status_code, 401)
        for secret in ('', 'run-secret', 'observation-secret'):
            with patch.dict('os.environ', {'CCSDK_ASSET_JWT_SECRET': secret}):
                self.assertEqual(self.client.get('/internal/v1/assets/catalog',
                                 headers=self.headers()).status_code, 401)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_default_persistent_store_is_discovered_and_uses_shared_skills(self):
        from runtime import asset_management, capabilities
        from runtime.config import prepare_capability_assets
        builtin = Path(self.temporary.name) / 'builtin/capabilities'
        builtin.mkdir(parents=True)
        managed = Path(self.temporary.name) / 'runtime-data/capabilities'
        body = self.body()
        body['manifest']['skillRefs'] = ['document-review']
        with patch.object(capabilities, 'CAPABILITIES_ROOT', builtin), \
             patch.object(asset_management, 'CAPABILITIES_ROOT', builtin), \
             patch.object(capabilities, 'MANAGED_CAPABILITIES_ROOT', managed, create=True), \
             patch.object(asset_management, 'MANAGED_CAPABILITIES_ROOT', managed, create=True):
            app = FastAPI()
            app.include_router(asset_management.create_asset_router())
            with TestClient(app) as client:
                result = client.post('/internal/v1/assets/capabilities', json=body, headers=self.headers())
            self.assertEqual(result.status_code, 201, result.text)
            self.assertTrue((managed / 'business-report/capability.json').is_file())
            self.assertEqual(list(builtin.iterdir()), [])
            self.assertEqual(list(managed.parent.iterdir()), [managed])
            # 重建管理接口后仍从同一持久目录发现，Runtime 装配复用源码 Skill。
            app = FastAPI()
            app.include_router(asset_management.create_asset_router())
            with TestClient(app) as client:
                duplicate = client.post('/internal/v1/assets/capabilities', json=body, headers=self.headers())
            self.assertEqual(duplicate.status_code, 409)
            self.assertIn('business-report', capabilities.load_capabilities())
            assets = prepare_capability_assets({'capability_ref': 'business-report'})
            self.assertIn(body['prompt'], assets['prompt'])
            self.assertIn('document-review', assets['prompt'])
            self.assertEqual(Path(assets['capability']['_skill_root']), capabilities.SKILLS_ROOT)

    def test_managed_capability_cannot_override_builtin_name(self):
        body = self.body()
        body['manifest']['ref'] = 'conversation'
        result = self.client.post('/internal/v1/assets/capabilities', json=body, headers=self.headers())
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_assets_never_become_visible(self):
        for change in ({'ref': '../escape'}, {'workflowRefs': []}, {'toolRefs': ['missing']},
                       {'toolConfig': {'office': '../outside'}},
                       {'data': {'access': 'required', 'sourceRefs': ['missing']}},
                       {'runtime': None}, {'runtime': {'mode': []}},
                       {'runtime': {'thinking': {'type': []}}},
                       {'runtime': {'effort': {}}}, {'runtime': {'prompt_mode': []}},
                       {'data': {'access': [], 'sourceRefs': ['schoolDoubleHigh']}},
                       {'data': {'access': 'required', 'sourceRefs': ['schoolDoubleHigh'],
                                 'contextTopics': [{}]}}):
            body = self.body()
            body['manifest'].update(change)
            with self.subTest(change=change):
                result = self.client.post('/internal/v1/assets/capabilities', json=body, headers=self.headers())
                self.assertEqual(result.status_code, 400, result.text)
                self.assertEqual(list(self.root.iterdir()), [])
