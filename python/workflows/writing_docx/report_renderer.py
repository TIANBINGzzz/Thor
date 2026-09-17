"""Apply evidence-backed edits to current DOCX paragraphs, preserving other parts."""

from decimal import Decimal
from copy import deepcopy
import json
import re
from zipfile import ZipFile
from difflib import SequenceMatcher
from string import Template

from lxml import etree

from data_access.context import DataError
from .document_map import NS, document_xml, locate
from .template_assets import load_template
from .report_locations import resolve_target

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


class DraftNumberError(DataError):
    def __init__(self, target, numbers):
        super().__init__('DRAFT_NUMBER_UNSUPPORTED')
        self.public_details = {'target':target, 'unsupported_numbers':sorted(numbers)}


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
        raise DraftNumberError(draft['target'], {str(n) for n in unsupported})


def replace_paragraph(node, text):
    nodes = node.xpath('.//w:t[not(ancestor::w:txbxContent)]', namespaces=NS)
    if not nodes:
        run = etree.SubElement(node, '{'+NS['w']+'}r')
        nodes = [etree.SubElement(run, '{'+NS['w']+'}t')]
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
    drafts = {}
    for draft in section_drafts:
        location = resolve_target(plan['locations'], draft.get('target'))
        key = location['location_hint']
        if key in drafts:
            raise DataError('DRAFT_DUPLICATE')
        state = draft.get('evidence_state')
        if state not in {'supported','limited','none'}:
            raise DataError('EVIDENCE_STATE_REQUIRED')
        if not draft['text'].strip() or len(draft['text']) > 12000:
            raise DataError('EVIDENCE_REQUIRED')
        scopes = plan['evidence_scopes']
        for reference in draft['evidence_refs']:
            try:
                metadata = executor.results.get(reference)['metadata']
            except DataError:
                raise DataError('EVIDENCE_REQUIRED') from None
            if (metadata.get('complete') is not True or not any(
                    all(metadata.get(k) == scope[k] for k in ('source_key', 'domain', 'scope_ref'))
                    for scope in scopes)):
                raise DataError('EVIDENCE_REQUIRED')
        parameter_refs = draft.get('parameter_refs', [])
        if any(name not in plan['report_parameters'] or plan['report_parameters'][name] in (None, '', [])
               for name in parameter_refs):
            raise DataError('EVIDENCE_REQUIRED')
        if state in {'supported','limited'}:
            if not parameter_refs and not any(executor.results.get(ref)['rows'] for ref in draft['evidence_refs']):
                raise DataError('EVIDENCE_REQUIRED')
        if state == 'supported' and draft.get('gap', '').strip():
            raise DataError('EVIDENCE_STATE_CONFLICT')
        if state != 'supported':
            fields = ['gap'] + (['analysis_basis','next_action'] if state=='none' and not location['table'] else [])
            if any(not draft.get(field,'').strip() or draft[field] not in draft['text'] for field in fields):
                raise DataError('EVIDENCE_GAP_REQUIRED')
        if re.fullmatch(r'[\s/_\-—]+|待补|待填',draft['text']):
            raise DataError('REPORT_BODY_INCOMPLETE')
        validate_draft_numbers(draft, plan, executor)
        drafts[key] = {**draft, 'target': {'location_hint': key}}
    return drafts


