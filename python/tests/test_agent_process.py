import unittest

from runtime.process import prompt_without_workflow_prefix, workflow_name_from_prompt


class AgentProcessTests(unittest.TestCase):
    def test_workflow_prefix(self):
        self.assertEqual(workflow_name_from_prompt("/database-qa 统计项目数"), "database-qa")
        self.assertEqual(workflow_name_from_prompt("  /professional-report 写报告"), "professional-report")

    def test_plain_prompt_has_no_workflow(self):
        self.assertIsNone(workflow_name_from_prompt("请统计项目数"))
        self.assertIsNone(workflow_name_from_prompt("someone@example.com"))

    def test_workflow_prefix_is_removed_before_sdk_query(self):
        self.assertEqual(prompt_without_workflow_prefix(" /database-qa 统计项目数 "), "统计项目数")
        self.assertEqual(prompt_without_workflow_prefix("请统计项目数"), "请统计项目数")


if __name__ == "__main__":
    unittest.main()
