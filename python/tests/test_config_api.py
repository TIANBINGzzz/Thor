import time
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from runtime.auth import encode_hs256_jwt
from runtime.config_api import router
from tests.deployment_fixtures import install_configuration_store

class ConfigurationAPITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('runtime.config_store._STORE'))
        self.store=install_configuration_store()
        item=self.store.get('settings','system')
        item['auth_configuration_jwt_secret']='management-only-secret'
        self.store.save('settings','system',item)
        app=FastAPI();app.include_router(router)
        self.client=TestClient(app)
        now=int(time.time())
        self.claims={'sub':'admin','iss':'string-ai-center-service','aud':'ccsdk-config',
                     'scope':'configuration.manage','iat':now,'exp':now+60}
        self.headers={'Authorization':'Bearer '+encode_hs256_jwt(self.claims,'management-only-secret')}

    def test_run_key_cannot_manage_configuration(self):
        headers={'Authorization':'Bearer '+encode_hs256_jwt(self.claims,'test-runtime-secret')}
        self.assertEqual(self.client.get('/internal/config/v1/capabilities',headers=headers).status_code,401)

    def test_search_budgets_are_validated_and_reach_worker_snapshot(self):
        from runtime.configuration import execution_entry
        from runtime.deployment_config import configuration_scope, worker_configuration
        from runtime.runtime_settings import RUNTIME_SETTINGS
        path='/internal/config/v1/settings/system'
        for value in (0, True, '4096', 500):
            with self.subTest(value=value):
                response=self.client.patch(path,headers=self.headers,json={'runtime_web_search_thinking_max_tokens':value})
                self.assertEqual(response.status_code,400,response.text)
        response=self.client.patch(path,headers=self.headers,json={
            'runtime_web_search_max_tokens':750,'runtime_web_search_thinking_max_tokens':5000})
        self.assertEqual(response.status_code,200,response.text)
        entry=execution_entry('conversation')
        with configuration_scope(entry['_configuration']):
            snapshot=worker_configuration()
        with configuration_scope(snapshot):
            self.assertEqual(RUNTIME_SETTINGS.limits.web_search_max_tokens,750)
            self.assertEqual(RUNTIME_SETTINGS.limits.web_search_thinking_max_tokens,5000)

    def test_save_prompt_changes_next_execution_and_hides_secrets(self):
        from runtime.configuration import execution_entry
        path='/internal/config/v1/capabilities/conversation'
        item=self.client.get(path,headers=self.headers).json()
        item['prompt']='这是新的能力提示词'
        response=self.client.put(path,headers=self.headers,json=item)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(execution_entry('conversation')['capability']['_body'],'这是新的能力提示词')
        response=self.client.get('/internal/config/v1/model_connections/default',headers=self.headers)
        self.assertIsNone(response.json()['api_key'])
        self.assertNotIn('model-secret',response.text)

    def test_invalid_skill_dependency_does_not_change_saved_capability(self):
        path='/internal/config/v1/capabilities/conversation'
        item=self.client.get(path,headers=self.headers).json()
        before=item['prompt']
        item.update(prompt='错误修改',skills=[{'ref':'unknown','required':True,'sort_order':0}])
        self.assertEqual(self.client.put(path,headers=self.headers,json=item).status_code,400)
        self.assertEqual(self.store.get('capabilities','conversation')['prompt'],before)

    def test_unused_records_are_validated_before_save(self):
        for resource, ref, item in [
            ('settings', 'unknown', {'value':{}}),
            ('model_connections', 'unused', {'name':'Unused','base_url':'https://model.test',
                'adapter':'unknown','api_key':'secret','parameters':{},'enabled':True}),
            ('skills', 'unsafe', {'name':'Unsafe','description':'test','content':'test',
                'tool_refs':[], 'resources':{'../outside.md':'escape'}, 'enabled':True}),
        ]:
            with self.subTest(resource=resource):
                response=self.client.put(f'/internal/config/v1/{resource}/{ref}',headers=self.headers,json=item)
                self.assertEqual(response.status_code,400,response.text)