def compose_document(template, drafts):
    xml = document_xml(template['_docx'])
    # Resolve before inserting paragraphs, so earlier splits cannot move later targets.
    targets = [(locate(xml, resolve_target(template['_locations'], draft['target'])['locator']), draft)
               for draft in drafts]
    for node, draft in targets:
        parts = re.split(r'\n\s*\n', draft['text'].strip())
        if node.xpath('.//w:txbxContent', namespaces=NS):
            raise DataError('DRAFT_TEXTBOX_UNSUPPORTED')
        location = resolve_target(template['_locations'], draft['target'])
        if len(parts) > 1 and (location['heading_level'] or node.xpath(
                './/w:fldChar|.//w:fldSimple|.//w:instrText|.//w:drawing|.//w:pict|.//w:br|.//w:tab|.//w:hyperlink', namespaces=NS)):
            raise DataError('PARAGRAPH_SPLIT_UNSUPPORTED')
        inserted = [node]
        for text in parts[1:]:
            paragraph = etree.Element('{'+NS['w']+'}p')
            properties = node.find('w:pPr', NS)
            if properties is not None:
                properties = deepcopy(properties)
                for section in properties.findall('w:sectPr', NS):
                    properties.remove(section)
                paragraph.append(properties)
            run = etree.SubElement(paragraph, '{'+NS['w']+'}r')
            run_properties = node.find('w:r/w:rPr', NS)
            if run_properties is not None:
                run.append(deepcopy(run_properties))
            etree.SubElement(run, '{'+NS['w']+'}t')
            inserted[-1].addnext(paragraph)
            inserted.append(paragraph)
        # A section break belongs after all paragraphs produced from its original paragraph.
        if len(inserted) > 1:
            section = node.find('w:pPr/w:sectPr', NS)
            if section is not None:
                section.getparent().remove(section)
                inserted[-1].find('w:pPr', NS).append(section)
        for paragraph, text in zip(inserted, parts):
            replace_paragraph(paragraph, text)
            if template.get('clear_fill_markers'):
                clear_fill_markers(paragraph)
            if draft['evidence_state'] != 'supported':
                mark_uncertainty(paragraph)
    return xml


def unresolved_markers(path):
    issues = []
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r'word/(document|header\d+|footer\d+)\.xml', name):
                continue
            xml = etree.fromstring(archive.read(name), etree.XMLParser(resolve_entities=False, no_network=True))
            for index, paragraph in enumerate(xml.xpath('.//w:p', namespaces=NS), 1):
                text = ''.join(paragraph.xpath('.//w:t/text()', namespaces=NS))
                if re.search(r'\{\{[^{}]+\}\}|\$\{[^{}]+\}|_{2,}|【待(?:填|补)[^】]*】|键入[章节]?标题|单击此处输入文字', text):
                    issues.append({'part': name, 'paragraph': index, 'text': text[:160]})
    return issues


def render(template, plan, section_drafts, executor):
    # Recheck file hash and every physical locator immediately before writing.
    current = load_template(template["template_key"], executor.context.capability_ref,
                            template["_directory"].parent)
    if current['_revision'] != template['_revision']:
        raise DataError('TEMPLATE_MISMATCH')
    drafts = validate_drafts(plan, section_drafts, executor)
    if not drafts:
        raise DataError('REPORT_EDITS_REQUIRED')
    xml = compose_document(template, list(drafts.values()))
    directory = executor.context.run_directory / "report"
    directory.mkdir(parents=True, exist_ok=True)
    name = report_file_name(template, plan.get('report_parameters', {}))
    output = directory / (plan["plan_ref"] + "-" + name)
    content = etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone=True)
    with ZipFile(template["_docx"]) as original, ZipFile(output, "w") as target:
        for member in original.infolist():
            target.writestr(member, content if member.filename == "word/document.xml" else original.read(member.filename))
    missing_path = directory / (plan["plan_ref"] + "-missing.json")
    gaps = [{'location_hint': key, 'reason': draft['gap']} for key, draft in drafts.items()
            if draft['evidence_state'] != 'supported']
    markers = unresolved_markers(output)
    missing_path.write_text(json.dumps({'unresolved_markers': markers, 'data_gaps':gaps}, ensure_ascii=False, indent=2), encoding='utf-8')
    from .report_validator import check_fidelity
    check_fidelity(template, output, list(drafts.values()))
    return {"status": "rendered_with_data_gaps" if gaps else "rendered", "path": str(output),
            'edits': list(drafts.values()), 'unresolved_markers': markers,
            "file_name": name, "missing_count": len(markers), "missing_path": str(missing_path),
            "data_gap_count":len(gaps),
            "layout_validation": "required_before_final_acceptance"}
