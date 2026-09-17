import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock

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
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(create_run_services({}))
            config = load_workflow_config("database-qa")
            self.assertEqual(config["data_access"], "required")
            self.assertNotIn("data_sources", config)
            options = build_options({"workflow_name": "database-qa", "capability_ref":"national-excellence-data-qa"})
        self.assertEqual(options.tools, [])
        self.assertEqual(options.skills, [])
        self.assertEqual(options.setting_sources, [])
        self.assertTrue(options.strict_mcp_config)
        self.assertEqual(list(options.mcp_servers), ["data"])
        self.assertEqual(options.allowed_tools, ["mcp__data__*"])
        self.assertIn("不要再次调用 Skill、Workflow、Task", options.system_prompt["append"])

    def test_database_prompt_contains_guards_and_explicit_semantic_loading(self):
        config = load_workflow_config("database-qa")
        prompt = build_system_prompt(database_enabled=True, workflow_config=config)["append"]
        self.assertNotIn("t_hpm_project", prompt)
        self.assertNotIn("schoolDoubleHigh", prompt)
        self.assertIn("describe_data_source", prompt)
        from data_access.catalog import Catalog
        topics = Catalog().domain("schoolDoubleHigh", "hpm")[1]["documents"]
        for topic in topics:
            self.assertIn(f"`{topic}`", prompt)
        self.assertNotIn("DBHub", prompt)
        self.assertNotIn("semantics", config["documents"])

    def test_fixed_template_uses_general_harness_and_stages_source(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            options = build_options({"workflow_name":"writing-docx", "capability_ref":"document-writing",
                "_template_key":"szpt-midterm", "session_directory":directory,
                "work_directory":str(Path(directory)/'work'), "deliverables_directory":str(Path(directory)/'output')})
            copies=list(Path(directory).rglob('template.docx'))
            self.assertEqual(len(copies),1)
            self.assertIn(str(copies[0]),options.system_prompt['append'])
        self.assertEqual(set(options.mcp_servers), {"data", "docx", "artifacts"})
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
        self.assertIn('instructions.md', options.system_prompt['append'])

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
        with self.assertRaisesRegex(RuntimeError, "workflow 不存在"):
            load_workflow_config("does-not-exist")

    def test_unregistered_flat_script_is_not_a_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'legacy.js').write_text('export const meta = {};', encoding='utf-8')
            with patch('runtime.config.WORKFLOWS_ROOT', Path(directory)):
                with self.assertRaisesRegex(RuntimeError, 'workflow 不存在'):
                    load_workflow_config('legacy')

    def test_workflow_credentials_are_not_in_prompt(self):
        values = {
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "do-not-leak",
        }
        with patch.dict("os.environ", values, clear=True):
            config = load_workflow_config("database-qa")
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

        values["CCSDK_BUSINESS_MCP_CAPABILITIES"] = "business-report"
        with patch.dict("os.environ", values, clear=True):
            options = build_options({
                "capability_ref": "business-report",
                "credentials": {"platformBearer": "token"},
            })
        self.assertIn("business", options.mcp_servers)
        self.assertEqual(
            options.mcp_servers["business"]["headers"]["Authorization"],
            "Bearer token",
        )

    def test_workflow_documents_are_loaded_from_declared_paths(self):
        config = load_workflow_config("database-qa")
        documents = workflow_prompt_documents(config)
        self.assertIn("问数流程", documents)
        self.assertNotIn("HPM 术语与指标语义层", documents)

    def test_workflow_environment_path_is_colocated(self):
        config = load_workflow_config("database-qa")
        path = workflow_environment_path(config)
        self.assertEqual(path.name, "workflow.env")
        self.assertEqual(path.parent.name, "database-qa")

    def test_common_instructions_are_injected_with_only_selected_template_guide(self):
        from workflows.writing_docx.template_assets import load_template
        config=load_workflow_config('writing-docx')
        common=workflow_prompt_documents(config)
        template=load_template('szpt-midterm','document-writing')
        selected=workflow_prompt_documents(config,template=template)
        self.assertFalse(config.get('skills'))
        instructions=(Path(config['_directory'])/'instructions.md').read_bytes().decode('utf-8').strip()
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
                        load_runtime_environment("database-qa")
        self.assertEqual(load_dotenv.call_count, 2)
        self.assertEqual(load_dotenv.call_args_list[1].args[0], Path(env_file.name))

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
            "skills": ["data-analysis"],
            "agents": ["data-analyst"],
            "commands": ["data-analysis"],
        })
        self.assertEqual(event["tools"], 2)
        self.assertEqual(event["skills"], [])
        self.assertEqual(event["agents"], [])
        self.assertEqual(event["commands"], [])


if __name__ == "__main__":
    unittest.main()
