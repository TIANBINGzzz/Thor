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


def customer_config():
    return {'deployment': {'tenantId': 'customer-a'},
            'model': {'baseUrl': 'https://model.example.test/apps/anthropic', 'apiKey': 'private-model-key'},
            'security': {'runtimeJwtSecret': 'private-runtime-key',
                         'observationJwtSecret': 'private-observation-key'},
            'runtime': {'timeouts': {'execution-ms': 4200000},
                        'models': {'default': 'custom-model', 'available': ['custom-model'],
                                   'sdk': dict.fromkeys(('haiku', 'sonnet', 'opus', 'subagent'), 'custom-model')}},
            'databases': {'schoolDoubleHigh': {
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
        worker['deployment']['tenantId'] = 'changed'
        self.assertEqual(deployment_config.deployment_section('deployment')['tenantId'], 'customer-a')

    def test_invalid_deployment_fails_without_publishing_or_echoing_secrets(self):
        self.assertTrue(callable(getattr(deployment_config, 'initialize_deployment', None)))
        for section, field, value in [('deployment', 'tenantId', '*'), ('deployment', 'tenantId', ''),
                                      ('model', 'baseUrl', 'http://model.test'), ('model', 'apiKey', ''),
                                      ('security', 'runtimeJwtSecret', ''),
                                      ('security', 'observationJwtSecret', 'private-runtime-key')]:
            invalid = copy.deepcopy(self.document)
            invalid[section][field] = value
            with self.subTest(section=section, field=field), self.assertRaises(ValueError) as caught:
                self.initialize(invalid)
            self.assertNotIn('private-', str(caught.exception))
            self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_deployment_binding_rejects_other_customer(self):
        self.initialize()
        deployment_config.require_tenant('customer-a')
        with self.assertRaisesRegex(ValueError, 'tenant'):
            deployment_config.require_tenant('customer-b')

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

    def test_bootstrap_loads_only_bootstrap_keys_and_process_environment_wins(self):
        import tempfile
        from runtime import bootstrap
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.env').write_text('CCSDK_NACOS_GROUP=base\nCCSDK_NACOS_PASSWORD=base\n'
                                      'ANTHROPIC_AUTH_TOKEN=old-secret\n', encoding='utf-8')
            (root / '.env.local').write_text('CCSDK_NACOS_GROUP=local\nCCSDK_NACOS_PASSWORD=local\n'
                                            'CCSDK_RUNTIME_JWT_SECRET=old-secret\n', encoding='utf-8')
            before = dict(os.environ)
            with patch.object(bootstrap, '__file__', str(root / 'python/runtime/bootstrap.py')), \
                    patch.object(bootstrap, 'initialize_deployment', return_value={}) as initialize:
                bootstrap.initialize_runtime(env={'CCSDK_NACOS_GROUP': 'process'})
            selected = initialize.call_args.args[0]
            self.assertEqual(selected['CCSDK_NACOS_GROUP'], 'process')
            self.assertEqual(selected['CCSDK_NACOS_PASSWORD'], 'local')
            self.assertNotIn('ANTHROPIC_AUTH_TOKEN', selected)
            self.assertNotIn('CCSDK_RUNTIME_JWT_SECRET', selected)
            self.assertEqual(dict(os.environ), before)

    def test_nacos_unavailable_does_not_publish_old_environment_secrets(self):
        environment = {'CCSDK_NACOS_URL': 'https://nacos.example.test',
                       'ANTHROPIC_AUTH_TOKEN': 'old-secret', 'CCSDK_RUNTIME_JWT_SECRET': 'old-secret'}
        with self.assertRaises(ValueError) as caught:
            deployment_config.initialize_deployment(environment,
                transport=httpx.MockTransport(lambda request: httpx.Response(503, text='private-response')))
        self.assertNotIn('private-response', str(caught.exception))
        self.assertIsNone(deployment_config._DEPLOYMENT)

    def test_empty_issuer_and_optional_service_mistakes_are_rejected_before_publish(self):
        cases = [({'runtimeJwtIssuer': None}, 'security'), ({'runtimeJwtIssuer': ''}, 'security'),
                 ({'runtimeJwtAudience': None}, 'security'), (None, 'images'), (False, 'images'), ({}, 'images'),
                 (None, 'fileBroker'), ({'url': 'http://broker.example.test'}, 'fileBroker'),
                 ({'url': 'https://broker.example.test', 'allowedHosts': 'host.test'}, 'fileBroker'),
                 ({'url': 'https://broker.example.test', 'authMode': 'service'}, 'fileBroker'),
                 ({'url': 'https://broker.example.test', 'clientKey': 'client.key'}, 'fileBroker')]
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
            self.document['runtime']['observability'] = {'enabled': True, 'storage': 'customer.sqlite'}
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
    def test_one_read_resolves_nested_references_without_mutating_assets(self):
        requests = []

        def respond(request):
            requests.append(request)
            return httpx.Response(200, text='service:\n  url: https://service.test/mcp\n'
                                  '  timeout: 12\n  enabled: false\nprivate: secret\n')

        template = {'url': '${service.url}', 'options': ['${service.timeout}', '${service.enabled}'],
                    'static': 'fixed'}
        original = copy.deepcopy(template)
        config = ConfigSnapshot({'CCSDK_NACOS_URL': 'http://nacos.test'},
                                transport=httpx.MockTransport(respond))
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
            server = ConfigSnapshot({'CCSDK_NACOS_PASSWORD': 'private-password'})
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
        with patch('runtime.nacos_config.fetch_config', side_effect=lambda env, **kw: document):
            first = ConfigSnapshot()
            section = first.get('service')
            section['hosts'].append('caller')
            document['service']['hosts'].append('second')
            self.assertEqual(first.get('service'), {'hosts': ['first']})
            self.assertEqual(ConfigSnapshot().get('service'), {'hosts': ['first', 'second']})

    def test_remote_values_are_data_not_recursive_references(self):
        config = ConfigSnapshot(values={'service.value': '${env:SECRET}'})
        self.assertEqual(config.resolve('${service.value}'), '${env:SECRET}')
