"""Replace registered OOXML paragraphs while copying every other ZIP member."""

from decimal import Decimal
from copy import deepcopy
import json
import re
from zipfile import ZipFile
from difflib import SequenceMatcher
from string import Template

from lxml import etree

from data_access.context import DataError
from .bindings import NS, document_xml, load_template, locate

UNCERTAINTY_COLOR = 'FFC000'


def mark_uncertainty(node):
    for run in node.xpath('.//w:r[w:t][not(ancestor::w:txbxContent)]', namespaces=NS):
        if not ''.join(run.xpath('w:t/text()', namespaces=NS)).strip():
            continue
        properties = run.find('w:rPr', NS)
        if properties is None:
            properties = etree.Element('{'+NS['w']+'}rPr')
            run.insert(0, properties)
        for color in list(properties.findall('w:color', NS)):
            properties.remove(color)
        color = etree.SubElement(properties, '{'+NS['w']+'}color')
        color.set('{'+NS['w']+'}val', UNCERTAINTY_COLOR)


def normalize_uncertainty(original, revised):
    """Allow only the deliberate yellow color change, preserving all other run properties."""
    before = original.xpath('.//w:r[not(ancestor::w:txbxContent)]', namespaces=NS)
    after = revised.xpath('.//w:r[not(ancestor::w:txbxContent)]', namespaces=NS)
    if len(before) != len(after):
        raise DataError('TEMPLATE_STRUCTURE_CHANGED')
    for old, new in zip(before, after):
        properties = new.find('w:rPr', NS)
        if properties is None:
            continue
        color = properties.find('w:color', NS)
        if color is None or dict(color.attrib) != {'{'+NS['w']+'}val':UNCERTAINTY_COLOR}:
            continue
        properties.remove(color)
        old_properties = old.find('w:rPr', NS)
        if old_properties is None:
            if len(properties)==0 and not properties.attrib:
                new.remove(properties)
        else:
            for index, item in enumerate(old_properties):
                if item.tag == '{'+NS['w']+'}color':
                    properties.insert(index, deepcopy(item))


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


def replace_paragraph(node, text):
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


def validate_drafts(plan, section_drafts, executor):
    slots = {s['slot_key']: s for s in plan['slots']}
    drafts = {}
    for draft in section_drafts:
        key = draft.get('slot_key')
        if key in drafts:
            raise DataError('DRAFT_DUPLICATE')
        slot = slots.get(key)
        if not slot or not (slot['kind'] == 'narrative' or slot.get('draftable')) or slot['section_key'] != draft['section_key']:
            raise DataError('DRAFT_LOCATION_AMBIGUOUS')
        state = draft.get('evidence_state')
        if state not in {'supported','limited','none'}:
            raise DataError('EVIDENCE_STATE_REQUIRED')
        if (not draft['text'].strip() or len(draft['text']) > 1200
                or not set(draft['evidence_refs']) <= set(slot.get('evidence_refs', []))):
            raise DataError('EVIDENCE_REQUIRED')
        if state in {'supported','limited'}:
            if not draft['evidence_refs'] or not any(executor.results.get(ref)['rows'] for ref in draft['evidence_refs']):
                raise DataError('EVIDENCE_REQUIRED')
        if state == 'supported' and draft.get('gap', '').strip():
            raise DataError('EVIDENCE_STATE_CONFLICT')
        if state != 'supported':
            fields = ['gap'] + (['analysis_basis','next_action'] if state=='none' and slot['kind']=='narrative' else [])
            if any(not draft.get(field,'').strip() or draft[field] not in draft['text'] for field in fields):
                raise DataError('EVIDENCE_GAP_REQUIRED')
        if re.fullmatch(r'[\s/_\-—]+|待补|待填',draft['text']):
            raise DataError('REPORT_BODY_INCOMPLETE')
        validate_draft_numbers(draft, plan, executor)
        drafts[key] = draft
    return drafts


def render(template, plan, section_drafts, executor):
    # Recheck file hash and every physical locator immediately before writing.
    current = load_template(template["template_key"], executor.context.capability_ref,
                            template["_directory"].parent)
    if current['_revision'] != template['_revision']:
        raise DataError('TEMPLATE_MISMATCH')
    xml = document_xml(template["_docx"])
    values = {s["slot_key"]: s for s in plan["slots"]}
    bindings = {s["slot_key"]: s for s in template["_slots"]}
    drafts = validate_drafts(plan, section_drafts, executor)
    if any(s['kind'] == 'narrative' and s['required'] and s['slot_key'] not in drafts for s in template['_slots']):
        raise DataError('REPORT_BODY_INCOMPLETE')
    values.update({key: {'value_status': 'filled' if draft['evidence_state']=='supported' else 'unavailable',
                         'value': draft['text'], **({'reason':draft['gap']} if draft['evidence_state']!='supported' else {})}
                   for key, draft in drafts.items()})
    for slot_key, binding in bindings.items():
        if binding['kind'] == 'static':
            continue
        value = values[slot_key]
        if value['value_status'] not in {'filled', 'unavailable'}:
            raise DataError('REPORT_INCOMPLETE')
        if not str(value['value']).strip() or re.fullmatch(r'[\s/_\-—]+',str(value['value'])):
            raise DataError('REPORT_INCOMPLETE')
        node = locate(xml, binding['locator'])
        replace_paragraph(node, str(value['value']))
        if template.get('clear_fill_markers'):
            clear_fill_markers(node)
        if value['value_status']=='unavailable':
            mark_uncertainty(node)
    directory = executor.context.run_directory / "report"
    directory.mkdir(parents=True, exist_ok=True)
    name = report_file_name(template, plan.get('report_parameters', {}))
    output = directory / (plan["plan_ref"] + "-" + name)
    content = etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(template["_docx"]) as original, ZipFile(output, "w") as target:
        for member in original.infolist():
            target.writestr(member, content if member.filename == "word/document.xml" else original.read(member.filename))
    missing_path = directory / (plan["plan_ref"] + "-missing.json")
    gaps = [{"slot_key":key, 'reason':value['reason']} for key,value in values.items() if value.get('reason')]
    missing_path.write_text(json.dumps({"missing": [], "data_gaps":gaps}, ensure_ascii=False, indent=2), encoding='utf-8')
    from .validation import check_fidelity
    check_fidelity(template, output)
    return {"status": "complete_with_data_gaps" if gaps else "complete", "path": str(output),
            "file_name": name, "missing_count": 0, "missing_path": str(missing_path),
            "data_gap_count":len(gaps),
            "layout_validation": "required_before_final_acceptance"}
