import dataclasses
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from runtime import runtime_settings


class RuntimeSettingsTests(unittest.TestCase):
    def write_config(self, directory):
        path = Path(directory) / 'application.yml'
        path.write_text('''runtime:
  timeouts:
    execution-ms: 3600000
    client-queue-ms: 300000
    client-idle-ms: 300000
    file-prepare-ms: 600000
    file-broker-ms: 15000
    file-upload-connect-ms: 10000
    worker-start-ms: 60000
    worker-send-ms: 5000
    worker-close-ms: 5000
    worker-control-ms: 5000
    document-render-ms: 180000
    document-start-ms: 30000
    image-ms: 600000
    web-search-ms: 90000
    mcp-http-ms: 30000
    nacos-ms: 10000
    nacos-request-ms: 5000
  limits:
    max-turns: 30
    file-max-bytes: 268435456
    sdk-buffer-bytes: 16777216
    http-body-bytes: 2097152
    prompt-bytes: 32768
  sse-heartbeat-ms: 15000
''', encoding='utf-8')
        return path

    def test_local_fields_override_yaml_without_environment_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_config(folder)
            path.with_name('application.local.yml').write_text(
                'runtime:\n  timeouts:\n    execution-ms: 4200000\n  limits:\n    max-turns: 42\n',
                encoding='utf-8')
            with patch.dict('os.environ', {'CCSDK_RUN_EXECUTION_TIMEOUT_MS': '1',
                                          'SCRIBE_MAX_TURNS': '1'}):
                settings = runtime_settings.load_runtime_settings(path)
            self.assertEqual(settings.timeouts.execution_ms, 4200000)
            self.assertEqual(settings.timeouts.file_prepare_ms, 600000)
            self.assertEqual(settings.limits.max_turns, 42)
            self.assertEqual(settings.sse_heartbeat_ms, 15000)
            with self.assertRaises(dataclasses.FrozenInstanceError):
                settings.sse_heartbeat_ms = 1

    def test_missing_and_invalid_budgets_fail_before_execution(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_config(folder)
            original = yaml.safe_load(path.read_text(encoding='utf-8'))
            for section, field, value in [('timeouts', 'execution-ms', 0),
                                          ('timeouts', 'client-idle-ms', True),
                                          ('timeouts', 'image-ms', '600000'),
                                          ('timeouts', 'typo-ms', 10),
                                          ('limits', 'max-turns', -1)]:
                with self.subTest(section=section, field=field, value=value):
                    local = {'runtime': {section: {field: value}}}
                    path.with_name('application.local.yml').write_text(yaml.safe_dump(local), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'runtime'):
                        runtime_settings.load_runtime_settings(path)
            path.with_name('application.local.yml').unlink()
            for value in (None, False, '15000', 0):
                with self.subTest(heartbeat=value):
                    path.with_name('application.local.yml').write_text(
                        yaml.safe_dump({'runtime': {'sse-heartbeat-ms': value}}), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, 'runtime'):
                        runtime_settings.load_runtime_settings(path)
            path.with_name('application.local.yml').unlink()
            del original['runtime']['timeouts']['execution-ms']
            path.write_text(yaml.safe_dump(original), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'runtime'):
                runtime_settings.load_runtime_settings(path)

    def test_yaml_limits_reach_sdk_and_file_download(self):
        from runtime import config, file_broker
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_config(folder)
            path.with_name('application.local.yml').write_text('''runtime:
  limits:
    max-turns: 47
    sdk-buffer-bytes: 8388608
    file-max-bytes: 4096
  timeouts:
    file-broker-ms: 2500
''', encoding='utf-8')
            settings = runtime_settings.load_runtime_settings(path)
            with patch.object(config, 'RUNTIME_SETTINGS', settings), \
                 patch.object(file_broker, 'RUNTIME_SETTINGS', settings), \
                 patch.dict('os.environ', {'SCRIBE_MAX_TURNS': '1', 'CCSDK_FILE_MAX_BYTES': '1',
                                          'CCSDK_FILE_BROKER_TIMEOUT_MS': '1'}):
                options = config.build_options({})
                self.assertEqual(options.max_turns, 47)
                self.assertEqual(options.max_buffer_size, 8388608)
                self.assertEqual(config._client_connection_values({})['max_turns'], 47)
                broker = file_broker.FileBroker('https://broker.example.test/grant')
                self.assertEqual(broker.max_bytes, 4096)
                self.assertEqual(broker.timeout_ms, 2500)

    def test_fresh_process_uses_one_budget_in_server_worker_and_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write_config(folder)
            path.with_name('application.local.yml').write_text('''runtime:
  timeouts:
    execution-ms: 4200000
    worker-start-ms: 2345
    worker-close-ms: 678
    client-idle-ms: 3456
''', encoding='utf-8')
            script = '''import sys
from runtime import runtime_settings
runtime_settings.RUNTIME_SETTINGS = runtime_settings.load_runtime_settings(sys.argv[1])
import server, agent_worker
from runtime.process import ClientWorkerProcess
from runtime.claude_sdk import ClaudeSDKClient, build_agent_options
assert server.RUN_EXECUTION_TIMEOUT_MS == agent_worker.DEFAULT_TIMEOUT_MS == 4200000
assert server._create_session_manager()._idle_ttl_ms == 3456
worker = ClientWorkerProcess()
assert (worker.start_timeout_ms, worker.close_timeout_ms) == (2345, 678)
client = ClaudeSDKClient(build_agent_options(model='test'))
assert (client._connect_timeout_ms, client._disconnect_timeout_ms) == (2345, 678)
assert client._query_timeout_ms == client._receive_timeout_ms == 4200000
'''
            result = subprocess.run([sys.executable, '-c', script, str(path)],
                                    cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
