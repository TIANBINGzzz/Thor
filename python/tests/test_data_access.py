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
from runtime import deployment_config
from runtime.auth import encode_hs256_jwt
from data_access.sql_policy import validate_sql
from runtime.template_assets import load_template
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
        catalog = {**dict(CAPABILITIES), 'qa': replace(CAPABILITIES['document-writing'], ref='qa')}
        self.enterContext(patch('runtime.capabilities.CAPABILITIES', catalog))
        from runtime.capabilities import capability_entry
        entry = capability_entry(CAPABILITIES['document-writing'].directory)
        entry['data'] = {'access':'optional','sourceRefs':['first','second']}
        from runtime.config import load_execution_entry
        original = load_execution_entry
        self.enterContext(patch('runtime.config.load_execution_entry', side_effect=lambda ref:
            {'capability': deepcopy(entry)} if ref == 'qa' else original(ref)))
        self.env = {}
        from tests.deployment_fixtures import deployment_document
        self.deployment = {**deployment_document(), 'databases': {}}
        self.enterContext(patch.object(deployment_config, '_DEPLOYMENT', self.deployment))
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
            self.config['connections'][source] = {'driver':'sqlite',
                'database':f'{source}.db','timeout_seconds':1,'max_rows':1000}
            self.config['policies'][source] = {'domains':{'sales':{
                'tables':{'sales':{'tenant':'TEXT','amount':'INTEGER','private_id':'TEXT'}},
                'functions':['SUM','COUNT','MAX','COALESCE','CASE','IF','ROUND'], 'internal_columns':['private_id','tenant'],
                'tenant_column':'tenant'}}}
        self.catalog = Catalog(self.root/'databases')
        self.context = DataContext('run-a','runtime-a','u1','qa',self.root/'run-a',data_tenant_id='business-a')
        self.executor = self.make_executor()

    def make_executor(self, context=None):
        self.save_connections()
        return Executor(context or self.context, self.env, self.catalog, ['first','second'])

    def save_connections(self):
        sources = {}
        for source in ('first','second'):
            policy = self.config['policies'][source]
            for name, domain in policy['domains'].items():
                save(self.root/f'databases/{source}/schema/{name}.json',
                     {k:domain[k] for k in ('tables','functions','internal_columns','tenant_column')})
            original = self.config['connections'][source]
            connection = {k:v for k,v in original.items() if k in ('driver','host','port','username','password','tls')}
            connection['database'] = str(self.root/f'{source}.db')
            sources[source] = {'connection': connection,
                'access': {'tenantIds': policy.get('tenantIds', ['self'])}, 'query': {
                'timeout_seconds': original['timeout_seconds'], 'max_rows': original['max_rows'],
                'dynamic_sql_enabled': policy.get('dynamic_sql_enabled', False)}}
        self.deployment['databases'] = sources

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
        self.assertEqual(self.executor.find_query_specs('first','sales',intent='Total')['queries'][0]['id'],'total')

    def test_pending_definition_stays_discoverable_but_cannot_execute(self):
        domain=self.root/'databases/first/metrics/sales'
        path=domain/'pending.yaml'
        path.write_text(yaml.safe_dump({'pending':{'score':{'name':'Scoring','description':'Scoring rule missing',
             'status':'needs_definition','version':1,'blockers':['No scoring formula']}}}),encoding='utf-8')
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

    def test_runtime_tenant_does_not_choose_business_data(self):
        executor = self.make_executor(replace(self.context, tenant_id='other-customer'))
        self.assertEqual(len(executor.list_data_sources()['sources']), 2)
        result = executor.execute_query_spec('first','sales','total',{},self.school(executor))
        self.assertEqual(result['rows'], [{'total': 10}])

    def test_all_customer_users_share_data_but_not_scope_or_result_references(self):
        previous = None
        for user in ('u1', 'u2'):
            executor = self.make_executor(replace(self.context, user_id=user))
            scope = self.school(executor)
            result = executor.execute_query_spec('first', 'sales', 'total', {}, scope)
            self.assertEqual(result['rows'], [{'total': 10}])
            if previous:
                with self.assertRaisesRegex(DataError, 'SCOPE_FORBIDDEN'):
                    executor.execute_query_spec('first','sales','total',{},previous[0])
                with self.assertRaisesRegex(DataError, 'RESULT_FORBIDDEN'):
                    executor.results.page(previous[1])
            previous = (scope, result['result_ref'])

    def test_business_identity_selects_self_independently_of_run_identity(self):
        context = replace(self.context, data_tenant_id='business-b')
        executor = self.make_executor(context)
        result = executor.execute_query_spec('first','sales','total',{},self.school(executor))
        self.assertEqual(result['rows'], [{'total': 999}])

    def test_source_selection_stays_bound_to_trusted_capability_assets(self):
        executor = Executor(self.context, self.env, self.catalog, ['first'])
        with self.assertRaisesRegex(DataError, 'SOURCE_FORBIDDEN'):
            executor.access('second')
        self.assertEqual(len(executor.list_data_sources()['sources']), 1)

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
        for marker in ('private-host-marker','PRIVATE_SECRET_MARKER','business-a','business-a'):
            self.assertNotIn(marker,public)
            self.assertNotIn(marker,assets)
        self.deployment['databases']['first']['query']['max_rows'] = 2
        self.assertEqual(self.catalog.revision('first'), revision)
        self.assertEqual(executor.access('first')[2]['max_rows'], 1000)
        refreshed=Executor(self.context,self.env,self.catalog,['first'])
        self.assertEqual(refreshed.access('first')[2]['max_rows'], 2)

    def test_central_connection_rejects_conflicting_source_identity(self):
        self.deployment['databases']['first']['connection']['source_key'] = 'second'
        with self.assertRaisesRegex(DataError, 'CONFIG_INVALID'):
            Executor(self.context,self.env,self.catalog,['first'])

    def test_conversation_and_optional_writing_without_database(self):
        self.deployment['databases'] = {}
        self.assertEqual(data_source_keys({'capability_ref':'conversation'}), [])
        self.assertEqual(data_source_keys({'capability_ref':'qa'}), [])
        self.deployment['databases'] = []
        with self.assertRaisesRegex(DataError, 'CONFIG_INVALID'):
            data_source_keys({'capability_ref':'qa'})

    def test_optional_writing_discovers_configured_sources_and_template_requires_them(self):
        payload={'capability_ref':'qa'}
        from runtime.capabilities import capability_entry
        def entry_for_template():
            return capability_entry(Path('.claude/capabilities/document-writing'))
        with patch.dict('os.environ',self.env):
            self.assertEqual(data_source_keys(payload),['first','second'])
            del self.deployment['databases']['second']
            self.assertEqual(data_source_keys(payload),['first','second'])
            payload={'capability_ref':'qa'}
            self.assertEqual(data_source_keys(payload),['first'])
            locked={'capability_ref':'document-writing','_template_key':'szpt-midterm'}
            with patch('runtime.config.load_execution_entry', return_value={'capability': {**entry_for_template(), 'data': {'access':'optional','sourceRefs':['first']}}}), self.assertRaisesRegex(DataError,'SOURCE_FORBIDDEN'):
                data_source_keys(locked)
            with patch('runtime.config.load_execution_entry', return_value={'capability': {**entry_for_template(), 'data': {'access':'optional','sourceRefs':['schoolDoubleHigh','second']}}}):
                locked={'capability_ref':'document-writing','_template_key':'szpt-midterm'}
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
             patch('runtime.data_services.Catalog', return_value=self.catalog):
            selected = worker_environment()
            self.assertIn('CCSDK_WORKER_CONFIG_SECRET', selected)
            self.assertNotIn('CCSDK_DATABASES_FILE', selected)
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

    def test_dynamic_sql_requires_database_enforced_scope_and_matching_source(self):
        scope = self.school()
        with self.assertRaisesRegex(DataError,'DYNAMIC_SQL_FORBIDDEN'):
            self.executor.execute_readonly_sql('first','sales','SELECT amount FROM sales',{},'test',scope)
        policy = self.config['policies']['first']
        policy['dynamic_sql_enabled']=True
        self.executor=self.make_executor()
        # 保留另一学校的数据，执行器必须在数据库读取前强制学校范围。
        scope=self.school()
        result=self.executor.execute_readonly_sql('first','sales','SELECT SUM(amount) AS n FROM sales WHERE amount > :minimum',{'minimum':0},'test',scope)
        self.assertEqual(result['rows'],[{'n':10}])
        policy['dynamic_sql_enabled']=False
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
            payload={'run_id':'r1','_data_identity':{'tenant_id':'business-a','user_id':'u1'},
                     'capability_ref':'qa','_data_run_directory':str(self.root/'r1'),
                     'credentials': {'platformBearer': encode_hs256_jwt({'tenantId':'business-a'},'test-business-key')}}
            await services.bind(payload)
            old=services.current()
            ref=old.results.save([{'amount':0}],{'complete':True},[{'name':'amount'}])
            await services.bind({**payload,'run_id':'r2','_data_run_directory':str(self.root/'r2')})
            with self.assertRaises(DataError): services.current().results.page(ref)
            with self.assertRaises(DataError): old.access('first')
            self.save_connections()
            del self.deployment['databases']['first']
            with self.assertRaisesRegex(DataError, 'CONNECTION_UNAVAILABLE'):
                await services.bind({**payload,'run_id':'r3'})
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
        for private in ('private-db-password', 'business-a', 'business-a', str(self.root), 'username', 'password'):
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
            payload = {'run_id': 'r1', '_data_identity': {'tenant_id': 'business-a', 'user_id': 'u1'},
                       'capability_ref': 'qa', '_data_run_directory': str(self.root/'r1'),
                       'credentials': {'platformBearer': encode_hs256_jwt({'tenantId':'business-a'},'test-business-key')}}
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
                await services.bind({'run_id': 'r1', '_data_identity': {'tenant_id': 'business-a', 'user_id': 'u1'},
                                     'capability_ref': 'qa', '_data_run_directory': str(self.root/'r1')})
                self.assertEqual(services.prepare_prompt('original question'), 'original question')
                prepare.assert_not_called()
            await services.close()
        asyncio.run(scenario())


class RegisteredAssetsTests(unittest.TestCase):
    def test_chinese_business_queries_rank_existing_definitions(self):
        document = {'databases': {
            'schoolDoubleHigh': {'connection': {'driver': 'sqlite', 'database': 'unused.db'},
                                 'access': {'tenantIds': ['self']}}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(deployment_config, '_DEPLOYMENT', document):
            executor=Executor(DataContext('r','test','tester','national-excellence-data-qa',Path(directory),data_tenant_id='business-a'),
                              {}, Catalog(), source_keys=['schoolDoubleHigh'])
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
