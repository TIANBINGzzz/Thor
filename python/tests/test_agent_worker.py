import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_agent_sdk import AssistantMessage, ResultMessage, StreamEvent, TextBlock

from agent_worker import direct_workflow_event, event_from_stream, events_from_assistant
from runtime.config import (
    build_options,
    build_system_prompt,
    create_database_mcp_server,
    agent_environment,
    database_environment,
    worker_environment,
    load_workflow_config,
    load_runtime_environment,
    workflow_environment_path,
    workflow_prompt_documents,
)


class AgentWorkerTests(unittest.TestCase):
    def test_database_mcp_is_disabled_without_connection(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(create_database_mcp_server())

    def test_database_mcp_uses_python_owned_environment(self):
        values = {
            "DB_TYPE": "mysql",
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "p@ss",
            "DB_NAME": "test_hpm_dev",
            "NODE_BIN": "node-test",
        }
        with patch.dict("os.environ", values, clear=True):
            server = create_database_mcp_server()
        self.assertIsNotNone(server)
        self.assertEqual(server["command"], "node-test")
        self.assertIn("DB_PASSWORD", server["env"])
        self.assertNotIn("DSN", server["env"])

    def test_database_config_uses_workflow_owned_readonly_profile(self):
        values = {
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "secret",
            "NODE_BIN": "node-test",
        }
        with patch.dict("os.environ", values, clear=True):
            config = load_workflow_config("database-qa")
            server = create_database_mcp_server(config)
        self.assertIsNotNone(server)
        self.assertNotIn("DSN", server["env"])
        self.assertIn("--config", server["args"])
        self.assertIn(".claude\\workflows\\database-qa", server["args"][-1])

    def test_database_prompt_contains_workflow_table_scope(self):
        config = load_workflow_config("database-qa")
        prompt = build_system_prompt(database_enabled=True, workflow_config=config)["append"]
        self.assertIn("t_hpm_project, t_hpm_project_fund", prompt)

    def test_database_prompt_contains_hpm_scope_guards(self):
        config = load_workflow_config("database-qa")
        prompt = build_system_prompt(database_enabled=True, workflow_config=config)["append"]
        self.assertIn("禁止用 `performance.high_flag_` 过滤", prompt)
        self.assertIn("Q6 的支撑材料必须来自任务反馈", prompt)
        self.assertIn("包括“国双高项目的三级任务”", prompt)
        self.assertIn("DBHub `execute_sql` 不支持参数绑定", prompt)
        self.assertIn("DBHub 最小调用协议", prompt)

    def test_database_workflow_runs_directly_with_only_db_tools(self):
        values = {
            "DB_HOST": "192.0.2.10",
            "DB_USER": "qa_user",
            "DB_PASSWORD": "secret",
            "NODE_BIN": "node-test",
        }
        with patch.dict("os.environ", values, clear=True):
            options = build_options({"workflow_name": "database-qa"})
        self.assertEqual(options.tools, [])
        self.assertEqual(options.skills, [])
        self.assertEqual(options.setting_sources, [])
        self.assertTrue(options.strict_mcp_config)
        self.assertEqual(list(options.mcp_servers), ["db"])
        self.assertEqual(options.allowed_tools, ["mcp__db__*"])
        self.assertIn("不要再次调用 Skill、Workflow、Task", options.system_prompt["append"])

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

    def test_workflow_database_requires_runtime_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "DB_HOST"):
                create_database_mcp_server(load_workflow_config("database-qa"))

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
            dbhub = database_environment()
            worker = worker_environment()
        self.assertEqual(provider["ANTHROPIC_AUTH_TOKEN"], "model-secret")
        self.assertNotIn("CCSDK_RUNTIME_JWT_SECRET", provider)
        self.assertNotIn("SCRIBE_TOKEN", provider)
        self.assertNotIn("DB_PASSWORD", provider)
        self.assertIn("DB_PASSWORD", dbhub)
        self.assertNotIn("CCSDK_RUNTIME_JWT_SECRET", dbhub)
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
        self.assertIn("问数约束", documents)
        self.assertIn("HPM 术语与指标语义层", documents)

    def test_workflow_environment_path_is_colocated(self):
        config = load_workflow_config("database-qa")
        path = workflow_environment_path(config)
        self.assertEqual(path.name, "workflow.env")
        self.assertEqual(path.parent.name, "database-qa")

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
