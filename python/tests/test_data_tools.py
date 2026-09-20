import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from data_access.context import DataError
from tools.data import create_data_server


class DataToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        catalog = Mock()
        catalog.source.return_value = {'domains': {'hpm': {'entities': {
            'project': {}, 'task_project': {}, 'task': {}, 'campus': {},
        }}}}
        self.executor = Mock()
        self.services = SimpleNamespace(
            source_keys=('test_source',), catalog=catalog,
            current=lambda: self.executor, call=AsyncMock(),
        )
        with patch('tools.data.create_sdk_mcp_server', side_effect=lambda **kwargs: kwargs):
            config = create_data_server(self.services)
        self.tools = {tool.name: tool for tool in config['tools']}

    async def test_entity_types_are_derived_from_registered_assets(self):
        schema = self.tools['resolve_entities'].input_schema['properties']['entity_type']
        self.assertEqual(set(schema.get('enum', [])), {'school', 'project', 'task_project', 'task', 'campus'})
        self.assertIn('school', schema.get('description', ''))

    async def test_invalid_entity_type_is_rejected_with_safe_repair_details(self):
        result = await self.tools['resolve_entities'].handler({
            'source_key': 'test_source', 'domain': 'hpm', 'entity_type': 'scope-secret-value', 'query': '',
        })
        self.assertTrue(result.get('isError'))
        error = json.loads(result['content'][0]['text'])['error']
        self.assertEqual(error['code'], 'PARAMETERS_INVALID')
        self.assertEqual(error['field'], 'entity_type')
        self.assertIn('school', error['allowedValues'])
        self.assertNotIn('scope-secret-value', json.dumps(result))
        self.services.call.assert_not_awaited()

    async def test_school_scope_uses_existing_executor_without_extra_lookup(self):
        self.services.call.return_value = {'candidates': [{'scope_ref': 'scope_test'}]}
        arguments = {'source_key': 'test_source', 'domain': 'hpm', 'entity_type': 'school', 'query': ''}
        result = await self.tools['resolve_entities'].handler(arguments)
        self.services.call.assert_awaited_once_with(self.executor.resolve_entities, **arguments)
        self.assertEqual(json.loads(result['content'][0]['text']), self.services.call.return_value)

    async def test_missing_parameter_identifies_only_the_missing_schema_field(self):
        result = await self.tools['resolve_entities'].handler({
            'source_key': 'test_source', 'domain': 'hpm', 'entity_type': 'school',
        })
        error = json.loads(result['content'][0]['text'])['error']
        self.assertEqual(error.get('field'), 'query')
        self.assertIn('description', error)
        self.services.call.assert_not_awaited()

    async def test_scope_denial_is_not_retried_or_replaced(self):
        self.services.call.side_effect = DataError('SCOPE_FORBIDDEN')
        result = await self.tools['resolve_entities'].handler({
            'source_key': 'test_source', 'domain': 'hpm', 'entity_type': 'school', 'query': '',
        })
        self.assertTrue(result['isError'])
        self.assertEqual(json.loads(result['content'][0]['text'])['error']['code'], 'SCOPE_FORBIDDEN')
        self.assertEqual(self.services.call.await_count, 1)

    async def test_unknown_exception_keeps_sensitive_details_private(self):
        self.services.call.side_effect = RuntimeError('database-password-do-not-expose')
        result = await self.tools['list_data_sources'].handler({})
        self.assertTrue(result['isError'])
        self.assertNotIn('database-password', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
