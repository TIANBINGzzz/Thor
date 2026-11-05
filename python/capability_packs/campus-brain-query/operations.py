"""校园 MCP 的受控 SDK 适配；业务词表和参数范围由显式资产提供。"""

import asyncio
from copy import deepcopy
import csv
from dataclasses import replace
import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from runtime.mcp_auth import MCPArgumentBinding
from runtime.mcp_transport import call_mcp_tool, validate_http_connection
from runtime.asset_registry import read_manifest
from runtime.deployment_config import ConfigSnapshot
from runtime.capability_operations import OperationInputError, _notify_mcp_error
from runtime.tool_services import service_asset_revision


class CampusInputError(OperationInputError):
    """可直接向模型反馈的本地参数校验错误；不包含上游正文。"""


ASSET_ROOT = Path(__file__).resolve().parents[3] / '.claude/capabilities/campus-brain-query'


def load_campus_assets(settings=None, directory=ASSET_ROOT, config_path=None, *, operations=None):
    """只读取登记文件；知识保留在服务端内存，不整表注入提示词。"""
    directory = Path(directory).resolve()
    entry = read_manifest(directory, 'capability.json')
    config_path = (directory / (config_path or entry['toolConfig']['campus'])).resolve()
    if not config_path.is_relative_to(directory):
        raise RuntimeError('校园工具资产路径无效')
    raw = config_path.read_bytes()
    config = json.loads(raw)
    settings = settings or ConfigSnapshot()
    connection = settings.resolve(config.pop('connection'))
    validate_http_connection(connection)
    config.update(connection)
    minimum = config['minimum_schools']
    if type(minimum) is not int or minimum < 1:
        raise RuntimeError('常模最少学校数量配置无效')
    maximum = config['max_calls']
    if type(maximum) is not int or maximum < 1:
        raise RuntimeError('校园查询调用上限配置无效')
    if operations is None:
        from capability_packs.registry import read_pack_manifest
        operations = read_pack_manifest('campus-brain-query').operations
    definitions = {operation.ref: operation for operation in operations}
    for name, rule in config['tools'].items():
        # 内部 Service 和 Agent Tool 使用同一份接口定义；资产只保留业务规则。
        rule['schema'] = deepcopy(definitions[name].input_schema['properties']['payload'])
    norm = config['tools']['get_norm_metrics']
    norm['schema']['properties']['schools']['minItems'] = minimum
    catalogs = {}
    for kind, name in config['catalogs'].items():
        path = (config_path.parent / name).resolve()
        if not path.is_relative_to(config_path.parent) or path.suffix != '.csv':
            raise RuntimeError('校园知识资产路径无效')
        with path.open(encoding='utf-8', newline='') as stream:
            catalogs[kind] = [{**row, 'analysis': kind} for row in csv.DictReader(stream)]
        if kind != 'schools':
            definitions = {}
            for row in catalogs[kind]:
                definitions.setdefault(row['code'], set()).add(row['name'])
            for row in catalogs[kind]:
                row['definition_conflict'] = len(definitions[row['code']]) > 1
    return {'config': config, 'catalogs': catalogs,
            'revision': service_asset_revision(directory, config_path.relative_to(directory), settings)}


def _normalized(text):
    """去除末尾括注及常见分隔符，统一检索文本的大小写。"""
    text = re.sub(r'[（(][^()（）]*[）)]$', '', text.strip())
    return re.sub(r'[\s，,。；;、：:]', '', text).casefold()


def _unique_strings(value):
    return (isinstance(value, list) and all(isinstance(item, str) for item in value)
            and len(value) == len(set(value)))


def _statistic(key, value):
    """数值字段不允许承载JSON、错误文本、布尔值或非有限数；来源名称不从上游透传。"""
    if value is None:
        return None
    if key == 'rank_type' and value in ('mock', 'real', 'simulated', 'actual'):
        return value
    if isinstance(value, str) and re.fullmatch(r'-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?', value):
        value = json.loads(value)
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RuntimeError('上游统计字段类型无效')
    return value


