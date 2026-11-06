"""按来源解析每轮业务租户及额外授权，固定和动态 SQL 均强制单学校范围。"""

import asyncio
import json
import sqlite3
import unittest
import yaml

from data_access.context import DataContext, DataError
from runtime.auth import encode_hs256_jwt
from runtime.data_services import RunServices
from tests import test_data_access as fixtures


def business_token(tenant):
    return encode_hs256_jwt({'tenantId': tenant, 'userId': 'business-user'}, 'test-business-secret')


class DataTenantScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DataAccessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for policy in self.fixture.config['policies'].values():
            policy['dynamic_sql_enabled'] = True
        self.fixture.config['policies']['first']['tenantIds'] = ['self', 'business-b']
        with sqlite3.connect(self.fixture.root / 'first.db') as db:
            db.execute('INSERT INTO sales VALUES (?, ?, ?)', ('business-c', 777, 'forbidden'))

    def payload(self, tenant='business-a', run='tenant-run'):
        return {'run_id': run, 'capability_ref': 'qa',
                '_data_identity': {'tenant_id': 'business-a', 'user_id': 'u1'},
                '_data_run_directory': str(self.fixture.root / run),
                'credentials': {'platformBearer': business_token(tenant)}}

    def executor(self, tenant='business-a'):
        return self.fixture.make_executor(DataContext.from_payload(self.payload(tenant)))

    def schools(self, executor):
        return executor.resolve_entities('first', 'sales', 'school', '')['candidates']

    def test_source_has_separate_self_and_extra_school_scopes(self):
        executor = self.executor()
        schools = self.schools(executor)
        self.assertEqual(len(schools), 2)
        self.assertEqual([school['name'] for school in schools], ['当前学校', '额外授权学校2'])
        self.assertEqual([executor.execute_query_spec('first','sales','total',{},school['scope_ref'])['rows']
                          for school in schools], [[{'total':10}], [{'total':999}]])
        second = executor.resolve_entities('second', 'sales', 'school', '')['candidates']
        self.assertEqual(len(second), 1)

    def test_missing_business_token_cannot_fall_back_to_run_identity_or_extra_school(self):
        payload = self.payload()
        payload.pop('credentials')
        for tenants in (['self', 'business-b'], ['business-b']):
            self.fixture.config['policies']['first']['tenantIds'] = tenants
            executor = self.fixture.make_executor(DataContext.from_payload(payload))
            with self.subTest(tenants=tenants), self.assertRaisesRegex(DataError, 'BUSINESS_IDENTITY_REQUIRED'):
                executor.access('first')

    def test_self_scope_is_resolved_from_each_business_token_and_deduplicated(self):
        executor = self.executor('business-b')
        schools = self.schools(executor)
        self.assertEqual(len(schools), 1)
        self.assertEqual(executor.execute_query_spec('first','sales','total',{},schools[0]['scope_ref'])['rows'], [{'total':999}])

    def test_business_payload_cannot_expand_source_tenants(self):
        payload = self.payload()
        payload['payload'] = {'tenantIds': ['self', 'business-c'], 'access': {'tenantIds': ['business-c']}}
        executor = self.fixture.make_executor(DataContext.from_payload(payload))
        schools = self.schools(executor)
        self.assertEqual([executor.execute_query_spec('first','sales','total',{},school['scope_ref'])['rows']
                          for school in schools], [[{'total':10}], [{'total':999}]])
        _, policy, _ = executor.access('first')
        with self.assertRaisesRegex(DataError, 'SCOPE_FORBIDDEN'):
            executor._scope_ref('first', 'sales', None, policy, 'business-c')

    def test_same_project_id_in_two_schools_keeps_entity_and_scope_separate(self):
        with sqlite3.connect(self.fixture.root / 'first.db') as db:
            db.execute("UPDATE sales SET private_id = 'shared-project'")
        source_path = self.fixture.root / 'databases/first/source.json'
        source = json.loads(source_path.read_text())
        source['domains']['sales']['entities'] = {'project': {'query_id': 'projects',
            'name_field': 'name', 'id_field': 'project_id', 'parameter': 'project_id'}}
        fixtures.save(source_path, source)
        path = self.fixture.root / 'databases/first/metrics/sales/sales.yaml'
        bundle = yaml.safe_load(path.read_text())
        base = bundle['metrics'][0]
        bundle['parameters']['project_id'] = {'type': ['string', 'null'], 'required': True,
                                             'origin': 'authorized_resolution'}
        bundle['metrics'] += [{**base, 'id': 'projects',
            'sql': 'SELECT private_id AS project_id, private_id AS name FROM sales WHERE tenant = :tenant_id',
            'output': [{'name': 'project_id', 'type': 'string'}, {'name': 'name', 'type': 'string'}]},
            {**base, 'id': 'project_total', 'parameters': ['project_id'],
             'sql': base['sql'] + ' AND private_id = :project_id'}]
        path.write_text(yaml.safe_dump(bundle), encoding='utf-8')
        executor = self.executor()
        projects = executor.resolve_entities('first', 'sales', 'project', '')['candidates']
        self.assertEqual(len(projects), 2)
        for project, expected in zip(projects, (10, 999)):
            result = executor.execute_query_spec('first', 'sales', 'project_total', {}, project['scope_ref'])
            self.assertEqual(result['rows'], [{'total': expected}])
        with self.assertRaisesRegex(DataError, 'ENTITY_FORBIDDEN'):
            executor.execute_query_spec('first', 'sales', 'project_total', {}, projects[0]['scope_ref'],
                                        {'project_id': projects[1]['entity_ref']})

    def test_dynamic_nested_queries_cannot_expand_either_school(self):
        executor = self.executor()
        queries = [
            'SELECT SUM(amount) AS n FROM sales',
            'SELECT SUM(amount) AS n FROM sales WHERE amount > :minimum OR 1 = 1',
            'WITH x AS (SELECT amount FROM sales) SELECT SUM(amount) AS n FROM x',
            'SELECT (SELECT SUM(amount) FROM sales) AS n',
            'SELECT MAX(a.amount + b.amount) AS n FROM sales a LEFT JOIN sales b ON a.private_id = b.private_id',
            'SELECT SUM(amount) AS n FROM sales UNION SELECT MAX(amount) AS n FROM sales',
        ]
        for school, expected in zip(self.schools(executor), (10, 999)):
            for sql in queries:
                with self.subTest(school=expected, sql=sql):
                    parameters = {'minimum': 0} if ':minimum' in sql else {}
                    result = executor.execute_readonly_sql('first', 'sales', sql, parameters, 'test', school['scope_ref'])
                    self.assertEqual(result['rows'], [{'n': expected * 2 if 'a.amount + b.amount' in sql else expected}])

    def test_dynamic_parameters_cannot_override_server_tenant_and_missing_column_fails(self):
        executor = self.executor()
        scope = self.schools(executor)[0]['scope_ref']
        with self.assertRaisesRegex(DataError, 'PARAMETERS_INVALID'):
            executor.execute_readonly_sql('first', 'sales', 'SELECT SUM(amount) AS n FROM sales',
                {'_tenant_scope': 'business-c'}, 'test', scope)
        with self.assertRaisesRegex(DataError, 'PARAMETERS_INVALID'):
            executor.execute_readonly_sql('first', 'sales', 'SELECT :_tenant_scope AS n FROM sales',
                {}, 'test', scope)
        self.fixture.config['policies']['first']['domains']['sales']['tenant_column'] = 'missing'
        with self.assertRaisesRegex(DataError, 'TENANT_SCOPE_NOT_ENFORCED'):
            self.executor().access('first')

    def test_grouped_join_keeps_each_physical_table_inside_its_own_scope(self):
        executor = self.executor()
        for school in self.schools(executor):
            result = executor.execute_readonly_sql('first', 'sales',
                'SELECT COUNT(*) AS n FROM (sales b JOIN sales c ON 1=1)', {}, 'test', school['scope_ref'])
            self.assertEqual(result['rows'], [{'n': 1}])
        with self.assertRaises(DataError):
            executor.execute_readonly_sql('first', 'sales',
                'SELECT COUNT(*) AS n FROM (sales b JOIN sales c ON 1=1) d', {}, 'test',
                self.schools(executor)[0]['scope_ref'])

    def test_fixed_query_missing_tenant_predicate_is_still_limited(self):
        path = self.fixture.root / 'databases/first/metrics/sales/sales.yaml'
        path.write_text(path.read_text().replace(' WHERE tenant = :tenant_id', ''), encoding='utf-8')
        executor = self.executor()
        self.assertEqual([executor.execute_query_spec('first', 'sales', 'total', {}, s['scope_ref'])['rows']
                          for s in self.schools(executor)], [[{'total': 10}], [{'total': 999}]])

    def test_user_cannot_export_tenant_identity(self):
        executor = self.executor()
        scope = self.schools(executor)[0]['scope_ref']
        with self.assertRaisesRegex(DataError, 'INTERNAL_COLUMN_FORBIDDEN'):
            executor.execute_readonly_sql('first','sales','SELECT tenant AS identity FROM sales',{},'test',scope)

    def test_registered_hpm_dynamic_sql_cannot_return_tenant_identity(self):
        schema = fixtures.Catalog().schema('schoolDoubleHigh', 'hpm')
        with self.assertRaisesRegex(DataError, 'INTERNAL_COLUMN_FORBIDDEN'):
            fixtures.validate_sql('SELECT tenant_id_ AS school FROM t_hpm_project', schema, dynamic=True)

    def test_prepared_context_and_results_do_not_expose_business_identity(self):
        executor = self.executor()
        context = executor.prepare_context(['schema'])
        domain = context['sources'][0]['domains'][0]
        self.assertEqual(len(domain['school_scopes']), 2)
        self.assertNotIn('scope_ref', domain)
        result = executor.execute_query_spec('first', 'sales', 'total', {}, domain['school_scopes'][0]['scope_ref'])
        for secret in ('business-a', 'business-b', business_token('business-a')):
            self.assertNotIn(secret, json.dumps(context) + json.dumps(result))

    def test_next_run_token_changes_self_and_invalidates_old_references(self):
        async def scenario():
            self.fixture.save_connections()
            services = RunServices(['first'], env=self.fixture.env, catalog=self.fixture.catalog)
            try:
                await services.bind(self.payload())
                old_scope = self.schools(services.current())[0]['scope_ref']
                old_result = services.current().execute_query_spec('first','sales','total',{},old_scope)['result_ref']
                await services.bind(self.payload('business-c', 'next-run'))
                executor = services.current()
                with self.assertRaisesRegex(DataError, 'SCOPE_FORBIDDEN'):
                    executor.execute_query_spec('first', 'sales', 'total', {}, old_scope)
                with self.assertRaisesRegex(DataError, 'RESULT_FORBIDDEN'):
                    executor.results.page(old_result)
                result = executor.execute_query_spec('first', 'sales', 'total', {}, self.schools(executor)[0]['scope_ref'])
                self.assertEqual(result['rows'], [{'total': 777}])
            finally:
                await services.close()
        asyncio.run(scenario())

    def test_invalid_business_token_or_tenant_is_rejected_without_echo(self):
        for token in ('opaque-invalid-token', business_token(''), business_token('*'), business_token('default')):
            with self.subTest(token_kind=token.count('.')):
                payload = self.payload()
                payload['credentials']['platformBearer'] = token
                with self.assertRaises(DataError) as caught:
                    DataContext.from_payload(payload)
                self.assertNotIn(token, str(caught.exception))
