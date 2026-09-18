import tempfile
import unittest
import json
from pathlib import Path

from tools.artifacts import publish_artifact


class ArtifactToolTests(unittest.TestCase):
    def test_publishes_only_from_session_roots(self):
        with tempfile.TemporaryDirectory() as root:
            session = Path(root) / "session"
            work = session / ".work"
            deliverables = session / ".deliverables"
            work.mkdir(parents=True)
            deliverables.mkdir()
            source = work / "draft.py"
            source.write_text("print('internal')", encoding="utf-8")

            result = publish_artifact("draft.py", "最终报告.md", work, deliverables, session)

            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["name"], "最终报告.md")
            snapshot = deliverables / result['artifactId']
            self.assertEqual((snapshot / 'content').read_text(encoding='utf-8'), "print('internal')")
            manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['name'], '最终报告.md')
            source.write_text('new version', encoding='utf-8')
            second = publish_artifact('draft.py', '最终报告.md', work, deliverables, session)
            self.assertNotEqual(result['artifactId'], second['artifactId'])
            self.assertEqual((snapshot / 'content').read_text(encoding='utf-8'), "print('internal')")

    def test_rejects_source_outside_session(self):
        with tempfile.TemporaryDirectory() as root:
            session = Path(root) / "session"
            work = session / ".work"
            deliverables = session / ".deliverables"
            work.mkdir(parents=True)
            deliverables.mkdir()
            outside = Path(root) / "outside.txt"
            outside.write_text("secret", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "当前会话目录"):
                publish_artifact(outside, "secret.txt", work, deliverables, session)

    def test_rejects_directory_traversal_target(self):
        with tempfile.TemporaryDirectory() as root:
            session = Path(root) / "session"
            work = session / ".work"
            deliverables = session / ".deliverables"
            work.mkdir(parents=True)
            deliverables.mkdir()
            source = work / "draft.txt"
            source.write_text("draft", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "不能包含目录路径"):
                publish_artifact(source, "../secret.txt", work, deliverables, session)


if __name__ == "__main__":
    unittest.main()
