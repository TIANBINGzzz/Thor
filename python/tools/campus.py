"""校园 MCP 的受控 SDK 适配；业务词表和参数范围由显式资产提供。"""

import asyncio
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from runtime.mcp_auth import MCPArgumentBinding
from runtime.mcp_transport import call_mcp_tool, validate_http_connection
from runtime.asset_registry import read_asset_body, read_manifest
from runtime.deployment_config import ConfigSnapshot


class CampusInputError(ValueError):
    """可直接向模型反馈的本地参数校验错误；不包含上游正文。"""


ASSET_ROOT = Path(__file__).resolve().parents[2] / '.claude/capabilities/campus-brain-query'


def load_campus_assets(settings=None, directory=ASSET_ROOT):
    """只读取登记文件；知识保留在服务端内存，不整表注入提示词。"""
    directory = Path(directory).resolve()
    entry = read_manifest(directory, 'capability.json')
    config_path = (directory / entry['toolConfig']['campus']).resolve()
    if not config_path.is_relative_to(Path(directory).resolve()):
        raise RuntimeError('校园工具资产路径无效')
    raw = config_path.read_bytes()
    config = json.loads(raw)
    connection = (settings or ConfigSnapshot()).resolve(config.pop('connection'))
    validate_http_connection(connection)
    config.update(connection)
    minimum = config['minimum_schools']
    if type(minimum) is not int or minimum < 1:
        raise RuntimeError('常模最少学校数量配置无效')
    norm = config['tools']['get_norm_metrics']
    norm['schema']['properties']['schools']['minItems'] = minimum
    norm['description'] = norm['description'].format(minimum_schools=minimum)
    catalogs = {}
    digest = hashlib.sha256(raw)
    digest.update(json.dumps(connection, sort_keys=True).encode('utf-8'))
    for kind, name in config['catalogs'].items():
        path = (config_path.parent / name).resolve()
        if not path.is_relative_to(config_path.parent) or path.suffix != '.csv':
            raise RuntimeError('校园知识资产路径无效')
        digest.update(path.read_bytes())
        with path.open(encoding='utf-8', newline='') as stream:
            catalogs[kind] = [{**row, 'analysis': kind} for row in csv.DictReader(stream)]
        if kind != 'schools':
            definitions = {}
            for row in catalogs[kind]:
                definitions.setdefault(row['code'], set()).add(row['name'])
            for row in catalogs[kind]:
                row['definition_conflict'] = len(definitions[row['code']]) > 1
    prompt = read_asset_body(directory, 'CAPABILITY.md').replace('{minimum_schools}', str(minimum))
    digest.update(prompt.encode('utf-8'))
    return {'config': config, 'catalogs': catalogs, 'prompt': prompt, 'revision': digest.hexdigest()}


def _normalized(text):
    """去除末尾括注及常见分隔符，统一检索文本的大小写。"""
    text = re.sub(r'[（(][^()（）]*[）)]$', '', text.strip())
    return re.sub(r'[\s，,。；;、：:]', '', text).casefold()


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
        self.bind(credentials)

    def tool_names(self):
        """返回知识检索及已配置查询工具名，供装配层生成白名单。"""
        return ['search_knowledge', *self.assets['config']['tools']]

    def bind(self, credentials):
        """每轮重新绑定；不得用上轮身份或调用预算授权下一轮。"""
        self.clear()
        self._binding = MCPArgumentBinding('campus', credentials)

    def clear(self):
        """清除凭据绑定、本校身份和本轮去重记录及调用计数。"""
        if getattr(self, '_binding', None):
            self._binding.clear()
        self._seen = set()
        self._calls = 0
        self._school_id = None
        self._identity_failed = False

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
        """校验本轮身份、查询范围与预算，注入凭据并过滤上游结果。"""
        async with self._lock:
            self._binding.inject({})
            rules = self.assets['config']['tools']
            if name not in rules or not isinstance(arguments, dict) or set(arguments) != {'payload'}:
                raise CampusInputError('查询参数无效')
            rule = rules[name]
            payload = arguments['payload']
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
            key = (name, payload.get('indicator_code'), payload.get('year'))
            if key in self._seen or self._calls >= self.assets['config']['max_calls']:
                raise CampusInputError('本轮已查询该组合或超出调用预算，不能重复试查')
            self._seen.add(key)
            self._calls += 1
            if name == 'get_school_info':
                self._identity_failed = True
            result = await self._request(name, self._binding.inject({'action': 'query', 'payload': payload}))
            if not isinstance(result, dict) or result.get('success') is not True or result.get('failed') is True:
                raise RuntimeError('上游查询失败')
            data = result.get('data')
            if data is None:
                return {'success': True, 'data': None}
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
                requested = payload.get('scopes', ['indicator_value'])
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
                self._school_id = str(safe['school_id'])
                self._identity_failed = False
            elif data and not safe:
                raise RuntimeError('上游结果结构尚不支持')
            return {'success': True, 'data': safe}

    async def _request(self, name, arguments):
        """将已绑定凭据的查询参数发送到可信资产指定的 MCP。"""
        return await call_mcp_tool(self.assets['config'], name, arguments)


def create_campus_server(service, *, on_error=None):
    """按服务资产注册知识检索与查询工具，统一隔离上游错误正文。"""
    def wrap(handler):
        """为工具处理器绑定 MCP 结果编码与分级错误反馈。"""
        async def invoke(arguments):
            """执行处理器；仅透出本地输入提示，其他错误返回固定文本。"""
            try:
                result = await handler(arguments)
                return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
            except CampusInputError as error:
                return {'isError': True, 'content': [{'type': 'text', 'text': str(error)}]}
            except ValueError:
                if on_error:
                    on_error()
                return {'isError': True, 'content': [{'type': 'text', 'text': '查询条件或本轮身份无效，请核对指标、年份、学校集合及调用预算。'}]}
            except Exception:
                if on_error:
                    on_error()
                return {'isError': True, 'content': [{'type': 'text', 'text': '查询服务暂时不可用或返回未支持的数据，未自动重试。'}]}
        return invoke

    async def search(arguments):
        """把 MCP 检索参数交给服务的本地登记词表检索。"""
        return service.search(arguments)
    tools = [sdk_tool('search_knowledge', '批量检索指标或常模学校；常模指标用 norm_analysis。多个候选直接选最贴近名称的一项，同样合理时取首项，不停下来澄清；回答展示所选全称。', {
        'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': list(service.assets['catalogs'])},
        'query': {'anyOf': [{'type': 'string', 'minLength': 1, 'maxLength': 200},
            {'type': 'array', 'items': {'type': 'string', 'minLength': 1, 'maxLength': 200}, 'minItems': 1, 'maxItems': 30}]},
        'offset': {'type': 'integer', 'minimum': 0}},
        'required': ['kind', 'query'], 'additionalProperties': False})(wrap(search))]
    for name, rule in service.assets['config']['tools'].items():
        async def call(arguments, tool_name=name):
            """固定本次注册的工具名，避免循环回调串用最后一个名称。"""
            return await service.call(tool_name, arguments)
        tools.append(sdk_tool(name, rule['description'], {'type': 'object',
            'properties': {'payload': rule['schema']}, 'required': ['payload'], 'additionalProperties': False})(wrap(call)))
    return create_sdk_mcp_server('campus', version='1.0.0', tools=tools)
