"""Load selected writing context and stage a verified template copy for the harness."""

from pathlib import Path
from hashlib import sha256
from data_access.catalog import PROJECT_ROOT, asset_path, key, read_json
from data_access.context import DataError, fingerprint
from runtime.asset_registry import read_manifest
from runtime.prompt_documents import read_documents

TEMPLATES = PROJECT_ROOT / ".claude/workflows/writing-docx/templates"


def document_digest(path):
    """计算模板文件字节的 SHA-256 摘要，用于冻结和核验实际版本。"""
    return sha256(path.read_bytes()).hexdigest()

def load_template(template_key, capability_ref, root=TEMPLATES):
    """校验模板登记与能力范围，加载指南和原稿并计算本轮资产版本。"""
    template_key = key(template_key)
    if Path(root).resolve()==TEMPLATES.resolve():
        registry=read_manifest(TEMPLATES.parent, 'workflow.json').get('templates', {})
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
    try:
        documents = read_documents(directory, [assets["writing_guide"]])
    except RuntimeError as error:
        raise DataError('TEMPLATE_DOCUMENT_INVALID') from error
    except (KeyError, TypeError):
        raise DataError('TEMPLATE_DOCUMENT_INVALID') from None
    docx = assets.get("docx") or {}
    path = asset_path(directory, docx.get("file"))
    digest = document_digest(path)
    warnings = []
    if docx.get('sha256') and digest != docx['sha256']:
        warnings.append('DOCX_BASELINE_CHANGED')
    runtime = {
        "source_roles": data["source_roles"],
        "file_name": report["file_name"],
    }
    return {**template, **runtime, "_directory": directory, "_docx": path,
            "_documents": documents, '_docx_digest': digest, '_warnings': warnings,
            "_revision": fingerprint([template, digest, documents])}


def stage_template(template, work_directory):
    """Copy the frozen source into the Run workspace without overwriting a draft."""
    root = Path(work_directory).resolve()
    destination = root / 'references' / template['template_key'] / template['_revision'] / 'template.docx'
    if not destination.resolve().is_relative_to(root):
        raise DataError('ASSET_PATH_INVALID')
    content = template['_docx'].read_bytes()
    if sha256(content).hexdigest() != template['_docx_digest']:
        raise DataError('TEMPLATE_MISMATCH')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open('xb') as output:
            output.write(content)
    except FileExistsError:
        if document_digest(destination) != template['_docx_digest']:
            raise DataError('TEMPLATE_COPY_MODIFIED') from None
    return destination
