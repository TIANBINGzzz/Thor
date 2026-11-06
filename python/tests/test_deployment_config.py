"""统一配置引用的读取、类型保留和 Worker 快照边界。"""

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.deployment_config import ConfigSnapshot, ConfigReferenceError
from runtime import deployment_config
from tests.deployment_fixtures import deployment_document, application_document


def customer_config():
    runtime = deployment_document()['runtime']
    runtime['timeouts']['execution-ms'] = 4200000
    runtime['models'] = {'default': 'custom-model', 'available': ['custom-model'],
                        'sdk': dict.fromkeys(('haiku', 'sonnet', 'opus', 'subagent'), 'custom-model')}
    return {'model': {'baseUrl': 'https://model.example.test/apps/anthropic', 'apiKey': 'private-model-key'},
            'security': {'runtimeJwtSecret': 'private-runtime-key',
                         'observationJwtSecret': 'private-observation-key'},
            'runtime': runtime,
            'databases': {'schoolDoubleHigh': {
                'access': {'tenantIds': ['self', 'extra-school']},
                'connection': {'driver': 'mysql+pymysql', 'host': 'db.example.test', 'database': 'customer',
                               'username': 'reader', 'password': 'private-database-key', 'tls': {'mode': 'disabled'}},
                'query': {'timeout_seconds': 30, 'max_rows': 10000, 'dynamic_sql_enabled': True}}},
            'fileService': {'baseUrl': 'https://files.example.test', 'remoteUrl': 'https://files.example.test',
                            'domainName': 'files.example.test', 'downloadPath': '/files/{fileId}/download'}}


class CustomerDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(deployment_config, '_DEPLOYMENT', None, create=True))
        self.enterContext(patch.object(deployment_config, '_WORKER', False))
        from runtime import runtime_settings
        self.enterContext(patch.object(runtime_settings, 'RUNTIME_SETTINGS', runtime_settings.RUNTIME_SETTINGS))
        self.document = customer_config()

    def initialize(self, document=None):
        initialize = getattr(deployment_config, 'initialize_deployment', None)
        self.assertTrue(callable(initialize), '缺少统一部署初始化入口')
        return initialize(document=self.document if document is None else document)

    def test_customer_values_override_defaults_without_changing_environment(self):
        before = dict(os.environ)
        self.initialize()
        from runtime.runtime_settings import load_model_settings, load_runtime_settings
        self.assertEqual(load_runtime_settings().timeouts.execution_ms, 4200000)
        self.assertGreater(load_runtime_settings().timeouts.worker_start_ms, 0)
        self.assertEqual(load_model_settings().default, 'custom-model')
        self.assertEqual(dict(os.environ), before)

    def test_startup_snapshot_is_fixed_and_worker_excludes_control_plane_secrets(self):
        self.initialize()
        self.document['fileService']['baseUrl'] = 'https://changed.test'
        with patch('runtime.nacos_config.fetch_config', side_effect=AssertionError('启动后禁止重新读取')):
            self.assertEqual(ConfigSnapshot().get('fileService.baseUrl'), 'https://files.example.test')
        worker = deployment_config.worker_configuration()
        serialized = json.dumps(worker)
        for secret in ('private-runtime-key', 'private-observation-key', 'security', 'fileService'):
            self.assertNotIn(secret, serialized)
        self.assertNotIn('nacos', worker)
        self.assertIn('private-model-key', serialized)
        self.assertIn('private-database-key', serialized)
        self.assertNotIn('deployment', worker)
        worker['databases']['schoolDoubleHigh']['access']['tenantIds'].append('changed')
        self.assertEqual(deployment_config.deployment_section('databases')['schoolDoubleHigh']['access']['tenantIds'],
                         ['self', 'extra-school'])

    def test_invalid_deployment_fails_without_publishing_or_echoing_secrets(self):
        self.assertTrue(callable(getattr(deployment_config, 'initialize_deployment', None)))
        for section, field, value in [('model', 'baseUrl', 'http://model.test'), ('model', 'apiKey', ''),
                                      ('security', 'runtimeJwtSecret', ''),
                                      ('security', 'observationJwtSecret', 'private-runtime-key')]:
            invalid = copy.deepcopy(self.document)
            invalid[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError) as caught:
                self.initialize(invalid)
            self.assertNotIn('private-', str(caught.exception))
            self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_source_access_tenants_are_required_and_validated_before_publish(self):
        for access in (None, {}, {'tenantIds': []}, {'tenantIds': '*'}, {'tenantIds': ['*']},
                       {'tenantIds': ['default']}, {'tenantIds': ['']}, {'tenantIds': [' self']},
                       {'tenantIds': [7]}, {'tenantIds': ['self', 'self']},
                       {'tenantIds': ['self'], 'tenantId': 'other'}):
            invalid = copy.deepcopy(self.document)
            invalid['databases']['schoolDoubleHigh']['access'] = access
            with self.subTest(access=access), self.assertRaisesRegex(ValueError, '^deployment_config_invalid$'):
                self.initialize(invalid)
            self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_source_self_scope_and_worker_snapshot_need_no_deployment_identity(self):
        self.document['databases']['schoolDoubleHigh']['access'] = {'tenantIds': ['self']}
        self.initialize()
        worker = deployment_config.worker_configuration()
        self.assertNotIn('deployment', worker)
        deployment_config.install_worker_configuration(worker)
        self.assertEqual(deployment_config.deployment_section('databases')['schoolDoubleHigh']['access'],
                         {'tenantIds': ['self']})

    def test_production_placeholders_cannot_publish_a_customer_snapshot(self):
        for section, field, value in [('model', 'apiKey', 'replace-model-api-key'),
                ('security', 'runtimeJwtSecret', 'replace-runtime-jwt-secret'),
                ('model', 'baseUrl', 'https://model.example.com/anthropic')]:
            invalid = copy.deepcopy(self.document)
            invalid[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaisesRegex(ValueError, '^deployment_config_invalid$'):
                self.initialize(invalid)
            self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_optional_image_service_keeps_full_yaml_fields_when_disabled(self):
        self.document['images'] = {'enabled': False, 'baseUrl': '', 'apiKey': '', 'model': 'qwen-image-3.0'}
        self.initialize()
        self.assertNotIn('images', deployment_config.worker_configuration())
        self.document['images'].update(enabled=True, baseUrl='https://images.test/v1', apiKey='image-private-key')
        self.initialize()
        self.assertEqual(deployment_config.worker_configuration()['images']['model'], 'qwen-image-3.0')
        self.document['images']['enabled'] = 'false'
        with self.assertRaisesRegex(ValueError, '^deployment_config_invalid$'):
            self.initialize()

    def test_missing_nacos_runtime_fields_cannot_be_filled_by_local_yaml(self):
        for section, field in [('timeouts', 'worker-close-ms'), ('limits', 'max-turns'),
                               ('models', 'default'), ('worker-pool', 'max-idle'),
                               ('observability', 'enabled')]:
            invalid = copy.deepcopy(self.document)
            del invalid['runtime'][section][field]
            with self.subTest(section=section, field=field), patch.object(deployment_config, '_DEPLOYMENT', None):
                with self.assertRaises(ValueError):
                    self.initialize(invalid)
                self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_nacos_document_is_validated_without_reading_local_runtime_defaults(self):
        with patch.object(deployment_config, 'application_document', side_effect=AssertionError('no local merge')):
            self.initialize()
        self.assertEqual(deployment_config.deployment_section('runtime'), self.document['runtime'])

    def test_invalid_customer_service_and_runtime_fields_fail_at_startup(self):
        for section, field, value in [('fileService', 'downloadPath', '/files/no-placeholder'),
                ('fileService', 'maxFileBytes', -1), ('campusMcp', 'url', 'https://user:private@host'),
                ('runtime', 'worker-pools', {}), ('runtime', 'observability', {'enabled': 'yes'})]:
            invalid = copy.deepcopy(self.document)
            invalid.setdefault('campusMcp', {'url': 'https://campus.example.test/mcp',
                                           'domainName': 'campus.example.test'})
            invalid[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                self.initialize(invalid)
            self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_nacos_unavailable_does_not_publish_old_environment_secrets(self):
        environment = {'CCSDK_NACOS_URL': 'https://nacos.example.test',
                       'ANTHROPIC_AUTH_TOKEN': 'old-secret', 'CCSDK_RUNTIME_JWT_SECRET': 'old-secret'}
        with self.assertRaises(ValueError) as caught:
            deployment_config.initialize_deployment(nacos=application_document()['nacos'],
                transport=httpx.MockTransport(lambda request: httpx.Response(503, text='private-response')))
        self.assertNotIn('private-response', str(caught.exception))
        self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_empty_issuer_and_optional_service_mistakes_are_rejected_before_publish(self):
        cases = [({'runtimeJwtIssuer': None}, 'security'), ({'runtimeJwtIssuer': ''}, 'security'),
                 ({'runtimeJwtAudience': None}, 'security'), (None, 'images'), (False, 'images'), ({}, 'images')]
        for changes, section in cases:
            invalid = copy.deepcopy(self.document)
            invalid[section] = {**invalid[section], **changes} if section == 'security' else changes
            with self.subTest(section=section, changes=changes), patch.object(deployment_config, '_DEPLOYMENT', None):
                with self.assertRaisesRegex(ValueError, '^deployment_config_invalid$'):
                    self.initialize(invalid)
                self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_observation_uses_customer_override_from_startup_snapshot(self):
        import tempfile
        from runtime.observability import create_observer
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'CCSDK_OBSERVABILITY_ENABLED': ''}):
            self.document['runtime']['observability'].update(enabled=True, storage='customer.sqlite')
            self.initialize()
            observer = create_observer(Path(folder))
            try:
                self.assertTrue(observer.enabled)
            finally:
                observer.close()

    def test_worker_installs_configuration_before_server_settings_are_imported(self):
        self.initialize()
        configuration = deployment_config.worker_configuration()
        program = '''import json, os
from runtime.deployment_config import install_worker_configuration
install_worker_configuration(json.loads(os.environ.pop('WORKER_TEST_CONFIG')))
from runtime.runtime_settings import RUNTIME_SETTINGS
from runtime.config import MODEL_SETTINGS, agent_environment
assert RUNTIME_SETTINGS.timeouts.execution_ms == 4200000
assert MODEL_SETTINGS.default == 'custom-model'
env = agent_environment()
assert env['ANTHROPIC_AUTH_TOKEN'] == 'private-model-key'
assert not any('DATABASE' in key or 'WORKER_CONFIG' in key or 'JWT' in key for key in env)
'''
        env = {**os.environ, 'WORKER_TEST_CONFIG': json.dumps(configuration)}
        result = subprocess.run([sys.executable, '-c', program], env=env,
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


class ConfigSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(deployment_config, '_DEPLOYMENT', None))
        self.enterContext(patch('runtime.nacos_config.application_settings', return_value=application_document()))

    def test_one_read_resolves_nested_references_without_mutating_assets(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, text='service:\n  url: https://service.test/mcp\n'
                                  '  timeout: 12\n  enabled: false\nprivate: secret\n')

        template = {'url': '${service.url}', 'options': ['${service.timeout}', '${service.enabled}'],
                    'static': 'fixed'}
        original = copy.deepcopy(template)
        config = ConfigSnapshot(transport=httpx.MockTransport(respond))
        result = config.resolve(template)
        self.assertEqual(result, {'url': 'https://service.test/mcp', 'options': [12, False], 'static': 'fixed'})
        self.assertEqual(config.get('service.url'), 'https://service.test/mcp')
        self.assertEqual(template, original)
        self.assertEqual(len(requests), 1)
        self.assertEqual(config.export(), {'service.url': 'https://service.test/mcp',
                                         'service.timeout': 12, 'service.enabled': False})

    def test_worker_uses_only_exported_values_without_network_or_credentials(self):
        with patch('runtime.nacos_config.fetch_config', return_value={
                'service': {'url': 'https://one.test', 'unused': 'private'}}):
            server = ConfigSnapshot()
            server.get('service.url')
        values = server.export()
        worker = ConfigSnapshot(values=values)
        values['service.url'] = 'https://changed.test'
        with patch('runtime.nacos_config.fetch_config', side_effect=AssertionError('offline snapshot')):
            self.assertEqual(worker.resolve('${service.url}'), 'https://one.test')
            with self.assertRaisesRegex(ConfigReferenceError, '^config_reference_missing$'):
                worker.get('service.unused')
        self.assertNotIn('private', str(worker.export()))

    def test_no_references_need_no_config_center(self):
        with patch('runtime.nacos_config.fetch_config', side_effect=AssertionError('unneeded network')):
            config = ConfigSnapshot()
            self.assertEqual(config.resolve({'constant': ['text', 1, None]}), {'constant': ['text', 1, None]})
            self.assertEqual(config.export(), {})

    def test_missing_or_invalid_references_fail_without_values(self):
        config = ConfigSnapshot(values={'service.null': None, 'service.url': 'https://service.test'})
        for reference in ('${missing}', '${service.null}'):
            with self.subTest(reference=reference), self.assertRaisesRegex(
                    ConfigReferenceError, '^config_reference_missing$'):
                config.resolve(reference)
        for reference in ('prefix-${service.url}', '${}', '${service..url}', '${env:SECRET}', '${service.url'):
            with self.subTest(reference=reference), self.assertRaisesRegex(
                    ConfigReferenceError, '^config_reference_invalid$'):
                config.resolve(reference)

    def test_snapshots_and_returned_sections_do_not_share_mutable_values(self):
        document = {'service': {'hosts': ['first']}}
        with patch('runtime.nacos_config.fetch_config', side_effect=lambda **kw: document):
            first = ConfigSnapshot()
            section = first.get('service')
            section['hosts'].append('caller')
            document['service']['hosts'].append('second')
            self.assertEqual(first.get('service'), {'hosts': ['first']})
            self.assertEqual(ConfigSnapshot().get('service'), {'hosts': ['first', 'second']})

    def test_remote_values_are_data_not_recursive_references(self):
        config = ConfigSnapshot(values={'service.value': '${env:SECRET}'})
        self.assertEqual(config.resolve('${service.value}'), '${env:SECRET}')
