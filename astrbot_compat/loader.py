# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""插件发现与加载器。"""

from __future__ import annotations

import functools
import importlib
import keyword
import logging
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

try:
    from packaging.specifiers import SpecifierSet  # type: ignore
except ImportError:
    SpecifierSet = None  # type: ignore

from .config import AstrBotConfig, load_conf_schema
from .registry import StarMetadata, star_handlers_registry, star_map, star_registry

logger = logging.getLogger("astrbot_compat.loader")

_loaded_dirs: set[str] = set()
_failed: dict[str, str] = {}


def _validate_importable_name(dir_name: str) -> bool:
    return (
        dir_name.isidentifier()
        and not keyword.iskeyword(dir_name)
        and not dir_name.startswith("_")
    )


def _read_metadata(plugin_dir: Path) -> dict | None:
    if yaml is None:
        return None
    for fname in ("metadata.yaml", "metadata.yml"):
        p = plugin_dir / fname
        if p.exists():
            try:
                with p.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)  # type: ignore[union-attr]
                if isinstance(data, dict):
                    return data
                logger.warning(f"[astrbot_compat] {p} 解析结果非 dict，已忽略")
                return None
            except Exception as e:
                logger.warning(f"[astrbot_compat] {p} 读取失败: {e}")
                return None
    return None


def _check_version(meta: dict, dir_name: str) -> bool:
    spec_str = meta.get("astrbot_version")
    if not spec_str:
        return True
    if SpecifierSet is None:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 版本约束 {spec_str} 因缺少 packaging 未校验")
        return True
    try:
        from config.settings import ASTRBOT_COMPAT_VERSION

        ver = ASTRBOT_COMPAT_VERSION
    except Exception:
        ver = "4.27.0"
    try:
        spec = SpecifierSet(str(spec_str))  # type: ignore[operator]
        if not spec.contains(ver, prereleases=True):
            logger.warning(
                f"[astrbot_compat] 插件 {dir_name} 要求 astrbot_version {spec_str}，"
                f"当前兼容声称版本 {ver} 不匹配，仍尝试加载"
            )
        return True
    except Exception as e:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 版本约束解析失败 {spec_str}: {e}")
        return True


def _resolve_metadata(
    dir_name: str, meta: dict | None, star_cls: type
) -> dict[str, Any]:
    """优先 metadata.yaml，否则 @register，最后回退。"""
    name = None
    author = None
    desc = None
    version = None
    repo = None
    if meta:
        name = meta.get("name")
        author = meta.get("author")
        desc = meta.get("desc") or meta.get("description")
        version = meta.get("version")
        repo = meta.get("repo")
    reg_meta = getattr(star_cls, "__astrbot_register_meta__", None)
    if reg_meta:
        args = reg_meta.get("args", ())
        kwargs = reg_meta.get("kwargs", {})
        keys = ["name", "author", "desc", "version", "repo"]
        for i, k in enumerate(keys):
            val = None
            if i < len(args):
                val = args[i]
            elif k in kwargs:
                val = kwargs[k]
            if k == "name" and not name and val:
                name = val
            elif k == "author" and not author and val:
                author = val
            elif k == "desc" and not desc and val:
                desc = val
            elif k == "version" and not version and val:
                version = val
            elif k == "repo" and not repo and val:
                repo = val
    if not name:
        name = dir_name
    if not author:
        author = "unknown"
    if not desc:
        desc = ""
    if not version:
        version = "0.0.0"
    return {"name": name, "author": author, "desc": desc, "version": version, "repo": repo}


def _failed_key(md: StarMetadata | None, fallback_dir: str = "") -> str:
    if md is not None:
        return md.root_dir_name or md.module_path or md.plugin_id or fallback_dir
    return fallback_dir


