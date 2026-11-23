import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from runtime.claude_sdk import ClaudeSDKClient, ClientState, SDKExecutionError, build_agent_options


class DynamicClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_hook_denies_unlisted_builtin_and_background_shell(self):
        from runtime.claude_sdk import ClientTurnPolicy
        from runtime.config import build_client_options
        policy = ClientTurnPolicy()
        options = build_client_options({'capability_ref': 'conversation'}, policy)
        policy.bind(options)
        self.assertEqual(await policy.authorize({'tool_name': 'Read'}, None, {}), {})
        self.assertEqual(await policy.authorize({'tool_name': 'WebFetch'}, None, {}), {})
        for name in ('CronCreate', 'ScheduleWakeup', 'Workflow', 'SendMessage', 'Task', 'FutureTool'):
            with self.subTest(name=name):
                result = await policy.authorize({'tool_name': name}, None, {})
                self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
        for name in ('Bash', 'PowerShell'):
            result = await policy.authorize({'tool_name': name, 'tool_input': {'run_in_background': True}}, None, {})
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')

    async def test_settings_update_without_mcp_change_and_explicit_reset(self):
        from runtime.claude_sdk import build_agent_options
        query = SimpleNamespace(_send_control_request=AsyncMock(return_value={}))
        provider = SimpleNamespace(_query=query, set_model=AsyncMock(), set_permission_mode=AsyncMock())
        baseline = build_agent_options(model='same', env={'ANTHROPIC_AUTH_TOKEN': 'base'}, mcp_servers={})
        client = ClaudeSDKClient(baseline)
        client._provider, client._state = provider, ClientState.READY
        turn = build_agent_options(model='same', mcp_servers={}, thinking={'type': 'disabled'},
            effort='low', add_dirs=['work'], permission_mode='bypassPermissions',
            env={'ANTHROPIC_AUTH_TOKEN': 'changed', 'CLAUDE_CODE_EXTRA_BODY': '{"thinking":{"type":"disabled"}}'})
        await client.configure_turn(turn)
        calls = [call.args[0] for call in query._send_control_request.await_args_list]
        self.assertIn({'subtype': 'set_max_thinking_tokens', 'max_thinking_tokens': 0}, calls)
        settings = next(value['settings'] for value in calls if value['subtype'] == 'apply_flag_settings')
        self.assertEqual(settings['env']['ANTHROPIC_AUTH_TOKEN'], 'changed')
        self.assertEqual(settings['permissions']['additionalDirectories'], ['work'])
        self.assertEqual(settings['effortLevel'], 'low')
        query._send_control_request.reset_mock()
        await client.configure_turn(baseline)
        calls = [call.args[0] for call in query._send_control_request.await_args_list]
        self.assertIn({'subtype': 'set_max_thinking_tokens', 'max_thinking_tokens': None}, calls)
        settings = next(value['settings'] for value in calls if value['subtype'] == 'apply_flag_settings')
        self.assertEqual(settings['env']['ANTHROPIC_AUTH_TOKEN'], 'base')
        self.assertEqual(settings['env']['CLAUDE_CODE_EXTRA_BODY'], '{}')
        self.assertEqual(settings['permissions']['additionalDirectories'], [])
        self.assertIsNone(settings['effortLevel'])

    async def test_turn_policy_replaces_rules_and_denies_old_or_missing_grants(self):
        from runtime.claude_sdk import ClientTurnPolicy
        policy = ClientTurnPolicy()
        options = SimpleNamespace(system_prompt={'append': 'RULE_A'}, tools=[],
                                  allowed_tools=['mcp__first__read'], disallowed_tools=[])
        policy.bind(options)
        context = await policy.context({}, None, {})
        self.assertIn('RULE_A', str(context))
        self.assertEqual(await policy.authorize({'tool_name': 'mcp__first__read'}, None, {}), {})
        self.assertEqual((await policy.authorize({'tool_name': 'Bash'}, None, {}))['hookSpecificOutput']['permissionDecision'], 'deny')
        options.system_prompt = 'RULE_B'
        options.allowed_tools = ['mcp__second__read']
        policy.bind(options)
        self.assertNotIn('RULE_A', str(await policy.context({}, None, {})))
        self.assertEqual((await policy.authorize({'tool_name': 'mcp__first__read'}, None, {}))['hookSpecificOutput']['permissionDecision'], 'deny')
        policy.clear()
        self.assertEqual((await policy.authorize({'tool_name': 'mcp__second__read'}, None, {}))['hookSpecificOutput']['permissionDecision'], 'deny')

    async def test_replacing_same_name_mcp_closes_old_bridge_and_preserves_unchanged(self):
        from claude_agent_sdk._internal.query import Query
        from unittest.mock import Mock
        from runtime.claude_sdk import create_sdk_mcp_server
        old = create_sdk_mcp_server(name='probe', tools=[])
        new = create_sdk_mcp_server(name='probe', tools=[])
        transport = Mock()
        query = Query(transport=transport, is_streaming_mode=True,
                      sdk_mcp_servers={'probe': old['instance']})
        bridge = query._sdk_mcp_bridges['probe']
        bridge.aclose = AsyncMock()
        query._send_control_request = AsyncMock(return_value={'errors': {}})
        provider = SimpleNamespace(_query=query, set_model=AsyncMock())
        client = ClaudeSDKClient(build_agent_options(model='old', mcp_servers={'probe': old}))
        client._provider = provider
        client._state = ClientState.READY
        await client.configure_turn(build_agent_options(model='new', mcp_servers={'probe': new}))
        self.assertIs(query.sdk_mcp_servers['probe'], new['instance'])
        bridge.aclose.assert_awaited_once()
        provider.set_model.assert_awaited_once_with('new')
        calls = query._send_control_request.await_args_list
        self.assertEqual(calls[0].args[0]['servers'], {})
        fresh = query._sdk_mcp_bridges['probe']
        await client.configure_turn(build_agent_options(model='new', mcp_servers={'probe': new}))
        self.assertIs(query._sdk_mcp_bridges['probe'], fresh)
        self.assertEqual(query._send_control_request.await_count, 2)
        await fresh.aclose()
        query._message_send.close()
        query.close_receive_stream()

    async def test_control_failure_marks_client_failed_and_never_queries(self):
        provider = SimpleNamespace(_query=SimpleNamespace(
            _send_control_request=AsyncMock(return_value={'errors': {'business': 'private'}}),
            sdk_mcp_servers={}, _sdk_mcp_bridges={}),
            disconnect=AsyncMock(), set_model=AsyncMock())
        client = ClaudeSDKClient(build_agent_options(model='same', mcp_servers={}))
        client._provider = provider
        client._state = ClientState.READY
        with self.assertRaises(SDKExecutionError):
            await client.configure_turn(build_agent_options(model='same', mcp_servers={'business': {'type': 'http', 'url': 'http://invalid'}}))
        self.assertEqual(client.state, ClientState.FAILED)
        with self.assertRaises(SDKExecutionError):
            await client.query('should never run')

