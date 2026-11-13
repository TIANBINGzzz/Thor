import tempfile
import unittest
import copy
from pathlib import Path
from unittest.mock import patch
import yaml

from runtime import runtime_settings


class ModelSettingsTests(unittest.TestCase):
    def test_each_source_capability_clears_previous_reasoning_configuration(self):
        from runtime import config, capabilities
        previous = {'model': 'old-model', 'thinking': {'type': 'disabled'}, 'effort': 'high'}
        for capability in capabilities.CAPABILITIES.values():
            entry = capabilities.capability_entry(capability.directory)
            if not Path(capability.directory).is_relative_to(capabilities.CAPABILITIES_ROOT):
                continue
            declared = entry['runtime']
            with self.subTest(capability=capability.ref):
                self.assertTrue({'model', 'thinking', 'effort'} <= declared.keys())
                with patch.object(config, 'prepare_capability_assets', return_value={'runtime': declared}):
                    effective = config.inherit_client_runtime({'capability_ref': capability.ref}, previous)
                self.assertEqual(effective['thinking'], declared['thinking'])
                self.assertEqual(effective['effort'], declared['effort'])
                self.assertNotIn('model', effective)

    def test_disabled_reasoning_is_explicit_in_provider_request_environment(self):
        from runtime import config
        entry = copy.deepcopy(config.load_execution_entry('conversation')['capability'])
        entry['runtime'] = {'model': '', 'thinking': {'type': 'disabled'}, 'effort': 'low'}
        with patch.object(config, 'load_execution_entry', return_value={'capability': entry}):
            options = config.build_options({})
        import json
        self.assertEqual(json.loads(options.env['CLAUDE_CODE_EXTRA_BODY']), {'thinking': {'type': 'disabled'}})
        self.assertEqual(options.model, config.MODEL_SETTINGS.default)

    def test_capability_model_is_selected_for_agent_and_web(self):
        from runtime import config
        entry = copy.deepcopy(config.load_execution_entry('conversation')['capability'])
        entry['runtime'] = {'model': 'other', 'thinking': {'type': 'adaptive'}, 'effort': 'medium'}
        with tempfile.TemporaryDirectory() as folder:
            settings = runtime_settings.load_model_settings(self.config(folder))
            with patch.object(config, 'MODEL_SETTINGS', settings), \
                    patch.object(config, 'load_execution_entry', return_value={'capability': entry}), \
                    patch('tools.web_search.deployment_section', return_value={
                        'baseUrl': 'https://example.maas.aliyuncs.com/apps/anthropic', 'apiKey': 'model-secret'}), \
                    patch('tools.web_search.create_web_server', return_value={}) as web:
                options = config.build_options({'model': settings.default})
            self.assertEqual(options.model, 'other')
            self.assertEqual(web.call_args.kwargs['model'], 'other')
            self.assertEqual(options.thinking, {'type': 'adaptive'})
            self.assertEqual(options.effort, 'medium')

    def test_trusted_capability_selects_model_without_a_second_allowlist(self):
        from runtime import config
        assets = config.prepare_capability_assets({})
        assets['runtime']['model'] = 'new-provider-model'
        options = config.build_options({'_capability_assets': assets})
        self.assertEqual(options.model, 'new-provider-model')

    def test_runtime_model_accepts_default_or_name_but_not_connections(self):
        from runtime.capabilities import _validate_runtime
        for value in ('', 'deepseek-v4.1-flash'):
            self.assertEqual(_validate_runtime({'model': value})['model'], value)
        for value in (None, 123, True, [], {}, ' ', ' padded', 'https://model.example.test'):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _validate_runtime({'model': value})

    def test_capability_model_reaches_http_payload_and_blank_client(self):
        import server
        from runtime import config
        from runtime.claude_sdk import ClientTurnPolicy
        from runtime.protocol import AgentRunRequest
        request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'cap-model',
            'messageId': 'm1', 'domainName': 'school.example.test', 'input': {'text': 'hello'}})
        entry = copy.deepcopy(config.load_execution_entry('conversation')['capability'])
        entry['runtime'] = {'model': 'other'}
        with tempfile.TemporaryDirectory() as folder:
            settings = runtime_settings.load_model_settings(self.config(folder))
            with patch.object(config, 'MODEL_SETTINGS', settings), patch.object(server, 'DEFAULT_MODEL', settings.default):
                payload = server._internal_worker_payload(request, Path(folder), execution_entry={'capability': entry})
                self.assertEqual(payload['model'], 'other')
                self.assertEqual(config.build_client_options(payload, ClientTurnPolicy()).model, 'other')

    def config(self, folder):
        path = Path(folder) / 'application.yml'
        path.write_text(yaml.safe_dump({'runtime': {'models': {
            'default': 'preferred', 'available': ['other', 'preferred'],
            'sdk': {'haiku': 'preferred', 'sonnet': 'preferred',
                    'opus': 'other', 'subagent': 'preferred'},
        }}}), encoding='utf-8')
        return path

    def test_explicit_nacos_file_ignores_local_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(folder)
            settings = runtime_settings.load_model_settings(path)
            self.assertEqual(settings.default, 'preferred')
            path.with_name('application.local.yml').write_text(
                'runtime:\n  models:\n    default: other\n    sdk:\n      haiku: other\n', encoding='utf-8')
            settings = runtime_settings.load_model_settings(path)
            self.assertEqual(settings.default, 'preferred')
            self.assertEqual(settings.sdk['haiku'], 'preferred')
            self.assertEqual(settings.sdk['sonnet'], 'preferred')

    def test_invalid_models_fail_without_env_fallback(self):
        invalid = [None, {}, {'default': 'unknown'}, {'available': []},
                   {'available': ['preferred', 'preferred']}, {'sdk': {'opus': 'unknown'}},
                   {'sdk': {'typo': 'preferred'}}, {'default': ' '}, {'available': 'preferred'}]
        with tempfile.TemporaryDirectory() as folder:
            for value in invalid:
                with self.subTest(value=value):
                    path = self.config(folder)
                    document = yaml.safe_load(path.read_text(encoding='utf-8'))
                    if isinstance(value, dict) and value:
                        document['runtime']['models'].update(value)
                    else:
                        document['runtime']['models'] = value
                    path.write_text(yaml.safe_dump(document), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'runtime.models'):
                        runtime_settings.load_model_settings(path)

    def test_yaml_controls_sdk_environment_and_options(self):
        from runtime import config
        with patch.dict('os.environ', {'ANTHROPIC_MODEL': 'obsolete',
                                      'ANTHROPIC_DEFAULT_HAIKU_MODEL': 'obsolete'}, clear=True):
            environment = config.agent_environment()
            self.assertEqual(environment['ANTHROPIC_MODEL'], config.MODEL_SETTINGS.default)
            self.assertEqual(environment['ANTHROPIC_DEFAULT_HAIKU_MODEL'], config.MODEL_SETTINGS.sdk['haiku'])
            self.assertEqual(config.worker_environment()['ANTHROPIC_MODEL'], config.MODEL_SETTINGS.default)
            self.assertEqual(config.build_options({}).model, config.MODEL_SETTINGS.default)
            self.assertNotIn('ANTHROPIC_MODEL', config.missing_environment())

    def test_missing_model_configuration_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'application.yml'
            for text in ('nacos: {}', 'runtime: {models: {default: preferred}}', 'runtime: []'):
                with self.subTest(text=text):
                    path.write_text(text, encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'runtime.models'):
                        runtime_settings.load_model_settings(path)

    def test_http_payload_uses_explicit_default_not_first_available(self):
        import server
        from runtime.protocol import AgentRunRequest
        request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'model-config',
            'messageId': 'm1', 'domainName': 'school.example.test', 'input': {'text': 'hello'}})
        with tempfile.TemporaryDirectory() as folder:
            settings = runtime_settings.load_model_settings(self.config(folder))
            with patch.object(server, 'DEFAULT_MODEL', settings.default):
                payload = server._internal_worker_payload(request, Path(folder))
            self.assertEqual(payload['model'], server.load_execution_entry('conversation')['capability']['runtime']['model'])
            self.assertNotEqual(payload['model'], settings.available[0])
