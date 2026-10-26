"""Capability 业务代码包注册与加载边界。"""

from __future__ import annotations

import importlib.util
import hashlib
from pathlib import Path
import sys
from threading import RLock
from types import ModuleType

from runtime.asset_registry import ENTRY_NAME, read_manifest

PACK_ROOT = Path(__file__).resolve().parent
# 部署代码只加载一次；不缓存 Run、凭据或业务 Service 实例。
_LOADED = {}
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
    for path in directory.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(directory):
            raise RuntimeError("能力代码包文件路径越界")
    return directory


def pack_digest(ref: str) -> str:
    """流式计算 Python 与声明指纹；重模板和数据仍归声明式资产目录。"""
    directory = validate_pack_reference(ref)
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*")
                       if item.is_file() and "__pycache__" not in item.parts
                       and (item.suffix == '.py' or item.name == 'pack.json')):
        resolved = path.resolve()
        if not resolved.is_relative_to(directory):
            raise RuntimeError("能力代码包文件路径越界")
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(resolved.stat().st_size.to_bytes(8, "big"))
        with resolved.open('rb') as source:
            while content := source.read(64 * 1024):
                digest.update(content)
    return digest.hexdigest()


def read_pack_manifest(ref: str):
    """读取不执行代码的 Operation 名称和 Schema，供能力校验及预览使用。"""
    directory = validate_pack_reference(ref)
    value = read_manifest(directory, "pack.json")
    if set(value) != {"ref", "operations"} or value.get("ref") != ref:
        raise RuntimeError("能力代码包声明无效")
    from runtime.capability_operations import manifest_pack

    return manifest_pack(value, ref)


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


def load_pack(ref: str, *, expected_digest: str):
    """按部署加载一次；代码变更必须重启，不在复用中的 Worker 混用版本。"""
    directory = validate_pack_reference(ref)
    with _LOAD_LOCK:
        current = pack_digest(ref)
        if not isinstance(expected_digest, str) or current != expected_digest:
            raise RuntimeError("能力代码包在 Run 准备后发生变化")
        if directory in _LOADED:
            digest, pack = _LOADED[directory]
            if digest != current or pack is None:
                raise RuntimeError("能力代码包已变更或加载失败，请重新部署并重启 Worker")
            return pack
        # 导入失败可能已执行部分模块级代码，禁止同进程再次尝试。
        _LOADED[directory] = (current, None)
        pack = _bind_pack(directory, ref)
        if pack_digest(ref) != current:
            raise RuntimeError("能力代码包在加载期间发生变化，请重启 Worker")
        _LOADED[directory] = (current, pack)
        return pack


def _bind_pack(directory: Path, ref: str):
    from dataclasses import replace
    from runtime.capability_operations import validate_pack

    pack = read_pack_manifest(ref)
    module = _load_module(directory)
    bound = []
    for operation in pack.operations:
        handler = getattr(module, operation.handler_name, None)
        if not callable(handler):
            raise RuntimeError("能力 Operation 执行器未登记")
        bound.append(replace(operation, execute=handler))
    return validate_pack(replace(pack, operations=tuple(bound)), ref)
