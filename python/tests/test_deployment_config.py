"""统一配置引用的读取、类型保留和 Worker 快照边界。"""

import copy
import unittest
from unittest.mock import patch

import httpx

from runtime.deployment_config import ConfigSnapshot, ConfigReferenceError


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
