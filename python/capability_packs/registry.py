"""Capability 业务代码包注册与加载边界。"""

from __future__ import annotations

import importlib.util
import hashlib
from functools import lru_cache
from pathlib import Path
import sys
from threading import RLock
from types import ModuleType

from runtime.asset_registry import ENTRY_NAME, read_manifest

PACK_ROOT = Path(__file__).resolve().parent
# 部署代码只加载一次；不缓存 Run、凭据或业务 Service 实例。
_LOADED = {}
_MANIFESTS = {}
_LOAD_LOCK = RLock()


def _directory(ref: str) -> Path:
    """将能力引用解析到固定代码根目录，不接受调用方路径。"""
    if not isinstance(ref, str) or not ENTRY_NAME.fullmatch(ref):
        raise RuntimeError("能力代码包引用无效")
    root = Path(PACK_ROOT).resolve()
    directory = (root / ref).resolve()
    if not directory.is_relative_to(root):
        raise RuntimeError("能力代码包路径越界")
    return directory


def validate_pack_reference(ref: str) -> Path:
    """检查固定代码包及声明文件；目录发现和预览不会导入业务代码。"""
    directory = _directory(ref)
    if not directory.is_dir():
        raise RuntimeError("能力代码包未登记")
    required = ("__init__.py", "operations.py", "pack.json")
    for name in required:
        path = (directory / name).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise RuntimeError("能力代码包未登记")
    return directory


def _pack_manifest(directory: Path, ref: str):
    if directory not in _MANIFESTS:
        _MANIFESTS[directory] = _read_pack_manifest(directory, ref)
    return _MANIFESTS[directory]


def _read_pack_manifest(directory: Path, ref: str):
    value = read_manifest(directory, "pack.json")
    if set(value) - {'ref', 'operations', 'services'} or value.get("ref") != ref:
        raise RuntimeError("能力代码包声明无效")
    from runtime.capability_operations import manifest_pack

    return manifest_pack(value, ref)


def read_pack_manifest(ref: str):
    """读取不执行代码的 Operation 名称和 Schema，供能力校验及预览使用。"""
    directory = _directory(ref)
    with _LOAD_LOCK:
        if directory in _MANIFESTS:
            return _MANIFESTS[directory]
        validate_pack_reference(ref)
        return _pack_manifest(directory, ref)


@lru_cache(maxsize=1)
def _operation_display_keys(root):
    """静态显示索引随进程缓存，事件处理不扫描磁盘或导入业务代码。"""
    keys = {}
    for path in root.glob('*/pack.json'):
        for operation in read_pack_manifest(path.parent.name).operations:
            keys.setdefault(operation.ref, set()).add(operation.display_key)
    # 不同能力的同名操作分类不一致时使用通用显示，避免误报业务状态。
    return {ref: next(iter(values)) for ref, values in keys.items() if len(values) == 1}


def operation_display_key(operation_ref):
    return _operation_display_keys(Path(PACK_ROOT).resolve()).get(operation_ref)


def _load_module(directory: Path) -> ModuleType:
    """模块随进程保留，支持函数内相对导入及 dataclass 的模块解析。"""
    package_name = '_ccsdk_capability_pack_' + hashlib.sha256(str(directory).encode()).hexdigest()
    package_spec = importlib.util.spec_from_file_location(
        package_name, directory / "__init__.py", submodule_search_locations=[str(directory)])
    if package_spec is None or package_spec.loader is None:
        raise RuntimeError("能力代码包加载失败")
    package = importlib.util.module_from_spec(package_spec)
    sys.modules[package_name] = package
    try:
        exec(compile((directory / '__init__.py').read_bytes(), str(directory / '__init__.py'), 'exec'), package.__dict__)
        # __init__ 可能已经导入业务模块；必须复用，不能重复初始化模块级资源。
        module_name = package_name + '.operations'
        if module_name in sys.modules:
            return sys.modules[module_name]
        module_spec = importlib.util.spec_from_file_location(
            module_name, directory / "operations.py")
        if module_spec is None or module_spec.loader is None:
            raise RuntimeError("能力代码包加载失败")
        module = importlib.util.module_from_spec(module_spec)
        sys.modules[module_spec.name] = module
        exec(compile((directory / 'operations.py').read_bytes(), str(directory / 'operations.py'), 'exec'), module.__dict__)
        package.operations = module
        return module
    except BaseException:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        raise


def load_pack(ref: str):
    """按 Worker 生命周期加载一次；部署代码变更通过重启 Worker 生效。"""
    directory = _directory(ref)
    with _LOAD_LOCK:
        if directory in _LOADED:
            pack = _LOADED[directory]
            if pack is None:
                raise RuntimeError("能力代码包加载失败，请重新部署并重启 Worker")
            return pack
        validate_pack_reference(ref)
        # 导入失败可能已执行部分模块级代码，禁止同进程再次初始化。
        _LOADED[directory] = None
        pack = _bind_pack(directory, ref)
        _LOADED[directory] = pack
        return pack


def _bind_pack(directory: Path, ref: str):
    from dataclasses import replace
    from runtime.capability_operations import validate_pack

    pack = _pack_manifest(directory, ref)
    module = _load_module(directory)
    bound = []
    for operation in pack.operations:
        handler = getattr(module, operation.handler_name, None)
        if not callable(handler):
            raise RuntimeError("能力 Operation 执行器未登记")
        bound.append(replace(operation, execute=handler))
    return validate_pack(replace(
        pack,
        operations=tuple(bound),
        load_service_assets=getattr(module, 'load_service_assets', None),
        create_service=getattr(module, 'create_service', None),
        update_service=getattr(module, 'update_service', None),
        specialize_operations=getattr(module, 'specialize_operations', None),
    ), ref)


def load_pack_service_assets(capability_ref, service_ref, settings, directory, config_path):
    """加载代码包声明的 Service 资产；只在实际执行装配时导入包代码。"""
    pack = load_pack(capability_ref)
    if service_ref not in pack.services or not callable(pack.load_service_assets):
        raise RuntimeError('能力 Service 资产未登记')
    return pack.load_service_assets(service_ref, settings, directory, config_path,
                                    pack.operations)


def create_pack_service(capability_ref, service_ref, assets, credentials):
    pack = load_pack(capability_ref)
    if service_ref not in pack.services or not callable(pack.create_service):
        raise RuntimeError('能力 Service 工厂未登记')
    return pack.create_service(service_ref, assets, credentials, pack.operations)


def update_pack_service(capability_ref, service_ref, service, assets):
    pack = load_pack(capability_ref)
    if service_ref not in pack.services or not callable(pack.update_service):
        raise RuntimeError('能力 Service 更新器未登记')
    return pack.update_service(service_ref, service, assets)
