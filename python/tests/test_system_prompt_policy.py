import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from runtime.claude_sdk import ClientTurnPolicy
from runtime.config import build_options, build_client_options, client_connection_fingerprint, inherit_client_runtime


class SystemPromptPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # 提示词/SDK 装配单测使用离线可信配置，不依赖校园配置中心的可用性。
        self.enterContext(patch('runtime.nacos_config.fetch_config', return_value={
            'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'}}))

    async def test_custom_prompt_is_injected_as_current_turn_rules(self):
        options = build_options({'capability_ref': 'campus-brain-query', 'run_id': 'prompt-test-run',
                                 'credentials': {'platformBearer': 'test-secret'}})
        policy = ClientTurnPolicy()
        policy.bind(options)
        context = (await policy.context({}, None, {}))['hookSpecificOutput']['additionalContext']
        self.assertIn('至少 8', context)
        self.assertEqual(options.system_prompt['type'], 'custom')
        self.assertIn(options.system_prompt['prompt'], context)
        self.assertNotIn('test-secret', context)

    async def test_snapshot_is_passed_to_both_prompt_modes_and_blank_clients(self):
        from runtime.capabilities import capability_entry, CAPABILITIES
        for ref in ('conversation', 'campus-brain-query'):
            for snapshot in (True, False):
                with self.subTest(ref=ref, snapshot=snapshot):
                    entry = capability_entry(CAPABILITIES[ref].directory)
                    entry.setdefault('runtime', {})['system_prompt_snapshot'] = snapshot
                    payload = {'capability_ref': ref, 'run_id': 'prompt-test-run',
                               'credentials': {'platformBearer': 'test-secret'}}
                    with patch('runtime.config.capability_entry', return_value=entry):
                        inherit_client_runtime(payload)
                        options = build_options(payload)
                        blank = build_client_options(payload, ClientTurnPolicy())
                    self.assertIs(options.system_prompt['snapshot'], snapshot)
                    self.assertIs(blank.system_prompt['snapshot'], snapshot)
                    self.assertTrue(options.verbatim_prompts)
                    self.assertTrue(blank.verbatim_prompts)
                    self.assertNotIn('至少 8', blank.system_prompt['prompt'])


class SnapshotConfigTests(unittest.TestCase):
    def test_snapshot_accepts_only_boolean_values(self):
        from runtime.capabilities import _validate_runtime
        for value in (True, False):
            self.assertEqual(_validate_runtime({'system_prompt_snapshot': value}),
                             {'system_prompt_snapshot': value})
        for value in (None, 0, 1, 'false', {}, []):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _validate_runtime({'system_prompt_snapshot': value})

    def test_snapshot_inherits_overrides_and_separates_only_fixed_groups(self):
        assets = {'runtime': {}}
        with patch('runtime.config.prepare_capability_assets', return_value=assets):
            first = {}
            self.assertIs(inherit_client_runtime(first)['system_prompt_snapshot'], True)
            restored = {}
            self.assertIs(inherit_client_runtime(restored, {'system_prompt_snapshot': False})['system_prompt_snapshot'], False)
            self.assertNotEqual(client_connection_fingerprint(first), client_connection_fingerprint(restored))
            assets['runtime'] = {'system_prompt_snapshot': True}
            self.assertIs(inherit_client_runtime(restored, {'system_prompt_snapshot': False})['system_prompt_snapshot'], True)
            self.assertEqual(client_connection_fingerprint(first), client_connection_fingerprint(restored))

    def test_startup_profiles_and_run_store_preserve_snapshot(self):
        import server
        from runtime.run_store import RunStore
        profile = server._startup_profile({'capability': {'ref': 'conversation', 'runtime': {}}},
                                          {'system_prompt_snapshot': False})
        self.assertIs(profile['_client_runtime']['system_prompt_snapshot'], False)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'runs.sqlite3'
            with RunStore(path) as store:
                store.create_run('r', tenant_id='t', user_id='u', business_session_id='s')
                store.save_client_runtime('r', {'system_prompt_snapshot': False})
            with RunStore(path) as store:
                self.assertEqual(store.latest_client_runtime('t', 'u', 's'), {'system_prompt_snapshot': False})
                self.assertEqual(store.latest_client_runtime('other', 'u', 's'), {})

