"""一部署一客户，固定和动态查询均不依赖模型补租户条件。"""

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

    def test_customer_has_one_scope_and_only_own_rows(self):
        executor = self.executor()
        schools = self.schools(executor)
        self.assertEqual(len(schools), 1)
        self.assertEqual(executor.execute_query_spec('first','sales','total',{},schools[0]['scope_ref'])['rows'], [{'total':10}])

    def test_missing_business_token_uses_fixed_deployment_and_mismatch_is_rejected(self):
        payload = self.payload()
        payload.pop('credentials')
        executor = self.fixture.make_executor(DataContext.from_payload(payload))
        self.assertEqual(len(self.schools(executor)), 1)
        with self.assertRaisesRegex(DataError, 'TENANT_FORBIDDEN'):
            self.executor('business-b').access('first')

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
        for school, expected in zip(self.schools(executor), (10,)):
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
                          for s in self.schools(executor)], [[{'total': 10}]])

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
        self.assertEqual(len(domain['school_scopes']), 1)
        self.assertEqual(domain['scope_ref'], domain['school_scopes'][0]['scope_ref'])
        result = executor.execute_query_spec('first', 'sales', 'total', {}, domain['scope_ref'])
        for secret in ('business-a', 'business-b', business_token('business-a')):
            self.assertNotIn(secret, json.dumps(context) + json.dumps(result))

    def test_next_run_token_changes_self_and_invalidates_old_references(self):
        async def scenario():
            self.fixture.save_connections()
            services = RunServices(['first'], env=self.fixture.env, catalog=self.fixture.catalog)
            try:
                await services.bind(self.payload())
                old_scope = self.schools(services.current())[0]['scope_ref']
                await services.bind(self.payload('business-a', 'next-run'))
                executor = services.current()
                with self.assertRaisesRegex(DataError, 'SCOPE_FORBIDDEN'):
                    executor.execute_query_spec('first', 'sales', 'total', {}, old_scope)
                result = executor.execute_query_spec('first', 'sales', 'total', {}, self.schools(executor)[0]['scope_ref'])
                self.assertEqual(result['rows'], [{'total': 10}])
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
