"""客户全量共享业务数据，执行身份和结果仍然隔离。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data_access.access import resolve_data_access
from data_access.connections import load_config
from data_access.context import DataContext, DataError
from data_access.catalog import Catalog


class CustomerDataBoundaryTests(unittest.TestCase):
    def test_connection_and_query_are_independent_of_catalog_permissions(self):
        document = {'databases': {
            'schoolDoubleHigh': {'connection': {'driver': 'sqlite', 'database': 'test.db'},
                                 'access': {'tenantIds': ['self']},
                                 'query': {'max_rows': 99, 'dynamic_sql_enabled': True}}}}
        with tempfile.TemporaryDirectory() as folder, patch('runtime.deployment_config._DEPLOYMENT', document):
            configured = load_config({})
            context = DataContext('run', 'runtime-a', 'user-a', 'qa', Path(folder), data_tenant_id='business-a')
            catalog = Catalog()
            source = catalog.source('schoolDoubleHigh')
            policy = resolve_data_access(context, source, configured['schoolDoubleHigh'], catalog)
            self.assertEqual(policy['authorized_tenants'], ['business-a'])
            self.assertEqual(policy['domains']['hpm']['tables'], catalog.schema('schoolDoubleHigh', 'hpm')['tables'])
            self.assertEqual(len(policy['domains']['hpm']['queries']), 34)
            self.assertTrue(policy['dynamic_sql_enabled'])
            other = DataContext('other', 'runtime-b', 'user-a', 'qa', Path(folder), data_tenant_id='business-b')
            self.assertEqual(resolve_data_access(other, source, configured['schoolDoubleHigh'], catalog)['authorized_tenants'],
                             ['business-b'])
