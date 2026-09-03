import unittest

from local.references import (
    decode_reference_value,
    encode_reference_value,
    is_source,
    list_sources,
    parse_references,
    reference_prompt_context,
    search_source,
)


class ReferenceTests(unittest.TestCase):
    def test_parse_and_deduplicate(self):
        found = parse_references("读 @file:python/server.py 和 @file:python/server.py")
        self.assertEqual(found, [{"type": "file", "value": "python/server.py", "raw": "@file:python/server.py"}])

    def test_chinese_punctuation_terminates_reference(self):
        self.assertEqual(parse_references("看 @file:README.md，然后")[0]["value"], "README.md")

    def test_scoped_package_and_spaces_round_trip(self):
        for value in ("@anthropic-ai/claude-agent-sdk", "a b/c.md"):
            self.assertEqual(decode_reference_value(encode_reference_value(value)), value)
            self.assertEqual(parse_references(f"看 @pkg:{encode_reference_value(value)}")[0]["value"], value)

    def test_email_is_not_reference(self):
        self.assertEqual(parse_references("someone@example.com"), [])

    def test_sources_and_search(self):
        types = [item["type"] for item in list_sources()]
        self.assertIn("file", types)
        self.assertIn("skill", types)
        self.assertTrue(is_source("pkg"))
        self.assertIsNone(search_source("unknown"))
        page = search_source("file", "server.py", limit=5)
        self.assertTrue(any(item["value"] == "python/server.py" for item in page["items"]))
        self.assertLessEqual(len(search_source("file", limit=9999)["items"]), 50)

    def test_prompt_context(self):
        self.assertEqual(reference_prompt_context("普通问题"), "")
        context = reference_prompt_context("读 @file:package.json")
        self.assertIn("项目文件", context)
        self.assertIn("字节", context)
        self.assertIn("不存在", reference_prompt_context("读 @file:not-real.py"))
        self.assertIn("未知引用类型", reference_prompt_context("看 @secret:token"))


if __name__ == "__main__":
    unittest.main()
