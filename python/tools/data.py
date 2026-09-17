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
SOURCE = {"source_key": REFERENCE, "domain": REFERENCE}


def tool_server(name, definitions):
    registered = []
    for tool_name, description, properties, required, handler in definitions:
        schema = {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

        async def invoke(args, _handler=handler, _schema=schema):
            try:
                if next(Draft202012Validator(_schema).iter_errors(args), None):
                    raise DataError("PARAMETERS_INVALID")
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
        ("resolve_entities", "在授权范围查找学校、项目、任务、指标或部门；多候选须消歧。", {**SOURCE,
            "entity_type": REFERENCE, "query": {"type": "string", "maxLength": 200},
            "parent_ref": REFERENCE, "parameters": PARAMETERS}, [*SOURCE, "entity_type", "query"], call("resolve_entities")),
        ("find_query_specs", "按业务意图或指标键检索已登记查询；缺定义查询不可执行。", {**SOURCE,
            "intent": STRING, "metric_key": STRING}, list(SOURCE), call("find_query_specs")),
        ("execute_query_spec", "执行固定查询及其依赖诊断；身份与项目键由运行时注入。", {**SOURCE,
            "query_id": REFERENCE, "parameters": PARAMETERS, "scope_ref": REFERENCE,
            "entity_refs": {"type": "object", "additionalProperties": REFERENCE}},
            [*SOURCE, "query_id", "parameters", "scope_ref"], call("execute_query_spec")),
        ("execute_readonly_sql", "执行授权只读SQL；仅在数据库侧已隔离数据范围时开放。", {**SOURCE,
            "sql": {"type": "string", "minLength": 1, "maxLength": 60000}, "parameters": PARAMETERS,
            "purpose": STRING, "scope_ref": REFERENCE}, [*SOURCE, "sql", "parameters", "purpose", "scope_ref"], call("execute_readonly_sql")),
        ("read_query_result", "读取当前Run内同一物化结果的下一页，不重复查询。",
            {"result_ref": REFERENCE, "cursor": REFERENCE}, ["result_ref"], read),
    ])
