"""显式登记知识库供应商实现，不允许配置选择动态导入路径。"""

from typing import Protocol

from knowledge.providers.weknora import WeKnoraProvider


class KnowledgeProvider(Protocol):
    def validate(self, connection_config, library_config): ...
    async def search(self, connection, library, query, limit, *, client_factory): ...
    async def read(self, connection, chunk_id, *, client_factory): ...


PROVIDERS = {'weknora': WeKnoraProvider()}
