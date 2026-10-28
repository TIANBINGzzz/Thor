"""受控有状态工具注册表；能力只引用工具名，不改变 Worker 生命周期。"""

from pathlib import Path
import hashlib
import json

from runtime.deployment_config import ConfigSnapshot
from runtime.asset_registry import read_manifest
from runtime.tool_registry import TOOL_CATALOG, PROVIDERS


def service_asset_revision(directory, config_path, settings):
    """计算服务资产与本轮部署值的内容摘要，不生成持久化快照。"""
    directory = Path(directory).resolve()
    config = (directory / config_path).resolve()
    if not config.is_relative_to(directory):
        raise RuntimeError('能力 Service 资产路径无效')
    root = config.parent.resolve()
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob('*') if item.is_file()):
        if not path.resolve().is_relative_to(root):
            raise RuntimeError('能力 Service 资产路径无效')
        digest.update(path.relative_to(root).as_posix().encode('utf-8'))
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(128 * 1024), b''):
                digest.update(chunk)
    values = settings.resolve(read_manifest(config.parent, config.name))
    digest.update(json.dumps(values, ensure_ascii=False, sort_keys=True,
                              separators=(',', ':')).encode('utf-8'))
    return digest.hexdigest()


def load_tool_assets(entry, settings, *, include_capability_services=False):
    """仅准备所选工具的资产，配置引用统一由同一个快照解析。"""
    refs = [*entry.get('tools', []), *entry.get('service_refs', [])]
    selected = TOOL_CATALOG.resolve_many(refs)
    result = {}
    for definition in selected:
        if definition.lifecycle != 'per_client':
            continue
        if definition.implementation == 'capability-pack':
            if not include_capability_services:
                relative = entry.get('tool_config', {}).get(definition.ref)
                if relative is not None:
                    directory = Path(entry['_directory']).resolve()
                    path = (directory / relative).resolve()
                    if not path.is_relative_to(directory):
                        raise RuntimeError('能力 Service 资产路径无效')
                    result[definition.ref] = {
                        'revision': service_asset_revision(directory, relative, settings),
                        'schema_revision': None,
                    }
                continue
            from capability_packs.registry import load_pack_service_assets
            result[definition.ref] = load_pack_service_assets(
                entry['ref'], definition.service_ref, settings, entry['_directory'],
                entry.get('tool_config', {}).get(definition.ref))
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
        self.services = {}
        self._cache = {}
        self._servers = {}
        self.tool_refs = set()
        self.configure(assets, credentials)

    def configure(self, assets, credentials):
        """完整修订校验冻结资产；仅 schema 变化重建适配器，内容按轮更新。"""
        self.clear()
        loaded = load_tool_assets(assets['capability'], ConfigSnapshot(values=assets['config_values']),
                                  include_capability_services=True)
        self.services = {}
        self.tool_refs = set(assets['capability'].get('tools', []))
        try:
            for name, value in loaded.items():
                if (name in assets['tool_revisions'] and value.get('revision')
                        != assets['tool_revisions'][name]):
                    raise RuntimeError('能力工具资产已变化，请重新发起请求')
                definition = TOOL_CATALOG.resolve(name)
                provider = PROVIDERS[definition.implementation]
                cache_key = ((assets['capability']['ref'], name)
                             if definition.implementation == 'capability-pack' else name)
                cached = self._cache.get(cache_key)
                if definition.implementation == 'capability-pack':
                    from capability_packs.registry import create_pack_service, update_pack_service
                    if cached is None:
                        cached = (None, create_pack_service(
                            assets['capability']['ref'], name, value, credentials))
                        self._cache[cache_key] = cached
                    else:
                        update_pack_service(assets['capability']['ref'], name, cached[1], value)
                elif cached is None or cached[0] != value['schema_revision']:
                    if provider.create_service is None:
                        raise RuntimeError(f'有状态工具缺少服务工厂：{name}')
                    service = provider.create_service(value, credentials)
                    cached = (value['schema_revision'], service)
                    self._cache[cache_key] = cached
                    self._servers.pop(name, None)
                else:
                    if provider.update_service is None:
                        raise RuntimeError(f'有状态工具缺少资产更新器：{name}')
                    provider.update_service(cached[1], value)
                self.services[name] = cached[1]
            self.bind(credentials)
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
        for _, service in self._cache.values():
            service.clear()

    def servers(self, on_error=None):
        """把已登记适配器挂载为 MCP，统一转交脱敏失败回调。"""
        servers = {}
        for name in self.tool_refs & self.services.keys():
            service = self.services[name]
            provider = PROVIDERS[TOOL_CATALOG.resolve(name).implementation]
            if provider.create_server is None:
                raise RuntimeError(f'有状态工具缺少 MCP 工厂：{name}')
            if name not in self._servers:
                self._servers[name] = provider.create_server(service, on_error=on_error)
            servers[name] = self._servers[name]
        return servers
