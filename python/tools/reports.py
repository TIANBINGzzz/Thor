"""Report tools share the current Run's data service and registered template."""

from data_access.context import DataError
from .data import PARAMETERS, REFERENCE, STRING, tool_server


def create_reports_server(services):
    def report():
        services.current()
        if services.report is None:
            raise DataError("TEMPLATE_REQUIRED")
        return services.report

    async def prepare(**args):
        return await report().prepare(**args)

    async def get(**args):
        if not args.get("plan_ref"):
            template = report().template
            return {"template_key":template["template_key"], "name":template["name"],
                    "report_parameters":template["parameters"], "source_roles":template["source_roles"],
                    "scope_roles":template["scope_roles"], "missing_policy":template["missing_policy"]}
        return report().get(**args)

    async def render(**args):
        result = await report().render(**args)
        from pathlib import Path
        from .artifacts import publish_artifact
        directories = services.artifact_directories
        if not all(directories.values()):
            raise DataError("DELIVERY_UNAVAILABLE")
        folder = Path(result["path"]).parent
        published = await services.call(publish_artifact, result["path"], result["file_name"],
            folder, directories["deliverables_directory"], directories["session_directory"])
        missing = await services.call(publish_artifact, result["missing_path"], "report-missing.json",
            folder, directories["deliverables_directory"], directories["session_directory"])
        return {"status": result["status"], "published": published["published"], "file_name": published["name"],
                "missing_file": missing["name"], "missing_count": result["missing_count"],
                "layout_validation": result["layout_validation"]}

    return tool_server("reports", [
        ("prepare_report_data", "按可信模板绑定启动批量计划；不传模板路径或数据库连接。",
         {"report_parameters": PARAMETERS, "scope_refs": {"type": "object",
             "description": "按source_role嵌套scope_role，值只传resolve_entities返回的scope_ref字符串。例如{hpm:{group_a:scope_...,group_b:scope_...}}；角色以get_report_data为准，不传entity_ref或候选对象。",
             "additionalProperties": {
             "type": "object", "additionalProperties": REFERENCE}}}, ["report_parameters", "scope_refs"], prepare),
        ("get_report_data", "不传参数读取当前模板角色及期间要求；传plan_ref读取计划、章节事实和缺项。",
         {"plan_ref": REFERENCE, "section_key": REFERENCE, "cursor": REFERENCE}, [], get),
        ("render_report", "校验绑定和证据并填充原DOCX；必填缺项只允许标注草稿。",
         {"plan_ref": REFERENCE, "section_drafts": {"type": "array", "maxItems": 100, "items": {
             "type": "object", "additionalProperties": False, "properties": {"section_key": REFERENCE, "slot_key": REFERENCE,
                 "text": {"type": "string", "maxLength": 20000}, "evidence_refs": {"type": "array", "items": REFERENCE}},
             "required": ["section_key", "text", "evidence_refs"]}}}, ["plan_ref", "section_drafts"], render),
    ])
