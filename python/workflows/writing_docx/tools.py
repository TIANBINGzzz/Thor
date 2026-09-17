"""Report tools share the current Run's data service and registered template."""

from data_access.context import DataError
from tools.data import PARAMETERS, REFERENCE, STRING, ToolContent, tool_server


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
                    "scope_roles":template["scope_roles"],
                    "recommended_datasets":template['_bindings']['datasets'],
                    "map_status":template['_map_status'], "warnings":template['_warnings'],
                    "location_policy":"optional_hints_current_document_targets",
                    "outline":template.get('outline',[]), "preserve_structure":template['preserve_structure']}
        return report().get(**args)

    async def render(**args):
        result = await report().render(**args)
        return {**{k:result[k] for k in ('status','file_name','missing_count','data_gap_count','layout_validation')},
                'unresolved_markers':result['unresolved_markers'],
                'coverage':report().plans[args['plan_ref']]['coverage']}

    async def save(**args):
        return report().save_drafts(**args)

    async def validate(plan_ref):
        planner=report()
        if plan_ref!=planner.latest: raise DataError('PLAN_SUPERSEDED')
        plan=planner.plans[plan_ref]
        if not plan.get('rendered'): raise DataError('REPORT_NOT_RENDERED')
        from workflows.writing_docx.report_validator import validate_document
        result=await services.call(validate_document, planner.template, plan['rendered'], services.env)
        plan['validation']=result
        planner._save(plan)
        return {k:v for k,v in result.items() if k not in {'pages','pdf_path'}}

    async def publish(plan_ref, validation_ref):
        planner=report()
        from workflows.writing_docx.report_validator import validated_plan
        plan,validation=validated_plan(planner,plan_ref,validation_ref)
        if validation.get('visual_review')!='passed': raise DataError('REPORT_VISUAL_REVIEW_REQUIRED')
        result=plan['rendered']
        from pathlib import Path
        from tools.artifacts import publish_artifact
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
                "data_gap_count":result['data_gap_count'],"layout_validation":"structure_and_all_pages_reviewed"}

    async def pages(plan_ref, validation_ref, page_numbers):
        import base64
        from pathlib import Path
        from workflows.writing_docx.report_validator import validated_plan
        planner=report()
        plan,validation=validated_plan(planner,plan_ref,validation_ref)
        if any(n>validation['page_count'] for n in page_numbers): raise DataError('PAGE_INVALID')
        content=[]
        for number in page_numbers:
            content.append({'type':'text','text':f'Page {number} / {validation["page_count"]}'})
            content.append({'type':'image','mimeType':'image/png','data':base64.b64encode(Path(validation['pages'][number-1]).read_bytes()).decode('ascii')})
        validation['pages_read']=sorted(set(validation.get('pages_read',[]))|set(page_numbers))
        planner._save(plan)
        return ToolContent(content)

    async def review(plan_ref, validation_ref, page_numbers, passed, notes):
        from workflows.writing_docx.report_validator import validated_plan, record_page_review
        planner=report()
        plan,validation=validated_plan(planner,plan_ref,validation_ref)
        result=record_page_review(validation,page_numbers,passed,notes)
        planner._save(plan)
        return result

    page_numbers={"type":"array","minItems":1,"maxItems":4,"uniqueItems":True,"items":{"type":"integer","minimum":1}}

    target_schema={"type":"object","minProperties":1,"additionalProperties":False,"properties":{
        "location_hint":REFERENCE,"section":STRING,"original_text":{"type":"string"},
        "table":{"type":"object","additionalProperties":False,
            "properties":{"table_id":REFERENCE, **{key:{"type":"integer","minimum":1}
                for key in ('row','column','paragraph')}},
            "required":["table_id","row","column","paragraph"]}}}
    draft_schema={"type":"array","maxItems":100,"items":{"type":"object","additionalProperties":False,
        "properties":{"target":target_schema,"text":{"type":"string","minLength":1,"maxLength":12000},
                      "evidence_refs":{"type":"array","items":REFERENCE},
                      "parameter_refs":{"type":"array","uniqueItems":True,"items":STRING},
                      "evidence_state":{"type":"string","enum":["supported","limited","none"]},
                      "gap":{"type":"string"},"analysis_basis":{"type":"string"},"next_action":{"type":"string"}},
        "required":["target","text","evidence_refs","evidence_state"]}}
    return tool_server("reports", [
        ("prepare_report_data", "建立报告与授权范围，按需选择推荐数据集；省略dataset_keys查询全部推荐项，空数组不预取。",
         {"report_parameters": PARAMETERS,
          "dataset_keys":{"type":"array","uniqueItems":True,"items":REFERENCE},
          "scope_refs": {"type": "object",
             "description": "按source_role嵌套scope_role，值只传resolve_entities返回的scope_ref字符串；角色以get_report_data为准，不传entity_ref或候选对象。",
             "additionalProperties": {
             "type": "object", "additionalProperties": REFERENCE}}}, ["report_parameters", "scope_refs"], prepare),
        ("get_report_data", "不传参数读取模板及推荐数据集；传plan_ref按section_key分页读取当前DOCX的location_hints与候选事实。writing_only仅隐藏地图建议的静态段。",
         {"plan_ref": REFERENCE, "section_key": STRING, "cursor": REFERENCE, "writing_only":{"type":"boolean"}}, [], get),
        ("save_report_sections", "按当前location_hint、章节+原文或表格物理行列唯一定位并保存；无须预标注。text中空行可拆段，不能改表格行列；证据须在授权范围内。",
         {"plan_ref":REFERENCE,"section_drafts":draft_schema}, ["plan_ref","section_drafts"],save),
        ("validate_report", "核验原模板结构与样式，渲染全文页面；失败不得发布。",
         {"plan_ref":REFERENCE},["plan_ref"],validate),
        ("read_report_pages", "查看已验证报告的页面图片，每次最多四页，检查裁切、重叠、表格和字体。",
         {"plan_ref":REFERENCE,"validation_ref":REFERENCE,"page_numbers":page_numbers},["plan_ref","validation_ref","page_numbers"],pages),
        ("review_report_pages", "记录刚查看页面的实际检查结论；全部页面通过后才能发布。",
         {"plan_ref":REFERENCE,"validation_ref":REFERENCE,"page_numbers":page_numbers,"passed":{"type":"boolean"},"notes":STRING},
         ["plan_ref","validation_ref","page_numbers","passed","notes"],review),
        ("publish_report", "仅发布已通过结构与全文渲染检查的同一份报告。",
         {"plan_ref":REFERENCE,"validation_ref":REFERENCE},["plan_ref","validation_ref"],publish),
        ("render_report", "应用已存及本次修改，校验证据与实际写入目标；未编辑的地图建议只提示，残留占位符阻止后续验收。此步不发布。",
         {"plan_ref": REFERENCE, "section_drafts": draft_schema}, ["plan_ref", "section_drafts"], render),
    ])