class ConnectionFingerprintTests(unittest.TestCase):
    def test_direct_and_agent_share_builtin_tools_and_prewarm_group(self):
        from unittest.mock import patch
        from runtime.config import build_client_options, client_connection_fingerprint, load_execution_entry
        from runtime.claude_sdk import ClientTurnPolicy
        direct = {'capability_ref': 'campus-brain-query'}
        agent = {'capability_ref': 'conversation'}
        # 与预热入口一致，只传已解析的启动参数，不装配本轮业务 Service。
        for payload in (direct, agent):
            payload['_client_runtime'] = load_execution_entry(payload['capability_ref'])['capability'].get('runtime', {})
        direct_tools = build_client_options(direct, ClientTurnPolicy()).tools
        tools = build_client_options(agent, ClientTurnPolicy()).tools
        self.assertEqual(direct_tools, tools)
        self.assertIsInstance(tools, list)
        self.assertTrue({'Read', 'Write', 'Edit', 'Glob', 'Grep'} <= set(tools))
        self.assertFalse({'Task', 'CronCreate', 'ScheduleWakeup', 'Workflow', 'SendMessage'} & set(tools))
        self.assertEqual(client_connection_fingerprint(direct), client_connection_fingerprint(agent))

    def test_queued_turn_uses_its_own_configuration_without_previous_settings(self):
        from unittest.mock import patch
        from runtime.config import inherit_client_runtime
        payload = {'_capability_assets': {'runtime': {'effort': 'low'}}}
        with patch('runtime.config.prepare_capability_assets', side_effect=lambda value: value['_capability_assets']):
            inherit_client_runtime(payload, {'thinking': {'type': 'disabled'}, 'max_turns': 7})
            latest = {'thinking': {'type': 'enabled', 'budget_tokens': 2048}, 'effort': 'high', 'max_turns': 9}
            runtime = inherit_client_runtime(payload, latest)
            self.assertEqual(runtime, {'effort': 'low', 'max_turns': 200, 'system_prompt_snapshot': True})
            self.assertEqual(payload['_capability_assets']['runtime'], {'effort': 'low'})

    def test_enabled_thinking_requires_and_preserves_sdk_budget(self):
        from runtime.capabilities import _validate_runtime
        value = {'thinking': {'type': 'enabled', 'budget_tokens': 2048}}
        self.assertEqual(_validate_runtime(value), value)
        for thinking in ({'type': 'enabled'}, {'type': 'enabled', 'budget_tokens': True},
                         {'type': 'enabled', 'budget_tokens': 0},
                         {'type': 'disabled', 'budget_tokens': 2048}):
            with self.assertRaises(RuntimeError):
                _validate_runtime({'thinking': thinking})

    def test_explicit_null_max_turns_resets_inherited_limit_to_yaml(self):
        from unittest.mock import patch
        from runtime.config import inherit_client_runtime, build_client_options
        from runtime.claude_sdk import ClientTurnPolicy
        assets = {'runtime': {'max_turns': None}}
        payload = {}
        with patch('runtime.config.prepare_capability_assets', return_value=assets):
            runtime = inherit_client_runtime(payload, {'max_turns': 7})
            self.assertEqual(runtime['max_turns'], 200)
            self.assertEqual(build_client_options(payload, ClientTurnPolicy()).max_turns, 200)

    def test_blank_client_matches_first_conversation_connection_without_a_workspace(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import server
        from runtime.protocol import AgentRunRequest
        from runtime.config import client_connection_fingerprint
        with tempfile.TemporaryDirectory() as root, patch.object(server, 'CLIENT_SESSION_ROOT', Path(root)):
            blank = server._blank_client_payload()
            request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'r',
                'messageId': 'm', 'businessSessionId': 's', 'domainName': 'school.example.test',
                'input': {'text': 'hello'}})
            actual = server._internal_worker_payload(request, Path(root) / 'run',
                runtime_mode='client', session_directory=Path(root) / 'session')
            self.assertNotIn('session_directory', blank)
            self.assertNotIn('additional_directories', blank)
            self.assertEqual(blank['_client_connection_fingerprint'], client_connection_fingerprint(actual))

    def test_only_immutable_options_rebuild_client(self):
        from runtime.config import client_connection_fingerprint
        from unittest.mock import patch
        assets = {'runtime': {}}
        with patch('runtime.config.prepare_capability_assets', return_value=assets):
            base = {'cwd': '.', 'additional_directories': ['workspace'], 'model': 'a'}
            first = client_connection_fingerprint(base)
            changed = {**base, 'model': 'b', 'capability_ref': 'chart-generation',
                       'credentials': {'platformBearer': 'changed'}}
            self.assertEqual(first, client_connection_fingerprint(changed))
            assets['runtime'] = {'thinking': {'type': 'disabled'}}
            self.assertEqual(first, client_connection_fingerprint(base))
            assets['runtime'] = {'effort': 'low'}
            self.assertEqual(first, client_connection_fingerprint({**base, 'additional_directories': ['other']}))
            assets['runtime'] = {'max_turns': 7}
            self.assertNotEqual(first, client_connection_fingerprint(base))

class ClientPoolReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_yaml_host_tool_settings_match_prewarmed_client(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import server
        from runtime import capabilities
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until

        class Worker:
            alive = False
            awaiting_connection = False
            process = None

            async def preconnect(self, payload):
                self.initial = payload
                self.alive = True

            async def terminate(self):
                self.alive = False

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / 'capability.env'
            binary = root / 'bin' / 'officecli'
            binary.parent.mkdir()
            binary.touch()
            private.write_text(f'CCSDK_OFFICECLI_PATH={binary.as_posix()}\n', encoding='utf-8')
            entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
            with patch('runtime.config.PROJECT_ROOT', root), \
                 patch.dict('os.environ', {'CCSDK_OFFICECLI_PATH':str(binary)}), \
                 patch.object(server, 'CLIENT_SESSION_ROOT', root / 'clients'):
                profile = server._startup_profile({'capability': entry})
                pool = WorkerPool(max_idle=1, max_starting=1, profile_payloads=[{
                    **profile, 'credentials': {'platformBearer': 'must-not-prewarm'},
                    'context': {'tenantId': 'must-not-prewarm'}}],
                    payload_factory=server._blank_client_payload, worker_factory=Worker)
                pool.start()
                try:
                    await until(lambda: pool.snapshot()['ready'] == 1)
                    worker = await pool.acquire(initial_payload={**profile, 'session_directory': str(root / 'work')})
                    self.assertEqual(pool.snapshot()['hits'], 1)
                    self.assertNotIn('credentials', worker.initial)
                    self.assertNotIn('context', worker.initial)
                    await worker.terminate()
                finally:
                    await pool.close()

    async def test_new_fixed_group_rebalances_shared_inventory(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        class Worker:
            alive = False
            awaiting_connection = False
            process = None
            async def preconnect(self, payload):
                self.alive = True
            async def terminate(self):
                self.alive = False
        base = {'_client_connection_fingerprint': 'base'}
        pool = WorkerPool(max_idle=6, max_starting=2,
            profile_payloads=[base],
            payload_factory=dict,
            worker_factory=lambda **kw: Worker())
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 6)
            special = {'_client_connection_fingerprint': 'special'}
            pool.register_profile(special)
            await until(lambda: pool.snapshot()['groups'].get('special') == 3)
            self.assertEqual(pool.snapshot()['groups'], {'base': 3, 'special': 3})
            worker = await pool.acquire(special)
            self.assertTrue(worker.alive)
            self.assertEqual(pool.snapshot()['live'], 6)
        finally:
            await pool.close()

    async def test_compatible_groups_share_inventory_and_incompatible_worker_is_left_for_others(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        class Worker:
            alive = False
            awaiting_connection = False
            process = None
            async def preconnect(self, payload):
                self.initial = payload
                self.alive = True
            async def terminate(self):
                self.alive = False
        profiles = [{'_client_connection_fingerprint': name} for name in ('default', 'special')]
        pool = WorkerPool(max_idle=6, max_starting=2,
            profile_payloads=profiles,
            payload_factory=dict,
            worker_factory=lambda **kw: Worker())
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 6)
            cold = await pool.acquire({'_client_connection_fingerprint': 'missing'})
            cold._ccsdk_release_start_slot()
            self.assertFalse(cold.alive)
            self.assertEqual(pool.snapshot()['ready'], 6)
            leases = [await pool.acquire(profiles[index % 2]) for index in range(6)]
            self.assertEqual(len(set(leases)), 6)
            self.assertEqual([worker.initial for worker in leases], profiles * 3)
            self.assertEqual(pool.snapshot()['hits'], 6)
        finally:
            await pool.close()

class ConfigurationEnvironmentTests(unittest.TestCase):
    def test_connection_fingerprint_ignores_removed_environment_files(self):
        import os,tempfile
        from pathlib import Path
        from unittest.mock import patch
        from runtime import config
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'capability.env').write_text('ANTHROPIC_AUTH_TOKEN=private-stale-value\n',encoding='utf-8')
            with patch.object(config,'PROJECT_ROOT',root),patch.object(config,'prepare_capability_assets',return_value={'runtime':{}}):
                before=dict(os.environ)
                self.assertEqual(config.client_connection_fingerprint({}),config.client_connection_fingerprint({'capability_ref':'conversation'}))
                self.assertEqual(dict(os.environ),before)
                self.assertNotIn('ANTHROPIC_AUTH_TOKEN',config._client_connection_values({})['env'])
