"""Load a trusted report template, its data plan and generated document map."""

from hashlib import sha256
from pathlib import Path
from data_access.catalog import PROJECT_ROOT, asset_path, key, read_json
from data_access.context import DataError, fingerprint
from runtime.prompt_documents import read_documents
from .document_map import load_document_map

TEMPLATES = PROJECT_ROOT / ".claude/workflows/writing-docx/templates"
def load_template(template_key, capability_ref, root=TEMPLATES):
    template_key = key(template_key)
    if Path(root).resolve()==TEMPLATES.resolve():
        registry=read_json(TEMPLATES.parent/'workflow.json').get('templates',{})
        if (template_key not in registry
                or registry[template_key] != f'templates/{key(template_key)}/template.json'):
            raise DataError('TEMPLATE_FORBIDDEN')
    directory = asset_path(Path(root), f"{key(template_key)}/template.json").parent
    template = read_json(directory / "template.json")
    if (template.get("template_key") != template_key or template.get("enabled") is not True
            or capability_ref not in template.get("capabilities", [])):
        raise DataError("TEMPLATE_FORBIDDEN")
    assets = template.get("assets") or {}
    data = template.get("data") or {}
    report = template.get("report") or {}
    output = template.get("output_policy") or {}
    try:
        documents = read_documents(directory, [assets["writing_guide"]])
    except RuntimeError as error:
        raise DataError('TEMPLATE_DOCUMENT_INVALID') from error
    except (KeyError, TypeError):
        raise DataError('TEMPLATE_DOCUMENT_INVALID') from None
    if output.get('preserve_structure') is not True or output.get('missing_policy') != 'reject':
        raise DataError('TEMPLATE_CONTRACT_INVALID')
    docx = assets.get("docx") or {}
    path = asset_path(directory, docx.get("file"))
    if sha256(path.read_bytes()).hexdigest() != docx.get("sha256"):
        raise DataError("TEMPLATE_MISMATCH")
    data_plan = read_json(asset_path(directory, assets["data_plan"]))
    if (data_plan.get("plan_version") != 1
            or data_plan.get("template_key") != template_key
            or data_plan.get("template_version") != template["version"]):
        raise DataError("TEMPLATE_MISMATCH")
    document_map, slots = load_document_map(
        directory,
        assets["document_map"],
        path,
        template_key,
        template["version"],
    )
    datasets = {d["dataset_key"] for d in data_plan["datasets"]}
    if len(datasets) != len(data_plan["datasets"]):
        raise DataError("BINDING_INVALID")
    for slot in slots:
        if slot['kind'] not in {'static', 'scalar', 'narrative'}:
            raise DataError('BINDING_INVALID')
        references = {v['dataset_key'] for v in slot.get('values', {}).values() if 'dataset_key' in v}
        if not references <= datasets:
            raise DataError("BINDING_INVALID")
    runtime = {
        "source_roles": data["source_roles"],
        "scope_roles": data["scope_roles"],
        "parameters": report["parameters"],
        "file_name": report["file_name"],
        "outline": report.get("outline", []),
        "preserve_structure": output["preserve_structure"],
        "clear_fill_markers": output.get("clear_fill_markers", False),
        "missing_policy": output["missing_policy"],
    }
    return {**template, **runtime, "_directory": directory, "_docx": path, "_slots": slots,
            "_document_map": document_map, "_bindings": data_plan,
            "_documents": documents, "_revision": fingerprint([template, data_plan, document_map, documents])}
