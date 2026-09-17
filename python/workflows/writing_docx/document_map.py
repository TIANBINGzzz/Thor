"""Generate and validate the structural location map for one DOCX template."""

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from data_access.catalog import asset_path, read_json
from data_access.context import DataError

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def document_locations(xml):
    """Return deterministic paragraph IDs, OOXML locators and table coordinates."""
    tree = xml.getroottree()
    tables = xml.xpath(".//w:tbl", namespaces=NS)
    table_numbers = {table: index for index, table in enumerate(tables, 1)}
    locations = []
    for position, paragraph in enumerate(xml.xpath(".//w:p[not(ancestor::w:txbxContent)]", namespaces=NS), 1):
        ancestors = paragraph.xpath("ancestor::w:tbl[1]", namespaces=NS)
        table = None
        if ancestors:
            table_node = ancestors[0]
            row_node = paragraph.xpath("ancestor::w:tr[1]", namespaces=NS)[0]
            cell_node = paragraph.xpath("ancestor::w:tc[1]", namespaces=NS)[0]
            table_number = table_numbers[table_node]
            row = table_node.xpath("./w:tr", namespaces=NS).index(row_node) + 1
            column = row_node.xpath("./w:tc", namespaces=NS).index(cell_node) + 1
            cell_paragraphs = [node for node in cell_node.xpath('.//w:p[not(ancestor::w:txbxContent)]', namespaces=NS)
                               if node.xpath('ancestor::w:tc[1]', namespaces=NS)[0] == cell_node]
            paragraph_number = cell_paragraphs.index(paragraph) + 1
            location_id = f"T{table_number:02}_R{row:03}_C{column:02}_P{paragraph_number:02}"
            table = {
                "table_id": f"T{table_number:02}",
                "row": row,
                "column": column,
                "paragraph": paragraph_number,
            }
        else:
            location_id = f"P{position:04}"
        locations.append(
            {
                "location_id": location_id,
                "template_text": "".join(
                    paragraph.xpath(".//w:t/text()", namespaces=NS)
                ),
                "locator": {
                    "part": "word/document.xml",
                    "path": tree.getpath(paragraph),
                    "expected_text_hash": text_hash(paragraph),
                },
                "table": table,
            }
        )
    return locations


def build_document_map(template_key, template_version, docx_path, annotations=None):
    """Build structural locations and merge only explicit business classifications."""
    path = Path(docx_path)
    from .report_locations import inspect_locations
    current, _ = inspect_locations(path, {'locations': annotations or []})
    # Reuse IDs only for exact, unambiguous matches; new locations get new IDs.
    reserved = {item['annotation']['location_id'] for item in current if item.get('annotation')}
    allocated = set(reserved)
    locations = []
    for index, item in enumerate(current, 1):
        annotation = item.get('annotation', {})
        if annotations is not None and not annotation and not item['text'].strip():
            continue
        location_id = annotation.get('location_id')
        if location_id is None:
            location_id = f'L{index:05}'
            while location_id in allocated:
                location_id += '_new'
            allocated.add(location_id)
        node_type = annotation.get('node_type', 'unclassified')
        location = {
            "location_id": location_id,
            "section_key": annotation.get('section_key', item['section']),
            "node_type": node_type,
            "required": node_type in {'scalar', 'narrative'},
            "scope_role": annotation.get("scope_role", "school"),
            "template_text": item['text'],
            "locator": item["locator"],
            "table": item["table"],
            "validation": {
                "preserve_structure": True,
                "reject_template_default": node_type != "static",
            },
        }
        if node_type != "static":
            location["label"] = annotation.get("label", location_id)
            location["context"] = annotation.get("context", "")
        if 'fill' in annotation:
            location['fill'] = annotation['fill']
        locations.append(location)
    if annotations is not None:
        order = {item['location_id']: index for index, item in enumerate(annotations)}
        locations.sort(key=lambda item: order.get(item['location_id'], len(order)))
    return {
        "map_version": 1,
        "template_key": template_key,
        "template_version": template_version,
        "generated_from": path.name,
        "locations": locations,
    }


def text_hash(element):
    return sha256("".join(element.xpath(".//w:t/text()", namespaces=NS)).encode()).hexdigest()


def document_xml(path):
    with ZipFile(path) as archive:
        return etree.fromstring(
            archive.read("word/document.xml"),
            etree.XMLParser(resolve_entities=False, no_network=True),
        )


def locate(xml, locator):
    if locator.get("part") != "word/document.xml":
        raise DataError("TEMPLATE_MISMATCH")
    nodes = xml.xpath(locator["path"], namespaces=NS)
    if (
        len(nodes) != 1
        or nodes[0].tag != "{" + NS["w"] + "}p"
        or text_hash(nodes[0]) != locator["expected_text_hash"]
    ):
        raise DataError("TEMPLATE_MISMATCH")
    return nodes[0]


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Regenerate the selected template document map.')
    parser.add_argument('--template-dir', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    directory = args.template_dir.resolve()
    template = read_json(directory / 'template.json')
    assets = template['assets']
    docx_path = asset_path(directory, assets['docx']['file'])
    map_path = (directory / assets['document_map']).resolve()
    if not map_path.is_relative_to(directory):
        raise DataError('ASSET_PATH_INVALID')
    original = read_json(map_path) if map_path.is_file() else {}
    generated = build_document_map(template['template_key'], template['version'], docx_path, original.get('locations'))
    if args.check:
        if generated != original:
            raise SystemExit('Document map differs from the DOCX-derived structure.')
    else:
        map_path.write_text(
            json.dumps(generated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Validated {len(generated['locations'])} document locations.")


if __name__ == '__main__':
    main()
