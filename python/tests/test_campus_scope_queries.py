"""用虚构统计值核验预置群体补查的请求、预算及身份隔离。"""

import unittest
from unittest.mock import AsyncMock, patch

from capability_packs.registry import _directory, _load_module

campus = _load_module(_directory('campus-brain-query'))


class CampusScopeTests(unittest.IsolatedAsyncioTestCase):
    def service(self, maximum=10):
        with patch('runtime.deployment_config._DEPLOYMENT', {'campusMcp': {
                'url': 'https://campus.example.test/mcp', 'domainName': 'campus.example.test', 'headers': {'app-key':'test-app-key', 'domain-name':'campus.example.test'}}}):
            assets = campus.load_campus_assets()
        assets['config']['max_calls'] = maximum
        return campus.CampusQuery(assets, {'platformBearer': 'first-secret'})

    async def query(self, service, scopes, year=2025):
        item = {'item_id': 'metric', 'indicator_code': 'hydss', 'scopes': scopes}
        if year is not None:
            item['year'] = year
        result = await service.execute_plan({'subject': 'current_school', 'items': [item]})
        return result['items'][0]

    async def test_supplement_only_requests_new_scopes_and_preserves_cached_value(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'year': 2025, 'indicator_value': 17}},
            {'success': True, 'data': {'year': 2025, 'indicator_value': 999,
                'scoped_metrics': [{'scope': 'province_median', 'value': 9},
                                   {'scope': 'province_rank', 'value': 4}]}}])
        await self.query(service, ['indicator_value'])
        result = await self.query(service, ['province_rank', 'indicator_value', 'province_median'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['data']['indicator_value'], 17)
        self.assertEqual({r['scope']: r['value'] for r in result['data']['scoped_metrics']},
                         {'province_median': 9, 'province_rank': 4})
        self.assertEqual(set(service._request.call_args.args[1]['payload']['scopes']),
                         {'province_median', 'province_rank'})
        self.assertEqual(service._request.await_count, 2)
        # 调用者修改返回值不能污染后续复用。
        result['data']['scoped_metrics'][0]['value'] = -1
        again = await self.query(service, ['province_median', 'indicator_value', 'province_rank'])
        self.assertEqual({r['scope']: r['value'] for r in again['data']['scoped_metrics']},
                         {'province_median': 9, 'province_rank': 4})
        self.assertEqual(service._request.await_count, 2)

    async def test_cached_queries_work_at_budget_limit_but_new_scopes_do_not(self):
        service = self.service(maximum=1)
        service._request = AsyncMock(return_value={'success': True, 'data': {'indicator_value': 0}})
        await self.query(service, ['indicator_value'])
        self.assertEqual((await self.query(service, ['indicator_value']))['data']['indicator_value'], 0)
        with self.assertRaisesRegex(ValueError, '预算'):
            await self.query(service, ['province_rank'])
        self.assertEqual(service._request.await_count, 1)

    async def test_plan_budget_counts_only_new_calls_and_rejects_before_execution(self):
        service = self.service(maximum=2)
        service._request = AsyncMock(return_value={'success': True, 'data': {'indicator_value': 0}})
        await self.query(service, ['indicator_value'])
        items = [
            {'item_id': 'cached', 'indicator_code': 'hydss', 'year': 2025, 'scopes': ['indicator_value']},
            {'item_id': 'new', 'indicator_code': 'hydss', 'year': 2024, 'scopes': ['indicator_value']}]
        result = await service.execute_plan({'subject': 'current_school', 'items': items})
        self.assertTrue(result['complete'])
        self.assertEqual(service._request.await_count, 2)
        with self.assertRaisesRegex(ValueError, '预算'):
            await service.execute_plan({'subject': 'current_school', 'items': [
                {**items[0], 'scopes': ['province_rank']},
                {**items[1], 'scopes': ['province_median']}]})
        self.assertEqual(service._request.await_count, 2)

    async def test_empty_scopes_are_not_retried_when_other_scopes_are_added(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': None},
            {'success': True, 'data': {'year': 2025, 'province_rank': 4}}])
        self.assertEqual((await self.query(service, ['indicator_value']))['status'], 'empty')
        self.assertEqual((await self.query(service, ['indicator_value']))['status'], 'empty')
        result = await self.query(service, ['indicator_value', 'province_rank'])
        self.assertEqual(result['data']['province_rank'], 4)
        self.assertEqual(service._request.call_args.args[1]['payload']['scopes'], ['province_rank'])
        self.assertEqual(service._request.await_count, 2)

    async def test_failed_scopes_do_not_trigger_another_upstream_attempt(self):
        service = self.service()
        service._request = AsyncMock(side_effect=RuntimeError('upstream failure'))
        self.assertEqual((await self.query(service, ['indicator_value']))['status'], 'failed')
        self.assertEqual((await self.query(service, ['indicator_value']))['status'], 'failed')
        self.assertEqual(service._request.await_count, 1)

    async def test_partial_failure_does_not_hide_successful_cached_and_new_scopes(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'indicator_value': 17}},
            RuntimeError('rank failed'),
            {'success': True, 'data': {'province_median': 9}}])
        await self.query(service, ['indicator_value'])
        self.assertEqual((await self.query(service, ['province_rank']))['status'], 'failed')
        result = await service.execute_plan({'subject': 'current_school', 'items': [{
            'item_id': 'all', 'indicator_code': 'hydss', 'year': 2025,
            'scopes': ['indicator_value', 'province_rank', 'province_median']}]})
        self.assertFalse(result['complete'])
        self.assertEqual(result['status'], 'partial')
        item = result['items'][0]
        self.assertEqual(item['data']['indicator_value'], 17)
        self.assertEqual(item['data']['province_median'], 9)
        self.assertEqual(item['failed_scopes'], ['province_rank'])
        self.assertEqual(service._request.call_args.args[1]['payload']['scopes'], ['province_median'])
        self.assertEqual(service._request.await_count, 3)

    async def test_failed_supplement_still_returns_requested_cached_values(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'indicator_value': 17}},
            RuntimeError('rank failed')])
        await self.query(service, ['indicator_value'])
        result = await self.query(service, ['indicator_value', 'province_rank'])
        self.assertEqual(result['data']['indicator_value'], 17)
        self.assertEqual(result['failed_scopes'], ['province_rank'])
        self.assertEqual((await self.query(service, ['province_rank']))['status'], 'failed')
        self.assertEqual(service._request.await_count, 2)

    async def test_missing_returned_scope_is_explicitly_empty_and_not_retried(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {'indicator_value': 0}})
        result = await self.query(service, ['indicator_value', 'province_rank'])
        self.assertEqual(result['data']['indicator_value'], 0)
        self.assertEqual(result['empty_scopes'], ['province_rank'])
        self.assertEqual((await self.query(service, ['province_rank']))['status'], 'empty')
        self.assertEqual(service._request.await_count, 1)

    async def test_latest_supplement_uses_first_returned_year_and_explicit_year_reuses_it(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'year': 2024, 'indicator_value': 17}},
            {'success': True, 'data': {'year': 2024, 'province_rank': 4}}])
        await self.query(service, ['indicator_value'], year=None)
        await self.query(service, ['province_rank'], year=None)
        self.assertEqual(service._request.call_args.args[1]['payload']['year'], 2024)
        self.assertEqual((await self.query(service, ['indicator_value'], year=2024))['data']['indicator_value'], 17)
        self.assertEqual(service._request.await_count, 2)

    async def test_latest_without_a_returned_year_cannot_supplement_by_guessing(self):
        service = self.service()
        service._request = AsyncMock(return_value={'success': True, 'data': {'indicator_value': 17}})
        await self.query(service, ['indicator_value'], year=None)
        with self.assertRaisesRegex(ValueError, '年份'):
            await self.query(service, ['province_rank'], year=None)
        self.assertEqual(service._request.await_count, 1)

    async def test_changed_upstream_year_cannot_be_merged_with_previous_results(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'year': 2025, 'indicator_value': 17}},
            {'success': True, 'data': {'year': 2024, 'province_rank': 4}}])
        await self.query(service, ['indicator_value'])
        self.assertEqual((await self.query(service, ['province_rank']))['status'], 'failed')
        self.assertEqual((await self.query(service, ['indicator_value']))['data']['indicator_value'], 17)

    async def test_rebinding_credentials_discards_all_cached_values(self):
        service = self.service()
        service._request = AsyncMock(side_effect=[
            {'success': True, 'data': {'indicator_value': 17}},
            {'success': True, 'data': {'indicator_value': 12}}])
        await self.query(service, ['indicator_value'])
        service.bind({'platformBearer': 'second-secret'})
        self.assertEqual((await self.query(service, ['indicator_value']))['data']['indicator_value'], 12)
        self.assertEqual(service._request.call_args.args[1]['user_context_token'], 'second-secret')
        service.clear()
        with self.assertRaises(ValueError):
            await self.query(service, ['indicator_value'])
        self.assertEqual(service._request.await_count, 2)

    async def test_missing_scopes_rejected_before_any_remote_query(self):
        service = self.service()
        service._request = AsyncMock()
        with self.assertRaisesRegex(ValueError, 'scopes'):
            await service.execute_plan({'subject': 'current_school', 'items': [
                {'item_id': 'missing', 'indicator_code': 'hydss', 'year': 2025}]})
        service._request.assert_not_awaited()

    def test_model_schema_exposes_scope_enum_without_cli_filtered_root_composition(self):
        from jsonschema import Draft202012Validator
        from capability_packs.registry import load_pack
        spec = next(o for o in load_pack('campus-brain-query').operations if o.ref == 'execute_query_plan')
        scopes = spec.input_schema['properties']['items']['items']['properties']['scopes']
        self.assertEqual(scopes['items']['enum'], self.service().assets['config']['tools'][
            'get_indicator_metrics']['schema']['properties']['scopes']['items']['enum'])
        validator = Draft202012Validator(spec.input_schema)
        item = {'item_id': 'metric', 'indicator_code': 'hydss'}
        # 真实 CLI 会静默过滤根级 allOf 工具；条件必填由 Service 严格校验。
        self.assertFalse({'allOf', 'anyOf', 'oneOf'} & spec.input_schema.keys())
        self.assertFalse(validator.is_valid({'subject': 'current_school', 'items': [
            {**item, 'scopes': ['made_up_statistic']}]}))
        self.assertTrue(validator.is_valid({'subject': 'current_school', 'items': [
            {**item, 'scopes': ['indicator_value']}]}))

    async def test_norm_scopes_rejected_before_any_remote_query(self):
        service = self.service()
        service._request = AsyncMock()
        code = next(r['code'] for r in service.assets['catalogs']['norm_analysis']
                    if not r['definition_conflict'])
        with self.assertRaisesRegex(ValueError, '不符合已开通范围'):
            await service.execute_plan({'subject': 'norm_group', 'school_names': ['武汉交通职业学院'],
                'items': [{'item_id': 'invalid', 'indicator_code': code,
                           'scopes': ['indicator_value']}]})
        service._request.assert_not_awaited()
