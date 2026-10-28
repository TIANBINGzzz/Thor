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
    def test_direct_and_agent_use_separate_prewarm_groups(self):
        from runtime.config import build_client_options, client_connection_fingerprint
        from runtime.claude_sdk import ClientTurnPolicy
        direct = {'capability_ref': 'campus-brain-query'}
        agent = {'capability_ref': 'conversation'}
        self.assertEqual(build_client_options(direct, ClientTurnPolicy()).tools, [])
        tools = build_client_options(agent, ClientTurnPolicy()).tools
        self.assertIsInstance(tools, list)
        self.assertTrue({'Read', 'Write', 'Edit', 'Glob', 'Grep'} <= set(tools))
        self.assertFalse({'Task', 'CronCreate', 'ScheduleWakeup', 'Workflow', 'SendMessage'} & set(tools))
        self.assertNotEqual(client_connection_fingerprint(direct), client_connection_fingerprint(agent))

    def test_queued_turn_inherits_latest_settings_without_freezing_old_inheritance(self):
        from unittest.mock import patch
        from runtime.config import inherit_client_runtime
        payload = {'_capability_assets': {'runtime': {'effort': 'low'}}}
        with patch('runtime.config.prepare_capability_assets', side_effect=lambda value: value['_capability_assets']):
            inherit_client_runtime(payload, {'thinking': {'type': 'disabled'}, 'max_turns': 7})
            latest = {'thinking': {'type': 'enabled', 'budget_tokens': 2048}, 'effort': 'high', 'max_turns': 9}
            runtime = inherit_client_runtime(payload, latest)
            self.assertEqual(runtime, {**latest, 'effort': 'low', 'system_prompt_snapshot': True})
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

    def test_blank_client_matches_first_conversation_connection(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import server
        from runtime.protocol import AgentRunRequest
        from runtime.config import client_connection_fingerprint
        with tempfile.TemporaryDirectory() as root, patch.object(server, 'CLIENT_SESSION_ROOT', Path(root)):
            blank = server._blank_client_payload()
            request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'r',
                'messageId': 'm', 'businessSessionId': 's', 'input': {'text': 'hello'}})
            actual = server._internal_worker_payload(request, Path(root) / 'run',
                runtime_mode='client', session_directory=Path(blank['session_directory']))
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

class ClientPoolWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_capability_environment_matches_prewarmed_client(self):
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
                 patch('runtime.config.capability_environment_path', return_value=private), \
                 patch.object(server, 'CLIENT_SESSION_ROOT', root / 'clients'):
                profile = server._startup_profile({'capability': entry})
                pool = WorkerPool(max_idle=1, max_starting=1, profile_payloads=[{
                    **profile, 'credentials': {'platformBearer': 'must-not-prewarm'},
                    'context': {'tenantId': 'must-not-prewarm'}}],
                    payload_factory=server._blank_client_payload, worker_factory=Worker)
                pool.start()
                try:
                    await until(lambda: pool.snapshot()['ready'] == 1)
                    directory = pool.reserve_workspace(profile)
                    self.assertIsNotNone(directory)
                    worker = await pool.acquire(initial_payload={**profile, 'session_directory': directory})
                    self.assertEqual(pool.snapshot()['hits'], 1)
                    self.assertNotIn('credentials', worker.initial)
                    self.assertNotIn('context', worker.initial)
                    await worker.terminate()
                finally:
                    await pool.close()

    async def test_new_fixed_group_rebalances_shared_inventory(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        from uuid import uuid4
        class Worker:
            alive = False
            awaiting_connection = False
            process = None
            async def preconnect(self, payload):
                self.alive = True
            async def terminate(self):
                self.alive = False
        base = {'_client_connection_fingerprint': 'base'}
        pool = WorkerPool(max_idle=6, max_starting=2, max_live=24,
            profile_payloads=[base],
            payload_factory=lambda profile: {**profile, 'session_directory': uuid4().hex},
            worker_factory=lambda **kw: Worker())
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 6)
            special = {'_client_connection_fingerprint': 'special'}
            pool.register_profile(special)
            await until(lambda: pool.snapshot()['groups'].get('special') == 3)
            self.assertEqual(pool.snapshot()['groups'], {'base': 3, 'special': 3})
            self.assertIsNotNone(pool.reserve_workspace(special))
            self.assertEqual(pool.snapshot()['live'], 6)
        finally:
            await pool.close()

    async def test_reservation_matches_before_removing_and_groups_share_budget(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        from uuid import uuid4
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
        pool = WorkerPool(max_idle=6, max_starting=2, max_live=24,
            profile_payloads=profiles,
            payload_factory=lambda profile: {**profile, 'session_directory': uuid4().hex},
            worker_factory=lambda **kw: Worker())
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 6)
            self.assertIsNone(pool.reserve_workspace({'_client_connection_fingerprint': 'missing'}))
            self.assertEqual(pool.snapshot()['ready'], 6)
            directories = [pool.reserve_workspace(profiles[index % 2]) for index in range(6)]
            self.assertTrue(all(directories))
            await asyncio.sleep(.02)
            self.assertEqual(pool.snapshot()['ready'] + pool.snapshot()['starting'] + pool.snapshot()['reserved'], 6)
            leases = [await pool.acquire(initial_payload={'session_directory': directory,
                **profiles[index % 2]}) for index, directory in enumerate(directories)]
            self.assertEqual(len(leases), 6)
            self.assertEqual(pool.snapshot()['hits'], 6)
        finally:
            await pool.close()

    async def test_parallel_cold_leases_respect_total_limit_until_terminated(self):
        from runtime.worker_pool import WorkerPool
        from runtime.process import ClientWorkerError
        class Worker:
            alive = False
            awaiting_connection = True
            process = None
            async def terminate(self):
                self.awaiting_connection = False
        pool = WorkerPool(max_idle=0, max_starting=1, max_live=2,
                          worker_factory=lambda **kwargs: Worker())
        try:
            results = await asyncio.gather(*(pool.acquire() for _ in range(6)), return_exceptions=True)
            leased = [item for item in results if isinstance(item, Worker)]
            self.assertEqual(len(leased), 2)
            self.assertEqual(sum(isinstance(item, ClientWorkerError) for item in results), 4)
            await leased[0].terminate()
            self.assertIsInstance(await pool.acquire(), Worker)
        finally:
            await pool.close()

    async def test_history_restore_cancels_starting_client_and_returns_capacity(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        made = []
        class Worker:
            alive = False
            awaiting_connection = True
            process = None
            terminated = False
            async def preconnect(self, payload):
                await asyncio.Event().wait()
            async def terminate(self):
                self.terminated = True
                self.awaiting_connection = False
        def factory(**kwargs):
            worker = Worker()
            made.append(worker)
            return worker
        pool = WorkerPool(max_idle=1, max_starting=1, max_live=1,
                          payload_factory=lambda: {'session_directory': 'blank'}, worker_factory=factory)
        pool.start()
        try:
            await until(lambda: len(made) == 1)
            restored = await pool.acquire(initial_payload={'resume': 'history'})
            self.assertTrue(made[0].terminated)
            self.assertIs(restored, made[1])
            self.assertEqual(pool.snapshot()['starting'], 0)
        finally:
            await pool.close()

    async def test_idle_clients_do_not_block_history_restore_at_total_limit(self):
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import FakeWorker, until
        FakeWorker.created = []
        FakeWorker.gate = asyncio.Event()
        FakeWorker.gate.set()
        pool = WorkerPool(max_idle=1, max_starting=1, max_live=1, worker_factory=FakeWorker)
        pool.start()
        try:
            await until(lambda: pool.snapshot()['ready'] == 1)
            # SDK 预连接模式不能把另一目录的空白连接拿来恢复历史。
            pool._payload_factory = lambda: {}
            restored = await pool.acquire(initial_payload={'session_directory': 'existing', 'resume': 'history'})
            self.assertFalse(restored.alive)
            self.assertTrue(FakeWorker.created[0].terminated)
            await until(lambda: FakeWorker.created[0].terminated)
        finally:
            await pool.close()

    async def test_server_reserves_only_for_new_identity_binding(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock, patch
        import server
        from runtime.run_store import RunStore
        with tempfile.TemporaryDirectory() as root, RunStore(':memory:') as store:
            directory = Path(root) / ('a' * 32)
            pool = Mock()
            pool.reserve_workspace.return_value = str(directory)
            with patch.multiple(server, RUN_STORE=store, CLIENT_SESSION_ROOT=Path(root), WORKER_POOL=pool):
                key = json.dumps(['t', 'u', 'session', 's'])
                self.assertEqual(server._client_session_directory(key), directory)
                self.assertEqual(server._client_session_directory(key), directory)
                pool.reserve_workspace.assert_called_once()
                self.assertEqual(store.find_workspace('t', 'u', 'session', 's'), 'a' * 32)

    async def test_preconnected_client_is_bound_once_to_its_reserved_workspace(self):
        import tempfile
        from pathlib import Path
        from runtime.worker_pool import WorkerPool
        from tests.test_worker_pool import until
        made = []
        class Worker:
            alive = False
            awaiting_connection = False
            process = None
            async def preconnect(self, payload):
                self.initial = payload
                self.alive = True
            async def terminate(self):
                self.alive = False
        with tempfile.TemporaryDirectory() as root:
            def payload():
                directory = str(Path(root) / str(len(made)))
                made.append(directory)
                return {'session_directory': directory, '_client_connection_fingerprint': 'fixed'}
            pool = WorkerPool(max_idle=2, max_starting=1, max_live=3,
                              payload_factory=payload, worker_factory=lambda **kw: Worker())
            pool.start()
            try:
                await until(lambda: pool.snapshot()['ready'] == 2)
                workspace = pool.reserve_workspace()
                self.assertIn(workspace, made)
                self.assertEqual(pool.snapshot()['reserved'], 1)
                worker = await pool.acquire(initial_payload={'session_directory': workspace, '_client_connection_fingerprint': 'fixed'})
                self.assertTrue(worker.alive)
                self.assertEqual(worker.initial['session_directory'], workspace)
                self.assertEqual(pool.snapshot()['reserved'], 0)
                other = pool.reserve_workspace()
                self.assertNotEqual(other, workspace)
                pool.release_workspace(other)
                await until(lambda: pool.snapshot()['ready'] == 2)
                self.assertTrue(worker.alive)
            finally:
                await pool.close()

class WorkflowEnvironmentTests(unittest.TestCase):
    def test_connection_fingerprint_uses_selected_environment_without_mutation(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from runtime import config
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / '.env').write_text('ANTHROPIC_BASE_URL=http://base.test\nSCRIBE_MAX_TURNS=30\n')
            path = root / 'capability.env'
            path.write_text('ANTHROPIC_BASE_URL=http://flow.test\nSCRIBE_MAX_TURNS=8\n'
                            'ANTHROPIC_AUTH_TOKEN=${PROBE_AUTH}-flow\n')
            with patch.object(config, 'PROJECT_ROOT', root), \
                 patch.object(config, '_capability_environment_original', {}), \
                 patch.dict(os.environ, {'PROBE_AUTH': 'synthetic'}), \
                 patch.object(config, 'capability_entry', return_value={'_directory': str(path.parent)}), \
                 patch.object(config, 'capability_environment_path', return_value=path), \
                 patch.object(config, 'prepare_capability_assets', return_value={'runtime': {}}):
                before = dict(os.environ)
                base = config.client_connection_fingerprint({})
                selected = config.client_connection_fingerprint({'capability_ref': 'conversation'})
                self.assertEqual(base, selected)
                self.assertEqual(before, dict(os.environ))
                try:
                    config.load_runtime_environment('conversation')
                    values = config._client_connection_values({'capability_ref': 'conversation'})
                    self.assertNotIn('ANTHROPIC_AUTH_TOKEN', values['env'])
                    self.assertEqual(values['max_turns'], config.RUNTIME_SETTINGS.limits.max_turns)
                    self.assertNotIn('ANTHROPIC_BASE_URL', values['env'])
                    self.assertEqual(selected, config.client_connection_fingerprint({'capability_ref': 'conversation'}))
                    self.assertEqual(base, config.client_connection_fingerprint({}))
                finally:
                    config.load_runtime_environment(None)

    def test_switch_removes_prior_capability_values_and_restores_inherited_values(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from runtime import config
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'FLOW_BASE': 'inherited'}):
            path = Path(root) / 'capability.env'
            path.write_text('FLOW_BASE=selected\nFLOW_ONLY=private\n')
            with patch.object(config, 'PROJECT_ROOT', Path(root)), \
                 patch.object(config, 'capability_entry', return_value={'_directory': str(path.parent)}), \
                 patch.object(config, 'capability_environment_path', return_value=path):
                try:
                    config.load_runtime_environment('conversation')
                    self.assertEqual(os.environ['FLOW_BASE'], 'selected')
                    config.load_runtime_environment(None)
                    self.assertEqual(os.environ['FLOW_BASE'], 'inherited')
                    self.assertNotIn('FLOW_ONLY', os.environ)
                finally:
                    config.load_runtime_environment(None)
