"""Validate template versions and physical paragraph locations before execution."""

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from data_access.catalog import PROJECT_ROOT, asset_path, key, read_json
from data_access.context import DataError, fingerprint

TEMPLATES = PROJECT_ROOT / ".claude/workflows/writing-docx/templates"
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def text_hash(element):
    return sha256("".join(element.xpath(".//w:t/text()", namespaces=NS)).encode()).hexdigest()


def document_xml(path):
    with ZipFile(path) as archive:
        return etree.fromstring(archive.read("word/document.xml"),
                                etree.XMLParser(resolve_entities=False, no_network=True))


def locate(xml, locator):
    if locator.get("part") != "word/document.xml":
        raise DataError("TEMPLATE_MISMATCH")
    nodes = xml.xpath(locator["path"], namespaces=NS)
    if len(nodes) != 1 or nodes[0].tag != "{" + NS["w"] + "}p" or text_hash(nodes[0]) != locator["expected_text_hash"]:
        raise DataError("TEMPLATE_MISMATCH")
    return nodes[0]


def load_template(template_key, capability_ref, root=TEMPLATES):
    if Path(root).resolve()==TEMPLATES.resolve():
        registry=read_json(TEMPLATES.parent/'workflow.json').get('templates',{})
        if template_key not in registry:
            raise DataError('TEMPLATE_FORBIDDEN')
    directory = asset_path(Path(root), f"{key(template_key)}/template.json").parent
    template = read_json(directory / "template.json")
    if (template.get("template_key") != template_key or template.get("enabled") is not True
            or capability_ref not in template.get("capabilities", [])):
        raise DataError("TEMPLATE_FORBIDDEN")
    if template.get('preserve_structure') is not True or template.get('missing_policy') != 'reject':
        raise DataError('TEMPLATE_CONTRACT_INVALID')
    path = asset_path(directory, template["docx_file"])
    if sha256(path.read_bytes()).hexdigest() != template["docx_sha256"]:
        raise DataError("TEMPLATE_MISMATCH")
    bindings = read_json(asset_path(directory, template["bindings_file"]))
    if bindings.get("template_version") != template["version"]:
        raise DataError("TEMPLATE_MISMATCH")
    slots = [s for f in bindings["slot_files"] for s in read_json(asset_path(directory, f))["slots"]]
    xml = document_xml(path)
    ids, positions = set(), set()
    datasets = {d["dataset_key"] for d in bindings["datasets"]}
    if len(datasets) != len(bindings["datasets"]):
        raise DataError("BINDING_INVALID")
    for slot in slots:
        if slot['kind'] not in {'static', 'scalar', 'narrative'} or any(k in slot for k in (
                'dataset_key', 'field', 'selector', 'format', 'columns', 'prefix', 'suffix', 'report_parameter', 'null_text')):
            raise DataError('BINDING_INVALID')
        position = (slot["locator"]["part"], slot["locator"]["path"])
        if slot["slot_key"] in ids or position in positions:
            raise DataError("DUPLICATE_SLOT")
        ids.add(slot["slot_key"])
        positions.add(position)
        locate(xml, slot["locator"])
        references = set(slot.get('evidence_datasets', [])) | set(slot.get('resolution', {}).get('require_empty', []))
        references.update(v['dataset_key'] for v in slot.get('values', {}).values() if 'dataset_key' in v)
        if not references <= datasets:
            raise DataError("BINDING_INVALID")
    return {**template, "_directory": directory, "_docx": path, "_slots": slots, "_bindings": bindings,
            "_revision": fingerprint([template, bindings, slots])}
