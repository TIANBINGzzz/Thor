"""Replace registered OOXML paragraphs while copying every other ZIP member."""

from decimal import Decimal, ROUND_HALF_UP
import json
import re
from zipfile import ZipFile
from copy import deepcopy
from difflib import SequenceMatcher
from string import Template

from lxml import etree

from data_access.context import DataError
from .bindings import NS, document_xml, load_template, locate


class DraftNumberError(DataError):
    def __init__(self, slot_key, numbers):
        super().__init__('DRAFT_NUMBER_UNSUPPORTED')
        self.public_details = {'slot_key':slot_key, 'unsupported_numbers':sorted(numbers)}


def validate_draft_numbers(draft, plan, executor):
    facts = str(plan.get('report_parameters', {}))
    for ref in draft['evidence_refs']:
        record = executor.results.get(ref)
        public = {c['name'] for c in record['output'] if c.get('visibility')!='internal_only'}
        facts += ' ' + str([{k:v for k,v in row.items() if k in public} for row in record['rows']])
    def numbers(text):
        return {Decimal(n) for n in re.findall(r'\d+(?:\.\d+)?', text)}
    unsupported = numbers(draft['text']) - numbers(facts)
    if unsupported:
        raise DraftNumberError(draft.get('slot_key',''), {str(n) for n in unsupported})


def replace_paragraph(node, text, *, missing=False):
    nodes = node.xpath('.//w:t[not(ancestor::w:txbxContent)]', namespaces=NS)
    if not nodes:
        if text:
            raise DataError("TEXT_SLOT_REQUIRED")
        return
    original = [n.text or '' for n in nodes]
    offsets, position = [], 0
    for value in original:
        offsets.append(position)
        position += len(value)
    # Patch text only, backwards in original coordinates. Run formatting,
    # bookmarks, links, fields, drawings and section properties stay intact.
    for operation, start, end, a, b in reversed(SequenceMatcher(None, ''.join(original), text, autojunk=False).get_opcodes()):
        if operation == 'equal':
            continue
        first = next((i for i in range(len(nodes)) if offsets[i] + len(original[i]) > start), len(nodes)-1)
        last = next((i for i in range(len(nodes)) if offsets[i] + len(original[i]) >= end and i >= first), len(nodes)-1)
        prefix = (nodes[first].text or '')[:start-offsets[first]]
        suffix = (nodes[last].text or '')[end-offsets[last]:]
        nodes[first].text = prefix + text[a:b] + (suffix if first == last else '')
        if first != last:
            for i in range(first+1,last): nodes[i].text = ''
            nodes[last].text = suffix
    for content in nodes:
        content.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')


def clear_fill_markers(node):
    for marker in node.xpath('.//w:rPr/w:highlight | .//w:rPr/w:color', namespaces=NS):
        if marker.tag == '{' + NS['w'] + '}highlight' or marker.get('{' + NS['w'] + '}val', '').upper() in {'FF0000', 'EE0000'}:
            marker.getparent().remove(marker)


def report_file_name(template, parameters):
    values = {key: '-'.join(map(str, value)) if isinstance(value, list) else str(value)
              for key, value in parameters.items()}
    try:
        name = Template(template.get('file_name', 'report.docx')).substitute(values)
    except (KeyError, ValueError):
        raise DataError('REPORT_FILE_NAME_INVALID') from None
    if not name.endswith('.docx') or re.search(r'[<>:"/\\|?*\x00-\x1f]', name):
        raise DataError('REPORT_FILE_NAME_INVALID')
    return name


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
        evidence = set(candidates[0].get('evidence_refs', []))
        evidence.update(next((s.get('evidence_refs', []) for s in plan['slots'] if s['slot_key'] == candidates[0]['slot_key']), []))
        evidence.update(s.get("evidence_ref") for s in plan["slots"] if s["section_key"] == key and s["value_status"] == "filled")
        if not draft["evidence_refs"] or not set(draft["evidence_refs"]) <= evidence:
            raise DataError("EVIDENCE_REQUIRED")
        validate_draft_numbers(draft, plan, executor)
        drafts[key, target] = draft
        values[candidates[0]["slot_key"]] = {"value_status": "filled", "value": draft["text"]}
    written={c['slot_key'] for d in section_drafts for c in template['_slots']
             if c['kind']=='narrative' and c['section_key']==d['section_key']
             and (d.get('slot_key') is None or c['slot_key']==d['slot_key'])}
    if any(s['kind']=='narrative' and s['required'] and s['slot_key'] not in written for s in template['_slots']):
        raise DataError('REPORT_BODY_INCOMPLETE')
    missing = []
    for slot_key, binding in bindings.items():
        if binding["kind"] == "static":
            continue
        value = values[slot_key]
        node = locate(xml, binding["locator"])
        if value["value_status"] in {"filled", "unavailable"}:
            if binding["kind"] == "table":
                fill_table(node, value["value"], binding["columns"], binding.get("empty_text", "无符合条件的记录"))
            else:
                formatting = {} if value.get("null_value") or value['value_status']=='unavailable' else binding.get("format", {})
                rendered = format_value(value["value"], formatting, value.get("unit"))
                replace_paragraph(node, binding.get("prefix", "") + rendered + binding.get("suffix", ""))
            if template.get('clear_fill_markers'):
                clear_fill_markers(node)
        else:
            missing.append({"slot_key": slot_key, "name": binding["name"], "reason": value["value_status"]})
            replace_paragraph(node, "【待核验：" + binding["name"][:70] + "】", missing=True)
    if missing and template["missing_policy"] != "annotated_draft":
        raise DataError("REPORT_INCOMPLETE")
    directory = executor.context.run_directory / "report"
    directory.mkdir(parents=True, exist_ok=True)
    name = "report-draft.docx" if missing else report_file_name(template, plan.get('report_parameters', {}))
    output = directory / (plan["plan_ref"] + "-" + name)
    content = etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(template["_docx"]) as original, ZipFile(output, "w") as target:
        for member in original.infolist():
            target.writestr(member, content if member.filename == "word/document.xml" else original.read(member.filename))
    missing_path = directory / (plan["plan_ref"] + "-missing.json")
    gaps = [{"slot_key":s['slot_key'], 'reason':s['reason']} for s in plan['slots'] if s.get('reason')]
    missing_path.write_text(json.dumps({"missing": missing, "data_gaps":gaps}, ensure_ascii=False, indent=2), encoding='utf-8')
    if template.get('preserve_structure'):
        from .validation import check_fidelity
        check_fidelity(template, output)
    return {"status": "draft" if missing else "complete_with_data_gaps" if gaps else "complete", "path": str(output),
            "file_name": name, "missing_count": len(missing), "missing_path": str(missing_path),
            "data_gap_count":len(gaps),
            "layout_validation": "required_before_final_acceptance"}
