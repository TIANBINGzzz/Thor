"""受控有状态工具注册表；能力只引用工具名，不改变 Worker 生命周期。"""

from runtime.deployment_config import ConfigSnapshot
from runtime.tool_registry import TOOL_CATALOG, PROVIDERS


def load_tool_assets(entry, settings):
    """仅准备所选工具的资产，配置引用统一由同一个快照解析。"""
    selected = TOOL_CATALOG.resolve_many(entry.get('tools', []))
    result = {}
    for definition in selected:
        if definition.lifecycle != 'per_client':
            continue
        provider = PROVIDERS[definition.implementation]
        if provider.load_assets is None:
            raise RuntimeError(f'有状态工具缺少资产加载器：{definition.ref}')
        result[definition.ref] = provider.load_assets(settings, directory=entry['_directory'])
    return result


class ToolServices:
    """持久 Client 只保留适配器，每一轮重新绑定并清理身份。"""

    def __init__(self, assets, credentials):
        """校验冻结版本并创建本 Client 的独立服务实例。"""
        loaded = load_tool_assets(assets['capability'], ConfigSnapshot(values=assets['config_values']))
        self.services = {}
        try:
            for name, value in loaded.items():
                if value['revision'] != assets['tool_revisions'].get(name):
                    raise RuntimeError('能力工具资产已变化，请重新发起请求')
                provider = PROVIDERS[TOOL_CATALOG.resolve(name).implementation]
                if provider.create_service is None:
                    raise RuntimeError(f'有状态工具缺少服务工厂：{name}')
                self.services[name] = provider.create_service(value, credentials)
        except Exception:
            self.clear()
            raise

    def bind(self, credentials):
        """先清空全部旧凭据，再绑定本轮；失败也不保留部分身份。"""
        self.clear()
        try:
            for service in self.services.values():
                service.bind(credentials)
        except Exception:
            self.clear()
            raise

    def clear(self):
        """释放每轮身份、预算与结果状态，不缓存业务 Token。"""
        for service in self.services.values():
            service.clear()

    def servers(self, on_error=None):
        """把已登记适配器挂载为 MCP，统一转交脱敏失败回调。"""
        servers = {}
        for name, service in self.services.items():
            provider = PROVIDERS[TOOL_CATALOG.resolve(name).implementation]
            if provider.create_server is None:
                raise RuntimeError(f'有状态工具缺少 MCP 工厂：{name}')
            servers[name] = provider.create_server(service, on_error=on_error)
        return servers
