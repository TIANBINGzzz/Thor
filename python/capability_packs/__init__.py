"""受信任的 Capability 业务代码包。

代码包随 Runtime 源码和镜像部署，只能由固定目录中的能力引用选择；
持久化能力资产和请求正文都不能指定 Python 模块。
"""

from .registry import PACK_ROOT, load_pack, validate_pack_reference

__all__ = ["PACK_ROOT", "load_pack", "validate_pack_reference"]
