"""执行资产 manifest、声明式装配和工具生命周期回归。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import capabilities


class ExecutionEntryTests(unittest.TestCase):
    def test_builtin_tool_catalog_loads_declared_operations(self):
        from runtime.tool_registry import TOOL_CATALOG

        image = TOOL_CATALOG.resolve('images')
        self.assertEqual(image.implementation, 'images')
        self.assertEqual(image.operation('generate').input_schema['required'], ['prompt', 'output_path'])

    def test_every_tool_uses_one_provider_catalog(self):
        from runtime.tool_registry import TOOL_CATALOG, PROVIDERS

        for ref in TOOL_CATALOG.refs:
            definition = TOOL_CATALOG.resolve(ref)
            provider = PROVIDERS[definition.implementation]
            with self.subTest(ref=ref):
                self.assertEqual(bool(provider.create_service), definition.lifecycle == 'per_client')
                self.assertEqual(bool(provider.create), definition.lifecycle == 'per_run')

    def test_opaque_tools_do_not_publish_placeholder_operations(self):
        from runtime.tool_registry import TOOL_CATALOG

        for ref in ('business', 'campus', 'data', 'office'):
            definition = TOOL_CATALOG.resolve(ref)
            with self.subTest(ref=ref):
                self.assertEqual(definition.scope, 'namespace')
                self.assertEqual(definition.operations, ())

    def test_capability_tool_refs_are_resolved_by_tool_catalog(self):
        from runtime.tool_registry import TOOL_CATALOG

        entry = capabilities.capability_entry(Path('.claude/capabilities/image-generation'))
        self.assertEqual(tuple(TOOL_CATALOG.resolve_many(entry['tools']))[2].ref, 'images')

    def test_declared_tools_are_built_by_one_registry(self):
        from runtime.tool_registry import build_registered_tools
        result = build_registered_tools({'tools': ['charts'], 'required_tools': []}, {'chart_sink': None})
        self.assertIn('charts', result.servers)

    def test_static_tool_declarations_match_registered_sdk_contracts(self):
        from runtime.tool_registry import TOOL_CATALOG
        from tools.attachments import create_attachment_server
        from tools.artifacts import create_artifact_server
        from tools.documents import create_document_server
        from tools.images import create_image_server
        from tools.mermaid import create_chart_server
        from tools.web_search import create_web_server

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work, output = root / 'work', root / 'output'
            work.mkdir()
            output.mkdir()
            cases = (
                ('attachments', 'tools.attachments', lambda: create_attachment_server(root)),
                ('artifacts', 'tools.artifacts', lambda: create_artifact_server(root, work, output)),
                ('documents', 'tools.documents', lambda: create_document_server(root)),
                ('images', 'tools.images', lambda: create_image_server(root,
                    base_url='https://image.test', api_key='test', model='test')),
                ('charts', 'tools.mermaid', create_chart_server),
                ('web', 'tools.web_search', lambda: create_web_server(
                    base_url='https://web.test', api_key='test', model='test')),
            )
            for ref, module, create in cases:
                with self.subTest(ref=ref), patch(module + '.create_sdk_mcp_server',
                                                  side_effect=lambda *args, **kwargs: kwargs):
                    actual = {item.name: item.input_schema for item in create()['tools']}
                declared = {item.ref: item.input_schema for item in TOOL_CATALOG.resolve(ref).operations}
                self.assertEqual(actual, declared)

    def test_entry_change_uses_current_workflow_and_freezes_request(self):
        import server
        from runtime.protocol import AgentRunRequest
        entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
        entry['workflow_refs'] = ['writing-docx']
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

    def _write_capability_tree(self, root, *, capability, workflow=None, skill=None):
        capabilities_root = root / 'capabilities'
        capability_dir = capabilities_root / capability['ref']
        capability_dir.mkdir(parents=True)
        (capability_dir / 'capability.json').write_text(json.dumps(capability), encoding='utf-8')
        (capability_dir / 'CAPABILITY.md').write_text('任务规则。', encoding='utf-8')
        if workflow:
            directory = root / 'workflows' / workflow['ref']
            directory.mkdir(parents=True)
            (directory / 'workflow.json').write_text(json.dumps(workflow), encoding='utf-8')
            (directory / 'WORKFLOW.md').write_text('流程规则。', encoding='utf-8')
        if skill:
            directory = root / 'skills' / skill['ref']
            directory.mkdir(parents=True)
            (directory / 'skill.json').write_text(json.dumps(skill), encoding='utf-8')
            (directory / 'SKILL.md').write_text('Skill规则。', encoding='utf-8')
        return capabilities_root

    def test_discovers_new_capability_without_python_name_mapping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {'ref': 'example', 'title': '示例', 'description': '示例任务',
                        'toolRefs': ['charts'], 'workflowRefs': [], 'skillRefs': []}
            capability_root = self._write_capability_tree(root, capability=manifest)
            item = capabilities.load_capabilities(capability_root)['example']
            self.assertEqual(item.tools, ('charts',))
            self.assertEqual(set(item.to_public_dict()), {'capabilityRef', 'name', 'description', 'supportsAttachments'})
            from runtime.config import build_options
            with patch.dict(capabilities.CAPABILITIES, {'example': item}), patch.dict(os.environ, {}, clear=True):
                options = build_options({'capability_ref': 'example'})
            self.assertEqual(set(options.mcp_servers), {'charts'})

    def test_manifest_rejects_invalid_runtime_missing_asset_and_ref_mismatch(self):
        cases = [{'runtime': {'max_turns': True}}, {'runtime': {'mode': 'typo'}},
                 {'runtime': {'thinking': {'type': 'unknown'}}}, {'execution': {'mode': 'typo'}}]
        for extra in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                manifest = {'ref': 'example', 'title': '示例', 'description': '示例',
                            'workflowRefs': [], 'skillRefs': [], **extra}
                capability_root = self._write_capability_tree(root, capability=manifest)
                with self.assertRaises(RuntimeError):
                    capabilities.load_capabilities(capability_root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {'ref': 'example', 'title': '示例', 'description': '示例',
                        'workflowRefs': ['missing'], 'skillRefs': []}
            capability_root = self._write_capability_tree(root, capability=manifest)
            with self.assertRaises(RuntimeError):
                capabilities.load_capabilities(capability_root)

    def test_declared_workflow_and_skill_are_loaded_from_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workflow = {'ref': 'review-flow', 'description': '审核流程', 'skillRefs': ['review']}
            skill = {'ref': 'review', 'description': '按需核验'}
            manifest = {'ref': 'example', 'title': '示例', 'description': '示例',
                        'workflowRefs': ['review-flow'], 'skillRefs': ['review'], 'toolRefs': [],
                        'requiredToolRefs': []}
            capability_root = self._write_capability_tree(root, capability=manifest,
                                                           workflow=workflow, skill=skill)
            item = capabilities.load_capabilities(capability_root)['example']
            from runtime.config import load_workflow_configs
            config = load_workflow_configs(item.workflow_refs, workflows_root=root / 'workflows')
            self.assertEqual(config['skills'], ['review'])
            self.assertIn('流程规则。', config['_body'])

    def test_multiple_executable_workflows_are_rejected(self):
        from runtime.config import load_workflow_configs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for ref in ('first', 'second'):
                directory = root / ref
                directory.mkdir()
                (directory / 'workflow.json').write_text(json.dumps({
                    'ref': ref, 'description': ref, 'execution': {'mode': 'agent'}}), encoding='utf-8')
                (directory / 'WORKFLOW.md').write_text(ref, encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, '只支持一个'):
                load_workflow_configs(['first', 'second'], workflows_root=root)

    def test_capability_registration_rejects_multiple_workflows(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {'ref': 'example', 'title': '示例', 'description': '示例',
                        'workflowRefs': ['first', 'second']}
            capability_root = self._write_capability_tree(root, capability=manifest)
            with self.assertRaisesRegex(RuntimeError, '只支持一个'):
                capabilities.load_capabilities(capability_root)

    def test_only_selected_skill_metadata_is_injected_and_content_changes_revision(self):
        from runtime.config import prepare_workflow_assets
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_dir = root / '.claude/skills/review'
            skill_dir.mkdir(parents=True)
            (skill_dir / 'skill.json').write_text('{"ref":"review","description":"按需核验"}', encoding='utf-8')
            path = skill_dir / 'SKILL.md'
            path.write_text('PRIVATE_SKILL_BODY', encoding='utf-8')
            entry = capabilities.capability_entry(capabilities.CAPABILITIES['conversation'].directory)
            entry['skill_refs'] = ['review']
            entry['_skill_root'] = str(skill_dir.parent)
            entry['workflow_refs'] = []
            entry['tools'] = []
            with patch('runtime.config.capability_entry', return_value=entry):
                payload = {'capability_ref': 'conversation'}
                before = prepare_workflow_assets(payload)
                self.assertIn('按需核验', before['prompt'])
                self.assertNotIn('PRIVATE_SKILL_BODY', before['prompt'])
                path.write_text(path.read_text(encoding='utf-8') + '\nCHANGED', encoding='utf-8')
                self.assertEqual(before, prepare_workflow_assets(payload))
                self.assertNotEqual(before['revision'], prepare_workflow_assets({'capability_ref': 'conversation'})['revision'])

    def test_capability_and_workflow_shared_skill_is_injected_once(self):
        from runtime.config import prepare_workflow_assets
        entry = capabilities.capability_entry(capabilities.CAPABILITIES['document-writing'].directory)
        entry['skill_refs'] = ['document-review']
        with patch('runtime.config.capability_entry', return_value=entry):
            assets = prepare_workflow_assets({'capability_ref': 'document-writing'})
        self.assertEqual(assets['prompt'].count('- document-review：'), 1)
