"""提示词归属、统一加载及实际 SDK 规则回归。"""

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from runtime.config import build_options, prepare_capability_assets
from runtime.capabilities import capability_entry, CAPABILITIES
from runtime.prompt_assembly import _render, load_prompt_assets, assemble_prompt


class PromptAssemblyTests(unittest.TestCase):
    def test_render_preserves_json_and_rejects_unknown_expressions(self):
        self.assertEqual(_render('{"a":{"b":1}} {{limit}}', {'limit': 3}), '{"a":{"b":1}} 3')
        for text in ('{{missing}}', '{{config.secret}}', '{{ x + 1 }}', '{{'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                _render(text, {})

    def test_chart_guidance_is_loaded_when_chart_tool_is_mounted(self):
        options = build_options({'capability_ref': 'chart-generation'})
        text = options.system_prompt['append']
        self.assertIn('极小项可能难以看清', text)
        self.assertIn('不能删除小项', text)

    def test_custom_mode_keeps_common_answer_rules(self):
        entry = capability_entry(CAPABILITIES['conversation'].directory)
        entry['runtime'] = {'prompt_mode': 'custom'}
        entry['tools'] = []
        with patch('runtime.config.load_execution_entry', return_value={'capability': entry}):
            options = build_options({'capability_ref': 'conversation'})
        self.assertIn('有可靠依据才陈述事实', options.system_prompt['prompt'])
        self.assertIn('始终使用简体中文', options.system_prompt['prompt'])

    def test_required_review_is_injected_without_hardcoded_read_instruction(self):
        assets = prepare_capability_assets({'capability_ref': 'document-writing'})
        self.assertIn('字号、加粗和数字前缀不等于标题级别', assets['prompt'])
        self.assertNotIn('交付DOCX/PDF前必须用Read读取项目根目录', assets['prompt'])

    def test_campus_loader_does_not_render_capability_prompt(self):
        from tools.campus import load_campus_assets
        with patch('runtime.nacos_config.fetch_config', return_value={
                'campusMcp': {'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test'}}):
            loaded = load_campus_assets()
        self.assertNotIn('prompt', loaded)

    def test_effective_tool_guidance_matches_runtime_and_omits_unmounted_tools(self):
        payload = {'capability_ref': 'conversation'}
        with patch.dict('os.environ', {}, clear=True):
            options = build_options(payload)
        compiled = assemble_prompt(payload['_capability_assets']['prompt_assets'],
                                   active_tools=list(options.mcp_servers), preview=True)
        self.assertEqual(compiled['text'], options.system_prompt['append'])
        self.assertNotIn('mcp__web__search', compiled['text'])
        self.assertNotIn('mcp__artifacts__publish_file', compiled['text'])
        self.assertTrue(any(item['source'] == 'tools/web/TOOL.md' for item in compiled['omitted']))


class PromptAssetValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / 'capabilities/example'
        self.directory.mkdir(parents=True)
        self.skills = self.root / 'skills'
        self.skills.mkdir()
        self.manifest = {'ref': 'example', 'title': '示例', 'description': '示例', 'toolRefs': []}
        self.body = '能力正文'

    def entry(self):
        (self.directory / 'capability.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        (self.directory / 'CAPABILITY.md').write_text(self.body, encoding='utf-8')
        return capability_entry(self.directory)

    def skill(self, name, *, tools=()):
        folder = self.skills / name
        folder.mkdir()
        (folder / 'skill.json').write_text(json.dumps({'ref': name, 'description': '适用时核验',
            'toolRefs': list(tools)}), encoding='utf-8')
        (folder / 'SKILL.md').write_text('方法正文_' + name, encoding='utf-8')

    def test_order_and_unregistered_documents(self):
        for name in ('first.md', 'second.md', 'unused.md'):
            (self.directory / name).write_text(name + '正文', encoding='utf-8')
        self.manifest['instructionRefs'] = ['second.md', 'first.md']
        result = assemble_prompt(load_prompt_assets(self.entry()), active_tools=[], preview=True)
        text = result['text']
        self.assertLess(text.index('能力正文'), text.index('second.md正文'))
        self.assertLess(text.index('second.md正文'), text.index('first.md正文'))
        self.assertNotIn('unused.md正文', text)

    def test_instruction_references_reject_unsafe_duplicate_or_large_files(self):
        (self.directory / 'ok.md').write_text('规则', encoding='utf-8')
        (self.directory / 'large.md').write_text('x' * 24_001, encoding='utf-8')
        for refs in (['../outside.md'], ['not_for_model.md'], ['ok.md', './ok.md'],
                     ['CAPABILITY.md'], ['./CAPABILITY.md'], ['large.md'], ['missing.md'], 'ok.md'):
            self.manifest['instructionRefs'] = refs
            with self.subTest(refs=refs), self.assertRaises(RuntimeError):
                self.entry()

    def test_required_and_deferred_skills_have_different_loading_and_safe_preview_paths(self):
        self.skill('required', tools=['documents'])
        self.skill('deferred')
        self.manifest.update(toolRefs=['documents'], skillRefs=['required', 'deferred'], requiredSkillRefs=['required'])
        assets = load_prompt_assets(self.entry())
        result = assemble_prompt(assets, active_tools=['documents'], preview=True)
        self.assertEqual(result['text'].count('方法正文_required'), 1)
        self.assertNotIn('方法正文_deferred', result['text'])
        self.assertNotIn(str(self.root), result['text'])
        self.assertEqual(result['deferredSkills'], ['skills/deferred/SKILL.md'])
        runtime = assemble_prompt(assets, active_tools=['documents'])
        self.assertIn(str(self.skills / 'deferred/SKILL.md'), runtime['text'])
        with self.assertRaisesRegex(RuntimeError, '工具未挂载'):
            assemble_prompt(assets, active_tools=[], preview=True)

    def test_human_only_skill_owners_are_rejected_for_both_loading_modes(self):
        for name in ('not_for_model', 'review-not-for-model'):
            self.skill(name)
            for required in ([], [name]):
                self.manifest.update(skillRefs=[name], requiredSkillRefs=required)
                with self.subTest(name=name, required=required), self.assertRaises(RuntimeError):
                    load_prompt_assets(self.entry())

    def test_host_directory_name_is_not_treated_as_an_asset_classification(self):
        self.directory = self.root / 'not_for_model-host/capabilities/example'
        self.directory.mkdir(parents=True)
        (self.directory / 'config.json').write_text('{"limit":3}', encoding='utf-8')
        self.manifest.update(toolRefs=['campus'], toolConfig={'campus': 'config.json'},
            promptVariables={'limit': {'toolRef': 'campus', 'field': 'limit'}})
        self.body = '阈值 {{limit}}'
        self.assertIn('阈值 3', assemble_prompt(load_prompt_assets(self.entry()),
                      active_tools=['campus'], preview=True)['text'])

    def test_skill_dependencies_do_not_grant_tools_and_direct_requires_preloaded_skills(self):
        self.manifest['skillRefs'] = ['../outside']
        with self.assertRaises(RuntimeError):
            self.entry()
        self.skill('review', tools=['documents'])
        self.manifest.update(skillRefs=['review'])
        with self.assertRaisesRegex(RuntimeError, '工具未在能力中声明'):
            self.entry()
        self.manifest.update(toolRefs=['documents'])
        result = assemble_prompt(load_prompt_assets(self.entry()), active_tools=[], preview=True)
        self.assertNotIn('适用时核验', result['text'])
        self.assertIn('缺少', result['omitted'][-1]['reason'])
        self.manifest['execution'] = {'mode': 'direct'}
        with self.assertRaisesRegex(RuntimeError, 'direct'):
            self.entry()
        self.manifest['requiredSkillRefs'] = ['review']
        self.assertIn('方法正文_review', assemble_prompt(load_prompt_assets(self.entry()),
                      active_tools=['documents'])['text'])

    def test_variables_use_only_registered_numeric_fields_without_connections(self):
        path = self.directory / 'config.json'
        path.write_text('{"limit":3,"api_key":123,"connection":"env:SECRET"}', encoding='utf-8')
        self.manifest.update(toolRefs=['campus'], toolConfig={'campus': 'config.json'},
            promptVariables={'limit': {'toolRef': 'campus', 'field': 'limit'}})
        self.body = '阈值 {{limit}}'
        assets = load_prompt_assets(self.entry())
        self.assertIn('阈值 3', assemble_prompt(assets, active_tools=['campus'], preview=True)['text'])
        for binding in ({'toolRef': 'campus', 'field': 'connection'}, {'toolRef': 'campus', 'field': 'api_key'},
                        {'env': 'SECRET'}, {'toolRef': 'office', 'field': 'limit'},
                        {'toolRef': 'campus', 'field': '../limit'}):
            self.manifest['promptVariables']['limit'] = binding
            with self.subTest(binding=binding), self.assertRaises(RuntimeError):
                self.entry()
