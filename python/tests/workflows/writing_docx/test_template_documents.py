"""Template selection, frozen instructions and client reuse must agree."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docx import Document

from data_access.context import DataError
from runtime.config import build_options, prepare_workflow_assets, workflow_prompt_documents
from runtime.prompt_documents import MAX_DOCUMENT_BYTES, read_documents
from runtime.protocol import AgentRunRequest
from workflows.writing_docx.bindings import load_template


class TemplateDocumentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        skill = self.root / '.claude/skills/writing-documents'
        skill.mkdir(parents=True)
        (skill / 'SKILL.md').write_text('COMMON_RULES', encoding='utf-8')
        self.directory = self.root / 'workflow'
        self.directory.mkdir()
        (self.directory / 'adapter.md').write_text('REPORT_ADAPTER', encoding='utf-8')
        self.workflow = {'name':'writing-docx', '_directory':str(self.directory),
                         'skills':['writing-documents'], 'documents':{'template':['adapter.md']},
                         'templates':{}, 'data_access':'optional'}
        for name in ('alpha','beta'):
            directory = self.directory / 'templates' / name
            directory.mkdir(parents=True)
            path = directory / 'template.docx'
            Document().save(path)
            self.save(directory/'slots.json', {'slots':[]})
            self.save(directory/'bindings.json', {'template_version':1, 'slot_files':['slots.json'], 'datasets':[]})
            self.save(directory/'template.json', {'template_key':name, 'enabled':True,
                'capabilities':['document-writing'], 'version':1,
                'docx_file':'template.docx', 'docx_sha256':sha256(path.read_bytes()).hexdigest(),
                'bindings_file':'bindings.json', 'source_roles':{'hpm':'source-a'},
                'preserve_structure':True, 'missing_policy':'reject', 'documents':['writing-guide.md']})
            (directory/'writing-guide.md').write_text(name.upper()+'_GUIDE',encoding='utf-8')
            self.workflow['templates'][name] = f'templates/{name}/template.json'
        for name, value in [('runtime.config.PROJECT_ROOT', self.root),
                            ('runtime.config.load_workflow_config', None)]:
            patcher = patch(name, return_value=self.workflow) if value is None else patch(name,value)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch('workflows.writing_docx.bindings.load_template', side_effect=self.load)
        patcher.start(); self.addCleanup(patcher.stop)

    @staticmethod
    def save(path, data):
        path.write_text(json.dumps(data),encoding='utf-8')

    def load(self, name, capability):
        return load_template(name,capability,self.directory/'templates')

    def payload(self, name=None):
        payload={'workflow_name':'writing-docx','capability_ref':'document-writing'}
        if name is not None: payload['_template_key']=name
        return payload

    def test_selected_guide_only_and_no_template_for_uploaded_reference(self):
        for name, present, absent in [('alpha','ALPHA_GUIDE','BETA_GUIDE'),('beta','BETA_GUIDE','ALPHA_GUIDE')]:
            prompt=prepare_workflow_assets(self.payload(name))['prompt']
            self.assertIn('COMMON_RULES',prompt)
            self.assertIn('REPORT_ADAPTER',prompt)
            self.assertIn(present,prompt)
            self.assertNotIn(absent,prompt)
        with patch('runtime.config.Catalog') as catalog, patch.dict('os.environ',{},clear=True):
            catalog.return_value.sources_for.return_value=[]
            options=build_options(self.payload())
        self.assertIn('COMMON_RULES',options.system_prompt['append'])
        for marker in ('ALPHA_GUIDE','BETA_GUIDE','REPORT_ADAPTER'):
            self.assertNotIn(marker,options.system_prompt['append'])
        self.assertNotIn('reports',options.mcp_servers)

    def test_declared_documents_order_and_unregistered_file_exclusion(self):
        directory=self.directory/'templates/alpha'
        config=json.loads((directory/'template.json').read_text())
        config['documents']=['second.md','writing-guide.md']
        self.save(directory/'template.json',config)
        (directory/'second.md').write_text('SECOND_GUIDE')
        (directory/'unregistered.md').write_text('HIDDEN_GUIDE')
        prompt=prepare_workflow_assets(self.payload('alpha'))['prompt']
        self.assertLess(prompt.index('SECOND_GUIDE'),prompt.index('ALPHA_GUIDE'))
        self.assertNotIn('HIDDEN_GUIDE',prompt)

    def test_guide_mutation_changes_next_run_revision_but_not_frozen_prompt(self):
        payload=self.payload('alpha')
        before=deepcopy(prepare_workflow_assets(payload))
        (self.directory/'templates/alpha/writing-guide.md').write_text('UPDATED_GUIDE')
        self.assertEqual(prepare_workflow_assets(payload),before)
        after=prepare_workflow_assets(self.payload('alpha'))
        self.assertNotEqual(before['revision'],after['revision'])
        self.assertNotEqual(before['template_revision'],after['template_revision'])
        self.assertIn('UPDATED_GUIDE',after['prompt'])
        # Reusing the same business payload with a new selection cannot reuse the old guide.
        payload['_template_key']='beta'
        self.assertIn('BETA_GUIDE',prepare_workflow_assets(payload)['prompt'])

    def test_common_rule_mutation_changes_client_fingerprint_and_payload_stays_serializable(self):
        from server import _client_config_fingerprint
        request=AgentRunRequest.from_dict({'protocol':'agent-run/v1','runId':'run-test',
            'messageId':'msg-test','businessSessionId':'session-test','capabilityRef':'document-writing',
            'input':{'text':'write'}})
        with patch('server._data_config_fingerprint',return_value=[]):
            old=self.payload('alpha')
            before=_client_config_fingerprint(request,old)
            json.dumps(old)
            (self.root/'.claude/skills/writing-documents/SKILL.md').write_text('CHANGED_COMMON')
            self.assertEqual(before,_client_config_fingerprint(request,old))
            self.assertNotEqual(before,_client_config_fingerprint(request,self.payload('alpha')))
            self.assertNotEqual(before,_client_config_fingerprint(request,self.payload('beta')))

    def test_invalid_guides_are_rejected_before_agent_start(self):
        directory=self.directory/'templates/alpha'
        original=json.loads((directory/'template.json').read_text())
        invalid=[None,'writing-guide.md',['missing.md'],['../beta/writing-guide.md'],
                 ['writing-guide.md','writing-guide.md'],['private.not_for_model.md'],
                 [str(directory/'writing-guide.md')],['config.json']]
        for names in invalid:
            with self.subTest(names=names):
                self.save(directory/'template.json',{**original,'documents':names})
                with self.assertRaisesRegex(DataError,'TEMPLATE_DOCUMENT_INVALID'):
                    prepare_workflow_assets(self.payload('alpha'))
        self.save(directory/'template.json',original)
        for content in ('', 'a'*(MAX_DOCUMENT_BYTES+1)):
            (directory/'writing-guide.md').write_text(content)
            with self.assertRaisesRegex(DataError,'TEMPLATE_DOCUMENT_INVALID'):
                self.load('alpha','document-writing')

    def test_rejects_cross_platform_absolute_paths_and_total_prompt_overflow(self):
        for name in ('C:/secret.md', '//server/share/secret.md'):
            with self.assertRaises(RuntimeError): read_documents(self.directory,[name])
        template=self.load('alpha','document-writing')
        template['_documents']=[{'name':str(n),'text':'a'*23000} for n in range(4)]
        with self.assertRaisesRegex(RuntimeError,'总量'):
            workflow_prompt_documents(self.workflow,template=template)

    def test_disabled_or_wrong_capability_template_is_rejected(self):
        with self.assertRaisesRegex(DataError,'TEMPLATE_FORBIDDEN'):
            self.load('alpha','conversation')
        path=self.directory/'templates/alpha/template.json'
        config=json.loads(path.read_text()); config['enabled']=False; self.save(path,config)
        with self.assertRaisesRegex(DataError,'TEMPLATE_FORBIDDEN'):
            prepare_workflow_assets(self.payload('alpha'))
