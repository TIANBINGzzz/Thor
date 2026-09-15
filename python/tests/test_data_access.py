import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from data_access.catalog import Catalog, PROJECT_ROOT
from data_access.context import DataContext, DataError
from data_access.executor import Executor
from runtime.data_services import RunServices
from data_access.sql_policy import validate_sql
from workflows.writing_docx.bindings import load_template
from runtime.config import worker_environment, isolated_sdk_environment, data_source_keys



def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


class DataAccessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = {'version': 1, 'connections': {}, 'policies': {}}
        for source, amount in [('first', 10), ('second', 20)]:
            folder = self.root / 'databases' / source
            save(folder/'source.json', {'source_key': source, 'name': source, 'enabled': True, 'version': 1,
                'capabilities':['qa'], 'connection_file':'private/connection.json',
                'domains': {'sales': {'metrics':'metrics/sales','schema':'schema/sales.json','documents':{}}}})
            domain = folder/'metrics/sales'
            save(domain/'pending.json', {})
            spec = {'name': 'Total', 'description': 'Sum sales', 'version': 1, 'parameters': {
                'tenant_id': {'type': 'string', 'required': True, 'origin': 'authorized_context'}},
                'output': [{'name': 'total', 'type': 'number', 'unit': 'USD'}]}
            save(domain/'total.json', spec)
            (domain/'total.sql').write_text('SELECT SUM(amount) AS total FROM sales WHERE tenant = :tenant_id')
            db = sqlite3.connect(self.root/f'{source}.db')
            db.execute('CREATE TABLE sales (tenant TEXT, amount INTEGER, private_id TEXT)')
            db.executemany('INSERT INTO sales VALUES (?, ?, ?)', [('business-a',amount,'hidden'), ('business-b',999,'other')])
            db.commit()
            db.close()
            self.config['connections'][source] = {'source_key':source,'tenant_id':'jwt-a','driver':'sqlite',
                'database':f'{source}.db','revision':1,'timeout_seconds':1,'max_rows':1000}
            self.config['policies'][source] = {'source_key':source,'tenant_id':'jwt-a','business_tenant_id':'business-a',
                'capabilities':['qa'], 'templates':[], 'users':['u1','u2'],'revision':1,
                'project_scope':{'mode':'all_school'},'domains':{'sales':{'queries':['total'],
                'tables':{'sales':{'tenant':'TEXT','amount':'INTEGER','private_id':'TEXT'}},
                'functions':['SUM','COUNT','MAX','COALESCE','CASE','IF','ROUND'], 'internal_columns':['private_id','tenant']}}}
        self.catalog = Catalog(self.root/'databases')
        self.context = DataContext('run-a','jwt-a','u1','qa',self.root/'run-a')
        self.executor = self.make_executor()

    def make_executor(self, context=None):
        self.save_connections()
        return Executor(context or self.context, {}, self.catalog, ['first','second'])

    def save_connections(self):
        for source in ('first','second'):
            policy=deepcopy(self.config['policies'][source])
            for name,domain in policy['domains'].items():
                save(self.root/f'databases/{source}/schema/{name}.json',
                     {k:domain[k] for k in ('tables','functions','internal_columns')})
                domain['tables']=list(domain['tables'])
                domain.pop('functions'); domain.pop('internal_columns')
            connection={**self.config['connections'][source], 'database':str(self.root/f'{source}.db')}
            save(self.root/f'databases/{source}/private/connection.json',
                 {'version':1,'connection':connection,'policy':policy})

    def school(self, executor=None, source='first'):
        return (executor or self.executor).resolve_entities(source,'sales','school','')['candidates'][0]['scope_ref']

    def test_identical_queries_route_to_distinct_sources_and_bind_business_tenant(self):
        for source, expected in [('first',10),('second',20)]:
            result = self.executor.execute_query_spec(source,'sales','total',{},self.school(source=source))
            self.assertEqual(result['rows'], [{'total':expected}])
        with self.assertRaises(DataError):
            self.executor.execute_query_spec('second','sales','total',{},self.school())

    def test_discovery_uses_query_fields_and_never_exposes_forbidden_queries(self):
        for source in ('first','second'):
            found=self.executor.find_query_specs(source,'sales',metric_key='total.total')['queries']
            self.assertEqual([q['id'] for q in found],['total'])
        self.assertEqual(self.executor.find_query_specs('first','sales',metric_key='total.tenant')['queries'],[])
        self.config['policies']['first']['domains']['sales']['queries']=[]
        executor=self.make_executor()
        self.assertEqual(executor.find_query_specs('first','sales',intent='Total')['queries'],[])
        self.assertEqual(executor.find_query_specs('second','sales',intent='Total')['queries'][0]['id'],'total')

    def test_pending_definition_stays_discoverable_but_cannot_execute(self):
        domain=self.root/'databases/first/metrics/sales'
        save(domain/'pending.json',{'score':{'name':'Scoring','description':'Scoring rule missing',
             'status':'needs_definition','version':1,'blockers':['No scoring formula']}})
        self.config['policies']['first']['domains']['sales']['queries'].append('score')
        executor=self.make_executor()
        self.assertEqual(executor.find_query_specs('first','sales',intent='Scoring')['queries'][0]['blockers'],['No scoring formula'])
        with patch.object(executor.connections, 'snapshot') as snapshot:
            with self.assertRaisesRegex(DataError,'QUERY_DEFINITION_MISSING'):
                executor.execute_query_spec('first','sales','score',{},self.school(executor))
            # No SQL is issued for a pending definition.
            snapshot.return_value.__enter__.return_value.execution_options.assert_not_called()
        save(domain/'pending.json',{'total':{'name':'Duplicate','status':'blocked','blockers':['Not verified']}})
        with self.assertRaisesRegex(DataError,'ASSET_MISMATCH'): self.make_executor()

    def test_run_asset_snapshot_ignores_tests_and_is_independent_of_later_files(self):
        frozen=self.executor.catalog
        revision=frozen.revision('first')
        domain=self.root/'databases/first/metrics/sales'
        save(domain/'tests/evidence.not_for_model.json',{'ignored':'test-only'})
        (domain/'unregistered.md').write_text('not model context')
        self.assertEqual(self.catalog.revision('first'),revision)
        spec=json.loads((domain/'total.json').read_text())
        save(domain/'new_query.json',spec)
        (domain/'new_query.sql').write_text('SELECT 1 AS total')
        (domain/'total.sql').write_text('SELECT 0 AS total')
        self.assertNotEqual(self.catalog.revision('first'),revision)
        (domain/'total.json').unlink()
        self.assertEqual(frozen.revision('first'),revision)
        self.assertEqual([q['id'] for q in frozen.domain('first','sales')[1]['queries']],['total'])
        self.assertEqual(self.executor.execute_query_spec('first','sales','total',{},self.school())['rows'],[{'total':10}])
        with self.assertRaisesRegex(DataError,'DOCUMENT_UNAVAILABLE'):
            frozen.documents('first','sales',['unregistered'])

    def test_access_denies_wrong_identity_empty_scope_and_unlisted_user(self):
        for change in [{'tenant_id':'jwt-b'}, {'user_id':'u3'}, {'capability_ref':'writing'}]:
            executor = self.make_executor(replace(self.context, **change))
            self.assertEqual(executor.list_data_sources()['sources'], [])
        self.config['policies']['first']['project_scope']={'mode':'selected','project_ids':[]}
        with self.assertRaises(DataError): self.school(self.make_executor())

    def test_private_config_is_not_frozen_or_exposed_and_next_run_refreshes_it(self):
        self.config['connections']['first'].update(host='private-host-marker', password_ref='env:PRIVATE_SECRET_MARKER')
        executor=self.make_executor()
        revision=executor.catalog.revision('first')
        public=json.dumps([executor.list_data_sources(), executor.describe_data_source('first','sales')])
        assets=' '.join(executor.catalog._contents.values())
        for marker in ('private-host-marker','PRIVATE_SECRET_MARKER','business-a','jwt-a'):
            self.assertNotIn(marker,public)
            self.assertNotIn(marker,assets)
        path=self.root/'databases/first/private/connection.json'
        config=json.loads(path.read_text());config['policy']['users']=[];save(path,config)
        self.assertEqual(self.catalog.revision('first'),revision)
        self.assertEqual(len(executor.list_data_sources()['sources']),2)
        refreshed=Executor(self.context,{},self.catalog,['first'])
        self.assertEqual(refreshed.list_data_sources()['sources'],[])

    def test_private_connection_cannot_reference_another_database(self):
        path=self.root/'databases/first/source.json'
        source=json.loads(path.read_text());source['connection_file']='../second/private/connection.json';save(path,source)
        with self.assertRaisesRegex(DataError,'ASSET_PATH_INVALID'):
            Executor(self.context,{},self.catalog,['first'])

    def test_optional_writing_discovers_configured_sources_and_template_requires_them(self):
        payload={'workflow_name':'writing-docx','capability_ref':'qa'}
        with patch('runtime.config.Catalog',return_value=self.catalog):
            self.assertEqual(data_source_keys(payload),['first','second'])
            (self.root/'databases/second/private/connection.json').unlink()
            self.assertEqual(data_source_keys(payload),['first'])
            locked={**payload,'_template_key':'demo'}
            self.assertEqual(data_source_keys(locked),['first','second'])
            with self.assertRaises(DataError):
                Executor(self.context,{},self.catalog,data_source_keys(locked))

    def test_no_identity_or_source_fallback_and_no_model_tenant(self):
        with self.assertRaises(DataError): DataContext.from_payload({'run_id':'x'})
        with self.assertRaises(DataError): self.executor.access('FIRST')
        with self.assertRaisesRegex(DataError, 'PARAMETERS_INVALID'):
            self.executor.execute_query_spec('first','sales','total',{'tenant_id':'business-b'},self.school())

    def test_result_paging_preserves_null_zero_and_owner(self):
        rows = [{'id': str(i), 'amount': None if i == 0 else i} for i in range(220)]
        ref = self.executor.results.save(rows, {'complete':True}, [{'name':'id','visibility':'internal_only'},{'name':'amount'}])
        page = self.executor.results.page(ref)
        self.assertEqual(page['rows'][0], {'amount':None})
        collected = list(page['rows'])
        while page['cursor']:
            page = self.executor.results.page(ref,page['cursor'])
            collected += page['rows']
        self.assertEqual(len(collected),220)
        with self.assertRaises(DataError): self.make_executor(replace(self.context,user_id='u2')).results.page(ref)
        with self.assertRaises(DataError): self.executor.results.page(ref,'invented')

    def test_result_provenance_excludes_identity_and_connection_policy(self):
        result = self.executor.execute_query_spec('first','sales','total',{},self.school())
        provenance = result['provenance']
        self.assertEqual(provenance['source_key'], 'first')
        self.assertEqual(provenance['query_id'], 'total')
        self.assertFalse(provenance['dynamic'])
        self.assertIn('collected_at', provenance)
        self.assertNotIn('access', provenance)
        self.assertNotIn('connection_revision', provenance)
        self.assertNotIn('owner', provenance)
        self.assertEqual(self.executor.results.page(result['result_ref'])['provenance'], provenance)

    def test_worker_receives_only_selected_authorized_secrets_and_sdk_receives_none(self):
        for source in ('first', 'second'):
            self.config['connections'][source]['password_ref'] = f'env:{source.upper()}_DB_SECRET'
        self.save_connections()
        source_path=self.root/'databases/second/source.json'
        source=json.loads(source_path.read_text());source['capabilities']=['other'];save(source_path,source)
        payload = {'workflow_name':'qa', 'run_id':'r1', 'capability_ref':'qa',
                   '_data_identity':{'tenant_id':'jwt-a','user_id':'u1'},
                   '_data_run_directory':str(self.root/'r1')}
        values = {'FIRST_DB_SECRET':'first-secret',
                  'SECOND_DB_SECRET':'second-secret', 'UNREGISTERED_SECRET':'not-forwarded'}
        with patch.dict('os.environ', values, clear=True), \
             patch('runtime.config.load_workflow_config', return_value={'data_access':'required'}), \
             patch('runtime.data_services.Catalog', return_value=self.catalog), \
             patch('runtime.config.Catalog', return_value=self.catalog):
            selected = worker_environment(payload)
            self.assertEqual(selected['FIRST_DB_SECRET'], 'first-secret')
            self.assertNotIn('SECOND_DB_SECRET', selected)
            self.assertNotIn('UNREGISTERED_SECRET', selected)
            self.assertNotIn('FIRST_DB_SECRET', worker_environment())
            with isolated_sdk_environment():
                import os
                self.assertNotIn('FIRST_DB_SECRET', os.environ)
                self.assertNotIn('SECOND_DB_SECRET', os.environ)
            self.assertEqual(os.environ['FIRST_DB_SECRET'], 'first-secret')
            denied = {**payload, '_data_identity':{'tenant_id':'jwt-b','user_id':'u1'}}
            self.assertNotIn('FIRST_DB_SECRET', worker_environment(denied))

    def test_sql_checks_nested_tables_functions_writes_comments_and_internal_columns(self):
        policy=self.config['policies']['first']['domains']['sales']
        valid=['SELECT SUM(amount) AS total FROM sales',
               'WITH s AS (SELECT amount FROM sales) SELECT SUM(amount) AS total FROM s',
               'SELECT COUNT(*) AS n FROM sales']
        for sql in valid: validate_sql(sql,policy,dynamic=True)
        invalid=['DELETE FROM sales','SELECT 1; SELECT 2','SELECT SLEEP(1)',
            'SELECT amount FROM other','SELECT x FROM sales','SELECT amount FROM mysql.sales',
            "SELECT amount INTO OUTFILE '/tmp/data' FROM sales",'SELECT amount FROM sales FOR UPDATE',
            'WITH s AS (SELECT amount FROM hidden) SELECT amount FROM s',
            'SELECT (SELECT password FROM users) FROM sales','SELECT LOAD_FILE(:path)',
            'SELECT * FROM sales', 'SELECT private_id AS public FROM sales',
            'WITH x AS (SELECT private_id AS p FROM sales) SELECT p AS n FROM x',
            "SELECT 1 /*! INTO OUTFILE 'x' */", 'SELECT @value',
            'SELECT amount FROM sales UNION SELECT amount FROM hidden']
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaises(DataError): validate_sql(sql,policy,dynamic=True)

    def test_dynamic_sql_requires_database_enforced_scope_and_revision(self):
        scope = self.school()
        with self.assertRaisesRegex(DataError,'DYNAMIC_SQL_FORBIDDEN'):
            self.executor.execute_readonly_sql('first','sales','SELECT amount FROM sales',{},'test',scope)
        policy = self.config['policies']['first']
        policy['dynamic_sql_enabled']=True
        self.config['connections']['first'].update(database_scope_enforced=True,scope_source_key='first',scope_policy_revision=1)
        self.executor=self.make_executor()
        # Test account visibility is reduced to the approved business tenant.
        db = sqlite3.connect(self.root/'first.db')
        db.execute("DELETE FROM sales WHERE tenant <> 'business-a'")
        db.commit(); db.close()
        scope=self.school()
        result=self.executor.execute_readonly_sql('first','sales','SELECT SUM(amount) AS n FROM sales WHERE amount > :minimum',{'minimum':0},'test',scope)
        self.assertEqual(result['rows'],[{'n':10}])
        policy['revision']=2
        self.executor=self.make_executor()
        with self.assertRaises(DataError):
            self.executor.execute_readonly_sql('first','sales','SELECT amount FROM sales',{},'test',self.school())

    def test_path_containment_and_changed_source_config(self):
        path=self.root/'databases/first/source.json'
        source=json.loads(path.read_text())
        source['domains']['sales']['metrics']='../second/metrics/sales'
        save(path,source)
        with self.assertRaises(DataError): self.catalog.domain('first','sales')

    def test_statement_timeout_and_cancel(self):
        connection=self.executor.access('first')[2]
        with self.assertRaises(Exception):
            with self.executor.connections.snapshot(connection) as db:
                db.exec_driver_sql('WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers) SELECT SUM(n) FROM numbers').fetchall()
        self.executor.connections.cancel()
        with self.assertRaisesRegex(DataError,'CANCELLED'): self.executor.access('first')

    def test_run_rebinding_invalidates_results_and_refreshes_policy(self):
        async def scenario():
            self.save_connections()
            services=RunServices(['first','second'],env={},catalog=self.catalog)
            payload={'run_id':'r1','_data_identity':{'tenant_id':'jwt-a','user_id':'u1'},
                     'capability_ref':'qa','_data_run_directory':str(self.root/'r1')}
            await services.bind(payload)
            old=services.current()
            ref=old.results.save([{'amount':0}],{'complete':True},[{'name':'amount'}])
            await services.bind({**payload,'run_id':'r2','_data_run_directory':str(self.root/'r2')})
            with self.assertRaises(DataError): services.current().results.page(ref)
            with self.assertRaises(DataError): old.access('first')
            self.config['policies']['first']['users']=[]
            self.save_connections()
            await services.bind({**payload,'run_id':'r3'})
            self.assertEqual([s['source_key'] for s in services.current().list_data_sources()['sources']],['second'])
            await services.close()
            with self.assertRaises(DataError): services.current()
        asyncio.run(scenario())


