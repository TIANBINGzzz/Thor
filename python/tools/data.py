"""Thin, schema-checked in-process MCP adapters for shared data access."""

import asyncio
import json

from jsonschema import Draft202012Validator
from runtime.claude_sdk import create_sdk_mcp_server, sdk_tool
from data_access.context import DataError
from data_access.results import json_value

STRING = {"type": "string", "minLength": 1, "maxLength": 1000}
REFERENCE = {"type": "string", "minLength": 1, "maxLength": 100}
PARAMETERS = {"type": "object", "maxProperties": 100}
SOURCE = {
    "source_key": {**REFERENCE, "description": "原样使用 list_data_sources 返回的 source_key。"},
    "domain": {**REFERENCE, "description": "使用该数据源返回的 domains 中的业务域。"},
}
SCOPE_REFERENCE = {**REFERENCE, "description": (
    "优先使用本轮database_context中的scope_ref；未提供时用resolve_entities获取，学校范围用entity_type=school、query=''。"
    "指定项目用 project 或 task_project 候选的 scope_ref，不得填名称、内部ID或自行构造。"
)}


def tool_server(name, definitions):
    registered = []
    for tool_name, description, properties, required, handler in definitions:
        schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

        async def invoke(args, _handler=handler, _schema=schema):
            try:
                invalid = next(Draft202012Validator(_schema).iter_errors(args), None)
                if invalid:
                    # 只返回可信 schema 的字段提示，不回显参数值或校验器原始错误。
                    details = {"constraint": invalid.validator}
                    field = next(iter(invalid.absolute_path), None)
                    if invalid.validator == 'required' and isinstance(args, dict):
                        field = next((key for key in _schema['required'] if key not in args), None)
                    if field in _schema['properties']:
                        definition = _schema['properties'][field]
                        details['field'] = field
                        if 'description' in definition:
                            details['description'] = definition['description']
                        if 'enum' in definition:
                            details['allowedValues'] = definition['enum']
                    error = DataError("PARAMETERS_INVALID")
                    error.public_details = details
                    raise error
                value = await _handler(**args)
                return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, default=json_value, allow_nan=False)}]}
            except asyncio.CancelledError:
                raise
            except Exception as error:
                code = error.code if isinstance(error, DataError) else "EXECUTION_FAILED"
                details = getattr(error, 'public_details', {}) if isinstance(error, DataError) else {}
                message = '数据操作未完成，请检查授权、参数或已登记的业务口径。'
                return {"isError": True, "content": [{"type": "text", "text": json.dumps({
                    "status": "failed", "error": {"code": code, "message": message, "retryable": False, **details}}, ensure_ascii=False)}]}

        registered.append(sdk_tool(tool_name, description, schema)(invoke))
    return create_sdk_mcp_server(name=name, version="1.0.0", tools=registered)


def create_data_server(services):
    # 实体类型跟随本次挂载的数据资产；枚举只说明语法，实际来源/范围授权仍由执行器校验。
    entity_types = {'school'}
    for source_key in services.source_keys:
        for domain in services.catalog.source(source_key)['domains'].values():
            entity_types.update(domain.get('entities', {}))

    def call(method):
        async def handler(**args):
            executor = services.current()
            return await services.call(getattr(executor, method), **args)
        return handler

    async def read(result_ref, cursor=None):
        return services.current().results.page(result_ref, cursor)

    return tool_server("data", [
        ("list_data_sources", "列出本次执行获准的数据源。", {}, [], call("list_data_sources")),
        ("describe_data_source", "按库和业务域读取字段、函数白名单及显式登记的语义主题。", {**SOURCE,
            "topics": {"type": "array", "items": REFERENCE, "maxItems": 20}}, list(SOURCE), call("describe_data_source")),
        ("resolve_entities", "取得本轮授权范围或查找业务对象，返回 scope_ref/entity_ref；多候选须消歧。", {**SOURCE,
            "entity_type": {**REFERENCE, "enum": sorted(entity_types), "description": (
                "school=当前已授权学校范围（仅 all_school 可用），不是按校名搜索；"
                "project=有效项目，task_project=按任务口径定位项目；"
                "task=任务，performance=绩效指标，department=部门。仅可使用枚举内且当前来源已登记的类型。"
            )},
            "query": {"type": "string", "maxLength": 200, "description": (
                "业务名称的搜索词，不是SQL或scope_ref。school 必须传空字符串；"
                "其他类型传名称片段，不限定名称时传空字符串，不能任取多候选中的第一条。"
            )},
            "parent_ref": {**REFERENCE, "description": (
                "task/performance/department 使用已定位项目的 scope_ref；"
                "school/project/task_project 省略，不填 entity_ref。"
            )},
            "parameters": {**PARAMETERS, "description": (
                "对象查询所需的业务筛选参数（如 year）；字段和取值遵循已登记查询定义，不传租户或内部ID。"
            )}}, [*SOURCE, "entity_type", "query"], call("resolve_entities")),
        ("find_query_specs", "按业务意图或指标键检索已登记查询；缺定义查询不可执行。", {**SOURCE,
            "intent": {**STRING, "description": (
                "用完整业务问题检索，一次提供范围、指标、分组和期间；通常仅传intent即可。"
            )},
            "metric_key": {**STRING, "description": (
                "仅在已知精确的 查询id.输出字段名 时使用；不知道时省略，改用intent。"
                "不要猜project_count或task_count之类的键；已有适用查询时不要重复检索。"
            )}}, list(SOURCE), call("find_query_specs")),
        ("execute_query_spec", "执行固定查询及其依赖诊断；身份与项目键由运行时注入。", {**SOURCE,
            "query_id": {**REFERENCE, "description": "原样使用 find_query_specs 返回的查询 id。"},
            "parameters": {**PARAMETERS, "description": (
                "按 find_query_specs 的 parameters 传值；required 字段不可遗漏，只在定义允许时传 null。"
                "不传 tenant_id、project_id 等服务端注入字段。"
            )}, "scope_ref": SCOPE_REFERENCE,
            "entity_refs": {"type": "object", "additionalProperties": REFERENCE, "description": (
                "需要指定对象时，使用参数名到本轮 entity_ref 的映射；不要传真实内部ID。"
            )}},
            [*SOURCE, "query_id", "parameters", "scope_ref"], call("execute_query_spec")),
        ("execute_readonly_sql", "执行授权只读SQL；仅在数据库侧已隔离数据范围时开放。", {**SOURCE,
            "sql": {"type": "string", "minLength": 1, "maxLength": 60000}, "parameters": PARAMETERS,
            "purpose": STRING, "scope_ref": SCOPE_REFERENCE}, [*SOURCE, "sql", "parameters", "purpose", "scope_ref"], call("execute_readonly_sql")),
        ("read_query_result", "读取当前Run内同一物化结果的下一页，不重复查询。",
            {"result_ref": REFERENCE, "cursor": REFERENCE}, ["result_ref"], read),
    ])
