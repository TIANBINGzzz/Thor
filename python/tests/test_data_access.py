import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import yaml
from unittest.mock import patch

from data_access.catalog import Catalog, PROJECT_ROOT
from data_access.context import DataContext, DataError
from data_access.executor import Executor
from runtime.data_services import RunServices
from data_access.sql_policy import validate_sql
from workflows.writing_docx.template_assets import load_template
from runtime.config import worker_environment, isolated_sdk_environment, data_source_keys



def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')


class DataAccessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        from runtime.capabilities import CAPABILITIES
        self.enterContext(patch.dict(CAPABILITIES, {'qa': replace(CAPABILITIES['document-writing'], ref='qa')}))
        self.config_path = self.root/'config/databases.json'
        self.env = {'CCSDK_DATABASES_FILE': str(self.config_path)}
        self.config = {'version': 1, 'connections': {}, 'policies': {}}
        for source, amount in [('first', 10), ('second', 20)]:
            folder = self.root / 'databases' / source
            save(folder/'source.json', {'source_key': source, 'name': source, 'enabled': True, 'version': 1,
                'capabilities':['qa'],
                'domains': {'sales': {'metrics':'metrics/sales','schema':'schema/sales.json','documents':{}}}})
            domain = folder/'metrics/sales'
            spec = {'name': 'Total', 'description': 'Sum sales', 'version': 1, 'parameters': {
                'tenant_id': {'type': 'string', 'required': True, 'origin': 'authorized_context'}},
                'output': [{'name': 'total', 'type': 'number', 'unit': 'USD'}]}
            domain.mkdir(parents=True)
            (domain/'sales.yaml').write_text(yaml.safe_dump({'parameters':{},'metrics':[
                {'id':'total','name':spec['name'],'description':spec['description'],'parameters':[],
                 'grain':'tenant','sql':'SELECT SUM(amount) AS total FROM sales WHERE tenant = :tenant_id',
                 'output':spec['output'],'validation':{}}]},sort_keys=False),encoding='utf-8')
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
        return Executor(context or self.context, self.env, self.catalog, ['first','second'])

    def save_connections(self):
        sources = {}
        for source in ('first','second'):
            policy=deepcopy(self.config['policies'][source])
            for name,domain in policy['domains'].items():
                save(self.root/f'databases/{source}/schema/{name}.json',
                     {k:domain[k] for k in ('tables','functions','internal_columns')})
                domain['tables']=list(domain['tables'])
                domain.pop('functions'); domain.pop('internal_columns')
            connection={**self.config['connections'][source], 'database':str(self.root/f'{source}.db')}
            connection.pop('source_key')
            policy.pop('source_key')
            sources[source] = {'connection':connection,'policy':policy}
        save(self.config_path, {'version':1,'sources':sources})

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
        path=domain/'pending.yaml'
        path.write_text(yaml.safe_dump({'pending':{'score':{'name':'Scoring','description':'Scoring rule missing',
             'status':'needs_definition','version':1,'blockers':['No scoring formula']}}}),encoding='utf-8')
        self.config['policies']['first']['domains']['sales']['queries'].append('score')
        executor=self.make_executor()
        self.assertEqual(executor.find_query_specs('first','sales',intent='Scoring')['queries'][0]['blockers'],['No scoring formula'])
        with patch.object(executor.connections, 'snapshot') as snapshot:
            with self.assertRaisesRegex(DataError,'QUERY_DEFINITION_MISSING'):
                executor.execute_query_spec('first','sales','score',{},self.school(executor))
            # No SQL is issued for a pending definition.
            snapshot.return_value.__enter__.return_value.execution_options.assert_not_called()
        path.write_text(yaml.safe_dump({'pending':{'total':{'name':'Duplicate','status':'blocked','blockers':['Not verified']}}}),encoding='utf-8')
        with self.assertRaisesRegex(DataError,'ASSET_MISMATCH'): self.make_executor()

    def test_run_asset_snapshot_ignores_tests_and_is_independent_of_later_files(self):
        frozen=self.executor.catalog
        revision=frozen.revision('first')
        domain=self.root/'databases/first/metrics/sales'
        save(domain/'tests/evidence.not_for_model.json',{'ignored':'test-only'})
        (domain/'unregistered.md').write_text('not model context')
        self.assertEqual(self.catalog.revision('first'),revision)
        bundle=yaml.safe_load((domain/'sales.yaml').read_text())
        bundle['metrics'].append({**bundle['metrics'][0],'id':'new_query','sql':'SELECT 1 AS total'})
        bundle['metrics'][0]['sql']='SELECT 0 AS total'
        (domain/'sales.yaml').write_text(yaml.safe_dump(bundle),encoding='utf-8')
        self.assertNotEqual(self.catalog.revision('first'),revision)
        (domain/'sales.yaml').unlink()
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

    def test_shared_source_accepts_other_tenants_and_users_with_fixed_business_scope(self):
        self.config['policies']['first'].update(tenant_id='*', users='all_authenticated')
        self.config['connections']['first']['tenant_id'] = '*'
        previous = None
        for tenant, user in [('jwt-b', 'u3'), ('jwt-c', 'u4')]:
            with self.subTest(tenant=tenant):
                executor = self.make_executor(replace(self.context, tenant_id=tenant, user_id=user))
                self.assertEqual([s['source_key'] for s in executor.list_data_sources()['sources']], ['first'])
                scope = self.school(executor)
                result = executor.execute_query_spec('first', 'sales', 'total', {}, scope)
                # 共享来源仍使用部署配置的业务范围，不读取另一业务租户的数据。
                self.assertEqual(result['rows'], [{'total': 10}])
                if previous:
                    with self.assertRaisesRegex(DataError, 'SCOPE_FORBIDDEN'):
                        executor.execute_query_spec('first', 'sales', 'total', {}, previous['scope'])
                    with self.assertRaisesRegex(DataError, 'RESULT_FORBIDDEN'):
                        executor.results.page(previous['result_ref'])
                previous = {'scope': scope, 'result_ref': result['result_ref']}

    def test_shared_tenant_requires_both_policy_and_connection_opt_in(self):
        context = replace(self.context, tenant_id='jwt-b', user_id='u3')
        for side, code in [('policies', 'CONNECTION_FORBIDDEN'), ('connections', 'SOURCE_FORBIDDEN')]:
            with self.subTest(side=side):
                self.config['policies']['first'].update(tenant_id='jwt-a', users='all_authenticated')
                self.config['connections']['first']['tenant_id'] = 'jwt-a'
                self.config[side]['first']['tenant_id'] = '*'
                executor = self.make_executor(context)
                with self.assertRaisesRegex(DataError, code):
                    executor.access('first')

    def test_shared_tenant_keeps_user_capability_template_and_query_restrictions(self):
        self.config['policies']['first']['tenant_id'] = '*'
        self.config['connections']['first']['tenant_id'] = '*'
        context = replace(self.context, tenant_id='jwt-b')
        self.assertEqual(len(self.make_executor(context).list_data_sources()['sources']), 1)
        denied = self.make_executor(replace(context, user_id='u3'))
        self.assertEqual(denied.list_data_sources()['sources'], [])
        self.config['policies']['first']['users'] = 'all_authenticated'
        denied = self.make_executor(replace(context, capability_ref='writing'))
        self.assertEqual(denied.list_data_sources()['sources'], [])
        denied = self.make_executor(replace(context, template_key='unregistered'))
        with self.assertRaisesRegex(DataError, 'TEMPLATE_FORBIDDEN'):
            denied.access('first')
        self.config['policies']['first']['domains']['sales']['queries'] = []
        executor = self.make_executor(context)
        with self.assertRaisesRegex(DataError, 'QUERY_FORBIDDEN'):
            executor.execute_query_spec('first', 'sales', 'total', {}, self.school(executor))

    def test_grouped_yaml_rejects_duplicate_keys_and_duplicate_metric_ids(self):
        path=self.root/'databases/first/metrics/sales/sales.yaml'
        content=path.read_text()
        path.write_text(content+'\nmetrics: []\n',encoding='utf-8')
        with self.assertRaisesRegex(DataError,'ASSET_MISMATCH'):self.make_executor()
        bundle=yaml.safe_load(content)
        bundle['metrics'].append(deepcopy(bundle['metrics'][0]))
        path.write_text(yaml.safe_dump(bundle),encoding='utf-8')
        with self.assertRaisesRegex(DataError,'ASSET_MISMATCH'):self.make_executor()

    def test_required_business_values_rejected_before_database_access(self):
        path=self.root/'databases/first/metrics/sales/sales.yaml'
        bundle=yaml.safe_load(path.read_text())
        bundle['parameters']={'year':{'type':['string','null'],'required':True,'origin':'user_intent'}}
        metric=bundle['metrics'][0]
        metric['parameters']=['year']
        metric['sql']+=' AND :year IS NOT NULL'
        metric['validation']['required_values']=['year']
        path.write_text(yaml.safe_dump(bundle),encoding='utf-8')
        e=self.make_executor()
        found=e.find_query_specs('first','sales',intent='total')['queries'][0]
        self.assertEqual(found['parameters']['year']['type'],['string'])
        with self.assertRaisesRegex(DataError,'PARAMETERS_INVALID'):
            e.execute_query_spec('first','sales','total',{'year':None},self.school(e))

    def test_conditional_scope_constraint_checks_injected_project_before_query(self):
        path=self.root/'databases/first/metrics/sales/sales.yaml'
        bundle=yaml.safe_load(path.read_text())
        bundle['parameters']={
            'project_id':{'type':['string','null'],'required':True,'origin':'authorized_resolution'},
            'scope_mode':{'type':'string','required':True,'enum':['national','project']},
        }
        metric=bundle['metrics'][0]
        metric['parameters']=['project_id','scope_mode']
        metric['sql']+=' AND (:scope_mode = :scope_mode) AND (:project_id IS NULL OR :project_id IS NOT NULL)'
        metric['validation']['parameter_schema']={
            'if':{'properties':{'scope_mode':{'const':'project'}}},
            'then':{'properties':{'project_id':{'type':'string','minLength':1}}},
        }
        path.write_text(yaml.safe_dump(bundle),encoding='utf-8')
        executor=self.make_executor()
        school=self.school(executor)
        with patch.object(executor,'_rows',side_effect=AssertionError('SQL must not run')):
            with self.assertRaisesRegex(DataError,'PARAMETERS_INVALID'):
                executor.execute_query_spec('first','sales','total',{'scope_mode':'project'},school)
        _,policy,_=executor.access('first')
        project=executor._scope_ref('first','sales','authorized-project',policy)
        result=executor.execute_query_spec('first','sales','total',{'scope_mode':'project'},project)
        self.assertEqual(result['rows'],[{'total':10}])

    def test_private_config_is_not_frozen_or_exposed_and_next_run_refreshes_it(self):
        self.config['connections']['first'].update(host='private-host-marker', password='PRIVATE_SECRET_MARKER')
        executor=self.make_executor()
        revision=executor.catalog.revision('first')
        public=json.dumps([executor.list_data_sources(), executor.describe_data_source('first','sales')])
        assets=' '.join(executor.catalog._contents.values())
        for marker in ('private-host-marker','PRIVATE_SECRET_MARKER','business-a','jwt-a'):
            self.assertNotIn(marker,public)
            self.assertNotIn(marker,assets)
        path=self.config_path
        config=json.loads(path.read_text());config['sources']['first']['policy']['users']=[];save(path,config)
        self.assertEqual(self.catalog.revision('first'),revision)
        self.assertEqual(len(executor.list_data_sources()['sources']),2)
        refreshed=Executor(self.context,self.env,self.catalog,['first'])
        self.assertEqual(refreshed.list_data_sources()['sources'],[])

    def test_central_connection_rejects_conflicting_source_identity(self):
        config=json.loads(self.config_path.read_text())
        config['sources']['first']['connection']['source_key']='second'
        save(self.config_path,config)
        with self.assertRaisesRegex(DataError,'CONFIG_INVALID'):
            Executor(self.context,self.env,self.catalog,['first'])

    def test_connection_rotation_changes_client_fingerprint_without_changing_assets(self):
        from server import _data_config_fingerprint
        with patch('data_access.catalog.Catalog',side_effect=lambda root=self.catalog.root: Catalog(root)), \
             patch('runtime.config.data_source_keys',return_value=['first']), patch.dict('os.environ',self.env):
            before=_data_config_fingerprint({})
            config=json.loads(self.config_path.read_text())
            config['sources']['first']['connection']['password']='rotated-secret'
            save(self.config_path,config)
            after=_data_config_fingerprint({})
        self.assertEqual(before[0][:2],after[0][:2])
        self.assertNotEqual(before[0][2],after[0][2])
        self.assertNotIn('rotated-secret',str(after))

    def test_conversation_and_optional_writing_without_config_and_malformed_config(self):
        with patch.dict('os.environ',self.env), patch('runtime.config.Catalog',return_value=self.catalog):
            self.config_path.unlink()
            self.assertEqual(data_source_keys({'capability_ref':'conversation'}),[])
            writing={'workflow_name':'writing-docx','capability_ref':'qa'}
            self.assertEqual(data_source_keys(writing),[])
            self.config_path.write_text('{broken')
            with self.assertRaisesRegex(DataError,'CONFIG_INVALID'): data_source_keys(writing)

    def test_optional_writing_discovers_configured_sources_and_template_requires_them(self):
        payload={'workflow_name':'writing-docx','capability_ref':'qa'}
        with patch('runtime.config.Catalog',return_value=self.catalog), patch.dict('os.environ',self.env):
            self.assertEqual(data_source_keys(payload),['first','second'])
            config=json.loads(self.config_path.read_text())
            del config['sources']['second']
            save(self.config_path,config)
            self.assertEqual(data_source_keys(payload),['first'])
            locked={**payload,'capability_ref':'document-writing','_template_key':'szpt-midterm'}
            with self.assertRaisesRegex(DataError,'SOURCE_FORBIDDEN'):
                data_source_keys(locked)
            with patch.object(self.catalog,'sources_for',return_value=['schoolDoubleHigh','second']):
                self.assertEqual(data_source_keys(locked),['schoolDoubleHigh'])
                with self.assertRaises(DataError):
                    Executor(self.context,self.env,self.catalog,data_source_keys(locked))

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

    def test_result_keeps_query_semantics_with_paged_evidence(self):
        # 写作时常直接复用结果；限定条件须随证据返回，不依赖较早的检索上下文。
        metric_path = self.root/'databases/first/metrics/sales/sales.yaml'
        asset = yaml.safe_load(metric_path.read_text(encoding='utf-8'))
        rules = ['当前登记值，不是历史截止日快照', '仅包含有效业务记录']
        asset['metrics'][0]['validation']['rules'] = rules
        metric_path.write_text(yaml.safe_dump(asset, allow_unicode=True), encoding='utf-8')
        executor = self.make_executor()
        scope = executor.resolve_entities('first', 'sales', 'school', '')['candidates'][0]['scope_ref']
        result = executor.execute_query_spec('first', 'sales', 'total', {}, scope)
        self.assertEqual(result['semantics'], rules)
        ref = executor.results.save([{'total': i} for i in range(101)],
            executor.results.get(result['result_ref'])['metadata'], [{'name': 'total'}])
        first = executor.results.page(ref)
        second = executor.results.page(ref, first['cursor'])
        self.assertEqual(second['semantics'], rules)
        self.assertNotIn('sql', json.dumps(second))

    def test_mysql_uses_literal_json_credentials_and_rejects_missing_values(self):
        from data_access.connections import Connections
        config={'_base_directory':self.root,'driver':'mysql+pymysql','host':'example.invalid',
                'database':'test','username':'reader@name','password':" literal:$() /@# ",
                'tls':{'mode':'disabled'}}
        with patch('data_access.connections.create_engine') as create:
            with Connections().snapshot(config):
                pass
            url=create.call_args.args[0]
            self.assertEqual(url.username,config['username'])
            self.assertEqual(url.password,config['password'])
        for key in ('username','password'):
            for value in (None,'',123):
                with patch('data_access.connections.create_engine') as create:
                    with self.assertRaisesRegex(DataError,'SECRET_REQUIRED'):
                        with Connections().snapshot({**config,key:value}):
                            pass
                    create.assert_not_called()

    def test_worker_and_sdk_do_not_receive_database_secret_environment(self):
        for source in ('first', 'second'):
            self.config['connections'][source]['password'] = f'{source}-secret'
        self.save_connections()
        source_path=self.root/'databases/second/source.json'
        source=json.loads(source_path.read_text());source['capabilities']=['other'];save(source_path,source)
        values = {**self.env, 'FIRST_DB_SECRET':'first-secret',
                  'SECOND_DB_SECRET':'second-secret', 'UNREGISTERED_SECRET':'not-forwarded'}
        with patch.dict('os.environ', values, clear=True), \
             patch('runtime.config.load_workflow_config', return_value={'data_access':'required'}), \
             patch('runtime.data_services.Catalog', return_value=self.catalog), \
             patch('runtime.config.Catalog', return_value=self.catalog):
            selected = worker_environment()
            self.assertEqual(selected['CCSDK_DATABASES_FILE'],self.env['CCSDK_DATABASES_FILE'])
            self.assertNotIn('FIRST_DB_SECRET', selected)
            self.assertNotIn('SECOND_DB_SECRET', selected)
            self.assertNotIn('UNREGISTERED_SECRET', selected)
            self.assertNotIn('FIRST_DB_SECRET', worker_environment())
            with isolated_sdk_environment():
                import os
                self.assertNotIn('FIRST_DB_SECRET', os.environ)
                self.assertNotIn('SECOND_DB_SECRET', os.environ)
                self.assertNotIn('CCSDK_DATABASES_FILE',os.environ)
            self.assertEqual(os.environ['FIRST_DB_SECRET'], 'first-secret')
            self.assertNotIn('FIRST_DB_SECRET', worker_environment())

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
            services=RunServices(['first','second'],env=self.env,catalog=self.catalog)
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

    def test_prepared_context_contains_usable_scope_and_no_connection_details(self):
        self.config['connections']['first']['password'] = 'private-db-password'
        executor = self.make_executor()
        context = executor.prepare_context(['schema'])
        self.assertEqual(len(context['sources']), 2)
        first = context['sources'][0]
        domain = first['domains'][0]
        self.assertEqual(domain['tables']['sales']['amount'], 'INTEGER')
        self.assertIn('schema', domain['documents'])
        result = executor.execute_query_spec('first', 'sales', 'total', {}, domain['scope_ref'])
        self.assertEqual(result['rows'], [{'total': 10}])
        serialized = json.dumps(context)
        for private in ('private-db-password', 'jwt-a', 'business-a', str(self.root), 'username', 'password'):
            self.assertNotIn(private, serialized)

    def test_prepared_context_fails_when_database_is_unavailable(self):
        executor = self.make_executor()
        self.root.joinpath('first.db').unlink()
        with self.assertRaisesRegex(DataError, 'CONNECTION_UNAVAILABLE'):
            executor.prepare_context(['schema'])

    def test_prepared_prompt_refreshes_per_run_and_clears_on_failure(self):
        async def scenario():
            self.save_connections()
            services = RunServices(['first'], env=self.env, catalog=self.catalog, context_topics=['schema'])
            payload = {'run_id': 'r1', '_data_identity': {'tenant_id': 'jwt-a', 'user_id': 'u1'},
                       'capability_ref': 'qa', '_data_run_directory': str(self.root/'r1')}
            await services.bind(payload)
            old_scope = next(iter(services.current().scopes))
            self.assertIn(old_scope, services.prepare_prompt('question-one'))
            self.assertIn('question-one', services.prepare_prompt('question-one'))
            await services.bind({**payload, 'run_id': 'r2'})
            self.assertNotIn(old_scope, services.prepare_prompt('question-two'))
            with patch.object(Executor, 'prepare_context', side_effect=DataError('CONNECTION_UNAVAILABLE')):
                with self.assertRaisesRegex(DataError, 'CONNECTION_UNAVAILABLE'):
                    await services.bind({**payload, 'run_id': 'r3'})
            with self.assertRaisesRegex(DataError, 'RUN_NOT_ACTIVE'):
                services.prepare_prompt('question-three')
        asyncio.run(scenario())

    def test_unconfigured_preparation_does_not_connect_or_change_prompt(self):
        async def scenario():
            services = RunServices(['first'], env=self.env, catalog=self.catalog)
            with patch.object(Executor, 'prepare_context') as prepare:
                await services.bind({'run_id': 'r1', '_data_identity': {'tenant_id': 'jwt-a', 'user_id': 'u1'},
                                     'capability_ref': 'qa', '_data_run_directory': str(self.root/'r1')})
                self.assertEqual(services.prepare_prompt('original question'), 'original question')
                prepare.assert_not_called()
            await services.close()
        asyncio.run(scenario())


