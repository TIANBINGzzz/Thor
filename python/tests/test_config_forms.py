"""管理表单的模型选择、局部保存及字段错误契约。"""
import unittest
from tests import test_config_api


class ConfigurationFormTests(unittest.TestCase):
    setUp = test_config_api.ConfigurationAPITests.setUp
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

    def test_fixed_setting_columns_are_applied_to_next_run(self):
        from runtime.configuration import execution_entry
        before = execution_entry()
        response = self.client.patch('/internal/config/v1/settings/system', headers=self.headers,
                                     json={'runtime_image_ms': 123456})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn('value', response.json())
        self.assertEqual(execution_entry()['_configuration']['runtime']['timeouts']['image-ms'], 123456)
        self.assertNotEqual(before['_configuration']['runtime']['timeouts']['image-ms'], 123456)

    def test_unsupported_model_parameter_reports_field_and_rolls_back(self):
        model = next(iter(self.store.list('models')))
        self.store.save('models', 'limited', {**model, 'ref':'limited', 'model_name':'limited-model', 'thinking_modes': ['disabled'], 'effort_options': []})
        self.store.save('capabilities', 'conversation', {'model_ref':'limited'}, partial=True)
        path = '/internal/config/v1/capabilities/conversation'
        for patch, field in [({'thinking_mode': 'adaptive'}, 'thinking_mode'),
                             ({'effort': 'high'}, 'effort'), ({'run_timeout_ms': -1}, 'run_timeout_ms'),
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
        self.assertEqual(set(values), {'models', 'tools', 'skills', 'mcp_servers', 'database_connections'})
        self.assertTrue(all('ref' in item and 'name' in item for items in values.values() for item in items))
        for secret in ('model-secret', 'private-image-key', 'management-only-secret'):
            self.assertNotIn(secret, response.text)

    def test_referenced_model_cannot_be_deleted_or_disabled(self):
        model = next(iter(self.store.list('models')))
        path = '/internal/config/v1/models/' + model['ref']
        self.assertEqual(self.client.delete(path, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.patch(path, headers=self.headers, json={'enabled': False}).status_code, 400)

    def test_database_and_mcp_columns_reach_runtime_without_json_editing(self):
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
                                     json={'auth_target':'user_context_token'})
        self.assertEqual(response.status_code,200,response.text)
        auth = execution_entry('campus-brain-query')['_configuration']['_mcp_catalog']['campus']['auth']
        self.assertEqual(auth, {'required':True,'arguments':{'user_context_token':'platformBearer'}})

    def test_bad_fixed_fields_report_the_column(self):
        for resource, ref, field, value in [
            ('database_connections','schoolDoubleHigh','query_max_rows',0),
            ('database_connections','schoolDoubleHigh','tls_mode','invalid'),
            ('settings','system','runtime_image_ms',-10),
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

    def test_missing_mcp_parameter_is_a_field_error_not_a_missing_record(self):
        path='/internal/config/v1/mcp_servers/campus'
        before=self.store.get('mcp_servers','campus')['parameters']
        response=self.client.patch(path,headers=self.headers,json={'parameters':{}})
        self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(response.json()['detail']['field'],'parameters.domainName')
        self.assertEqual(self.store.get('mcp_servers','campus')['parameters'],before)
