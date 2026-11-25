"""管理表单的模型选择、局部保存及字段错误契约。"""
import unittest
from tests import test_config_api


class ConfigurationFormTests(unittest.TestCase):
    setUp = test_config_api.ConfigurationAPITests.setUp

    def test_campus_patch_updates_prompt_and_tool_schema_only_on_next_run(self):
        from runtime.config import prepare_capability_assets
        from runtime.deployment_config import configuration_scope
        from runtime.tool_services import ToolServices
        from capability_packs.registry import load_pack
        from types import SimpleNamespace

        ref = 'campus-brain-query'
        before = prepare_capability_assets({'capability_ref': ref})
        response = self.client.patch(f'/internal/config/v1/capabilities/{ref}', headers=self.headers,
                                     json={'config': {'params': {'max_calls': 8, 'minimum_schools': 14}}})
        self.assertEqual(response.status_code, 200, response.text)
        after = prepare_capability_assets({'capability_ref': ref})
        self.assertEqual(before['prompt_assets']['variables']['minimum_schools'], 12)
        self.assertEqual(after['prompt_assets']['variables']['minimum_schools'], 14)
        pack = load_pack(ref)
        with configuration_scope(after['_configuration']):
            services = ToolServices(after, {'platformBearer': 'test-token'})
            self.addCleanup(services.clear)
            context = SimpleNamespace(services=SimpleNamespace(require=services.services.__getitem__))
            operations = {op.ref: op for op in pack.specialize_operations(context, pack.operations)}
            schema = operations['get_norm_metrics'].input_schema
            self.assertEqual(schema['properties']['payload']['properties']['schools']['minItems'], 14)
            self.assertEqual(operations['execute_query_plan'].input_schema['properties']['items']['maxItems'], 8)

    def test_template_registration_can_be_cleared_without_changing_loaded_run(self):
        from data_access.context import DataError
        from runtime.configuration import execution_entry
        from runtime.template_assets import load_template

        ref = 'document-writing'
        before = execution_entry(ref)['capability']
        response = self.client.patch(f'/internal/config/v1/capabilities/{ref}', headers=self.headers,
                                     json={'config': {'templates': []}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(load_template('szpt-midterm', ref, entry=before)['template_key'], 'szpt-midterm')
        with self.assertRaisesRegex(DataError, 'TEMPLATE_FORBIDDEN'):
            load_template('szpt-midterm', ref, entry=execution_entry(ref)['capability'])

    def test_invalid_campus_params_and_template_registration_do_not_save(self):
        for ref, config, field in [
            ('campus-brain-query', {'params': {'minimum_schools': 0}}, 'config.params.minimum_schools'),
            ('document-writing', {'templates': ['unavailable-template']}, 'config.templates'),
            ('document-writing', {'templates': ['../szpt-midterm']}, 'config.templates'),
        ]:
            with self.subTest(ref=ref, config=config):
                before = self.store.get('capabilities', ref)
                response = self.client.patch(f'/internal/config/v1/capabilities/{ref}', headers=self.headers,
                                             json={'config': config, 'prompt': '不应保存'})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()['detail']['field'], field)
                self.assertEqual(self.store.get('capabilities', ref), before)

    def test_model_list_filters_and_supports_same_name_on_another_connection(self):
        connection = self.store.load()['model_connections']['default']
        connection['ref'] = 'secondary'
        self.store.save('model_connections', 'secondary', connection)
        model = next(iter(self.store.list('models')))
        model.update(ref='secondary-model', connection_ref='secondary', enabled=False)
        self.store.save('models', 'secondary-model', model)
        response = self.client.get('/internal/config/v1/models?connection_ref=secondary&enabled=false', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([item['ref'] for item in response.json()], ['secondary-model'])
        self.assertNotIn('api_key', response.text)

    def test_patch_preserves_secrets_and_unmentioned_relations(self):
        before = self.store.load()['capabilities']['document-writing']
        response = self.client.patch('/internal/config/v1/capabilities/document-writing', headers=self.headers,
                                     json={'prompt': '新的文稿规则'})
        self.assertEqual(response.status_code, 200, response.text)
        after = self.store.load()['capabilities']['document-writing']
        self.assertEqual(after['skills'], before['skills'])
        self.assertEqual(after['databases'], before['databases'])
        response = self.client.patch('/internal/config/v1/model_connections/default', headers=self.headers,
                                     json={'name': '改名'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['configured_secrets']['api_key'])
        self.assertEqual(self.store.load()['model_connections']['default']['api_key'], 'model-secret')

    def test_setting_patch_is_applied_to_next_run(self):
        from runtime.configuration import execution_entry
        before = execution_entry()
        response = self.client.patch('/internal/config/v1/settings/runtime', headers=self.headers,
                                     json={'value': {'timeouts': {'image-ms': 123456}}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['value']['limits'], self.store.get('settings', 'runtime')['value']['limits'])
        self.assertEqual(execution_entry()['_configuration']['runtime']['timeouts']['image-ms'], 123456)
        self.assertNotEqual(before['_configuration']['runtime']['timeouts']['image-ms'], 123456)

    def test_unsupported_model_parameter_reports_field_and_rolls_back(self):
        model = next(iter(self.store.list('models')))
        self.store.save('models', 'limited', {**model, 'ref':'limited', 'model_name':'limited-model', 'thinking_modes': ['disabled'], 'effort_options': []})
        self.store.save('capabilities', 'conversation', {'model_ref':'limited'}, partial=True)
        path = '/internal/config/v1/capabilities/conversation'
        for patch, field in [({'config': {'runtime': {'thinking': {'type': 'adaptive'}}}}, 'config.runtime.thinking'),
                             ({'config': {'runtime': {'effort': 'high'}}}, 'config.runtime.effort'),
                             ({'config': {'runtime': {'timeout_ms': -1}}}, 'config.runtime.timeout_ms'),
                             ({'unknown': 1}, 'unknown')]:
            with self.subTest(field=field):
                response = self.client.patch(path, headers=self.headers, json={'prompt': '不能保存', **patch})
                self.assertEqual(response.status_code, 400, response.text)
                self.assertEqual(response.json()['detail']['field'], field)
                self.assertNotEqual(self.store.get('capabilities', 'conversation')['prompt'], '不能保存')

    def test_dropdown_options_have_refs_and_no_connection_secrets(self):
        response = self.client.get('/internal/config/v1/options', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        values = response.json()
        self.assertEqual(set(values), {'models', 'tools', 'skills', 'mcp_servers', 'database_connections',
                                       'knowledge_connections', 'knowledge_purposes', 'knowledge_libraries'})
        self.assertTrue(all('ref' in item and 'name' in item for items in values.values() for item in items))
        self.assertNotIn('campus', {item['ref'] for item in values['mcp_servers']})
        self.assertEqual(self.client.get('/internal/config/v1/mcp_servers/campus', headers=self.headers).status_code, 200)
        for secret in ('model-secret', 'private-image-key', 'management-only-secret'):
            self.assertNotIn(secret, response.text)

    def test_referenced_model_cannot_be_deleted_or_disabled(self):
        model = next(iter(self.store.list('models')))
        path = '/internal/config/v1/models/' + model['ref']
        self.assertEqual(self.client.delete(path, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.patch(path, headers=self.headers, json={'enabled': False}).status_code, 400)

    def test_database_and_mcp_patches_reach_runtime(self):
        from runtime.configuration import execution_entry
        path = '/internal/config/v1/database_connections/schoolDoubleHigh'
        response = self.client.patch(path, headers=self.headers, json={
            'query_timeout_seconds':17, 'query_max_rows':321, 'dynamic_sql_enabled':False,
            'tls_mode':'verify_identity', 'tls_ca_file':'certs/customer.pem'})
        self.assertEqual(response.status_code,200,response.text)
        db = execution_entry('national-excellence-data-qa')['_configuration']['databases']['schoolDoubleHigh']
        self.assertEqual(db['query'], {'timeout_seconds':17,'max_rows':321,'dynamic_sql_enabled':False})
        self.assertEqual(db['connection']['tls'], {'mode':'verify_identity','ca_file':'certs/customer.pem','verify_identity':True})
        response = self.client.patch('/internal/config/v1/mcp_servers/campus', headers=self.headers,
                                     json={'config': {'auth': {'target': 'new_context_token'}}})
        self.assertEqual(response.status_code,200,response.text)
        auth = execution_entry('campus-brain-query')['_configuration']['_mcp_catalog']['campus']['auth']
        self.assertEqual(auth, {'required':True,'arguments':{'new_context_token':'platformBearer'}})

    def test_bad_fixed_fields_report_the_column(self):
        for resource, ref, field, value in [
            ('database_connections','schoolDoubleHigh','query_max_rows',0),
            ('database_connections','schoolDoubleHigh','tls_mode','invalid'),
            ('model_connections','default','base_url','invalid'),
        ]:
            with self.subTest(field=field):
                response=self.client.patch(f'/internal/config/v1/{resource}/{ref}',headers=self.headers,json={field:value})
                self.assertEqual(response.status_code,400,response.text)
                self.assertEqual(response.json()['detail']['field'],field)

    def test_patch_missing_record_and_explicit_relation_clear(self):
        self.assertEqual(self.client.patch('/internal/config/v1/models/missing',headers=self.headers,json={'name':'new'}).status_code,404)
        response=self.client.patch('/internal/config/v1/capabilities/document-writing',headers=self.headers,
                                   json={'skills':[]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.store.get('capabilities','document-writing')['skills'],[])

    def test_model_unique_within_connection(self):
        model=next(iter(self.store.list('models')))
        model['ref']='duplicate'
        response=self.client.put('/internal/config/v1/models/duplicate',headers=self.headers,json=model)
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(response.json()['detail']['field'],'model_name')

    def test_missing_mcp_auth_target_is_a_field_error_not_a_missing_record(self):
        path='/internal/config/v1/mcp_servers/campus'
        before=self.store.get('mcp_servers','campus')['config']
        response=self.client.patch(path,headers=self.headers,json={'config': {'auth': {'target': None}}})
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(response.json()['detail']['field'],'config.auth.target')
        self.assertEqual(self.store.get('mcp_servers','campus')['config'],before)

    def test_patch_can_remove_obsolete_fields_from_discriminated_objects(self):
        path = '/internal/config/v1/capabilities/conversation'
        for thinking in ({'type': 'enabled', 'budget_tokens': 1024}, {'type': 'disabled', 'budget_tokens': None}):
            response = self.client.patch(path, headers=self.headers, json={'config': {'runtime': {'thinking': thinking}}})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['config']['runtime']['thinking'], {'type': 'disabled'})

        path = '/internal/config/v1/mcp_servers/example'
        response = self.client.put(path, headers=self.headers, json={
            'name': '示例', 'url': 'https://mcp.test', 'headers': {'X-Key': 'test-key'}, 'enabled': True,
            'config': {'auth': {'mode': 'header', 'target': 'Authorization', 'prefix': 'Bearer '}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.patch(path, headers=self.headers, json={
            'config': {'auth': {'mode': 'none', 'target': None, 'prefix': None}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['config']['auth'], {'mode': 'none'})
        self.assertIsNone(response.json()['headers'])
        self.assertEqual(self.store.get('mcp_servers', 'example', public=False)['headers'], {'X-Key': 'test-key'})

    def test_setting_update_keeps_redacted_secrets_on_full_save(self):
        path = '/internal/config/v1/settings/images'
        item = self.client.get(path, headers=self.headers).json()
        self.assertEqual(item['secrets'], {'apiKey': None})
        item['value']['model'] = 'new-image-model'
        response = self.client.put(path, headers=self.headers, json=item)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('private-image-key', response.text)
        self.assertEqual(self.store.get('settings', 'images', public=False)['secrets'], {'apiKey': 'private-image-key'})

    def test_image_service_disable_applies_to_next_run(self):
        from runtime.config import build_options, prepare_capability_assets

        old = {'capability_ref': 'conversation'}
        prepare_capability_assets(old)
        response = self.client.patch('/internal/config/v1/settings/images', headers=self.headers,
                                     json={'value': {'enabled': False}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('images', build_options(old).mcp_servers)
        self.assertNotIn('images', build_options({'capability_ref': 'conversation'}).mcp_servers)
        with self.assertRaisesRegex(RuntimeError, '必需工具未配置：images'):
            build_options({'capability_ref': 'image-generation'})

    def test_disabled_mcp_placeholder_cannot_mount_or_enable_without_an_address(self):
        path = '/internal/config/v1/mcp_servers/business'
        response = self.client.put(path, headers=self.headers, json={
            'name': '业务 MCP', 'url': '', 'headers': {}, 'enabled': False,
            'config': {'auth': {'mode': 'header', 'target': 'Authorization', 'prefix': 'Bearer '}},
        })
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.patch(path, headers=self.headers, json={'enabled': True})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.store.get('mcp_servers', 'business')['enabled'])
