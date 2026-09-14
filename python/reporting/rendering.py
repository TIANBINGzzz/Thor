"""Replace registered OOXML paragraphs while copying every other ZIP member."""

from decimal import Decimal, ROUND_HALF_UP
import json
import re
from zipfile import ZipFile
from copy import deepcopy

from lxml import etree

from data_access.context import DataError
from .bindings import NS, document_xml, load_template, locate


def replace_paragraph(node, text, *, missing=False):
    runs = node.findall("w:r", NS)
    if any(r.find("w:drawing", NS) is not None for r in runs):
        raise DataError("IMAGE_SLOT_PROTECTED")
    for child in list(node):
        if child.tag != "{" + NS["w"] + "}pPr":
            node.remove(child)
    run = etree.SubElement(node, "{" + NS["w"] + "}r")
    if runs and runs[0].find("w:rPr", NS) is not None:
        from copy import deepcopy
        run.append(deepcopy(runs[0].find("w:rPr", NS)))
    if missing:
        properties = run.find("w:rPr", NS)
        if properties is None:
            properties = etree.SubElement(run, "{" + NS["w"] + "}rPr")
        etree.SubElement(properties, "{" + NS["w"] + "}highlight", {"{" + NS["w"] + "}val": "yellow"})
    content = etree.SubElement(run, "{" + NS["w"] + "}t")
    content.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    content.text = text


def format_value(value, formatting, unit):
    if formatting.get("unit") and formatting["unit"] != unit:
        raise DataError("UNIT_MISMATCH")
    if "decimal_places" in formatting:
        places = formatting["decimal_places"]
        if not isinstance(places, int) or not 0 <= places <= 8:
            raise DataError("FORMAT_INVALID")
        value = Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return str(value)


def fill_table(anchor, rows, columns, empty_text):
    table = next((p for p in anchor.iterancestors() if p.tag == "{" + NS["w"] + "}tbl"), None)
    if table is None:
        raise DataError("TABLE_BINDING_INVALID")
    templates = table.findall("w:tr", NS)
    if len(templates) != 2 or len(templates[1].findall("w:tc", NS)) != len(columns):
        raise DataError("TABLE_BINDING_INVALID")
    prototype = templates[1]
    table.remove(prototype)
    for row in rows or [{c["field"]: empty_text if i == 0 else "" for i,c in enumerate(columns)}]:
        node = deepcopy(prototype)
        for cell, column in zip(node.findall("w:tc", NS), columns):
            value = row.get(column["field"])
            rendered = column.get("null_text", "未填报") if value is None else format_value(value, column.get("format", {}), column.get("unit"))
            paragraphs = cell.findall("w:p", NS)
            replace_paragraph(paragraphs[0], rendered)
            for paragraph in paragraphs[1:]: cell.remove(paragraph)
        table.append(node)


def render(template, plan, section_drafts, executor):
    # Recheck file hash and every physical locator immediately before writing.
    current = load_template(template["template_key"], executor.context.capability_ref,
                            template["_directory"].parent)
    if current['_revision'] != template['_revision']:
        raise DataError('TEMPLATE_MISMATCH')
    xml = document_xml(template["_docx"])
    values = {s["slot_key"]: s for s in plan["slots"]}
    bindings = {s["slot_key"]: s for s in template["_slots"]}
    drafts = {}
    for draft in section_drafts:
        key = draft["section_key"]
        target = draft.get("slot_key")
        if (key, target) in drafts:
            raise DataError("DRAFT_DUPLICATE")
        candidates = [s for s in template["_slots"] if s["section_key"] == key and s["kind"] == "narrative"
                      and (target is None or s["slot_key"] == target)]
        if len(candidates) != 1:
            raise DataError("DRAFT_LOCATION_AMBIGUOUS")
        # Only validated slot evidence is eligible; query candidates alone do
        # not establish the applicability of an historical business fact.
        evidence = {s.get("evidence_ref") for s in plan["slots"] if s["section_key"] == key and s["value_status"] == "filled"}
        if not draft["evidence_refs"] or not set(draft["evidence_refs"]) <= evidence:
            raise DataError("EVIDENCE_REQUIRED")
        facts = " ".join(str(s.get("value", "")) for s in plan["slots"] if s.get("evidence_ref") in draft["evidence_refs"])
        if not set(re.findall(r"\d+(?:\.\d+)?", draft["text"])) <= set(re.findall(r"\d+(?:\.\d+)?", facts)):
            raise DataError("DRAFT_NUMBER_UNSUPPORTED")
        drafts[key, target] = draft
        values[candidates[0]["slot_key"]] = {"value_status": "filled", "value": draft["text"]}
    missing = []
    for slot_key, binding in bindings.items():
        if binding["kind"] == "static":
            continue
        value = values[slot_key]
        node = locate(xml, binding["locator"])
        if value["value_status"] == "filled":
            if binding["kind"] == "table":
                fill_table(node, value["value"], binding["columns"], binding.get("empty_text", "无符合条件的记录"))
            else:
                formatting = {} if value.get("null_value") else binding.get("format", {})
                rendered = format_value(value["value"], formatting, value.get("unit"))
                replace_paragraph(node, binding.get("prefix", "") + rendered + binding.get("suffix", ""))
        else:
            missing.append({"slot_key": slot_key, "name": binding["name"], "reason": value["value_status"]})
            replace_paragraph(node, "【待核验：" + binding["name"][:70] + "】", missing=True)
    if missing and template["missing_policy"] != "annotated_draft":
        raise DataError("REPORT_INCOMPLETE")
    directory = executor.context.run_directory / "report"
    directory.mkdir(parents=True, exist_ok=True)
    name = "report-draft.docx" if missing else "report.docx"
    output = directory / (plan["plan_ref"] + "-" + name)
    content = etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(template["_docx"]) as original, ZipFile(output, "w") as target:
        for member in original.infolist():
            target.writestr(member, content if member.filename == "word/document.xml" else original.read(member.filename))
    missing_path = directory / (plan["plan_ref"] + "-missing.json")
    missing_path.write_text(json.dumps({"missing": missing}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "draft" if missing else "complete", "path": str(output),
            "file_name": name, "missing_count": len(missing), "missing_path": str(missing_path),
            "layout_validation": "required_before_final_acceptance"}
