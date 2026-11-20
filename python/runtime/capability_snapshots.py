"""导出 MySQL 能力正文和 Skill 的本地审阅副本。"""

import json
from pathlib import Path, PureWindowsPath

from runtime.asset_registry import ENTRY_NAME
from runtime.configuration import execution_entry

MANIFEST = '.db-snapshot.json'
RESOURCE_SUFFIXES = {'.md', '.txt', '.json', '.csv'}


def _safe_relative(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('snapshot_path_invalid')
    path = Path(value)
    if (path.is_absolute() or PureWindowsPath(value).drive
            or '..' in path.parts or path.suffix.lower() not in RESOURCE_SUFFIXES):
        raise ValueError('snapshot_path_invalid')
    return path


def _resolve_file(root, relative):
    candidate = root / relative
    cursor = candidate
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError('snapshot_path_invalid')
        cursor = cursor.parent
    path = candidate.resolve()
    if not path.is_relative_to(root):
        raise ValueError('snapshot_path_invalid')
    if root.is_symlink():
        raise ValueError('snapshot_path_invalid')
    return path


def _owned_relative(value):
    relative = _safe_relative(value)
    parts = relative.parts
    if parts == ('CAPABILITY.md',):
        return relative
    if (len(parts) >= 3 and parts[0] == 'skills'
            and ENTRY_NAME.fullmatch(parts[1])
            and not (len(parts) > 3 and parts[2] == 'SKILL.md')):
        return relative
    raise ValueError('snapshot_manifest_invalid')


def _snapshot_paths(entry):
    if not isinstance(entry.get('_body'), str):
        raise ValueError('snapshot_content_invalid')
    files = {'CAPABILITY.md': entry['_body']}
    for ref, skill in entry['_skills'].items():
        if not ENTRY_NAME.fullmatch(ref):
            raise ValueError('snapshot_skill_invalid')
        if not isinstance(skill.get('_body'), str):
            raise ValueError('snapshot_content_invalid')
        prefix = Path('skills') / ref
        files[(prefix / 'SKILL.md').as_posix()] = skill['_body']
        for name, content in skill.get('resources', {}).items():
            if not isinstance(content, str):
                raise ValueError('snapshot_content_invalid')
            relative = _safe_relative(name)
            target = (prefix / relative).as_posix()
            if target in files:
                raise ValueError('snapshot_path_invalid')
            files[target] = content
    if any(not isinstance(content, str) for content in files.values()):
        raise ValueError('snapshot_content_invalid')
    return files


def _read_previous(root, capability_ref):
    path = root / MANIFEST
    if not path.exists():
        return set()
    if path.is_symlink():
        raise ValueError('snapshot_manifest_invalid')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        files = value['files']
        if (value.get('capabilityRef') != capability_ref or not isinstance(files, list)
                or len(files) != len(set(files))):
            raise ValueError()
        for name in files:
            relative = _owned_relative(name)
            _resolve_file(root, relative)
        return set(files)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise ValueError('snapshot_manifest_invalid') from None


def export_capability_snapshot(capability_ref, *, output_root=None):
    """导出选定能力的数据库内容；Runtime 永不读取这个目录作为运行来源。"""
    if not isinstance(capability_ref, str) or not ENTRY_NAME.fullmatch(capability_ref):
        raise ValueError('capability_ref_invalid')
    entry = execution_entry(capability_ref)['capability']
    from capability_packs.registry import PACK_ROOT

    base = Path(output_root) if output_root is not None else PACK_ROOT
    base = base.resolve()
    root_path = base / capability_ref
    if root_path.is_symlink():
        raise ValueError('snapshot_path_invalid')
    root = root_path.resolve()
    if not root.is_relative_to(base):
        raise ValueError('snapshot_path_invalid')
    files = _snapshot_paths(entry)
    previous = _read_previous(root, capability_ref) if root.exists() else set()
    current = set(files)
    for name in current - previous:
        path = _resolve_file(root, _owned_relative(name))
        if path.exists():
            raise ValueError('snapshot_file_not_owned')
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = _resolve_file(root, _owned_relative(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    for name in previous - current:
        path = _resolve_file(root, _safe_relative(name))
        if path.is_file():
            path.unlink()
        parent = path.parent
        while parent != root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
    manifest = {'capabilityRef': capability_ref, 'files': sorted(current)}
    (root / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8')
    return sorted(current)
