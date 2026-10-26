"""Read only explicitly registered Markdown assets inside their owning directory."""

from pathlib import Path, PureWindowsPath

MAX_DOCUMENT_BYTES = 24_000
MAX_DOCUMENT_TOTAL_BYTES = 80_000


def read_documents(directory, names, *, asset_root=None):
    """读取显式登记的 Markdown，拒绝越界、人工材料和超量内容。"""
    if (not isinstance(names, list)
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)):
        raise RuntimeError("撰写说明必须是无重复的Markdown文件列表")
    root = Path(directory).resolve()
    # 检查可信资产边界内的所有者目录；宿主机父目录名称不是资产分类。
    boundary = Path(asset_root).resolve() if asset_root is not None else root.parent
    if (not root.is_relative_to(boundary)
            or 'not_for_model' in root.relative_to(boundary).as_posix().lower().replace('-', '_')):
        raise RuntimeError('提示词所有者路径越界或属于人工核验材料')
    documents = []
    seen = set()
    total = 0
    for name in names:
        relative = Path(name)
        if (relative.is_absolute() or PureWindowsPath(name).drive
                or '..' in relative.parts or relative.suffix.lower() != '.md'
                or 'not_for_model' in name.lower().replace('-', '_')):
            raise RuntimeError("撰写说明路径无效或属于人工核验材料")
        path = (root / relative).resolve()
        if (not path.is_relative_to(root) or not path.is_file()
                or 'not_for_model' in path.relative_to(boundary).as_posix().lower().replace('-', '_')):
            raise RuntimeError("撰写说明不存在或路径越界")
        if path in seen:
            raise RuntimeError("提示词文件重复引用")
        seen.add(path)
        try:
            with path.open('rb') as stream:
                content = stream.read(MAX_DOCUMENT_BYTES + 1)
            total += len(content)
            if len(content) > MAX_DOCUMENT_BYTES or total > MAX_DOCUMENT_TOTAL_BYTES:
                raise RuntimeError("撰写说明超过大小限制")
            text = content.decode('utf-8')
        except (OSError, UnicodeError) as error:
            raise RuntimeError("撰写说明无法读取") from error
        if not text.strip():
            raise RuntimeError("撰写说明为空")
        documents.append({'name': name, 'text': text})
    return documents
