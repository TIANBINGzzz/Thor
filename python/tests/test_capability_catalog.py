"""能力目录从数据库读取；修改在新 Run 生效。"""
import unittest
from unittest.mock import patch
from runtime import capabilities
from runtime.configuration import execution_entry
from tests.deployment_fixtures import install_configuration_store

class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('runtime.config_store._STORE'))
        self.store=install_configuration_store()

    def test_saved_name_is_visible_without_restart(self):
        item=self.store.get('capabilities','conversation');item['name']='新名称'
        self.store.save('capabilities','conversation',item)
        self.assertEqual(capabilities.CAPABILITIES['conversation'].name,'新名称')

    def test_disabled_capability_is_not_listed_or_executable(self):
        item=self.store.get('capabilities','chart-generation');item['enabled']=False
        self.store.save('capabilities','chart-generation',item)
        self.assertNotIn('chart-generation',capabilities.CAPABILITIES)
        with self.assertRaisesRegex(ValueError,'capability_not_found'):
            execution_entry('chart-generation')

    def test_skill_edit_is_seen_on_next_run_only(self):
        first=execution_entry('document-writing')
        item=self.store.get('skills','document-review');item['content']='新核验方法'
        self.store.save('skills','document-review',item)
        second=execution_entry('document-writing')
        self.assertNotEqual(first['capability']['_skills']['document-review']['_body'],'新核验方法')
        self.assertEqual(second['capability']['_skills']['document-review']['_body'],'新核验方法')

    def test_new_capability_reuses_existing_registered_tools(self):
        item=self.store.get('capabilities','conversation')
        item.pop('ref');item.update(name='新增图表',tool_refs=['charts'])
        self.store.save('capabilities','new-chart',item)
        self.assertEqual(execution_entry('new-chart')['capability']['tools'],['charts'])