class RegisteredAssetsTests(unittest.TestCase):
    def test_chinese_business_queries_rank_existing_definitions(self):
        config=json.loads((PROJECT_ROOT/'deploy/data-access.example.json').read_text(encoding='utf-8'))
        policy=config['policy']
        policy.update(tenant_id='test',business_tenant_id='test',users=['tester'],
                      capabilities=['national-excellence-data-qa'],project_scope={'mode':'all_school'})
        config['connection']['tenant_id']='test'
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'databases/schoolDoubleHigh'
            shutil.copytree(PROJECT_ROOT/'.claude/databases/schoolDoubleHigh',folder,ignore=shutil.ignore_patterns('private'))
            save(folder/'private/connection.json',config)
            executor=Executor(DataContext('r','test','tester','national-excellence-data-qa',Path(directory)),{},
                              Catalog(folder.parent),source_keys=['schoolDoubleHigh'])
            cases={'专业群':'project_catalog','资金执行率':'fund_totals',
                   '2025年三级任务完成情况':'task_progress_summary','加强党的建设':'report_task_sections',
                   '绩效反馈':'performance_feedback_candidates'}
            for intent,query_id in cases.items():
                with self.subTest(intent=intent):
                    found=executor.find_query_specs('schoolDoubleHigh','hpm',intent=intent)['queries']
                    self.assertEqual(found[0]['id'],query_id)
                    self.assertNotIn('tenant_id',found[0]['parameters'])
            self.assertEqual(executor.find_query_specs('schoolDoubleHigh','hpm',intent='明天的天气')['queries'],[])
            self.assertEqual(executor.find_query_specs('schoolDoubleHigh','hpm',metric_key='task_tree.task_id')['queries'],[])

    def test_all_defined_queries_pass_ast_policy(self):
        catalog=Catalog()
        policy=catalog.schema('schoolDoubleHigh','hpm')
        for entry in catalog.domain('schoolDoubleHigh','hpm')[1]['queries']:
            spec=catalog.spec('schoolDoubleHigh','hpm',entry['id'])
            if spec['status']=='defined':
                with self.subTest(query=spec['id']): validate_sql(catalog.sql('schoolDoubleHigh','hpm',spec),policy)

    def test_template_all_mappings_are_bound_to_original_physical_paragraphs(self):
        template=load_template('szpt-midterm','document-writing')
        self.assertEqual(len(template['_slots']),3503)
        self.assertEqual(len([s for s in template['_slots'] if s['section_key'].startswith('T')]),2710)
        self.assertEqual(len(template['_bindings']['tables']),40)
        self.assertEqual(template['source_roles'],{'hpm':'schoolDoubleHigh'})


if __name__ == '__main__': unittest.main()
