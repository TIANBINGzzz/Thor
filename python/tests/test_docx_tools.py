import tempfile
import unittest
from pathlib import Path

from docx import Document

from tools.docx import extract_document, inspect_document, replace_document


class DocxToolsTests(unittest.TestCase):
    def test_inspect_extract_and_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "template.docx"
            document = Document()
            document.add_paragraph("项目：{{project_name}}")
            document.add_table(rows=1, cols=1).cell(0, 0).text = "负责人：{{owner}}"
            document.save(source)

            summary = inspect_document(str(source), root)
            self.assertEqual(summary["placeholders"], ["owner", "project_name"])
            self.assertIn("项目：{{project_name}}", extract_document(str(source), root)["text"])

            result = replace_document(
                str(source), {"project_name": "中文项目", "owner": "李雷"}, root
            )
            self.assertEqual(result["changedParagraphs"], 2)
            self.assertIn("中文项目", extract_document(result["path"], root)["text"])

    def test_paths_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                inspect_document("..\\outside.docx", directory)


if __name__ == "__main__":
    unittest.main()
