"""Generate and validate the structural location map for one DOCX template."""

from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from data_access.catalog import asset_path, read_json
from data_access.context import DataError

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def _document_locations(xml):
    """Return deterministic paragraph IDs, OOXML locators and table coordinates."""
    tree = xml.getroottree()
    tables = xml.xpath(".//w:tbl", namespaces=NS)
    table_numbers = {table: index for index, table in enumerate(tables, 1)}
    locations = []
    for position, paragraph in enumerate(xml.xpath(".//w:p", namespaces=NS), 1):
        ancestors = paragraph.xpath("ancestor::w:tbl[1]", namespaces=NS)
        table = None
        if ancestors:
            table_node = ancestors[0]
            row_node = paragraph.xpath("ancestor::w:tr[1]", namespaces=NS)[0]
            cell_node = paragraph.xpath("ancestor::w:tc[1]", namespaces=NS)[0]
            table_number = table_numbers[table_node]
            row = table_node.xpath("./w:tr", namespaces=NS).index(row_node) + 1
            column = row_node.xpath("./w:tc", namespaces=NS).index(cell_node) + 1
            paragraph_number = cell_node.xpath("./w:p", namespaces=NS).index(paragraph) + 1
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


def build_document_map(template_key, template_version, docx_path, slots=None):
    """Build structural locations and merge only explicit business classifications."""
    path = Path(docx_path)
    structural = _document_locations(document_xml(path))
    by_path = {item["locator"]["path"]: item for item in structural}
    if slots is None:
        slots = [
            {
                "slot_key": item["location_id"],
                "section_key": "unclassified",
                "kind": "unclassified",
                "required": False,
                "scope_role": "school",
                "locator": item["locator"],
            }
            for item in structural
        ]
    locations = []
    for slot in slots:
        base = by_path.get(slot["locator"]["path"])
        if base is None or base["locator"] != slot["locator"]:
            raise DataError("TEMPLATE_MISMATCH")
        location_id = slot["slot_key"]
        location = {
            "location_id": location_id,
            "section_key": slot["section_key"],
            "node_type": slot["kind"],
            "required": bool(slot["required"]),
            "scope_role": slot.get("scope_role", "school"),
            "template_text": base["template_text"],
            "locator": base["locator"],
            "table": base["table"],
            "validation": {
                "preserve_structure": True,
                "reject_template_default": slot["kind"] != "static",
            },
        }
        if slot["kind"] != "static":
            location["label"] = slot.get("name", location_id)
            location["context"] = slot.get("business_context", "")
        if "text_template" in slot:
            location["fill"] = {
                "text_template": slot["text_template"],
                "values": slot.get("values", {}),
            }
        locations.append(location)
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


def _slot_from_location(location):
    """Expose the small runtime shape used by the planner and renderer."""
    slot = {
        "slot_key": location["location_id"],
        "section_key": location["section_key"],
        "kind": location["node_type"],
        "required": bool(location.get("required", False)),
        "name": location.get("label", location["location_id"]),
        "business_context": location.get("context", ""),
        "scope_role": location.get("scope_role", "school"),
        "locator": location["locator"],
        "template_text": location.get("template_text", ""),
    }
    fill = location.get("fill")
    if fill:
        slot.update({key: fill[key] for key in ("text_template", "values") if key in fill})
    return slot


def load_document_map(
    directory: Path,
    filename: str,
    docx_path: Path,
    template_key: str,
    template_version: int,
):
    """Return runtime slots from the consolidated structural map."""
    path = asset_path(directory, filename)
    data = read_json(path)
    if (
        data.get("map_version") != 1
        or data.get("template_key") != template_key
        or data.get("template_version") != template_version
        or data.get("generated_from") != docx_path.name
        or not isinstance(data.get("locations"), list)
    ):
        raise DataError("DOCUMENT_MAP_INVALID")

    xml = document_xml(docx_path)
    structural = {
        item["locator"]["path"]: item for item in _document_locations(xml)
    }
    ids, positions = set(), set()
    slots = []
    for location in data["locations"]:
        if (
            not isinstance(location, dict)
            or not isinstance(location.get("location_id"), str)
            or location.get("node_type") not in {"static", "scalar", "narrative"}
            or not isinstance(location.get("section_key"), str)
            or not isinstance(location.get("locator"), dict)
            or not isinstance(location.get("validation"), dict)
        ):
            raise DataError("DOCUMENT_MAP_INVALID")
        location_id = location["location_id"]
        position = (location["locator"].get("part"), location["locator"].get("path"))
        if location_id in ids or position in positions:
            raise DataError("DUPLICATE_SLOT")
        ids.add(location_id)
        positions.add(position)
        locate(xml, location["locator"])
        base = structural.get(location["locator"]["path"])
        validation = location["validation"]
        if (
            base is None
            or location.get('template_text') != base['template_text']
            or location.get("table") != base["table"]
            or validation.get("preserve_structure") is not True
            or validation.get("reject_template_default")
            is not (location["node_type"] != "static")
        ):
            raise DataError("DOCUMENT_MAP_INVALID")
        slots.append(_slot_from_location(location))
    return data, slots


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
    if sha256(docx_path.read_bytes()).hexdigest() != assets['docx']['sha256']:
        raise DataError('TEMPLATE_MISMATCH')
    original, slots = load_document_map(
        directory, assets['document_map'], docx_path, template['template_key'], template['version'])
    generated = build_document_map(template['template_key'], template['version'], docx_path, slots)
    if args.check:
        if generated != original:
            raise SystemExit('Document map differs from the DOCX-derived structure.')
    else:
        asset_path(directory, assets['document_map']).write_text(
            json.dumps(generated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"Validated {len(generated['locations'])} document locations.")


if __name__ == '__main__':
    main()
