"""执行入口的严格解析、目录发现和按需加载回归。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from runtime import prompt_documents
from runtime import capabilities


class ExecutionEntryTests(unittest.TestCase):
    def test_entry_change_uses_current_workflow_and_freezes_request(self):
        import server
        from runtime.protocol import AgentRunRequest
        entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
        entry['workflow'] = 'writing-docx'
        entry['supports_attachments'] = False
        request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'fresh-entry',
            'messageId': 'm1', 'input': {'text': 'hello'}})
        with patch('runtime.config.capability_entry', return_value=entry), patch.object(server, 'MODELS', ['test']):
            self.assertEqual(server._runtime_mode_for_request(request), 'client')
            with tempfile.TemporaryDirectory() as temporary:
                payload = server._internal_worker_payload(request, Path(temporary))
        self.assertEqual(payload['workflow_name'], 'writing-docx')
        self.assertFalse(payload['_workflow_assets']['capability']['supports_attachments'])

    def test_generic_tool_lifecycle_rebinds_and_clears_after_failure(self):
        from runtime.tool_services import ToolServices
        from runtime.mcp_auth import MCPAuthError
        from runtime.config import prepare_workflow_assets
        with patch('runtime.nacos_config.fetch_config', return_value={
                'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'}}):
            assets = prepare_workflow_assets({'capability_ref': 'campus-brain-query'})
        with patch('runtime.nacos_config.fetch_config', side_effect=AssertionError('offline worker')):
            services = ToolServices(assets, {'platformBearer': 'first'})
        campus = services.services['campus']
        services.bind({'platformBearer': 'second'})
        self.assertNotIn('first', str(campus._binding.inject({})))
        self.assertIn('second', str(campus._binding.inject({})))
        with self.assertRaises(MCPAuthError):
            services.bind({})
        with self.assertRaises(MCPAuthError):
            campus._binding.inject({})

    def test_markdown_entry_separates_private_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'CAPABILITY.md'
            path.write_text('---\nname: example\ntools: [charts]\n---\n只处理所选任务。', encoding='utf-8')
            self.assertTrue(hasattr(prompt_documents, 'read_entry'))
            entry = prompt_documents.read_entry(path)
            self.assertEqual(entry['name'], 'example')
            self.assertEqual(entry['_body'], '只处理所选任务。')
            self.assertNotIn('tools:', entry['_body'])

    def test_rejects_duplicate_keys_aliases_and_missing_frontmatter(self):
        self.assertTrue(hasattr(prompt_documents, 'read_entry'))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'CAPABILITY.md'
            for content in ('---\nname: a\nname: b\n---\nx',
                            '---\nname: &a hi\ntools: *a\n---\nx', 'no metadata'):
                with self.subTest(content=content):
                    path.write_text(content, encoding='utf-8')
                    with self.assertRaises(RuntimeError):
                        prompt_documents.read_entry(path)

    def test_discovers_new_capability_without_python_name_mapping(self):
        self.assertTrue(hasattr(capabilities, 'load_capabilities'))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / 'example'
            directory.mkdir()
            entry = directory / 'CAPABILITY.md'
            entry.write_text('---\nname: example\ntitle: 示例\ndescription: 示例任务\ntools: [charts]\n---\n任务规则。', encoding='utf-8')
            item = capabilities.load_capabilities(root)['example']
            self.assertEqual(item.tools, ('charts',))
            self.assertEqual(set(item.to_public_dict()), {'capabilityRef', 'name', 'description', 'supportsAttachments'})
            from runtime.config import build_options
            with patch.dict(capabilities.CAPABILITIES, {'example': item}), patch.dict(os.environ, {}, clear=True):
                options = build_options({'capability_ref': 'example', 'tools': ['campus']})
            self.assertEqual(set(options.mcp_servers), {'charts'})
            self.assertIn('任务规则。', options.system_prompt['append'])
            self.assertNotIn('校园大脑', options.system_prompt['append'])
            entry.write_text(entry.read_text(encoding='utf-8').replace('[charts]', '[unregistered]'), encoding='utf-8')
            with self.assertRaises(RuntimeError):
                capabilities.load_capabilities(root)

    def test_invalid_runtime_is_rejected_at_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'example'
            directory.mkdir()
            for value in ('runtime: {max_turns: true}', 'runtime: {mode: typo}',
                          'runtime: {thinking: {type: unknown}}', 'execution: {mode: typo}',
                          'runtime: {unknown: true}', 'skills: [../outside]'):
                with self.subTest(value=value):
                    (directory / 'CAPABILITY.md').write_text(
                        '---\nname: example\ntitle: 示例\ndescription: 示例\n' + value + '\n---\n正文', encoding='utf-8')
                    with self.assertRaises(RuntimeError):
                        capabilities.load_capabilities(temporary)

    def test_only_selected_skill_metadata_is_injected_and_content_changes_revision(self):
        from runtime.config import prepare_workflow_assets
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / '.claude/skills/review'
            skill.mkdir(parents=True)
            path = skill / 'SKILL.md'
            path.write_text('---\nname: review\ndescription: 按需核验\n---\nPRIVATE_SKILL_BODY', encoding='utf-8')
            entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
            entry['tools'] = []
            entry['skills'] = ['review']
            with patch('runtime.config.PROJECT_ROOT', root), patch('runtime.config.capability_entry', return_value=entry):
                payload = {'capability_ref': 'conversation'}
                before = prepare_workflow_assets(payload)
                self.assertIn('按需核验', before['prompt'])
                self.assertNotIn('PRIVATE_SKILL_BODY', before['prompt'])
                path.write_text(path.read_text(encoding='utf-8') + '\nCHANGED', encoding='utf-8')
                self.assertEqual(before, prepare_workflow_assets(payload))
                self.assertNotEqual(before['revision'], prepare_workflow_assets({'capability_ref': 'conversation'})['revision'])
