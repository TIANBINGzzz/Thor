"""远程配置保存、加密与每次读取的行为；离线使用同一 SQLAlchemy 查询。"""
import unittest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select

class ConfigStoreTests(unittest.TestCase):
    def setUp(self):
        from runtime.config_store import ConfigStore, metadata
        self.engine = create_engine('sqlite://')
        metadata.create_all(self.engine)
        self.store = ConfigStore(self.engine, Fernet.generate_key().decode())
        self.store.save('model_connections', 'primary', {
            'name': '模型服务', 'base_url': 'https://model.test', 'adapter': 'anthropic',
            'api_key': 'private-model-key', 'parameters': {}, 'enabled': True})
        from tests.deployment_fixtures import configuration_rows
        rows = configuration_rows()
        model = next(iter(rows['models'].values()))
        model['connection_ref'] = 'primary'
        self.store.save('models', model['ref'], model)
        capability = rows['capabilities']['conversation']
        capability.update(prompt='旧规则', tool_refs=[])
        self.store.save('capabilities', 'conversation', capability)

    def test_new_read_sees_saved_prompt_and_previous_read_is_unchanged(self):
        before = self.store.load()
        item = self.store.get('capabilities', 'conversation')
        item['prompt'] = '新规则'
        self.store.save('capabilities', 'conversation', item)
        after = self.store.load()
        self.assertEqual(before['capabilities']['conversation']['prompt'], '旧规则')
        self.assertEqual(after['capabilities']['conversation']['prompt'], '新规则')

    def test_secrets_are_encrypted_at_rest_and_not_returned_by_management(self):
        from runtime.config_store import TABLES
        with self.engine.connect() as connection:
            stored = connection.execute(select(TABLES['model_connections'])).mappings().one()
        self.assertNotIn('private-model-key', str(dict(stored)))
        self.assertIsNone(self.store.get('model_connections', 'primary')['api_key'])
        self.assertEqual(self.store.load()['model_connections']['primary']['api_key'], 'private-model-key')
        item=self.store.get('model_connections','primary')
        item['name']='改名'
        self.store.save('model_connections','primary',item)
        self.assertEqual(self.store.load()['model_connections']['primary']['api_key'],'private-model-key')

    def test_missing_relation_rolls_back_entire_change(self):
        item = self.store.get('capabilities', 'conversation')
        item.update(prompt='不应保存', skills=[{'ref':'missing','required':True,'sort_order':0}])
        with self.assertRaises(ValueError):
            self.store.save('capabilities', 'conversation', item)
        self.assertEqual(self.store.get('capabilities', 'conversation')['prompt'], '旧规则')

    def test_referenced_connection_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            self.store.delete('model_connections', 'primary')

    def test_internal_service_reference_prevents_mcp_deletion(self):
        self.store.save('mcp_servers','campus',{'name':'Campus','url':'https://campus.test',
            'headers':{},'auth_required':False,'auth_injection':'none','auth_target':None,'auth_prefix':None,'parameters':{},'enabled':True})
        item=self.store.get('capabilities','conversation')
        item['service_refs']=['campus']
        self.store.save('capabilities','conversation',item)
        with self.assertRaisesRegex(ValueError,'config_in_use'):
            self.store.delete('mcp_servers','campus')

