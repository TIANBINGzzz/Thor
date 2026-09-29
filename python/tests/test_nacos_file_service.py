"""Nacos 配置读取、环境隔离及失败关闭边界。"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
import yaml

from runtime.file_service import FileServiceError, file_service_config


class NacosFileServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = {'CCSDK_NACOS_URL': 'http://nacos.test:8848/nacos',
                    'CCSDK_NACOS_USERNAME': 'reader', 'CCSDK_NACOS_PASSWORD': 'private-password',
                    'CCSDK_NACOS_NAMESPACE': 'test-id'}
        self.config = {'fileService': {'baseUrl': 'https://files.test',
                       'remoteUrl': 'https://public.test', 'domainName': 'routing.test',
                       'downloadPath': '/files/{fileId}/download'}}

    def read(self, handler, **kwargs):
        return file_service_config(self.env, transport=httpx.MockTransport(handler), **kwargs)

    def test_authentication_namespace_and_snapshot(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertNotIn('private-password', str(request.url))
            self.assertNotIn('private-access-token', str(request.url))
            if request.method == 'POST':
                self.assertEqual(request.url.path, '/nacos/v1/auth/login')
                self.assertEqual(parse_qs(request.content.decode())['password'], ['private-password'])
                return httpx.Response(200, json={'accessToken': 'private-access-token'})
            self.assertEqual(request.headers['authorization'], 'Bearer private-access-token')
            self.assertEqual(dict(request.url.params), {'tenant': 'test-id',
                             'group': 'DEFAULT_GROUP', 'dataId': 'ai-center-agent-service'})
            return httpx.Response(200, json=self.config)
        old = self.read(handle, download=True)
        self.config['fileService']['baseUrl'] = 'https://new-files.test'
        new = self.read(handle, download=True)
        self.assertEqual(old['baseUrl'], 'https://files.test')
        self.assertEqual(new['baseUrl'], 'https://new-files.test')
        self.assertEqual(len(requests), 4)

    def test_public_namespace_custom_group_and_no_auth(self):
        self.env = {'CCSDK_NACOS_URL': 'http://nacos.test:8848',
                    'CCSDK_NACOS_NAMESPACE': 'public',
                    'CCSDK_NACOS_GROUP': 'staging', 'CCSDK_NACOS_DATA_ID': 'files.json'}
        def handle(request):
            self.assertEqual(request.url.path, '/nacos/v1/cs/configs')
            self.assertNotIn('authorization', request.headers)
            self.assertEqual(dict(request.url.params), {'group': 'staging', 'dataId': 'files.json'})
            return httpx.Response(200, json=self.config)
        self.read(handle)

    def test_network_auth_missing_and_invalid_config_fail_without_secrets(self):
        self.env.pop('CCSDK_NACOS_USERNAME')
        self.env.pop('CCSDK_NACOS_PASSWORD')
        for status, body, code in [(403, 'private-secret', 'file_service_nacos_unavailable'),
                                   (404, 'private-secret', 'file_service_not_configured'),
                                   (200, 'private-secret', 'file_service_config_invalid'),
                                   (200, '[]', 'file_service_config_invalid'),
                                   (200, '{}', 'file_service_not_configured')]:
            with self.subTest(status=status, body=body):
                with self.assertRaises(FileServiceError) as error:
                    self.read(lambda _: httpx.Response(status, text=body))
                self.assertEqual(str(error.exception), code)
        def timeout(request):
            raise httpx.ConnectTimeout('private-secret', request=request)
        with self.assertRaisesRegex(FileServiceError, '^file_service_nacos_unavailable$'):
            self.read(timeout)

    def test_bootstrap_validation_before_network(self):
        for env in ({'CCSDK_NACOS_URL': ''}, {'CCSDK_NACOS_URL': 'http://user:password@nacos.test'},
                    {'CCSDK_NACOS_URL': 'http://nacos.test/?token=secret'},
                    {'CCSDK_NACOS_URL': 'http://nacos.test', 'CCSDK_NACOS_USERNAME': 'reader'}):
            self.env = env
            with self.subTest(env=env), self.assertRaises(FileServiceError):
                self.read(lambda _: self.fail('invalid settings must not access Nacos'))

    def test_invalid_download_path_rejected_before_transfer(self):
        self.env = {'CCSDK_NACOS_URL': 'http://nacos.test'}
        self.config['fileService']['downloadPath'] = '//evil.test/{fileId}'
        with self.assertRaisesRegex(FileServiceError, '^file_service_config_invalid$'):
            self.read(lambda _: httpx.Response(200, json=self.config), download=True)

    def test_yaml_and_unsafe_yaml(self):
        self.env = {'CCSDK_NACOS_URL': 'http://nacos.test'}
        result = self.read(lambda _: httpx.Response(200, text=yaml.safe_dump(self.config)))
        self.assertEqual(result['baseUrl'], 'https://files.test')
        with self.assertRaisesRegex(FileServiceError, '^file_service_config_invalid$'):
            self.read(lambda _: httpx.Response(200, text='!!python/object/apply:builtins.print [secret]'))

    def test_bad_login_never_fetches_config_and_does_not_expose_response(self):
        for status, body in [(403, 'private-password'), (200, '{}'),
                             (200, '{"accessToken":null}'), (200, 'private-password')]:
            requests = []
            def handle(request):
                requests.append(request)
                return httpx.Response(status, text=body)
            with self.subTest(status=status, body=body):
                with self.assertRaisesRegex(FileServiceError, '^file_service_nacos_unavailable$'):
                    self.read(handle)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].method, 'POST')

    def test_nacos_credentials_excluded_from_model_and_worker_environments(self):
        from runtime.config import agent_environment, worker_environment
        with patch.dict('os.environ', self.env):
            for environment in (agent_environment(), worker_environment()):
                self.assertFalse(any(key.startswith('CCSDK_NACOS_') for key in environment))

    def test_slow_stream_and_oversized_config_are_stopped(self):
        self.env = {'CCSDK_NACOS_URL': 'http://nacos.test'}
        ticks = [0]
        class SlowStream(httpx.SyncByteStream):
            def __iter__(self):
                for _ in range(20):
                    ticks[0] += 1
                    yield b' '
        with patch('runtime.nacos_config.time.monotonic', side_effect=lambda: ticks[0]):
            with self.assertRaisesRegex(FileServiceError, '^file_service_nacos_unavailable$'):
                self.read(lambda _: httpx.Response(200, stream=SlowStream()))
        self.assertLessEqual(ticks[0], 10)
        with self.assertRaisesRegex(FileServiceError, '^file_service_nacos_unavailable$'):
            self.read(lambda _: httpx.Response(200, content=b' ' * (128 * 1024 + 1)))

    def test_application_yaml_supplies_bootstrap_and_environment_can_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            path.write_text(yaml.safe_dump({'nacos': {'server-addr': 'yaml-nacos.test:8848',
                'namespace': 'yaml-namespace', 'group': 'yaml-group', 'data-id': 'yaml-service'}}))
            self.env = {}
            def handle(request):
                self.assertEqual(request.url.host, 'yaml-nacos.test')
                self.assertEqual(request.url.path, '/nacos/v1/cs/configs')
                self.assertEqual(dict(request.url.params), {'tenant': 'yaml-namespace',
                    'group': 'yaml-group', 'dataId': 'yaml-service'})
                return httpx.Response(200, json=self.config)
            with patch('runtime.nacos_config.APPLICATION_CONFIG_FILE', path):
                self.read(handle)
                self.env = {'CCSDK_NACOS_URL': 'https://override.test/nacos',
                    'CCSDK_NACOS_NAMESPACE': '', 'CCSDK_NACOS_GROUP': 'override',
                    'CCSDK_NACOS_DATA_ID': 'override-service'}
                def overridden(request):
                    self.assertEqual(str(request.url).split('?')[0], 'https://override.test/nacos/v1/cs/configs')
                    self.assertEqual(dict(request.url.params), {'group': 'override', 'dataId': 'override-service'})
                    return httpx.Response(200, json=self.config)
                self.read(overridden)

    def test_invalid_application_yaml_fails_before_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            with patch('runtime.nacos_config.APPLICATION_CONFIG_FILE', path):
                for content in (None, '[]', 'nacos: [bad]', 'nacos: {server-addr: 123}',
                                'nacos: {server-addr: localhost:8848, namespace: null}',
                                'nacos: {server-addr: localhost:8848, password: secret}'):
                    if content is not None:
                        path.write_text(content)
                    with self.subTest(content=content):
                        with self.assertRaisesRegex(FileServiceError, '^file_service_nacos_config_invalid$'):
                            self.read(lambda _: self.fail('invalid YAML must not access Nacos'))

    def test_local_yaml_merges_fields_and_environment_has_highest_priority(self):
        from runtime.nacos_config import _nacos_settings
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            path.write_text(yaml.safe_dump({'nacos': {'server-addr': 'base.test:8848',
                'namespace': 'base-tenant', 'group': 'base-group', 'data-id': 'base-service'}}))
            local = path.with_name('application.local.yml')
            with patch('runtime.nacos_config.APPLICATION_CONFIG_FILE', path):
                self.assertEqual(_nacos_settings({})['CCSDK_NACOS_URL'], 'http://base.test:8848')
                local.write_text('nacos:\n  server-addr: local.test:8848\n  namespace: ""\n')
                merged = _nacos_settings({})
                self.assertEqual(merged, {'CCSDK_NACOS_URL': 'http://local.test:8848',
                    'CCSDK_NACOS_NAMESPACE': '', 'CCSDK_NACOS_GROUP': 'base-group',
                    'CCSDK_NACOS_DATA_ID': 'base-service',
                    'CCSDK_NACOS_USERNAME': '', 'CCSDK_NACOS_PASSWORD': ''})
                self.assertEqual(_nacos_settings({'CCSDK_NACOS_URL': 'https://env.test'})['CCSDK_NACOS_URL'],
                                 'https://env.test')
                self.assertEqual(_nacos_settings({'CCSDK_NACOS_URL': ''})['CCSDK_NACOS_URL'], '')
                local.unlink()
                self.assertEqual(_nacos_settings({})['CCSDK_NACOS_URL'], 'http://base.test:8848')

    def test_invalid_local_yaml_is_not_silently_ignored(self):
        from runtime.nacos_config import _nacos_settings, NacosConfigError
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            path.write_text(yaml.safe_dump({'nacos': {'server-addr': 'base.test:8848',
                'namespace': '', 'group': 'base-group', 'data-id': 'base-service'}}))
            local = path.with_name('application.local.yml')
            with patch('runtime.nacos_config.APPLICATION_CONFIG_FILE', path):
                for content in ('[]', '', 'nacos: null', 'nacos: {server-addr: null}',
                                'nacos: {password: 123}', 'nacos: {unknown: value}', 'nacos: ['):
                    local.write_text(content)
                    with self.subTest(content=content), self.assertRaisesRegex(
                            NacosConfigError, '^nacos_config_invalid$'):
                        _nacos_settings({})

    def test_yaml_credentials_authenticate_and_environment_overrides(self):
        from runtime.nacos_config import fetch_config
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            path.write_text(yaml.safe_dump({'nacos': {'server-addr': 'nacos.test:8848',
                'namespace': '', 'group': 'DEFAULT_GROUP', 'data-id': 'service',
                'username': 'yaml-user', 'password': 'yaml-$^password'}}))
            for env, expected in (({}, b'username=yaml-user&password=yaml-%24%5Epassword'),
                    ({'CCSDK_NACOS_USERNAME': 'env-user', 'CCSDK_NACOS_PASSWORD': 'env-password'},
                     b'username=env-user&password=env-password')):
                calls = []
                def handle(request):
                    calls.append(request.url.path)
                    if request.url.path.endswith('/auth/login'):
                        self.assertEqual(request.content, expected)
                        return httpx.Response(200, json={'accessToken': 'test-token'})
                    self.assertEqual(request.headers['Authorization'], 'Bearer test-token')
                    return httpx.Response(200, text='fileService: {}\ncampusMcp: {}\n')
                with patch('runtime.nacos_config.APPLICATION_CONFIG_FILE', path):
                    self.assertEqual(set(fetch_config(env, transport=httpx.MockTransport(handle))),
                                     {'fileService', 'campusMcp'})
                self.assertEqual(calls, ['/nacos/v1/auth/login', '/nacos/v1/cs/configs'])
