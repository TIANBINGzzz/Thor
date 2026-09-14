"""Register existing paragraph mappings without inventing missing business rules."""

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path

from markdown_it import MarkdownIt

from data_access.catalog import Catalog
from .bindings import NS, document_xml, text_hash


def markdown_rows(content):
    tokens = MarkdownIt("commonmark").enable("table").parse(content)
    row = None
    for token in tokens:
        if token.type == "tr_open":
            row = []
        elif token.type == "inline" and row is not None:
            row.append(token.content)
        elif token.type == "tr_close":
            yield row
            row = None


def register(directory):
    directory = Path(directory)
    docx = next(p for p in directory.glob("*规范化模板.docx") if not p.name.startswith("~$"))
    source = next(directory.glob("*模板数据来源.md"))
    bindings = json.loads((directory / "query-bindings.json").read_text(encoding="utf-8"))
    xml = document_xml(docx)
    paragraphs = xml.xpath(".//w:p", namespaces=NS)
    tree = xml.getroottree()
    grouped, datasets = {}, {}
    catalog = Catalog()
    for row in markdown_rows(source.read_text(encoding="utf-8")):
        table = bool(row and re.fullmatch(r"T\d+/R\d+/C\d+/P\d+", row[0]))
        body = bool(len(row) == 7 and re.fullmatch(r"P\d+", row[0]) and re.fullmatch(r"P\d+", row[1]))
        if not table and not body:
            continue
        new_p, original, title, codes, instruction = (row[2], row[3], row[4], row[6], row[7]) if table else (row[1], row[2], row[3], row[5], row[6])
        node = paragraphs[int(new_p[1:]) - 1]
        current = "".join(node.xpath(".//w:t/text()", namespaces=NS))
        table_key = row[0].split("/")[0] if table else None
        section = table_key or "body_" + sha256(title.encode()).hexdigest()[:10]
        role = "school"
        if table_key:
            number = int(table_key[1:])
            role = "group_a" if 17 <= number <= 27 else "group_b" if 28 <= number <= 39 else "school"
        elif "通信技术专业群" in title:
            role = "group_a"
        elif "电子信息工程技术专业群" in title:
            role = "group_b"
        dynamic = "__" in current or "【待" in current
        kind = "scalar" if table and dynamic else "narrative" if dynamic else "static"
        slot = {"slot_key": row[0].replace("/", "_") if table else new_p,
                "section_key": section, "kind": kind, "required": dynamic,
                "name": original, "business_context": title, "scope_role": role,
                "source_rules": codes.split("+"), "instruction": instruction,
                "locator": {"part": "word/document.xml", "path": tree.getpath(node), "expected_text_hash": text_hash(node)},
                "binding_status": "definition_missing" if dynamic else "static"}
        grouped.setdefault(section, []).append(slot)
        for code in codes.split("+"):
            for query_id in bindings["rules"].get(code, {}).get("query_ids", []):
                dataset_key = f"{role}_{query_id}"
                spec = catalog.spec("schoolDoubleHigh", "hpm", query_id)
                parameter_bindings = {}
                for name, definition in spec["parameters"].items():
                    if definition.get("origin", "").startswith("authorized_"):
                        continue
                    if name == "year":
                        parameter_bindings[name] = {"from": "report_parameter", "key": "years", "expand": "each"}
                    elif name in {"name_pattern", "member_type", "level", "threshold"}:
                        parameter_bindings[name] = {"from": "literal", "value": {"level": 3, "threshold": 50}.get(name)}
                datasets.setdefault(dataset_key, {"dataset_key": dataset_key, "source_role": "hpm", "domain": "hpm",
                    "scope_role": role, "query_id": query_id, "parameter_bindings": parameter_bindings,
                    "depends_on": [], "section_keys": [], "usage": "candidate_facts"})["section_keys"].append(section)
    slots_dir = directory / "slots"
    slots_dir.mkdir(exist_ok=True)
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for section, slots in grouped.items():
        save(slots_dir / f"{section}.json", {"section_key": section, "slots": slots})
    for dataset in datasets.values():
        dataset["section_keys"] = sorted(set(dataset["section_keys"]))
    bindings.update({"version": 2, "template_version": 1, "path_base": "template_root",
        "source_key": "schoolDoubleHigh", "status": "registered_with_definition_gaps",
        "source_document": source.name, "slot_files": [f"slots/{s}.json" for s in grouped], "datasets": list(datasets.values())})
    bindings.pop("query_catalog", None)
    for table in bindings["tables"]:
        table["source_key"] = "schoolDoubleHigh"
    save(directory / "query-bindings.json", bindings)
    save(directory / "template.json", {"template_key": "szpt-midterm", "name": "双高计划中期自评报告",
        "version": 1, "enabled": True, "capabilities": ["document-writing"], "docx_file": docx.name,
        "docx_sha256": sha256(docx.read_bytes()).hexdigest(), "bindings_file": "query-bindings.json",
        "source_roles": {"hpm": "schoolDoubleHigh"}, "scope_roles": {"hpm": ["school", "group_a", "group_b"]},
        "missing_policy": "annotated_draft", "parameters": {"type": "object", "additionalProperties": False,
            "properties": {"years": {"type": "array", "minItems": 1, "maxItems": 10, "uniqueItems": True,
                "items": {"type": "string", "pattern": "^[0-9]{4}$"}}, "as_of": {"type": "string", "format": "date"},
                "period_mode": {"enum": ["annual", "cumulative"]}, "timezone": {"const": "Asia/Shanghai"}},
            "required": ["years", "period_mode", "timezone"]}})
    print(json.dumps({"slots": sum(map(len, grouped.values())), "table_sections": sum(s.startswith('T') for s in grouped),
                      "datasets": len(datasets)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_directory", type=Path)
    register(parser.parse_args().template_directory)