class CampusQuery:
    def __init__(self, assets, credentials):
        """绑定可信校园资产与本轮凭据，串行执行身份和统计查询。"""
        self.assets = assets
        self._lock = asyncio.Lock()
        self.clear()
        if credentials is not None:
            self.bind(credentials)

    def configure_assets(self, assets):
        """在两轮之间更新知识与连接；旧轮身份和调用状态不得带入新资产。"""
        self.clear()
        self.assets = assets

    def bind(self, credentials):
        """每轮重新绑定；不得用上轮身份或调用预算授权下一轮。"""
        self.clear()
        self._binding = MCPArgumentBinding('campus', credentials)

    def clear(self):
        """清除凭据、身份和本轮结果；Client 复用不能复用上轮数据。"""
        if getattr(self, '_binding', None):
            self._binding.clear()
        self._seen = set()
        self._indicator_results = {}
        self._latest_years = {}
        self._calls = 0
        self._school_id = None
        self._identity_failed = False

    def _indicator_state(self, payload):
        """按本轮已查统计项判断补查范围；最新值补查须固定已返回年份。"""
        year = payload.get('year', self._latest_years.get(payload['indicator_code']))
        key = (payload['indicator_code'], year)
        state = self._indicator_results.get(key)
        missing = [scope for scope in payload['scopes']
                   if state is None or scope not in state['attempted']]
        if state is not None and year is None and missing:
            raise CampusInputError('首次查询未返回年份，不能猜测年份补查；请明确查询年份')
        return key, state, missing

    async def _query_indicator(self, payload, rule):
        key, state, missing = self._indicator_state(payload)
        if missing:
            if self._calls >= self.assets['config']['max_calls']:
                raise CampusInputError('本轮业务查询预算已用完，不能继续补查')
            if state is None:
                state = {'attempted': set(), 'failed': set(), 'values': {}, 'year': key[1]}
                self._indicator_results[key] = state
            # 在请求前登记尝试；上游失败、空结果均不能通过重排 scopes 自动重试。
            state['attempted'].update(missing)
            state['failed'].update(missing)
            self._calls += 1
            try:
                state = await self._load_indicator_scopes(payload, rule, key, state, missing)
            except Exception:
                # 补查失败仍可返回本次请求的已成功项；失败范围留在 state，禁止重试。
                if not any(state['values'].get(scope) for scope in payload['scopes']):
                    raise
        result = {}
        for scope in payload['scopes']:
            value = state['values'].get(scope)
            if value:
                result.update({k: v for k, v in value.items() if k != 'scoped_metrics'})
                if 'scoped_metrics' in value:
                    result.setdefault('scoped_metrics', []).extend(value['scoped_metrics'])
        if result and state['year'] is not None:
            result['year'] = state['year']
        if not result and any(scope in state['failed'] for scope in payload['scopes']):
            raise RuntimeError('所请求统计项此前查询失败，本轮不自动重试')
        return {'success': True, 'data': deepcopy(result) if result else None}

    async def _load_indicator_scopes(self, payload, rule, key, state, missing):
        """请求新增统计项，校验实际年份后合并本轮证据。"""
        request = {**payload, 'scopes': missing}
        if key[1] is not None:
            request['year'] = key[1]
        data = await self._fetch('get_indicator_metrics', request, rule)
        year = data.get('year') if data else None
        if year is not None:
            if type(year) not in (int, float) or not 1000 <= year <= 9999 or int(year) != year:
                raise RuntimeError('上游返回年份无效')
            year = int(year)
            if key[1] is not None and year != key[1]:
                raise RuntimeError('上游返回年份与本次查询不一致')
        year = key[1] if year is None else year
        state['year'] = year
        for scope in missing:
            value = {}
            if data:
                if data.get(scope) is not None:
                    value = {scope: data[scope], **{k: data[k] for k in (
                        'rank_type', 'school_count', 'cohort_size', 'percentile') if k in data}}
                scoped = [r for r in data.get('scoped_metrics', [])
                          if r['scope'] == scope and r.get('value') is not None]
                if scoped:
                    value['scoped_metrics'] = scoped
            state['values'][scope] = value or None
        state['failed'].difference_update(missing)
        if payload.get('year') is None and year is not None:
            # 最新查询与其实际年份共享结果；已查项保留首次证据，避免覆盖。
            target = self._indicator_results.setdefault((key[0], year), state)
            if target is not state:
                for scope in state['attempted'] - target['attempted']:
                    target['attempted'].add(scope)
                    if scope in state['failed']:
                        target['failed'].add(scope)
                    else:
                        target['values'][scope] = state['values'][scope]
                state = target
            self._latest_years[key[0]] = year
            self._indicator_results[key] = state
        return state

    def search(self, arguments):
        """检索本地登记词表并分页返回候选，文字命中不代表身份确认。"""
        if (not isinstance(arguments, dict) or set(arguments) - {'kind', 'query', 'offset'}
                or arguments.get('kind') not in self.assets['catalogs']):
            raise CampusInputError('请选择有效的知识类型')
        query = arguments.get('query')
        offset = arguments.get('offset', 0)
        if isinstance(query, list):
            if not 1 <= len(query) <= 30 or any(not isinstance(q, str) for q in query):
                raise CampusInputError('批量检索须为1至30个检索词')
            return {'queries': [{'query': q, **self.search({**arguments, 'query': q})} for q in query]}
        if not isinstance(query, str) or not query.strip() or len(query) > 200 or type(offset) is not int or offset < 0:
            raise CampusInputError('请提供具体检索词和有效页位置')
        needle = _normalized(query)
        if not needle:
            raise CampusInputError('请提供具体检索词')
        rows = self.assets['catalogs'][arguments['kind']]
        # 精确候选优先但不隐去其他口径，消歧由Agent根据用户语义完成。
        found = [r for r in rows if needle in _normalized(r['name']) or query == r['code']]
        if not found:
            # 只提供按字序匹配的候选，不把简称猜测成唯一正式身份。
            pattern = '.*'.join(re.escape(c) for c in needle)
            found = [r for r in rows if re.search(pattern, _normalized(r['name']))]
        def match_basis(row):
            """区分名称全匹配、编码匹配、子串及字序匹配。"""
            if _normalized(row['name']) == needle:
                return 'exact'
            if query == row['code']:
                return 'code'
            return 'substring' if needle in _normalized(row['name']) else 'subsequence'

        def match_order(row):
            """优先名称全匹配与编码匹配，再按名称和年份稳定排序。"""
            return match_basis(row) not in ('exact', 'code'), row['name'], row.get('year', '')

        found.sort(key=match_order)
        # 匹配依据只描述文字命中方式，不代表语义置信度；不修改共享知识记录。
        records = [{**r, 'match_basis': match_basis(r)} for r in found[offset:offset + 5]]
        return {'records': records, 'total': len(found), 'has_more': len(found) > offset + 5}

    async def call(self, name, arguments):
        async with self._lock:
            return await self._call_locked(name, arguments)

    async def _call_locked(self, name, arguments):
        """校验本轮身份、查询范围与预算，注入凭据并过滤上游结果。"""
        self._binding.inject({})
        rules = self.assets['config']['tools']
        if name not in rules or not isinstance(arguments, dict) or set(arguments) != {'payload'}:
            raise CampusInputError('查询参数无效')
        rule = rules[name]
        payload = arguments['payload']
        if name == 'get_indicator_metrics' and isinstance(payload, dict) and 'scopes' not in payload:
            raise CampusInputError('本校及预置群体查询必须显式填写 scopes；只查本校用 indicator_value')
        if not Draft202012Validator(rule['schema']).is_valid(payload):
            raise CampusInputError('查询参数不符合已开通范围，请核对指标、年份和学校数量')
        if rule.get('catalog'):
            records = [r for r in self.assets['catalogs'][rule['catalog']] if r['code'] == payload['indicator_code']]
            if not records:
                raise CampusInputError('指标编码必须来自对应分析知识记录')
            if any(r['definition_conflict'] for r in records):
                raise CampusInputError('指标编码存在定义冲突，需先核实来源，不能试查')
            if self._identity_failed:
                raise CampusInputError('本轮学校身份未确认，请重新登录或联系管理员')
        if 'schools' in payload:
            if not self._school_id:
                raise CampusInputError('请先读取本轮当前登录本校身份')
            known = {r['code'] for r in self.assets['catalogs']['schools']}
            if self._school_id in payload['schools'] or not set(payload['schools']) <= known:
                raise CampusInputError('参照组须剔除本校，学校编码必须来自目录')
        if name == 'get_indicator_metrics':
            return await self._query_indicator(payload, rule)
        key = (name, payload.get('indicator_code'), payload.get('year'))
        if key in self._seen or self._calls >= self.assets['config']['max_calls']:
            raise CampusInputError('本轮已查询该组合或超出调用预算，不能重复试查')
        self._seen.add(key)
        self._calls += 1
        if name == 'get_school_info':
            self._identity_failed = True
        safe = await self._fetch(name, payload, rule)
        if name == 'get_school_info' and safe:
            self._school_id = str(safe['school_id'])
            self._identity_failed = False
        return {'success': True, 'data': safe}

    async def _fetch(self, name, payload, rule):
        """只在真实调用时注入凭据，并在保存结果前过滤上游字段。"""
        result = await self._request(name, self._binding.inject({'action': 'query', 'payload': payload}))
        if not isinstance(result, dict) or result.get('success') is not True or result.get('failed') is True:
            raise RuntimeError('上游查询失败')
        data = result.get('data')
        if data is None:
            return None
        if not isinstance(data, dict):
            raise RuntimeError('上游结果结构尚不支持')
        # 不允许外校明细借字符串数值字段穿过边界。
        if name == 'get_school_info':
            if any(not isinstance(data.get(k), str) or not data[k].strip() or len(data[k]) > 200
                   or any(c in data[k] for c in '{}[]\r\n')
                   for k in ('school_id', 'school_name')):
                raise RuntimeError('学校身份字段无效')
            safe = {k: data[k] for k in ('school_id', 'school_name')}
        else:
            safe = {k: _statistic(k, v) for k, v in data.items() if k in rule['output_fields']}
        if name == 'get_indicator_metrics' and isinstance(data.get('scoped_metrics'), list):
            requested = payload['scopes']
            safe['scoped_metrics'] = []
            for item in data['scoped_metrics']:
                if not isinstance(item, dict) or item.get('scope') not in requested:
                    continue
                values = {k: _statistic(k, v) for k, v in item.items()
                          if k in {'value', 'rank_type', 'school_count', 'cohort_size', 'percentile'}}
                safe['scoped_metrics'].append({'scope': item['scope'], **values})
        self._binding.check_response(safe)
        if name == 'get_school_info':
            if not safe.get('school_id') or not safe.get('school_name'):
                raise RuntimeError('学校身份无法识别')
        elif data and not safe:
            raise RuntimeError('上游结果结构尚不支持')
        return safe

    async def execute_plan(self, arguments):
        """先校验计划与真实调用预算；允许预置统计补项，保持常模学校组约束。"""
        async with self._lock:
            self._binding.inject({})
            if not isinstance(arguments, dict) or set(arguments) - {'subject', 'schools', 'items'}:
                raise CampusInputError('查询计划格式无效')
            subject = arguments.get('subject')
            items = arguments.get('items')
            if subject not in {'current_school', 'norm_group'} or not isinstance(items, list) or not items:
                raise CampusInputError('查询计划必须包含对象和查询项')
            top_schools = arguments.get('schools')
            if top_schools is not None and not _unique_strings(top_schools):
                raise CampusInputError('学校组格式无效')
            normalized = []
            group = None
            seen_plan = set()
            seen_items = set()
            for item in items:
                if not isinstance(item, dict) or set(item) - {'item_id', 'indicator_code', 'year', 'scopes', 'schools'}:
                    raise CampusInputError('查询计划项格式无效')
                item_id = item.get('item_id')
                code = item.get('indicator_code')
                if not isinstance(item_id, str) or not item_id.strip() or not isinstance(code, str) or not code.strip():
                    raise CampusInputError('查询计划项缺少标识或指标')
                if item_id in seen_items:
                    raise CampusInputError('查询计划项标识重复')
                seen_items.add(item_id)
                schools = item.get('schools', top_schools)
                is_norm = schools is not None
                if subject == 'norm_group' and not is_norm:
                    raise CampusInputError('常模计划必须包含学校组')
                if subject == 'current_school' and is_norm:
                    raise CampusInputError('本校计划不能携带外校组')
                if is_norm:
                    if (not _unique_strings(schools)
                            or group is not None and schools != group):
                        raise CampusInputError('学校组在同一计划中不一致')
                    group = list(schools)
                    tool = 'get_norm_metrics'
                else:
                    tool = 'get_indicator_metrics'
                    if 'scopes' not in item:
                        raise CampusInputError('本校及预置群体查询必须显式填写 scopes；请一次列全所需统计项')
                payload = {'indicator_code': code}
                if 'year' in item:
                    payload['year'] = item['year']
                if 'scopes' in item:
                    payload['scopes'] = item['scopes']
                if is_norm:
                    payload['schools'] = schools
                rule = self.assets['config']['tools'][tool]
                if not Draft202012Validator(rule['schema']).is_valid(payload):
                    raise CampusInputError('查询计划项不符合已开通范围')
                records = [r for r in self.assets['catalogs'][rule['catalog']] if r['code'] == code]
                if not records or any(r['definition_conflict'] for r in records):
                    raise CampusInputError('查询计划项的指标口径无法确认')
                key = (tool, code, payload.get('year'))
                if tool == 'get_indicator_metrics':
                    indicator_key = self._indicator_state(payload)[0]
                    key = (tool, *indicator_key)
                if key in seen_plan or tool != 'get_indicator_metrics' and key in self._seen:
                    raise CampusInputError('查询计划包含重复组合')
                seen_plan.add(key)
                normalized.append((item_id, tool, payload))
            identity_needed = 1 if group is not None and not self._school_id else 0
            calls_needed = sum(bool(self._indicator_state(payload)[2])
                               if tool == 'get_indicator_metrics' else 1
                               for _, tool, payload in normalized)
            if self._calls + calls_needed + identity_needed > self.assets['config']['max_calls']:
                raise CampusInputError('整题查询计划超过本轮预算')
            if group is not None and not self._school_id:
                try:
                    identity = await self._call_locked('get_school_info', {'payload': {}})
                except Exception:
                    return {'items': [], 'planned': len(normalized), 'executed': 0,
                            'complete': False, 'status': 'blocked',
                            'reason': 'identity_unavailable'}
                if not identity.get('data') or not self._school_id:
                    return {'items': [], 'planned': len(normalized), 'executed': 0,
                            'complete': False, 'status': 'blocked',
                            'reason': 'identity_unavailable'}
            results = []
            for item_id, tool, payload in normalized:
                try:
                    value = await self._call_locked(tool, {'payload': payload})
                    data = value.get('data')
                    item = {'item_id': item_id, 'status': 'empty' if data is None else 'success',
                            **({'data': data} if data is not None else {})}
                    if tool == 'get_indicator_metrics':
                        _, state, _ = self._indicator_state(payload)
                        for field, scopes in (
                                ('failed_scopes', [s for s in payload['scopes'] if s in state['failed']]),
                                ('empty_scopes', [s for s in payload['scopes']
                                                  if s not in state['failed'] and not state['values'].get(s)])):
                            if scopes:
                                item[field] = scopes
                    results.append(item)
                except CampusInputError:
                    raise
                except Exception:
                    results.append({'item_id': item_id, 'status': 'failed'})
            complete = all(item['status'] != 'failed' and not item.get('failed_scopes') for item in results)
            return {'items': results, 'planned': len(normalized),
                    'executed': len(results), 'complete': complete,
                    'status': 'completed' if complete else 'partial'}

    async def _request(self, name, arguments):
        """将已绑定凭据的查询参数发送到可信资产指定的 MCP。"""
        return await call_mcp_tool(self.assets['config'], name, arguments)


