import json
import tempfile
import unittest
from pathlib import Path

from local import sessions as store


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_root = store.SESSION_ROOT
        store.SESSION_ROOT = Path(self.temp.name) / ".scribe-sessions"
        store.reset_session_cache()

    def tearDown(self):
        store.reset_session_cache()
        store.SESSION_ROOT = self.original_root
        self.temp.cleanup()

    def create(self, model="test-model"):
        return store.create_session(model=model)["appSessionId"]

    def publish(self, session_id, name, content="result"):
        directory = Path(store.session_deliverables_directory(session_id))
        (directory / name).write_text(content, encoding="utf-8")
        manifest = directory / store.DELIVERABLE_MANIFEST
        saved = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {"version": 1, "files": {}}
        saved["files"][name] = {}
        manifest.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")

    def test_upload_preserves_chinese_filename(self):
        session_id = self.create()
        result = store.save_uploads(session_id, [("季度经营分析 报告-v2.md", "text/markdown", "标题".encode())])
        self.assertEqual(result["files"][0]["originalName"], "季度经营分析 报告-v2.md")
        self.assertEqual(result["files"][0]["source"], "upload")

    def test_only_manifest_published_files_are_visible(self):
        session_id = self.create()
        Path(store.session_work_directory(session_id), "draft.py").write_text("internal", encoding="utf-8")
        Path(store.session_directory(session_id), "unpublished.docx").write_text("draft", encoding="utf-8")
        Path(store.session_deliverables_directory(session_id), "unregistered.txt").write_text("draft", encoding="utf-8")
        self.publish(session_id, "report.md")
        files = store.list_session_files(session_id)["files"]
        self.assertEqual([file["originalName"] for file in files], ["report.md"])
        with self.assertRaisesRegex(RuntimeError, "可见文件目录"):
            store.resolve_session_file(session_id, "unpublished.docx")

    def test_generated_file_enters_prompt_context(self):
        session_id = self.create()
        self.publish(session_id, "后续报告.md")
        context = store.session_prompt_context(session_id)
        self.assertIn("后续报告.md", context)
        self.assertIn("已发布交付物", context)
        self.assertIn("publish_file", context)

    def test_legacy_session_hides_scripts(self):
        session_id = self.create()
        directory = Path(store.session_directory(session_id))
        store.cleanup_session(session_id)
        directory.mkdir(parents=True)
        (directory / store.SESSION_META).write_text(json.dumps({"id": session_id, "files": [], "history": []}), encoding="utf-8")
        (directory / "旧报告.pdf").write_text("pdf", encoding="utf-8")
        (directory / "过程脚本.py").write_text("internal", encoding="utf-8")
        files = store.list_session_files(session_id)["files"]
        self.assertEqual([file["originalName"] for file in files], ["旧报告.pdf"])

    def test_stream_turn_update_preserves_one_pair(self):
        session_id = self.create()
        store.upsert_session_turn(session_id, turn_id="stream", prompt="处理文档", events=[])
        store.upsert_session_turn(
            session_id,
            turn_id="stream",
            prompt="处理文档",
            agent_session_id="agent-session",
            events=[{"type": "thinking", "text": "读取"}, {"type": "text", "scope": "main", "text": "处理中"}],
        )
        data = store.web_session(session_id)
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][1]["content"], "处理中")
        self.assertEqual(data["session"]["agentSessionId"], "agent-session")

    def test_files_attach_to_their_turn(self):
        session_id = self.create()
        self.publish(session_id, "第一轮.docx", "first")
        store.upsert_session_turn(
            session_id,
            turn_id="one",
            prompt="第一份",
            events=[{"type": "text", "scope": "main", "text": "完成一"}],
            files=[".deliverables/第一轮.docx"],
        )
        self.publish(session_id, "第二轮.docx", "second")
        store.upsert_session_turn(
            session_id,
            turn_id="two",
            prompt="第二份",
            events=[{"type": "text", "scope": "main", "text": "完成二"}],
            files=[".deliverables/第二轮.docx"],
        )
        messages = store.web_session(session_id)["messages"]
        self.assertEqual([file["name"] for file in messages[1]["files"]], ["第一轮.docx"])
        self.assertEqual([file["name"] for file in messages[3]["files"]], ["第二轮.docx"])

    def test_download_rejects_traversal_and_keeps_original_name(self):
        session_id = self.create()
        store.save_uploads(session_id, [("数据口径说明.txt", "text/plain", "口径".encode())])
        storage_name = store.list_session_files(session_id)["files"][0]["name"]
        file = store.resolve_session_file(session_id, storage_name)
        self.assertEqual(file["downloadName"], "数据口径说明.txt")
        with self.assertRaisesRegex(RuntimeError, "可见文件目录"):
            store.resolve_session_file(session_id, "../../package.json")

    def test_web_session_and_stats_share_state(self):
        session_id = self.create()
        store.upsert_session_turn(
            session_id,
            prompt="生成摘要",
            agent_session_id="sdk-session",
            events=[
                {"type": "text", "scope": "main", "text": "摘要完成"},
                {"type": "result", "inputTokens": 10, "outputTokens": 5, "costUsd": 0.01},
            ],
        )
        data = store.web_session(session_id)
        self.assertEqual(data["messages"][1]["tokens"], 15)
        model = next(item for item in store.session_stats()["models"] if item["modelId"] == "test-model")
        self.assertEqual(model["responses"], 1)
        self.assertEqual(model["tokens"], 15)

    def test_file_id_round_trip(self):
        encoded = store.encode_file_id("a" * 12, ".deliverables/报告.docx")
        self.assertEqual(store.decode_file_id(encoded), {"sessionId": "a" * 12, "name": ".deliverables/报告.docx"})


if __name__ == "__main__":
    unittest.main()
