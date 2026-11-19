"""提示词归属、统一加载及实际 SDK 规则回归。"""

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from runtime.config import build_options, prepare_capability_assets
from runtime.capabilities import CAPABILITIES
from tests.deployment_fixtures import campus_assets, fixture_capability_entry as capability_entry
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

    def test_office_batch_and_visual_review_guidance_loads_with_office(self):
        payload = {'capability_ref': 'conversation'}
        with patch.dict('os.environ', {}, clear=True):
            options = build_options(payload)
        active = list(options.mcp_servers)
        compiled = assemble_prompt(payload['_capability_assets']['prompt_assets'],
                                   active_tools=active, preview=True)
        self.assertIn('一次性批量写入', compiled['text'])
        self.assertIn('文档创建和修改必须通过 `mcp__office__officecli` MCP 完成', compiled['text'])
        self.assertIn('不要通过 Bash 或 shell 直接调用 `officecli`', compiled['text'])
        self.assertIn('普通撰写不加载完整 Word Skill', compiled['text'])
        self.assertIn('普通撰写不编写 Python-docx 或 docx-js 临时文档生成器', compiled['text'])
        self.assertIn('可见的实质缺陷', compiled['text'])
        self.assertIn('普通文章默认只用内置标题层级，不添加封面、目录、页眉页脚或页码', compiled['text'])

        without_office = assemble_prompt(payload['_capability_assets']['prompt_assets'],
                                         active_tools=[ref for ref in active if ref != 'office'], preview=True)
        self.assertNotIn('一次性批量写入', without_office['text'])
        self.assertTrue(any(item['source'] == 'tools/office/TOOL.md'
                            for item in without_office['omitted']))

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
        self.assertNotIn('prompt', campus_assets())

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
        (self.directory / 'guide.md').write_text('业务阈值说明', encoding='utf-8')
        self.manifest['instructionRefs'] = ['guide.md']
        self.assertIn('业务阈值说明', assemble_prompt(load_prompt_assets(self.entry()),
                      active_tools=[], preview=True)['text'])

    def test_skill_dependencies_do_not_grant_tools_and_direct_can_load_on_demand(self):
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
        result = assemble_prompt(load_prompt_assets(self.entry()), active_tools=['documents'])
        self.assertIn('适用时核验', result['text'])
        self.assertNotIn('方法正文_review', result['text'])
        self.manifest['requiredSkillRefs'] = ['review']
        self.assertIn('方法正文_review', assemble_prompt(load_prompt_assets(self.entry()),
                      active_tools=['documents'])['text'])

    def test_unregistered_parameters_cannot_be_interpolated(self):
        self.body = '阈值 {{limit}}'
        with self.assertRaisesRegex(RuntimeError, '变量未声明'):
            self.entry()
        self.manifest['params'] = {'limit': 3}
        with self.assertRaisesRegex(RuntimeError, '专属配置未登记'):
            self.entry()
