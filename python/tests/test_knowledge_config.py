import unittest
from unittest.mock import patch

from runtime.configuration import execution_entry
from tests.deployment_fixtures import configuration_rows


def add_knowledge_rows(rows):
    rows['knowledge_connections'] = {
        'school-a': {'ref':'school-a','name':'A 校知识库','provider':'weknora',
            'base_url':'http://weknora-a.test','tenant_id':'school-a',
            'credentials':{'api_key':'private-a'},'config':{'workspace_id':51},
            'timeout_seconds':10,'max_results':5,'enabled':True},
        'school-b': {'ref':'school-b','name':'B 校知识库','provider':'weknora',
            'base_url':'http://weknora-b.test','tenant_id':'school-b',
            'credentials':{'api_key':'private-b'},'config':{'workspace_id':52},
            'timeout_seconds':10,'max_results':5,'enabled':True},
        'shared': {'ref':'shared','name':'公共政策库','provider':'weknora',
            'base_url':'http://weknora-shared.test','tenant_id':'*',
            'credentials':{'api_key':'private-shared'},'config':{'workspace_id':53},
            'timeout_seconds':10,'max_results':5,'enabled':True},
    }
    rows['knowledge_purposes'] = {
        'policy': {'ref':'policy','name':'政策','description':'政策与制度'},
        'teaching': {'ref':'teaching','name':'教学','description':'教学资料'},
    }
    rows['knowledge_libraries'] = {
        ref: {'ref':ref,'name':name,'connection_ref':connection,'purpose_ref':purpose,
            'external_id':external_id,'config':{},'enabled':True}
        for ref,name,connection,purpose,external_id in (
            ('policy-a','A 校本政策','school-a','policy','kb-school-a'),
            ('policy-b','B 校本政策','school-b','policy','kb-school-b'),
            ('policy-shared','公共政策','shared','policy','kb-shared'),
            ('teaching-a','A 校教学资料','school-a','teaching','kb-teaching-a'),
        )
    }
    rows['capabilities']['conversation']['knowledge'] = [
        {'ref':'policy','required':True}, {'ref':'teaching','required':False}]
    return rows


class KnowledgeConfigurationTests(unittest.TestCase):
    def test_execution_entry_resolves_only_this_tenant_and_shared_libraries(self):
        rows = add_knowledge_rows(configuration_rows())

        entry = execution_entry('conversation', rows=rows, tenant_id='school-a')
        knowledge = entry['_configuration']['knowledge']

        self.assertEqual({library['ref'] for library in knowledge['libraries']},
                         {'policy-a','policy-shared','teaching-a'})
        self.assertEqual(set(knowledge['connections']), {'school-a','shared'})
        self.assertEqual(knowledge['connections']['school-a']['credentials']['api_key'], 'private-a')
        self.assertNotIn('private-b', str(knowledge))
        self.assertIn('knowledge', entry['capability']['toolRefs'])

    def test_required_purpose_without_a_tenant_library_fails_before_worker_assembly(self):
        rows = add_knowledge_rows(configuration_rows())
        rows['knowledge_libraries'].pop('policy-a')
        rows['knowledge_libraries'].pop('policy-shared')

        with self.assertRaisesRegex(ValueError, 'knowledge_purpose_unavailable'):
            execution_entry('conversation', rows=rows, tenant_id='school-a')

    def test_run_knowledge_resolution_requires_tenant_identity(self):
        rows = add_knowledge_rows(configuration_rows())
        with patch('runtime.configuration.read_configuration', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'knowledge_tenant_required'):
                execution_entry('conversation', include_knowledge=True)

    def test_worker_configuration_accepts_private_knowledge_connection(self):
        from runtime.deployment_config import configuration_scope, install_worker_configuration, worker_configuration
        from runtime import runtime_settings
        entry = execution_entry('conversation', rows=add_knowledge_rows(configuration_rows()),
                                tenant_id='school-a')
        document = entry['_configuration']
        with configuration_scope(document):
            private_configuration = worker_configuration()
        private_configuration['model'] = {'baseUrl':'https://model.test','apiKey':'model-key'}
        with (
            patch('runtime.deployment_config._DEPLOYMENT', None),
            patch('runtime.deployment_config._WORKER', False),
            patch('runtime.deployment_config._runtime_configuration', return_value={}),
            patch.object(runtime_settings, '_SETTINGS', None),
        ):
            install_worker_configuration(private_configuration)
            self.assertEqual(worker_configuration()['knowledge'], entry['_configuration']['knowledge'])
