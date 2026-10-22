"""能力直接组合规则、模板和来源，业务请求不能选择内部执行资产。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import capabilities
from runtime.config import build_options, prepare_capability_assets


class CapabilityCompositionTests(unittest.TestCase):
    def test_writing_and_qa_own_their_rules_and_data(self):
        for ref in ('document-writing', 'national-excellence-data-qa'):
            entry = capabilities.capability_entry(capabilities.CAPABILITIES[ref].directory)
            self.assertNotIn('workflow_refs', entry)
            self.assertEqual(entry['data']['sourceRefs'], ['schoolDoubleHigh'])
        writing = capabilities.capability_entry(capabilities.CAPABILITIES['document-writing'].directory)
        self.assertIn('szpt-midterm', writing['templates'])
        self.assertEqual(writing['skill_refs'], ['document-review'])

    def test_new_capability_can_bind_existing_data_without_source_name_map(self):
        from runtime.config import data_source_keys
        entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
        entry['data'] = {'access': 'required', 'sourceRefs': ['schoolDoubleHigh']}
        entry['tools'] = ['data']
        with patch('runtime.config.load_execution_entry', return_value={'capability': entry}):
            self.assertEqual(data_source_keys({'capability_ref': 'new-business'}), ['schoolDoubleHigh'])

    def test_old_workflow_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'example'
            directory.mkdir()
            (directory / 'CAPABILITY.md').write_text('业务规则', encoding='utf-8')
            (directory / 'capability.json').write_text(json.dumps({
                'ref': 'example', 'title': '示例', 'description': '示例', 'workflowRefs': []
            }), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                capabilities.capability_entry(directory)

    def test_mcp_preparation_uses_private_environment_without_global_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / 'capability.env'
            binary = root / 'bin' / 'officecli'
            binary.parent.mkdir()
            binary.touch()
            private.write_text(f'CCSDK_OFFICECLI_PATH={binary.as_posix()}\n'
                               'BUSINESS_MCP_URL=https://business.test/mcp\n', encoding='utf-8')
            entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
            entry['tools'].append('business')
            with patch('runtime.config.PROJECT_ROOT', root), \
                 patch('runtime.config.capability_environment_path', return_value=private), \
                 patch('runtime.config.load_execution_entry', return_value={'capability': entry}):
                before = dict(os.environ)
                payload = {'capability_ref': 'conversation', 'credentials': {'platformBearer': 'run-token'}}
                assets = prepare_capability_assets(payload)
                self.assertEqual(assets['mcp_connections']['office']['command'], binary.as_posix())
                self.assertEqual(assets['mcp_connections']['business']['url'], 'https://business.test/mcp')
                options = build_options(payload)
                self.assertTrue(options.env['PATH'].startswith(str(binary.parent)))
                self.assertEqual(dict(os.environ), before)

    def test_conversation_has_file_creation_preview_reading_and_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            options = build_options({'capability_ref': 'conversation',
                'session_directory': str(root), 'work_directory': str(root / 'work'),
                'deliverables_directory': str(root / 'output')})
            self.assertNotEqual(options.tools, [])
            for name in ('office', 'documents', 'artifacts'):
                self.assertIn(name, options.mcp_servers)
            self.assertIn('mcp__documents__render', options.allowed_tools)
            self.assertIn('mcp__documents__read_pdf', options.allowed_tools)
            self.assertIn('mcp__artifacts__publish_file', options.allowed_tools)
