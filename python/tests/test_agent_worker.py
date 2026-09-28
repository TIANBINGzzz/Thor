import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, StreamEvent, TextBlock

from agent_worker import direct_workflow_event, event_from_stream, events_from_assistant
from runtime.config import (
    build_options,
    build_system_prompt,
    create_run_services,
    agent_environment,
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
                    self.assertIn('没有可用的联网搜索能力', options.system_prompt if isinstance(options.system_prompt, str) else options.system_prompt['append'])

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
        self.assertIsNone(options.max_turns)
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
        self.assertEqual(environment["ANTHROPIC_MODEL"], "qwen")

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
        with tempfile.NamedTemporaryFile(suffix=".env") as env_file:
            with patch.dict("os.environ", {}, clear=True):
                with patch("runtime.config.load_dotenv") as load_dotenv:
                    with patch("runtime.config.workflow_environment_path", return_value=Path(env_file.name)):
                        load_runtime_environment("double-high-qa")
        self.assertEqual(load_dotenv.call_count, 3)
        self.assertEqual(load_dotenv.call_args_list[1].args[0].name, '.env.local')
        self.assertEqual(load_dotenv.call_args_list[2].args[0], Path(env_file.name))

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


if __name__ == "__main__":
    unittest.main()
