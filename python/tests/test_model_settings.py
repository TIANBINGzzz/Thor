import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

from runtime import runtime_settings


class ModelSettingsTests(unittest.TestCase):
    def config(self, folder):
        path = Path(folder) / 'application.yml'
        path.write_text(yaml.safe_dump({'runtime': {'models': {
            'default': 'preferred', 'available': ['other', 'preferred'],
            'sdk': {'haiku': 'preferred', 'sonnet': 'preferred',
                    'opus': 'other', 'subagent': 'preferred'},
        }}}), encoding='utf-8')
        return path

    def test_explicit_default_and_local_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.config(folder)
            settings = runtime_settings.load_model_settings(path)
            self.assertEqual(settings.default, 'preferred')
            path.with_name('application.local.yml').write_text(
                'runtime:\n  models:\n    default: other\n    sdk:\n      haiku: other\n', encoding='utf-8')
            settings = runtime_settings.load_model_settings(path)
            self.assertEqual(settings.default, 'other')
            self.assertEqual(settings.sdk['haiku'], 'other')
            self.assertEqual(settings.sdk['sonnet'], 'preferred')

    def test_invalid_models_fail_without_env_fallback(self):
        invalid = [None, {}, {'default': 'unknown'}, {'available': []},
                   {'available': ['preferred', 'preferred']}, {'sdk': {'opus': 'unknown'}},
                   {'sdk': {'typo': 'preferred'}}, {'default': ' '}, {'available': 'preferred'}]
        with tempfile.TemporaryDirectory() as folder:
            for value in invalid:
                with self.subTest(value=value):
                    path = self.config(folder)
                    path.with_name('application.local.yml').write_text(
                        yaml.safe_dump({'runtime': {'models': value}}), encoding='utf-8')
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
            'messageId': 'm1', 'input': {'text': 'hello'}})
        with tempfile.TemporaryDirectory() as folder:
            settings = runtime_settings.load_model_settings(self.config(folder))
            with patch.object(server, 'DEFAULT_MODEL', settings.default):
                payload = server._internal_worker_payload(request, Path(folder))
            self.assertEqual(payload['model'], 'preferred')
            self.assertNotEqual(payload['model'], settings.available[0])
