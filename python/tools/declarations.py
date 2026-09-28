"""从 Tool Catalog 读取进程内工具的模型可见契约。"""


def operation(ref: str, name: str):
    """延迟读取受信任目录，避免 Tool 实现与 Catalog 的导入循环。"""
    from runtime.tool_registry import TOOL_CATALOG
    return TOOL_CATALOG.resolve(ref).operation(name)