def search_knowledge(context, arguments):
    return context.services.require('campus').search(arguments)


async def get_school_info(context, arguments):
    return await context.services.require('campus').call('get_school_info', arguments)


async def get_indicator_metrics(context, arguments):
    return await context.services.require('campus').call('get_indicator_metrics', arguments)


async def get_norm_metrics(context, arguments):
    return await context.services.require('campus').call('get_norm_metrics', arguments)


async def execute_query_plan(context, arguments):
    result = await context.services.require('campus').execute_plan(arguments)
    if result.get('status') == 'blocked' or any(
            item.get('status') == 'failed' or item.get('failed_scopes') for item in result.get('items', [])):
        _notify_mcp_error(context.mcp_error_sink, {
            'stage': 'capability_operation',
            'operation': 'execute_query_plan',
            'failureKind': ('upstream_identity' if result.get('status') == 'blocked'
                            else 'upstream_query'),
        })
    return result


def load_service_assets(service_ref, settings, directory, config_path, operations):
    """按 Capability 资产引用装入校园 MCP 配置和知识表。"""
    if service_ref != 'campus' or not isinstance(config_path, str):
        raise RuntimeError('campus_service_asset_invalid')
    return load_campus_assets(settings, directory=directory, config_path=config_path,
                              operations=operations)


def create_service(service_ref, assets, credentials, operations):
    if service_ref != 'campus':
        raise RuntimeError('campus_service_invalid')
    return CampusQuery(assets, None)


def update_service(service_ref, service, assets):
    if service_ref != 'campus' or not isinstance(service, CampusQuery):
        raise RuntimeError('campus_service_invalid')
    service.configure_assets(assets)


def specialize_operations(context, operations):
    """将已验证业务配置的数量边界同步到当轮 Operation Schema。"""
    service = context.services.require('campus')
    minimum = service.assets['config']['minimum_schools']
    specialized = []
    for operation in operations:
        schema = json.loads(json.dumps(operation.input_schema))
        description = operation.description
        if operation.ref == 'execute_query_plan':
            schema['properties']['items']['maxItems'] = service.assets['config']['max_calls']
        elif operation.ref == 'get_norm_metrics':
            schema['properties']['payload']['properties']['schools']['minItems'] = minimum
            description = re.sub(r'至少 \d+ 所', f'至少 {minimum} 所', description)
        specialized.append(replace(operation, description=description, input_schema=schema,
                                   input_validator=Draft202012Validator(schema)))
    return specialized