class RegisteredAssetsTests(unittest.TestCase):
    def test_chinese_business_queries_rank_existing_definitions(self):
        config=json.loads((PROJECT_ROOT/'deploy/data-access.example.json').read_text(encoding='utf-8'))
        entry=config['sources']['schoolDoubleHigh']
        policy=entry['policy']
        policy.update(tenant_id='test',business_tenant_id='test',users=['tester'],
                      capabilities=['national-excellence-data-qa'],project_scope={'mode':'all_school'})
        entry['connection']['tenant_id']='test'
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)/'databases/schoolDoubleHigh'
            shutil.copytree(PROJECT_ROOT/'.claude/databases/schoolDoubleHigh',folder,ignore=shutil.ignore_patterns('private'))
            path=Path(directory)/'config/databases.json'
            save(path,config)
            executor=Executor(DataContext('r','test','tester','national-excellence-data-qa',Path(directory)),
                              {'CCSDK_DATABASES_FILE':str(path)},
                              Catalog(folder.parent),source_keys=['schoolDoubleHigh'])
            cases={'专业群':'project_catalog','资金执行率':'fund_totals',
                   '2025年三级任务完成情况':'task_progress_summary','加强党的建设':'first_task_progress_feedback',
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

    def test_template_context_does_not_require_map_or_plan(self):
        template=load_template('szpt-midterm','document-writing')
        self.assertNotIn('_locations',template)
        self.assertNotIn('_bindings',template)
        self.assertTrue(template['_docx'].is_file())
        self.assertTrue(template['_documents'])
        self.assertEqual(template['source_roles'],{'hpm':'schoolDoubleHigh'})


if __name__ == '__main__': unittest.main()
