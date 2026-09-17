"""Load a trusted report template, its data plan and generated document map."""

from pathlib import Path
from data_access.catalog import PROJECT_ROOT, asset_path, key, read_json
from data_access.context import DataError, fingerprint
from runtime.prompt_documents import read_documents
from .report_locations import document_digest, inspect_locations

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
    if output.get('preserve_structure') is not True:
        raise DataError('TEMPLATE_CONTRACT_INVALID')
    docx = assets.get("docx") or {}
    path = asset_path(directory, docx.get("file"))
    digest = document_digest(path)
    warnings = []
    if docx.get('sha256') and digest != docx['sha256']:
        warnings.append('DOCX_BASELINE_CHANGED')
    data_plan = (read_json(asset_path(directory, assets['data_plan'])) if assets.get('data_plan') else
                 {'plan_version': 1, 'template_key': template_key,
                  'template_version': template['version'], 'datasets': []})
    if (data_plan.get("plan_version") != 1
            or data_plan.get("template_key") != template_key
            or data_plan.get("template_version") != template["version"]):
        raise DataError("TEMPLATE_MISMATCH")
    document_map = None
    if assets.get('document_map'):
        relative = Path(assets['document_map'])
        map_path = (directory / relative).resolve()
        if relative.is_absolute() or not map_path.is_relative_to(directory.resolve()):
            raise DataError('ASSET_PATH_INVALID')
        if map_path.is_file():
            try:
                candidate = read_json(map_path)
            except DataError:
                candidate = {}
            if (isinstance(candidate, dict) and candidate.get('map_version') == 1 and candidate.get('template_key') == template_key
                    and candidate.get('template_version') == template['version']
                    and isinstance(candidate.get('locations'), list)
                    and all(isinstance(item, dict) and isinstance(item.get('location_id'), str)
                            and isinstance(item.get('template_text'), str)
                            and isinstance(item.get('section_key'), str)
                            and isinstance(item.get('locator'), dict)
                            and isinstance(item['locator'].get('path'), str)
                            for item in candidate['locations'])
                    and len({item.get('location_id') for item in candidate['locations']}) == len(candidate['locations'])):
                document_map = candidate
            else:
                warnings.append('DOCUMENT_MAP_IGNORED')
        else:
            warnings.append('DOCUMENT_MAP_MISSING')
    locations, map_status = inspect_locations(path, document_map)
    if map_status['unmatched_annotations']:
        warnings.append('DOCUMENT_MAP_PARTIALLY_MATCHED')
    datasets = {d["dataset_key"] for d in data_plan["datasets"]}
    if len(datasets) != len(data_plan["datasets"]):
        raise DataError("BINDING_INVALID")
    runtime = {
        "source_roles": data["source_roles"],
        "scope_roles": data["scope_roles"],
        "parameters": report["parameters"],
        "file_name": report["file_name"],
        "outline": report.get("outline", []),
        "preserve_structure": output["preserve_structure"],
        "clear_fill_markers": output.get("clear_fill_markers", False),
    }
    return {**template, **runtime, "_directory": directory, "_docx": path, "_locations": locations,
            "_document_map": document_map, "_bindings": data_plan,
            "_documents": documents, '_docx_digest': digest, '_map_status': map_status, '_warnings': warnings,
            "_revision": fingerprint([template, digest, data_plan, document_map, documents])}
