"""Current DOCX locations with optional, conservatively matched template annotations."""

from collections import Counter
from hashlib import sha256
from zipfile import ZipFile

from lxml import etree

from data_access.context import DataError
from .document_map import NS, document_xml, document_locations


def inspect_locations(path, document_map):
    xml = document_xml(path)
    with ZipFile(path) as archive:
        styles = etree.fromstring(archive.read('word/styles.xml'),
                                  etree.XMLParser(resolve_entities=False, no_network=True)) if 'word/styles.xml' in archive.namelist() else None
    definitions = {node.get('{'+NS['w']+'}styleId'): node for node in styles} if styles is not None else {}
    current = document_locations(xml)
    annotations = (document_map or {}).get('locations', [])
    old_counts = Counter(item.get('template_text', '') for item in annotations)
    new_counts = Counter(item['template_text'] for item in current)
    by_text = {item.get('template_text', ''): item for item in annotations}
    by_path = {item.get('locator', {}).get('path'): item for item in annotations}
    current_by_path = {item['locator']['path']: item for item in current}
    same_structure = bool(annotations) and all(
        (current_by_path.get(item['locator']['path'], {}).get('template_text') == item['template_text']
         and current_by_path.get(item['locator']['path'], {}).get('table') == item.get('table')
         and (not item['template_text'].strip() or old_counts[item['template_text']] == new_counts[item['template_text']]))
        for item in annotations)
    headings, result, matched = [], [], 0
    for index, item in enumerate(current, 1):
        node = xml.xpath(item['locator']['path'], namespaces=NS)[0]
        style = node.xpath('./w:pPr/w:pStyle/@w:val', namespaces=NS)
        level = node.xpath('./w:pPr/w:outlineLvl/@w:val', namespaces=NS)
        style_name = style[0] if style else ''
        visited, style_id = set(), style_name
        while not level and style_id in definitions and style_id not in visited:
            visited.add(style_id)
            definition = definitions[style_id]
            level = definition.xpath('./w:pPr/w:outlineLvl/@w:val', namespaces=NS)
            base = definition.xpath('./w:basedOn/@w:val', namespaces=NS)
            style_id = base[0] if base else ''
        if not level and style_name.lower().startswith('heading'):
            suffix = style_name[7:].strip()
            level = [str(int(suffix) - 1)] if suffix.isdigit() else []
        if level and 0 <= int(level[0]) <= 8 and not item['table']:
            depth = int(level[0])
            headings = [(d, text) for d, text in headings if d < depth]
            headings.append((depth, item['template_text']))
        annotation = None
        if same_structure:
            annotation = by_path.get(item['locator']['path'])
        elif item['template_text'] and old_counts[item['template_text']] == new_counts[item['template_text']] == 1:
            annotation = by_text[item['template_text']]
        hint = {
            'location_hint': f'loc_{index:05}', 'text': item['template_text'],
            'section': headings[-1][1] if headings else 'document',
            'heading_path': [text for _, text in headings], 'style': style_name,
            'heading_level': int(level[0]) + 1 if level and int(level[0]) < 9 else None,
            'table': item['table'], 'locator': item['locator'],
        }
        if item['table']:
            cell = node.xpath('ancestor::w:tc[1]', namespaces=NS)[0]
            span = cell.xpath('./w:tcPr/w:gridSpan/@w:val', namespaces=NS)
            merge = cell.find('w:tcPr/w:vMerge', NS)
            hint['cell_layout'] = {'column_span': int(span[0]) if span else 1,
                                   'vertical_merge': (merge.get('{'+NS['w']+'}val', 'continue')
                                                      if merge is not None else None),
                                   'coordinates': 'physical_cells_not_visual_grid'}
        if annotation:
            matched += 1
            hint['annotation'] = {key: annotation[key] for key in (
                'location_id', 'section_key', 'node_type', 'scope_role', 'label', 'context', 'fill')
                if key in annotation}
        hint['section_key'] = hint.get('annotation', {}).get('section_key', hint['section'])
        result.append(hint)
    return result, {'matched_annotations': matched, 'unmatched_annotations': len(annotations) - matched,
                    'current_locations': len(current)}


def resolve_target(locations, target):
    """Resolve only exact selectors against the current Run's document snapshot."""
    if (not isinstance(target, dict) or not target
            or set(target) - {'location_hint', 'section', 'original_text', 'table'}):
        raise DataError('DRAFT_TARGET_INVALID')
    matches = locations
    for key, field in (('location_hint', 'location_hint'), ('section', 'section'), ('original_text', 'text')):
        if key in target:
            matches = [item for item in matches if item[field] == target[key]]
    if 'table' in target:
        table = target['table']
        if (not isinstance(table, dict) or set(table) != {'table_id', 'row', 'column', 'paragraph'}
                or not isinstance(table['table_id'], str)
                or any(type(table[k]) is not int or table[k] < 1 for k in ('row', 'column', 'paragraph'))):
            raise DataError('DRAFT_TARGET_INVALID')
        matches = [item for item in matches if item['table'] == table]
    if len(matches) != 1:
        raise DataError('DRAFT_LOCATION_AMBIGUOUS')
    if matches[0].get('cell_layout', {}).get('vertical_merge') == 'continue':
        raise DataError('DRAFT_MERGED_CELL_CONTINUATION')
    return matches[0]


def public_location(location):
    return {key: value for key, value in location.items() if key != 'locator'}


def document_digest(path):
    return sha256(path.read_bytes()).hexdigest()
