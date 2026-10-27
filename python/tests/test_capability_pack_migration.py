import unittest
from unittest.mock import patch

from runtime.capabilities import CAPABILITIES, capability_entry
from runtime.config import build_options


class CapabilityPackMigrationTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('runtime.nacos_config.fetch_config', return_value={
            'campusMcp': {
                'url': 'https://campus.example.test/mcp',
                'domainName': 'campus.example.test',
            }}))

    def test_campus_business_operations_are_the_agent_tools(self):
        entry = capability_entry(CAPABILITIES['campus-brain-query'].directory)

        self.assertEqual(entry['tools'], [])
        self.assertEqual(entry['service_refs'], ['campus'])
        self.assertEqual(set(entry['operation_refs']), {
            'search_knowledge', 'get_school_info', 'get_indicator_metrics', 'get_norm_metrics'})

        options = build_options({
            'capability_ref': 'campus-brain-query',
            'run_id': 'migration-test-run',
            'credentials': {'platformBearer': 'test-secret'},
        })

        self.assertEqual(set(options.mcp_servers), {'capability_ops'})
        self.assertEqual(set(options.allowed_tools), {
            'mcp__capability_ops__search_knowledge',
            'mcp__capability_ops__get_school_info',
            'mcp__capability_ops__get_indicator_metrics',
            'mcp__capability_ops__get_norm_metrics',
        })
        self.assertNotIn('test-secret', str(options))


if __name__ == '__main__':
    unittest.main()
