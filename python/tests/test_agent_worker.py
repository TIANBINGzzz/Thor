import unittest
import os
import asyncio
import io
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock, ToolUseBlock

import agent_worker
from agent_worker import direct_workflow_event, event_from_stream, events_from_assistant
from runtime.claude_sdk import ClientState, SDKMessage, build_agent_options
from runtime.config import (
    build_options,
    build_system_prompt,
    create_run_services,
    agent_environment,
    MODEL_SETTINGS,
    worker_environment,
    load_workflow_config,
    load_runtime_environment,
    workflow_environment_path,
    workflow_prompt_documents,
)


class AgentWorkerTests(unittest.TestCase):
    def test_worker_reads_utf8_json_under_local_encoding(self):
        import json
        import os
        import subprocess
        import sys
        root = Path(__file__).resolve().parents[2]
        env = {**os.environ, 'PYTHONPATH': str(root / 'python'), 'PYTHONUTF8': '0',
               'PYTHONIOENCODING': 'gbk'}
        payload = {'prompt': '按章节撰写，保留“学校”原文；参数使用 JSON。'}
        result = subprocess.run(
            [sys.executable, '-c', 'import agent_worker,json,sys; print(json.dumps(json.load(sys.stdin),ensure_ascii=False))'],
            input=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            capture_output=True, env=env, cwd=root, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(result.stdout.decode('utf-8')), payload)

    def test_artifact_prompt_exposes_only_current_output_directories(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict("os.environ", {}, clear=True):
            work = str(Path(folder) / "work")
            output = str(Path(folder) / "output")
            options = build_options({"session_directory": folder, "work_directory": work,
                                     "deliverables_directory": output, "skill_refs": []})
        prompt = options.system_prompt["append"]
        self.assertIn(work, prompt)
        self.assertIn(output, prompt)
        self.assertIn("mcp__artifacts__publish_file", prompt)
        self.assertIn("不输出服务器本地路径", prompt)

    def test_data_tools_are_capability_selected(self):
        from runtime.capabilities import resolve_capability
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(create_run_services({}))
            capability = resolve_capability("national-excellence-data-qa")
            config = load_workflow_config("double-high-qa")
            self.assertEqual(config["data_access"], "required")
            self.assertNotIn("data_sources", config)
            options = build_options({"workflow_name": capability.workflow_ref, "capability_ref": capability.ref})
        self.assertEqual(options.tools, [])
        self.assertEqual(options.skills, [])
        self.assertEqual(options.setting_sources, [])
        self.assertTrue(options.strict_mcp_config)
        self.assertEqual(list(options.mcp_servers), ["data"])
        self.assertEqual(options.allowed_tools, ["mcp__data__*"])
        self.assertIn("不要再次调用 Skill、Workflow、Task", options.system_prompt["append"])

    def test_enabled_capabilities_and_fixed_template_mount_web_search(self):
        values = {'ANTHROPIC_BASE_URL': 'https://workspace.cn-beijing.maas.aliyuncs.com/apps/anthropic',
                  'ANTHROPIC_AUTH_TOKEN': 'model-secret', 'ANTHROPIC_MODEL': 'deepseek-v4.1-flash'}
        with patch.dict('os.environ', values, clear=True), tempfile.TemporaryDirectory() as folder:
            for payload in ({}, {'capability_ref': 'conversation'}, {'capability_ref': 'chart-generation'},
                            {'capability_ref': 'document-writing', 'workflow_name': 'writing-docx'},
                            {'capability_ref': 'document-writing', 'workflow_name': 'writing-docx',
                             '_template_key': 'szpt-midterm', 'session_directory': folder,
                             'work_directory': str(Path(folder) / 'work'),
                             'deliverables_directory': str(Path(folder) / 'output')}):
                with self.subTest(payload=payload):
                    options = build_options(payload)
                    self.assertIn('web', options.mcp_servers)
                    self.assertIn('mcp__web__search', options.allowed_tools)
                    self.assertIn('WebSearch', options.disallowed_tools)
                    self.assertIn('mcp__web__search', options.system_prompt['append'])
                    self.assertNotIn('没有可用的联网搜索能力', options.system_prompt['append'])
                    self.assertNotIn('model-secret', options.system_prompt['append'])
                    self.assertNotIn('当前通用问答', options.system_prompt['append'])

    def test_unconfigured_capabilities_do_not_enable_provider_web_search(self):
        self.enterContext(patch('runtime.nacos_config.fetch_config', return_value={'campusMcp': {
            'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'}}))
        values = {'ANTHROPIC_BASE_URL': 'https://workspace.cn-beijing.maas.aliyuncs.com/apps/anthropic',
                  'ANTHROPIC_AUTH_TOKEN': 'model-secret', 'ANTHROPIC_MODEL': 'deepseek-v4.1-flash'}
        from runtime.capabilities import CAPABILITIES
        with patch.dict('os.environ', values, clear=True):
            for capability in CAPABILITIES.values():
                if capability.ref in {'conversation', 'chart-generation', 'document-writing'}:
                    continue
                with self.subTest(capability=capability.ref):
                    options = build_options({'capability_ref': capability.ref,
                                             'credentials': {'platformBearer': 'test-business-token'},
                                             'workflow_name': capability.workflow_ref})
                    self.assertNotIn('web', options.mcp_servers)
                    self.assertNotIn('mcp__web__search', options.allowed_tools)
                    self.assertIn('WebSearch', options.disallowed_tools)
                    self.assertIn('没有可用的联网搜索能力', options.system_prompt.get('prompt', options.system_prompt.get('append', '')))

    def test_web_search_follows_trusted_capability_configuration_not_payload(self):
        from runtime.capabilities import CAPABILITIES, capability_entry
        values = {'ANTHROPIC_BASE_URL': 'https://workspace.cn-beijing.maas.aliyuncs.com/apps/anthropic',
                  'ANTHROPIC_AUTH_TOKEN': 'model-secret', 'ANTHROPIC_MODEL': 'deepseek-v4.1-flash'}
        configured = capability_entry(CAPABILITIES['chart-generation'].directory)
        configured['tools'].remove('web')
        with patch.dict('os.environ', values, clear=True), patch('runtime.config.capability_entry', return_value=configured):
            options = build_options({'capability_ref': 'chart-generation', 'web_search': True,
                                     'tools': ['mcp__web__search']})
        self.assertNotIn('web', options.mcp_servers)
        self.assertIn('没有可用的联网搜索能力', options.system_prompt['append'])
        self.assertNotIn('web_search', CAPABILITIES['chart-generation'].to_public_dict())

    def test_missing_or_non_bailian_provider_does_not_advertise_web_search(self):
        for base in ('', 'https://other.test/apps/anthropic'):
            with self.subTest(base=base), patch.dict('os.environ', {
                'ANTHROPIC_BASE_URL': base, 'ANTHROPIC_AUTH_TOKEN': 'secret', 'ANTHROPIC_MODEL': 'qwen'}, clear=True):
                options = build_options({'capability_ref': 'conversation'})
                self.assertNotIn('web', options.mcp_servers)
                self.assertIn('没有可用的联网搜索能力', options.system_prompt['append'])

    def test_web_search_reuses_selected_model_key_without_business_token(self):
        from tools.web_search import create_web_server
        values = {'ANTHROPIC_BASE_URL': 'https://workspace.cn-beijing.maas.aliyuncs.com/apps/anthropic',
                  'ANTHROPIC_AUTH_TOKEN': 'model-secret', 'ANTHROPIC_MODEL': 'default-model'}
        with patch.dict('os.environ', values, clear=True), patch(
                'tools.web_search.create_web_server', wraps=create_web_server) as create:
            options = build_options({'capability_ref': 'conversation', 'model': 'selected-model',
                                     'credentials': {'platformBearer': 'business-secret'}})
        self.assertEqual(create.call_args.kwargs, {
            'base_url': values['ANTHROPIC_BASE_URL'], 'api_key': 'model-secret', 'model': 'selected-model'})
        self.assertNotIn('headers', options.mcp_servers['web'])
        self.assertNotIn('business-secret', str(options.mcp_servers['web']))

    def test_database_prompt_starts_from_prepared_context_and_query_definitions(self):
        config = load_workflow_config("double-high-qa")
        prompt = build_system_prompt(database_enabled=True, workflow_config=config)["append"]
        self.assertNotIn("t_hpm_project", prompt)
        self.assertNotIn("schoolDoubleHigh", prompt)
        self.assertIn("本轮database_context由程序", prompt)
        self.assertIn("先find_query_specs", prompt)
        self.assertNotIn("先调用 mcp__data__list_data_sources", prompt)
        services = create_run_services({'workflow_name': 'double-high-qa',
                                        'capability_ref': 'national-excellence-data-qa'})
        self.assertEqual(services.context_topics, ['schema', 'relationships', 'business'])
        from data_access.catalog import Catalog
        topics = Catalog().domain("schoolDoubleHigh", "hpm")[1]["documents"]
        for topic in topics:
            self.assertIn(f"`{topic}`", prompt)
        self.assertNotIn("DBHub", prompt)
        self.assertNotIn("documents", config)

    def test_fixed_template_uses_general_harness_and_stages_source(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            options = build_options({"workflow_name":"writing-docx", "capability_ref":"document-writing",
                "_template_key":"szpt-midterm", "session_directory":directory,
                "work_directory":str(Path(directory)/'work'), "deliverables_directory":str(Path(directory)/'output')})
            copies=list(Path(directory).rglob('template.docx'))
            self.assertEqual(len(copies),1)
            self.assertIn(str(copies[0]),options.system_prompt['append'])
        self.assertEqual(set(options.mcp_servers), {"data", "office", "documents", "artifacts"})
        self.assertEqual(options.max_turns, 200)
        self.assertEqual(options.disallowed_tools, ['WebSearch'])
        self.assertEqual(options.tools, {'type':'preset','preset':'claude_code'})
        self.assertEqual(options.setting_sources, ['project','local'])
        self.assertFalse(options.strict_mcp_config)
        self.assertNotIn('save_report_sections',options.system_prompt['append'])
        self.assertIn('mcp__artifacts__publish_file',options.system_prompt['append'])

    def test_regular_writing_without_configured_database_keeps_common_instructions(self):
        with patch.dict('os.environ',{},clear=True), patch('runtime.config.Catalog') as catalog:
            catalog.return_value.sources_for.return_value=[]
            options=build_options({'workflow_name':'writing-docx','capability_ref':'document-writing'})
        self.assertNotIn('data',options.mcp_servers)
        self.assertNotIn('reports',options.mcp_servers)
        self.assertNotIn('prepare_report_data',options.system_prompt['append'])
        self.assertEqual(options.skills,[])
        self.assertIn('WORKFLOW.md', options.system_prompt['append'])

    def test_database_prompt_does_not_read_table_scope_from_environment(self):
        with patch.dict("os.environ", {"DB_ALLOWED_TABLES": "secret_table"}, clear=True):
            prompt = build_system_prompt(database_enabled=True)["append"]
        self.assertNotIn("secret_table", prompt)

    def test_database_prompt_does_not_assume_hpm_for_generic_database(self):
        with patch.dict("os.environ", {}, clear=True):
            prompt = build_system_prompt(database_enabled=True)["append"]
        self.assertNotIn("t_hpm_project", prompt)

    def test_workflow_config_rejects_path_traversal(self):
        with self.assertRaises(RuntimeError):
            load_workflow_config("../outside")

    def test_unknown_workflow_is_rejected(self):
        for name in ("does-not-exist", "database-qa"):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "workflow 不存在"):
                load_workflow_config(name)

    def test_workflow_credentials_are_not_in_prompt(self):
        values = {
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "do-not-leak",
        }
        with patch.dict("os.environ", values, clear=True):
            config = load_workflow_config("double-high-qa")
            prompt = build_system_prompt(database_enabled=True, workflow_config=config)["append"]
        self.assertNotIn("do-not-leak", prompt)

    def test_database_credentials_are_not_passed_to_agent_process(self):
        values = {
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "do-not-leak",
            "ANTHROPIC_MODEL": "qwen",
        }
        with patch.dict("os.environ", values, clear=True):
            environment = agent_environment()
        self.assertNotIn("DB_PASSWORD", environment)
        self.assertNotIn("DB_HOST", environment)
        self.assertNotIn("DATABASE_URL", environment)
        self.assertEqual(environment["ANTHROPIC_MODEL"], MODEL_SETTINGS.default)

    def test_provider_process_does_not_receive_runtime_or_ui_secrets(self):
        values = {
            "ANTHROPIC_AUTH_TOKEN": "model-secret",
            "ANTHROPIC_BASE_URL": "https://model.internal",
            "ANTHROPIC_MODEL": "qwen",
            "CCSDK_RUNTIME_JWT_SECRET": "runtime-secret",
            "SCRIBE_TOKEN": "ui-secret",
            "DB_PASSWORD": "db-secret",
            "BUSINESS_MCP_URL": "https://mcp.internal",
            "CCSDK_LIBREOFFICE_PATH": "configured-office",
            "CCSDK_UNO_PYTHON": "configured-python",
            "CCSDK_RENDER_IMAGE": "renderer:test",
        }
        with patch.dict("os.environ", values, clear=True):
            provider = agent_environment()
            worker = worker_environment()
        self.assertEqual(provider["ANTHROPIC_AUTH_TOKEN"], "model-secret")
        self.assertNotIn("CCSDK_RUNTIME_JWT_SECRET", provider)
        self.assertNotIn("SCRIBE_TOKEN", provider)
        self.assertNotIn("DB_PASSWORD", provider)
        self.assertIn("BUSINESS_MCP_URL", worker)
        self.assertNotIn("CCSDK_RUNTIME_JWT_SECRET", worker)
        self.assertEqual(provider["CCSDK_LIBREOFFICE_PATH"], "configured-office")
        self.assertEqual(provider["CCSDK_UNO_PYTHON"], "configured-python")
        self.assertEqual(provider["CCSDK_RENDER_IMAGE"], "renderer:test")
        self.assertEqual(worker["CCSDK_RENDER_IMAGE"], "renderer:test")

    def test_business_mcp_requires_explicit_capability_allowlist(self):
        values = {
            "ANTHROPIC_MODEL": "qwen",
            "BUSINESS_MCP_URL": "https://mcp.internal",
            "credentials": "unused",
        }
        with patch.dict("os.environ", values, clear=True):
            options = build_options({
                "capability_ref": "conversation",
                "credentials": {"platformBearer": "token"},
            })
        self.assertNotIn("business", options.mcp_servers)

        values["CCSDK_BUSINESS_MCP_CAPABILITIES"] = "conversation"
        with patch.dict("os.environ", values, clear=True):
            options = build_options({
                "capability_ref": "conversation",
                "credentials": {"platformBearer": "token"},
            })
        self.assertIn("business", options.mcp_servers)
        self.assertEqual(
            options.mcp_servers["business"]["headers"]["Authorization"],
            "Bearer token",
        )
        for name in ("office", "documents"):
            self.assertNotIn("headers", options.mcp_servers[name])
            self.assertNotIn("token", str(options.mcp_servers[name].get("env", {})))

    def test_shell_and_mcp_resolve_same_office_version(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'officecli'
            binary.touch()
            with patch.dict('os.environ', {'CCSDK_OFFICECLI_PATH': str(binary), 'PATH': 'previous'}, clear=True):
                options = build_options({})
                self.assertEqual(options.mcp_servers['office']['command'], str(binary))
                self.assertTrue(options.env['PATH'].startswith(directory))

    def test_workflow_documents_are_loaded_from_declared_paths(self):
        config = load_workflow_config("double-high-qa")
        documents = workflow_prompt_documents(config)
        self.assertIn("问数流程", documents)
        self.assertNotIn("HPM 术语与指标语义层", documents)

    def test_workflow_environment_path_is_colocated(self):
        config = load_workflow_config("double-high-qa")
        path = workflow_environment_path(config)
        self.assertEqual(path.name, "workflow.env")
        self.assertEqual(path.parent.name, "double-high-qa")

    def test_common_instructions_are_injected_with_only_selected_template_guide(self):
        from workflows.writing_docx.template_assets import load_template
        config=load_workflow_config('writing-docx')
        common=workflow_prompt_documents(config)
        template=load_template('szpt-midterm','document-writing')
        selected=workflow_prompt_documents(config,template=template)
        self.assertEqual(config.get('skills'), ['document-review'])
        instructions=config['_body']
        self.assertIn(instructions,common)
        self.assertIn(common,selected)
        self.assertNotIn('szpt-midterm',common)
        self.assertNotIn('writing-guide.md',common)
        self.assertIn(template['_documents'][0]['text'].strip(),selected)
        self.assertEqual(selected.count(instructions),1)
        config['skills']=['../outside']
        with self.assertRaises(RuntimeError):workflow_prompt_documents(config,template=template)

    def test_selected_workflow_environment_is_loaded_after_root_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('FLOW_VALUE=root\n', encoding='utf-8')
            (root / '.env.local').write_text('FLOW_VALUE=local\n', encoding='utf-8')
            env_file = root / 'workflow.env'
            env_file.write_text('FLOW_VALUE=workflow\n', encoding='utf-8')
            with patch.dict('os.environ', {}, clear=True), patch('runtime.config.PROJECT_ROOT', root), \
                 patch('runtime.config.workflow_environment_path', return_value=env_file):
                try:
                    load_runtime_environment('double-high-qa')
                    self.assertEqual(os.environ['FLOW_VALUE'], 'workflow')
                    load_runtime_environment()
                    self.assertEqual(os.environ['FLOW_VALUE'], 'local')
                finally:
                    load_runtime_environment()

    def test_local_environment_overrides_defaults_and_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('HTTP_PROXY=http://default.test:80\n', encoding='utf-8')
            with patch('runtime.config.PROJECT_ROOT', root), patch.dict('os.environ', {}, clear=True):
                load_runtime_environment()
                self.assertEqual(os.environ['HTTP_PROXY'], 'http://default.test:80')
                (root / '.env.local').write_text('HTTP_PROXY=http://localhost:7897\n', encoding='utf-8')
                load_runtime_environment()
                self.assertEqual(os.environ['HTTP_PROXY'], 'http://localhost:7897')

    def test_stream_text_is_not_emitted_again_by_assistant_message(self):
        streaming = {}
        start = StreamEvent(
            uuid="u1",
            session_id="s1",
            event={"type": "message_start", "message": {"id": "m1"}},
        )
        event_from_stream(start, streaming)
        message = AssistantMessage(
            content=[TextBlock(text="重复文本")],
            model="qwen",
            message_id="m1",
        )
        self.assertEqual(events_from_assistant(message, streaming), [])

    def test_assistant_turn_uses_real_stream_message_id_and_tool_link(self):
        streaming = {}
        start = StreamEvent(uuid='u1', session_id='s1', parent_tool_use_id='parent-tool',
                            event={'type': 'message_start', 'message': {'id': 'm1'}})
        self.assertEqual(event_from_stream(start, streaming), [
            {'type': 'assistant_turn', 'scope': 'sub:parent-tool', 'messageId': 'm1'}])
        message = AssistantMessage(
            content=[ToolUseBlock(id='tool-1', name='Read', input={'file': 'example.txt'})],
            model='qwen', message_id='m1', parent_tool_use_id='parent-tool')
        events = events_from_assistant(message, streaming)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['messageId'], 'm1')
        self.assertEqual(events[0]['scope'], 'sub:parent-tool')

    def test_missing_message_id_does_not_invent_assistant_turn_or_tool_link(self):
        streaming = {}
        start = StreamEvent(uuid='u1', session_id='s1', event={'type': 'message_start', 'message': {}})
        self.assertEqual(event_from_stream(start, streaming), [])
        message = AssistantMessage(content=[ToolUseBlock(id='tool-1', name='Read', input={})], model='qwen')
        events = events_from_assistant(message, streaming)
        self.assertEqual([event['type'] for event in events], ['tool_use'])
        self.assertNotIn('messageId', events[0])

    def test_assistant_text_without_partial_stream_is_emitted(self):
        message = AssistantMessage(
            content=[TextBlock(text="直接输出")],
            model="qwen",
            message_id="m2",
        )
        events = events_from_assistant(message, {})
        self.assertEqual(events[0]["type"], "text")
        self.assertEqual(events[0]["text"], "直接输出")

    def test_direct_workflow_hides_disabled_capabilities_from_init(self):
        event = direct_workflow_event({
            "type": "init",
            "tools": 2,
            "skills": ["example-skill"],
            "agents": ["example-agent"],
            "commands": ["example-command"],
        })
        self.assertEqual(event["tools"], 2)
        self.assertEqual(event["skills"], [])
        self.assertEqual(event["agents"], [])
        self.assertEqual(event["commands"], [])


class WorkerDiagnosticTests(unittest.IsolatedAsyncioTestCase):
    def assert_private_exception(self, events, expected_type):
        diagnostics = [event for event in events if event['type'] == 'diagnostic']
        self.assertTrue(diagnostics, events)
        self.assertEqual(diagnostics[0]['exceptionType'], expected_type)
        self.assertIn('[REDACTED]', diagnostics[0]['message'])
        self.assertNotIn('business-private-value', json.dumps(events))
        self.assertTrue(diagnostics[0]['frames'])
        for frame in diagnostics[0]['frames']:
            self.assertEqual(set(frame), {'file', 'line', 'function'})
            self.assertFalse(Path(frame['file']).is_absolute())

    async def test_query_failure_keeps_private_exception_before_safe_worker_error(self):
        payload = {'prompt': 'test', 'credentials': {'platformBearer': 'business-private-value'}}
        events = []
        def fail_tools(*args):
            raise ValueError('provider rejected business-private-value')
        with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1'}, clear=True), \
             patch.object(agent_worker.sys, 'stdin', io.StringIO(json.dumps(payload) + '\n')), \
             patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                            missing_environment=lambda: [], create_run_services=lambda _: None,
                            prepare_workflow_assets=lambda _: {}, ToolServices=fail_tools, emit=events.append):
            await agent_worker.main()
        self.assert_private_exception(events, 'ValueError')
        self.assertEqual(events[-1], {'type': 'worker_error', 'message': 'Python Agent worker 执行失败'})

    async def test_diagnostic_disabled_or_write_failure_preserves_safe_query_error(self):
        payload = {'prompt': 'test', 'credentials': {'platformBearer': 'business-private-value'}}
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                events = []
                def emit(event):
                    if event['type'] == 'diagnostic':
                        raise OSError('diagnostic output failed')
                    events.append(event)
                def fail_tools(*args):
                    raise ValueError('provider rejected business-private-value')
                with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1' if enabled else '0'}, clear=True), \
                     patch.object(agent_worker.sys, 'stdin', io.StringIO(json.dumps(payload) + '\n')), \
                     patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                                    missing_environment=lambda: [], create_run_services=lambda _: None,
                                    prepare_workflow_assets=lambda _: {}, ToolServices=fail_tools, emit=emit):
                    await agent_worker.main()
                self.assertEqual(events[-1], {'type': 'worker_error', 'message': 'Python Agent worker 执行失败'})
                self.assertFalse(any(event['type'] == 'diagnostic' for event in events))
                self.assertNotIn('business-private-value', json.dumps(events))

    async def test_client_failures_keep_sanitized_evidence_at_each_catch_boundary(self):
        for boundary in ('connect', 'run', 'cleanup', 'timeout'):
            with self.subTest(boundary=boundary):
                events = []
                command = {'type': 'client_query', 'run_id': 'failed-run', 'prompt': 'test',
                           'credentials': {'platformBearer': 'business-private-value'}}
                def fail():
                    if boundary == 'timeout':
                        raise TimeoutError('provider timed out business-private-value')
                    raise ValueError('provider rejected business-private-value')
                class Client:
                    state = ClientState.NEW
                    async def connect(self):
                        if boundary == 'connect':
                            fail()
                        self.state = ClientState.READY
                    async def configure_turn(self, options):
                        if boundary in {'run', 'timeout'}:
                            fail()
                    async def query(self, prompt, session_id):
                        pass
                    async def receive_response(self, **kwargs):
                        yield SDKMessage(kind='result', data={'subtype': 'success', 'is_error': False})
                    async def disconnect(self):
                        self.state = ClientState.CLOSED
                class Data:
                    async def bind(self, command):
                        pass
                    def prepare_prompt(self, prompt):
                        return prompt
                    async def close(self):
                        if boundary == 'cleanup':
                            fail()
                done = asyncio.Event()
                async def commands(queue):
                    await queue.put(command)
                    await done.wait()
                    await queue.put({'type': 'client_close'})
                def emit(event):
                    events.append(event)
                    if event['type'] == 'client_run_completed':
                        done.set()
                with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1'}, clear=True), \
                     patch.multiple(agent_worker, load_runtime_environment=lambda _: None,
                                    missing_environment=lambda: [], create_run_services=lambda _: Data(),
                                    prepare_workflow_assets=lambda _: {},
                                    ToolServices=lambda *args: SimpleNamespace(clear=lambda: None),
                                    build_client_options=lambda *args: SimpleNamespace(),
                                    build_options=lambda *args, **kw: build_agent_options(tools=[], strict_mcp_config=True),
                                    ClaudeSDKClient=lambda *args, **kw: Client(), isolated_sdk_environment=nullcontext,
                                    _read_client_commands=commands, emit=emit):
                    await asyncio.wait_for(agent_worker.run_client({'credentials': command['credentials']}), 3)
                self.assert_private_exception(events, 'TimeoutError' if boundary == 'timeout' else 'ValueError')
                scopes = [event['scope'] for event in events if event['type'] == 'diagnostic']
                self.assertIn({'connect': 'worker_client', 'run': 'worker_client_run',
                               'cleanup': 'worker_client_cleanup',
                               'timeout': 'worker_client_run'}[boundary], scopes)
                if boundary == 'cleanup':
                    self.assertTrue(any(event['type'] == 'result' and event['ok'] for event in events))
                self.assertTrue(any(event['type'] == 'client_error' for event in events))
                self.assertFalse(any('message' in event for event in events if event['type'] == 'client_error'))
                applied = [event for event in events if event['type'] == 'client_runtime_applied']
                self.assertEqual(len(applied), int(boundary == 'cleanup'))

    async def test_disconnect_wrapper_keeps_provider_cause_for_private_evidence(self):
        from runtime.claude_sdk import ClaudeSDKClient, SDKCleanupError
        from runtime.telemetry import exception_event
        class Provider:
            async def connect(self, prompt=None):
                pass
            async def disconnect(self):
                raise ValueError('disconnect rejected business-private-value')
        client = ClaudeSDKClient(build_agent_options(), client_factory=lambda _: Provider())
        await client.connect()
        with self.assertRaises(SDKCleanupError) as caught:
            await client.disconnect()
        event = exception_event(caught.exception, scope='worker_client_disconnect',
                                secrets=('business-private-value',))
        self.assertEqual(event['causes'][0]['exceptionType'], 'ValueError')
        self.assertEqual(event['causes'][0]['message'], 'disconnect rejected [REDACTED]')
        self.assertTrue(event['causes'][0]['frames'])


if __name__ == "__main__":
    unittest.main()