class ConfigurationBindingTests(unittest.TestCase):
    def test_next_turn_removes_deleted_skill_resources_and_unselected_skills(self):
        import tempfile
        from pathlib import Path
        from runtime.config import stage_skill_files
        with tempfile.TemporaryDirectory() as root:
            selected={'sections':[{'load':'on_demand','source':'skills/review/SKILL.md',
                'body':'Read the guide','resources':{'guide.md':'old content'}}]}
            stage_skill_files(selected,root)
            self.assertTrue((Path(root)/'.skills/review/guide.md').is_file())
            selected['sections'][0]['resources']={}
            stage_skill_files(selected,root)
            self.assertFalse((Path(root)/'.skills/review/guide.md').exists())
            stage_skill_files({'sections':[]},root)
            self.assertFalse((Path(root)/'.skills/review/SKILL.md').exists())

    def test_worker_payload_does_not_include_control_plane_secrets(self):
        import json, tempfile
        from pathlib import Path
        import server
        from runtime.protocol import AgentRunRequest
        from runtime.configuration import execution_entry
        from tests.deployment_fixtures import configuration_rows
        rows=configuration_rows()
        rows['settings']['system']['auth_configuration_jwt_secret']='management-secret-not-for-worker'
        entry=execution_entry(rows=rows)
        request=AgentRunRequest.from_dict({'protocol':'agent-run/v1','runId':'secret-boundary',
            'messageId':'m','domainName':'school.test','input':{'text':'hello'}})
        with tempfile.TemporaryDirectory() as folder:
            payload=server._internal_worker_payload(request,Path(folder),execution_entry=entry)
        self.assertNotIn('management-secret-not-for-worker',json.dumps(payload))
        self.assertNotIn('test-runtime-secret',json.dumps(payload))

    def test_connection_and_runtime_are_bound_to_each_run(self):
        from runtime.configuration import execution_entry
        from runtime.deployment_config import configuration_scope, deployment_section
        from runtime.runtime_settings import RUNTIME_SETTINGS
        from tests.deployment_fixtures import configuration_rows
        rows=configuration_rows()
        first=execution_entry(rows=rows)
        rows['model_connections']['default']['api_key']='rotated-key'
        rows['capabilities']['conversation']['run_timeout_ms']=12345
        second=execution_entry(rows=rows)
        with configuration_scope(first['_configuration']):
            self.assertEqual(deployment_section('model')['apiKey'],'model-secret')
            self.assertEqual(RUNTIME_SETTINGS.timeouts.execution_ms,3600000)
        with configuration_scope(second['_configuration']):
            self.assertEqual(deployment_section('model')['apiKey'],'rotated-key')
            self.assertEqual(RUNTIME_SETTINGS.timeouts.execution_ms,12345)

    def test_sdk_options_use_current_connection_and_explicit_model_parameters(self):
        from runtime.configuration import execution_entry
        from runtime.config import build_options
        from tests.deployment_fixtures import configuration_rows
        rows=configuration_rows()
        rows['model_connections']['default']['api_key']='new-secret'
        rows['model_connections']['default']['base_url']='https://other.test'
        rows['models'][rows['capabilities']['conversation']['model_ref']]['model_name']='new-model'
        rows['capabilities']['conversation'].update(effort='high',thinking_mode='disabled')
        entry=execution_entry(rows=rows)
        options=build_options({'capability_ref':'conversation','_execution_entry':entry})
        self.assertEqual(options.env['ANTHROPIC_AUTH_TOKEN'],'new-secret')
        self.assertEqual(options.env['ANTHROPIC_BASE_URL'],'https://other.test')
        self.assertEqual(options.model,'new-model')
        self.assertEqual(options.effort,'high')



class RunCallbackConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_reused_actor_callback_uses_current_run_configuration(self):
        import asyncio
        import server
        from types import SimpleNamespace
        from unittest.mock import patch
        from runtime.deployment_config import deployment_section
        ready, done = asyncio.Event(), asyncio.Event()
        observed = []
        async def callback():
            await ready.wait()
            await server._handle_client_public_event('run-config-test', {'type':'text'})
            done.set()
        async def capture(*_):
            observed.append(deployment_section('fileService'))
        async def execute(*args, **kwargs):
            ready.set()
            await done.wait()
        actor = asyncio.create_task(callback())
        with patch.object(server, '_execute_internal_run_bound', execute), patch.object(server, '_handle_agent_event', capture):
            await server._execute_internal_run(SimpleNamespace(run_id='run-config-test'), {},
                execution_entry={'_configuration':{'fileService':{'baseUrl':'https://new.test'}}})
        await actor
        self.assertEqual(observed, [{'baseUrl':'https://new.test'}])
