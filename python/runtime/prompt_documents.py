"""Read only explicitly registered Markdown assets inside their owning directory."""

from pathlib import Path, PureWindowsPath

import yaml

MAX_DOCUMENT_BYTES = 24_000
MAX_DOCUMENT_TOTAL_BYTES = 80_000


def read_documents(directory, names):
    """读取显式登记的 Markdown，拒绝越界、人工材料和超量内容。"""
    if (not isinstance(names, list)
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)):
        raise RuntimeError("撰写说明必须是无重复的Markdown文件列表")
    root = Path(directory).resolve()
    documents = []
    total = 0
    for name in names:
        relative = Path(name)
        if (relative.is_absolute() or PureWindowsPath(name).drive
                or '..' in relative.parts or relative.suffix.lower() != '.md'
                or 'not_for_model' in name.lower().replace('-', '_')):
            raise RuntimeError("撰写说明路径无效或属于人工核验材料")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError("撰写说明不存在或路径越界")
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


class _EntryLoader(yaml.SafeLoader):
    """入口只允许普通 YAML 值，禁止别名和重复键掩盖配置。"""

    def compose_node(self, parent, index):
        """禁止别名引用，避免递归对象和隐式共享配置。"""
        if self.check_event(yaml.AliasEvent):
            raise ValueError('入口不支持YAML别名')
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        """每层配置只接受唯一的字符串键。"""
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        if any(not isinstance(key, str) for key in keys) or len(set(keys)) != len(keys):
            raise ValueError('入口存在非字符串键或重复键')
        return super().construct_mapping(node, deep=deep)


def read_entry(path):
    """分离服务端元数据与模型正文；不执行 YAML 对象或模板表达式。"""
    path = Path(path)
    text = read_documents(path.parent, [path.name])[0]['text']
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise RuntimeError('执行入口缺少YAML元数据')
    try:
        end = lines.index('---', 1)
        metadata = yaml.load('\n'.join(lines[1:end]), Loader=_EntryLoader)
        if not isinstance(metadata, dict) or any(key.startswith('_') for key in metadata):
            raise ValueError('入口元数据必须为对象且不能使用内部字段')
    except (ValueError, yaml.YAMLError) as error:
        raise RuntimeError('执行入口元数据无效') from error
    body = '\n'.join(lines[end + 1:]).strip()
    if not body:
        raise RuntimeError('执行入口正文为空')
    return {**metadata, '_body': body, '_directory': str(path.parent.resolve())}