def load_plugin(plugin_dir: Path) -> StarMetadata | None:
    dir_name = plugin_dir.name
    # a
    if not _validate_importable_name(dir_name):
        msg = f"目录名 {dir_name!r} 非合法 Python 标识符，请重命名"
        _failed[dir_name] = msg
        logger.error(f"[astrbot_compat] {msg}")
        return None
    # b
    if not (plugin_dir / "main.py").exists():
        return None
    # c
    meta_raw = _read_metadata(plugin_dir)
    if meta_raw is not None:
        _check_version(meta_raw, dir_name)
    # 移除旧的 before = len(...)，改用 module_name 精确定位
    module_name = f"data.plugins.{dir_name}.main"
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        _failed[dir_name] = repr(e)
        logger.exception(f"[astrbot_compat] 插件 {dir_name} import 失败: {e}")
        return None
    # f
    md = star_map.get(module_name)
    if md is None:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 未继承 Star，已跳过")
        return None
    # g
    star_cls = md.star_cls_type
    if star_cls is None:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} star_cls_type 为空")
        md.activated = False
        return None
    resolved = _resolve_metadata(dir_name, meta_raw, star_cls)
    md.name = resolved["name"]
    md.author = resolved["author"]
    md.desc = resolved["desc"]
    md.version = resolved["version"]
    md.repo = resolved["repo"]
    md.module_path = module_name
    md.root_dir_name = dir_name
    md.module = mod  # type: ignore[assignment]
    # 注入到 Star 类（供插件通过 self.name / self.plugin_id 读取，与上游一致）
    try:
        star_cls.name = resolved["name"]  # type: ignore[attr-defined]
        star_cls.author = resolved["author"]  # type: ignore[attr-defined]
        star_cls.version = resolved["version"]  # type: ignore[attr-defined]
        star_cls.desc = resolved["desc"]  # type: ignore[attr-defined]
        star_cls.plugin_id = f"{resolved['author'].lower()}/{resolved['name'].lower()}".replace("/", "_")  # type: ignore[attr-defined]
    except Exception:
        pass
    # h
    schema = load_conf_schema(plugin_dir)
    if schema:
        try:
            cfg = AstrBotConfig(dir_name, schema)
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {dir_name} 配置初始化失败: {e}")
            cfg = None
    else:
        cfg = None
    md.config = cfg
    # i
    from .context import get_context

    ctx = get_context()
    inst = None
    if cfg is not None:
        try:
            inst = star_cls(ctx, cfg)  # type: ignore[call-arg]
        except TypeError:
            try:
                inst = star_cls(ctx)  # type: ignore[call-arg]
            except Exception as e2:
                _failed[dir_name] = repr(e2)
                logger.exception(f"[astrbot_compat] 插件 {dir_name} 实例化失败: {e2}")
                md.activated = False
                return None
        except Exception as e:
            _failed[dir_name] = repr(e)
            logger.exception(f"[astrbot_compat] 插件 {dir_name} 实例化失败: {e}")
            md.activated = False
            return None
    else:
        try:
            inst = star_cls(ctx)  # type: ignore[call-arg]
        except Exception as e:
            _failed[dir_name] = repr(e)
            logger.exception(f"[astrbot_compat] 插件 {dir_name} 实例化失败: {e}")
            md.activated = False
            return None
    md.star_cls = inst
    # j: handler 重绑定 —— 一律靠 module_name 查，绝不靠下标区间（避免 sort 串位）
    own_handlers = star_handlers_registry.get_handlers_by_module_name(module_name)
    for h in own_handlers:
        try:
            raw = h.handler
            if isinstance(raw, functools.partial):
                raw = raw.func
            h.handler = functools.partial(raw, inst)  # type: ignore[assignment]
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {dir_name} handler 重绑定失败 {h.handler_name}: {e}")
    md.star_handler_full_names = [hh.handler_full_name for hh in own_handlers]
    # k
    logger.info(f"[astrbot_compat] 已加载插件 {md.name} v{md.version} ({md.plugin_id})")
    _loaded_dirs.add(dir_name)
    return md


def discover_plugins() -> list[Path]:
    try:
        from config.settings import ASTRBOT_PLUGINS_DIR

        plugins_dir = ASTRBOT_PLUGINS_DIR
    except Exception:
        plugins_dir = Path(__file__).resolve().parent.parent / "data" / "plugins"
    if not plugins_dir.exists():
        try:
            plugins_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return []
    result: list[Path] = []
    for p in plugins_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if name.startswith(".") or name.startswith("_") or name == "__pycache__":
            continue
        result.append(p)
    result.sort(key=lambda x: x.name)
    return result


def load_all_plugins() -> list[StarMetadata]:
    try:
        from config.settings import ASTRBOT_COMPAT_ENABLED

        if not ASTRBOT_COMPAT_ENABLED:
            logger.info("[astrbot_compat] ASTRBOT_COMPAT_ENABLED=false，跳过插件加载")
            return []
    except Exception:
        pass
    try:
        from config.settings import PROJECT_ROOT

        root_str = str(PROJECT_ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
    except Exception:
        pass
    success: list[StarMetadata] = []
    plugins = discover_plugins()
    for p in plugins:
        try:
            md = load_plugin(p)
            if md is not None:
                success.append(md)
        except Exception as e:
            logger.exception(f"[astrbot_compat] 插件 {p.name} 加载异常: {e}")
            _failed[p.name] = repr(e)
    logger.info(f"[astrbot_compat] 插件加载完成：成功 {len(success)} 个，失败 {len(_failed)} 个" + (f"（失败: {', '.join(_failed.keys())}）" if _failed else ""))
    return success


async def initialize_plugins() -> None:
    from .context import _MODEL_DEPENDENT_PLUGINS
    from .exceptions import StellaCompatNotSupported

    for md in list(star_registry):
        if not md.activated:
            continue
        inst = md.star_cls
        if inst is None:
            continue
        try:
            await inst.initialize()
        except StellaCompatNotSupported as e:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} 依赖未实现能力 {e}，已标记为受限")
            md.activated = False
            _MODEL_DEPENDENT_PLUGINS.add(md.plugin_id)
            key = _failed_key(md, md.root_dir_name)
            _failed[key] = f"StellaCompatNotSupported: {e}"
        except Exception as e:
            logger.exception(f"[astrbot_compat] 插件 {md.plugin_id} initialize 失败: {e}")
            md.activated = False
            key = _failed_key(md, md.root_dir_name)
            _failed[key] = repr(e)


async def terminate_plugins() -> None:
    import asyncio

    for md in reversed(list(star_registry)):
        inst = md.star_cls
        if inst is None:
            continue
        try:
            await asyncio.wait_for(inst.terminate(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 超时")
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 异常: {e}")


def get_failed_plugins() -> dict[str, str]:
    return dict(_failed)
