"""完整 YAML 启动配置与环境版本的遗漏检测。"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

from runtime import bootstrap


from tests.deployment_fixtures import application_document

class ApplicationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('runtime.application_config._APPLICATION', None))

    def test_all_fields_required_and_unknown_or_wrong_types_fail_without_secret_values(self):
        from runtime.application_config import validate_application
        document = application_document()
        self.assertEqual(validate_application(document), document)
        for section, fields in document.items():
            for field in fields:
                invalid = copy.deepcopy(document)
                del invalid[section][field]
                with self.subTest(missing=section+'.'+field), self.assertRaisesRegex(ValueError, 'application_config_invalid'):
                    validate_application(invalid)
        for invalid in (document | {'typo': {}}, document | {'server': document['server'] | {'port': True}},
                        document | {'nacos': document['nacos'] | {'password': 'private-secret'}},
                        document | {'network': document['network'] | {'https-proxy': 'bad-proxy'}},
                        document | {'nacos': document['nacos'] | {'request-timeout-ms': 0}}):
            with self.assertRaises(ValueError) as error:
                validate_application(invalid)
            self.assertNotIn('private-secret', str(error.exception))

    def test_only_selected_complete_yaml_supplies_process_and_nacos_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = application_document()
            document['tools']['officecli'] = '${LOCALAPPDATA}/OfficeCLI/officecli.exe'
            path = root/'application.yml'
            path.write_text(yaml.safe_dump(document), encoding='utf-8')
            (root/'.env').write_text('CCSDK_NACOS_URL=http://old-env.test\n', encoding='utf-8')
            (root/'application.local.yml').write_text('nacos: {server-addr: http://old-local.test}', encoding='utf-8')
            with patch.dict(os.environ, {'LOCALAPPDATA': str(root), 'CCSDK_NACOS_URL': 'http://process.test',
                                         'HTTP_PROXY': 'http://old-proxy.test', 'ALL_PROXY': 'http://old-proxy.test'}, clear=True), \
                    patch('runtime.bootstrap.initialize_deployment', return_value={}) as initialize:
                bootstrap.initialize_runtime(config_path=path)
                self.assertEqual(initialize.call_args.kwargs['nacos'], document['nacos'])
                self.assertNotIn('HTTP_PROXY', os.environ)
                self.assertNotIn('ALL_PROXY', os.environ)
                self.assertEqual(Path(os.environ['CCSDK_OFFICECLI_PATH']), root/'OfficeCLI/officecli.exe')
                self.assertNotIn('CCSDK_NACOS_PASSWORD', os.environ)

    def test_duplicate_keys_and_unresolved_path_variables_are_rejected(self):
        from runtime.application_config import load_application
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'application.yml'
            path.write_text(yaml.safe_dump(application_document()) + '\nnacos: {}\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'application_config_invalid'):
                load_application(path)
            document = application_document()
            document['tools']['officecli'] = '${UNKNOWN_PRIVATE_VARIABLE}/officecli'
            path.write_text(yaml.safe_dump(document), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'application_config_invalid'):
                load_application(path)

    def test_unfilled_production_bootstrap_is_rejected_before_network_access(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'application.yml'
            document = application_document()
            document['nacos'].update(username='replace-nacos-reader', password='replace-nacos-password')
            path.write_text(yaml.safe_dump(document), encoding='utf-8')
            with patch('runtime.bootstrap.initialize_deployment') as initialize:
                with self.assertRaisesRegex(ValueError, '^application_config_invalid$'):
                    bootstrap.initialize_runtime(config_path=path)
                initialize.assert_not_called()

    def test_repository_variants_have_identical_field_paths_and_types(self):
        root = Path(__file__).resolve().parents[2]/'config'
        def signature(document, prefix=''):
            result = {}
            for key, value in document.items():
                name = prefix+'.'+key if prefix else key
                if isinstance(value, dict):
                    result.update(signature(value, name))
                else:
                    result[name] = type(value).__name__
            return result
        for base in ('application', 'nacos-ai-center-agent-service'):
            paths = [root/f'{base}{suffix}.yml' for suffix in ('.example', '.production')]
            local = root/f'{base}.yml'
            if local.exists():
                paths.append(local)
            with self.subTest(family=base):
                documents = [yaml.safe_load(path.read_text(encoding='utf-8')) for path in paths]
                expected = signature(documents[0])
                for path, document in zip(paths, documents):
                    self.assertEqual(signature(document), expected, path.name)
                    for line in path.read_text(encoding='utf-8').splitlines():
                        if line.strip() and not line.lstrip().startswith('#'):
                            self.assertIn(' # ', line, path.name)
