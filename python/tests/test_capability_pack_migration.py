import unittest
from unittest.mock import MagicMock, patch

from runtime.capabilities import CAPABILITIES, capability_entry
from runtime.config import build_options
from capability_packs.registry import _directory, _load_module

_CAMPUS = _load_module(_directory('campus-brain-query'))


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

    def test_same_service_ref_from_different_capability_packs_gets_separate_instances(self):
        from runtime.tool_services import ToolServices

        def assets(ref):
            return {
                'capability': {'ref': ref, 'tools': [], 'service_refs': ['campus']},
                'config_values': {},
                'tool_revisions': {},
            }

        first, second = MagicMock(), MagicMock()
        with patch('runtime.tool_services.load_tool_assets', return_value={
                'campus': {'revision': 'same', 'schema_revision': None}}), \
             patch('capability_packs.registry.create_pack_service', side_effect=[first, second]) as create, \
             patch('capability_packs.registry.update_pack_service') as update:
            services = ToolServices(assets('first-pack'), {'platformBearer': 'one'})
            services.configure(assets('second-pack'), {'platformBearer': 'two'})

        self.assertEqual([call.args[0] for call in create.call_args_list], ['first-pack', 'second-pack'])
        update.assert_not_called()
        self.assertIs(services.services['campus'], second)

    def test_asset_revision_is_the_only_service_manifest_resolution(self):
        from runtime.capabilities import CAPABILITIES, capability_entry
        from runtime.tool_services import load_tool_assets
        from unittest.mock import Mock

        settings = Mock()
        entry = capability_entry(CAPABILITIES['campus-brain-query'].directory)
        with patch('runtime.tool_services.service_asset_revision', return_value='revision'):
            load_tool_assets(entry, settings)

        settings.resolve.assert_not_called()

    def test_campus_service_is_bound_once_during_client_configuration(self):
        from runtime.config import prepare_capability_assets
        from runtime.tool_services import ToolServices

        binding_type = _CAMPUS.MCPArgumentBinding
        with patch.object(_CAMPUS, 'MCPArgumentBinding', wraps=binding_type) as binding:
            services = ToolServices(
                prepare_capability_assets({'capability_ref': 'campus-brain-query'}),
                {'platformBearer': 'test-secret'})
            services.clear()

        self.assertEqual(binding.call_count, 1)


if __name__ == '__main__':
    unittest.main()
