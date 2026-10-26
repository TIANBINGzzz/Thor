"""Capability Operation 的受控执行和 MCP 适配。

Operation 是能力代码包中的业务动作；MCP Tool 只是把显式登记的动作暴露给
Agent。代码包不属于公共 Tool Provider，也不能由持久化能力资产动态指定。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
import json
from pathlib import Path
import re
from typing import Any, Callable

from jsonschema import Draft202012Validator, SchemaError
from referencing import Registry

from data_access.results import json_value
from runtime.asset_registry import ENTRY_NAME
from runtime.claude_sdk import create_sdk_mcp_server, run_tool_thread, sdk_tool


OperationHandler = Callable[["CapabilityContext", dict[str, Any]], Any]
MAX_OPERATION_INPUT_BYTES = 128_000
MAX_OPERATION_RESULT_BYTES = 1_000_000
# 禁用 jsonschema 默认的远端获取，包括从本地 JSON Pointer 间接引用远端的情况。
_SCHEMA_REGISTRY = Registry()


@dataclass(frozen=True)
class OperationDefinition:
    """一个可由能力显式登记的业务 Operation。"""

    ref: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler_name: str
    execute: OperationHandler | None = None


@dataclass(frozen=True)
class CapabilityPack:
    """能力代码包的稳定入口；业务实现不得通过全局注册表隐式暴露。"""

    ref: str
    operations: tuple[OperationDefinition, ...]


class CapabilityData:
    """给能力代码的最小数据服务门面，不暴露连接、凭据或原始 RunServices。"""

    def __init__(self, services):
        self._services = services

    def _executor(self):
        if self._services is None:
            raise RuntimeError("data_unavailable")
        return self._services.current()

    async def list_data_sources(self):
        return await self._services.call(self._executor().list_data_sources)

    async def describe_data_source(self, source_key, domain, topics=None):
        return await self._services.call(self._executor().describe_data_source,
                                         source_key, domain, topics)

    async def resolve_entities(self, source_key, domain, entity_type, query,
                               parent_ref=None, parameters=None):
        return await self._services.call(self._executor().resolve_entities,
                                         source_key, domain, entity_type, query,
                                         parent_ref, parameters)

    async def find_query_specs(self, source_key, domain, intent=None, metric_key=None):
        return await self._services.call(self._executor().find_query_specs,
                                         source_key, domain, intent, metric_key)

    async def execute_query_spec(self, source_key, domain, query_id, parameters,
                                 scope_ref, entity_refs=None):
        return await self._services.call(self._executor().execute_query_spec,
                                         source_key, domain, query_id, parameters,
                                         scope_ref, entity_refs)

    async def execute_readonly_sql(self, source_key, domain, sql, parameters,
                                   purpose, scope_ref):
        return await self._services.call(self._executor().execute_readonly_sql,
                                         source_key, domain, sql, parameters,
                                         purpose, scope_ref)

    def read_query_result(self, result_ref, cursor=None):
        return self._executor().results.page(result_ref, cursor)


class CapabilityDocuments:
    """复用通用文档 Service；所有输入和输出仍受本 Run 目录白名单约束。"""

    def __init__(self, roots):
        self.roots = tuple(Path(root).resolve() for root in roots if root)
        if not self.roots:
            raise RuntimeError("document_workspace_unavailable")
        self.base_dir = self.roots[0]

    async def render(self, path, output_dir):
        from tools.document_conversion import render_document

        return await run_tool_thread(render_document, path, output_dir, self.base_dir,
                                     [str(root) for root in self.roots[1:]])

    async def read_pdf(self, path, *, start=1, limit=5, render=False, output_dir=None):
        from tools.document_conversion import read_pdf

        return await run_tool_thread(read_pdf, path, self.base_dir,
                                     [str(root) for root in self.roots[1:]],
                                     start, limit, render, output_dir)


class CapabilityArtifacts:
    """复用通用成果快照和事件通知；仅接收本 Run 工作/交付目录。"""

    def __init__(self, *, work, deliverables, session, sink=None):
        self.work, self.deliverables, self.session = work, deliverables, session
        self.sink = sink

    async def publish(self, source_path, file_name):
        from tools.artifacts import publish_artifact

        result = await run_tool_thread(publish_artifact, source_path, file_name,
                                       self.work, self.deliverables, self.session)
        if self.sink is not None:
            self.sink({"type": "artifact.published", "artifactId": result["artifactId"]})
        return {key: result[key] for key in ("artifactId", "name", "size")}


@dataclass(frozen=True)
class CapabilityContext:
    """Operation 可见的本轮上下文；不含业务 Token、模型密钥或连接配置。"""

    run_id: str
    capability_ref: str
    data: CapabilityData | None = None
    documents: CapabilityDocuments | None = None
    artifacts: CapabilityArtifacts | None = None
    input_directory: Path | None = None
    work_directory: Path | None = None
    deliverables_directory: Path | None = None

    @classmethod
    def from_runtime(cls, entry: dict[str, Any], context: dict[str, Any]):
        """从 Runtime 已校验的上下文构造门面，路径仅来自服务端载荷。"""
        def path(name):
            value = context.get(name)
            return Path(value).resolve() if value else None

        run_id = context.get("run_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise RuntimeError("Operation Run 上下文无效")
        paths = {name: path(name) for name in (
            "input_directory", "work_directory", "deliverables_directory")}
        roots = [paths[name] for name in (
            "work_directory", "deliverables_directory", "input_directory")]
        roots.extend(Path(item).resolve() for item in (context.get("additional_directories") or ()))
        roots = list(dict.fromkeys(root for root in roots if root is not None))
        artifact = None
        if path("session_directory") is not None and all(paths[name] is not None for name in (
                "work_directory", "deliverables_directory")):
            artifact = CapabilityArtifacts(
                work=paths["work_directory"], deliverables=paths["deliverables_directory"],
                session=path("session_directory"), sink=context.get("artifact_sink"))
        return cls(
            run_id=run_id,
            capability_ref=entry["ref"],
            data=CapabilityData(context.get("data_services")) if context.get("data_services") else None,
            documents=CapabilityDocuments(roots) if roots else None,
            artifacts=artifact,
            input_directory=paths["input_directory"],
            work_directory=paths["work_directory"],
            deliverables_directory=paths["deliverables_directory"],
        )


def _ref(value, label):
    if not isinstance(value, str) or not ENTRY_NAME.fullmatch(value) or '__' in value or len(value) > 64:
        raise RuntimeError(f"{label}无效")


def _schema(value, label):
    if not isinstance(value, dict) or value.get("type") != "object":
        raise RuntimeError(f"{label}必须是对象 Schema")
    if value.get("additionalProperties") is not False:
        raise RuntimeError(f"{label}必须拒绝未登记字段")
    def local_refs(node):
        # 校验不得联网加载 Schema；$id 也可能改变本地引用的解析基准。
        if isinstance(node, dict):
            if '$id' in node or any(key in node and (
                    not isinstance(node[key], str) or not node[key].startswith('#'))
                    for key in ('$ref', '$dynamicRef')):
                raise RuntimeError(f"{label}只允许本地 Schema 引用")
            # 仅遍历子 Schema，properties 的业务字段名、const/default 等值不是 Schema。
            for key in ('properties', 'patternProperties', '$defs', 'definitions', 'dependentSchemas'):
                children = node.get(key)
                if isinstance(children, dict):
                    for child in children.values():
                        local_refs(child)
            for key in ('additionalProperties', 'unevaluatedProperties', 'propertyNames',
                        'items', 'additionalItems', 'unevaluatedItems', 'contains',
                        'not', 'if', 'then', 'else', 'contentSchema'):
                local_refs(node.get(key))
            for key in ('allOf', 'anyOf', 'oneOf', 'prefixItems'):
                children = node.get(key)
                if isinstance(children, list):
                    for child in children:
                        local_refs(child)
    local_refs(value)
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError:
        raise RuntimeError(f"{label}无效") from None


def manifest_pack(value: dict[str, Any], ref: str) -> CapabilityPack:
    """仅校验静态 pack.json；能力目录和提示词预览不得导入 Python 代码。"""
    if (not isinstance(value, dict) or set(value) != {"ref", "operations"}
            or value.get("ref") != ref):
        raise RuntimeError("能力代码包声明无效")
    definitions = value.get("operations")
    if not isinstance(definitions, list) or not definitions or len(definitions) > 64:
        raise RuntimeError("能力代码包操作数量无效")
    seen = set()
    operations = []
    for item in definitions:
        if not isinstance(item, dict) or set(item) != {
                "ref", "description", "inputSchema", "outputSchema", "handler"}:
            raise RuntimeError("能力代码包操作声明无效")
        operation_ref = item.get("ref")
        description = item.get("description")
        handler_name = item.get("handler")
        _ref(operation_ref, "Operation 引用")
        if (operation_ref in seen or not isinstance(description, str) or not description.strip()
                or not isinstance(handler_name, str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", handler_name)):
            raise RuntimeError("Operation 声明重复或说明无效")
        input_schema, output_schema = item.get("inputSchema"), item.get("outputSchema")
        _schema(input_schema, "Operation 输入")
        _schema(output_schema, "Operation 输出")
        operations.append(OperationDefinition(operation_ref, description, input_schema,
                                              output_schema, handler_name))
        seen.add(operation_ref)
    return CapabilityPack(ref, tuple(operations))


def validate_pack(pack, ref: str) -> CapabilityPack:
    """检查代码包导出的 Operation 处理器和静态 Schema 一一匹配。"""
    if not isinstance(pack, CapabilityPack) or pack.ref != ref:
        raise RuntimeError("能力代码包声明无效")
    if not isinstance(pack.operations, tuple) or not pack.operations or len(pack.operations) > 64:
        raise RuntimeError("能力代码包操作数量无效")
    seen = set()
    for operation in pack.operations:
        if not isinstance(operation, OperationDefinition):
            raise RuntimeError("能力代码包操作声明无效")
        _ref(operation.ref, "Operation 引用")
        if (operation.ref in seen or not isinstance(operation.description, str)
                or not operation.description.strip() or not callable(operation.execute)):
            raise RuntimeError("Operation 执行器未登记")
        _schema(operation.input_schema, "Operation 输入")
        _schema(operation.output_schema, "Operation 输出")
        seen.add(operation.ref)
    return pack


def _error(code):
    return {"isError": True, "content": [{"type": "text", "text": json.dumps({
        "status": "failed", "error": {"code": code, "message": "能力操作未完成", "retryable": False}
    }, ensure_ascii=False)}]}


async def _execute(operation: OperationDefinition, context: CapabilityContext, args):
    """调用同步或异步业务实现；同步实现在线程中执行并可收尾。"""
    if inspect.iscoroutinefunction(operation.execute):
        return await operation.execute(context, args)
    result = await run_tool_thread(operation.execute, context, args)
    if inspect.isawaitable(result):
        return await result
    return result


def build_operation_server(entry: dict[str, Any], context: dict[str, Any]):
    """只挂载能力 manifest operationRefs 中明确列出的 Operation。"""
    from capability_packs.registry import load_pack

    refs = entry.get("operation_refs", [])
    if not refs:
        raise RuntimeError("能力未声明 Operation")
    pack = load_pack(entry["ref"], expected_digest=entry.get("_operation_package_digest"))
    available = {operation.ref: operation for operation in pack.operations}
    selected = []
    for ref in refs:
        if ref not in available:
            raise RuntimeError("Operation 未在能力代码包中登记")
        selected.append(available[ref])
    capability_context = CapabilityContext.from_runtime(entry, context)
    registered = []
    for operation in selected:
        spec = operation

        @sdk_tool(spec.ref, spec.description, spec.input_schema, run_only=True)
        async def invoke(args, _operation=spec):
            try:
                if not isinstance(args, dict):
                    return _error("PARAMETERS_INVALID")
                try:
                    encoded_args = json.dumps(args, ensure_ascii=False, separators=(",", ":"),
                                              allow_nan=False).encode("utf-8")
                except (TypeError, ValueError):
                    return _error("PARAMETERS_INVALID")
                if len(encoded_args) > MAX_OPERATION_INPUT_BYTES:
                    return _error("PARAMETERS_INVALID")
                invalid = next(Draft202012Validator(
                    _operation.input_schema, registry=_SCHEMA_REGISTRY).iter_errors(args), None)
                if invalid:
                    return _error("PARAMETERS_INVALID")
                result = await _execute(_operation, capability_context, args)
                # 预先序列化，避免 SDK 处理不可见的 Decimal/日期或 NaN。
                try:
                    text = json.dumps(result, ensure_ascii=False, default=json_value, allow_nan=False)
                except (TypeError, ValueError):
                    return _error("RESULT_INVALID")
                if len(text.encode("utf-8")) > MAX_OPERATION_RESULT_BYTES:
                    return _error("RESULT_LIMIT")
                output_error = next(Draft202012Validator(
                    _operation.output_schema, registry=_SCHEMA_REGISTRY).iter_errors(json.loads(text)), None)
                if output_error:
                    return _error("RESULT_INVALID")
                return {"content": [{"type": "text", "text": text}]}
            except asyncio.CancelledError:
                raise
            except Exception:
                return _error("OPERATION_FAILED")

        registered.append(invoke)
    # 当前一次 Run 只装配一个 Capability；独立固定 namespace 避免 ref 中的
    # 分隔符破坏 SDK 的 mcp__server__tool 名称解析。
    name = "capability_ops"
    return name, create_sdk_mcp_server(name, version="1.0.0", tools=registered), [item.ref for item in selected]
