# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""插件发现与加载器。"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib
import keyword
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺依赖时降级
    yaml = None

try:
    from packaging.specifiers import SpecifierSet
except ImportError:  # pragma: no cover - 环境缺依赖时降级
    SpecifierSet = None

from .config import AstrBotConfig, load_conf_schema
from .registry import (
    EventType,
    StarMetadata,
    star_handlers_registry,
    star_map,
    star_registry,
)

logger = logging.getLogger("astrbot_compat.loader")

_loaded_dirs: set[str] = set()
_failed: dict[str, str] = {}


def _compat_version() -> str:
    try:
        from config.settings import ASTRBOT_COMPAT_VERSION

        return ASTRBOT_COMPAT_VERSION
    except Exception:
        return "4.27.0"


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
        if not p.exists():
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as e:
            logger.warning(f"[astrbot_compat] {p} 读取失败: {e}")
            return None
        if isinstance(data, dict):
            return data
        logger.warning(f"[astrbot_compat] {p} 解析结果非 dict，已忽略")
        return None
    return None


def _check_version(meta: dict, dir_name: str) -> bool:
    """校验 astrbot_version 约束。不匹配时只告警，仍尝试加载。"""
    spec_str = meta.get("astrbot_version")
    if not spec_str:
        return True
    if SpecifierSet is None:
        logger.warning(
            f"[astrbot_compat] 插件 {dir_name} 版本约束 {spec_str} 因缺少 packaging 未校验",
        )
        return True
    ver = _compat_version()
    try:
        if not SpecifierSet(str(spec_str)).contains(ver, prereleases=True):
            logger.warning(
                f"[astrbot_compat] 插件 {dir_name} 要求 astrbot_version {spec_str}，"
                f"当前兼容声称版本 {ver} 不匹配，仍尝试加载",
            )
    except Exception as e:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 版本约束解析失败 {spec_str}: {e}")
    return True


def _install_requirements(plugin_dir: Path, dir_name: str) -> None:
    """按需安装插件依赖。默认关闭，避免未经确认地执行 pip。"""
    try:
        from config.settings import ASTRBOT_AUTO_INSTALL_REQUIREMENTS

        enabled = ASTRBOT_AUTO_INSTALL_REQUIREMENTS
    except Exception:
        enabled = False
    req = plugin_dir / "requirements.txt"
    if not req.exists():
        return
    if not enabled:
        logger.info(
            f"[astrbot_compat] 插件 {dir_name} 声明了 requirements.txt，"
            f"但 ASTRBOT_AUTO_INSTALL_REQUIREMENTS=false，未自动安装",
        )
        return
    logger.info(f"[astrbot_compat] 正在为插件 {dir_name} 安装依赖 {req}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req)],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                f"[astrbot_compat] 插件 {dir_name} 依赖安装失败（退出码 "
                f"{result.returncode}）：{result.stderr.strip()[:500]}",
            )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 依赖安装异常: {e}")


def _resolve_metadata(dir_name: str, meta: dict | None, star_cls: type) -> dict[str, Any]:
    """优先 metadata.yaml，其次 @register 的参数，最后回退。"""
    fields = ["name", "author", "desc", "version", "repo"]
    resolved: dict[str, Any] = dict.fromkeys(fields)
    if meta:
        resolved["name"] = meta.get("name")
        resolved["author"] = meta.get("author")
        resolved["desc"] = meta.get("desc") or meta.get("description")
        resolved["version"] = meta.get("version")
        resolved["repo"] = meta.get("repo")

    reg_meta = getattr(star_cls, "__astrbot_register_meta__", None)
    if reg_meta:
        args = reg_meta.get("args", ())
        kwargs = reg_meta.get("kwargs", {})
        for i, k in enumerate(fields):
            if resolved[k]:
                continue
            if i < len(args):
                resolved[k] = args[i]
            elif k in kwargs:
                resolved[k] = kwargs[k]

    resolved["name"] = resolved["name"] or dir_name
    resolved["author"] = resolved["author"] or "unknown"
    resolved["desc"] = resolved["desc"] or ""
    resolved["version"] = resolved["version"] or "0.0.0"
    return resolved


def _apply_extra_metadata(md: StarMetadata, meta: dict | None) -> None:
    if not meta:
        return
    md.display_name = meta.get("display_name") or md.display_name
    md.short_desc = meta.get("short_desc") or md.short_desc
    if isinstance(meta.get("support_platforms"), list):
        md.support_platforms = [str(p) for p in meta["support_platforms"]]
    if isinstance(meta.get("astrbot_version"), str):
        md.astrbot_version = meta["astrbot_version"]
    if isinstance(meta.get("pages"), list):
        md.pages = meta["pages"]


def _failed_key(md: StarMetadata | None, fallback_dir: str = "") -> str:
    if md is not None:
        return md.root_dir_name or md.module_path or fallback_dir
    return fallback_dir


def _import_plugin_module(module_name: str) -> Any:
    """导入插件模块。找不到时先清一次导入缓存再重试。

    `data` / `data.plugins` 是命名空间包，导入系统会缓存其目录清单；插件目录若在本
    进程启动之后才出现（热装、并行测试），首次导入会假性 ModuleNotFoundError。
    """
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError:
        importlib.invalidate_caches()
        return importlib.import_module(module_name)


def _instantiate(star_cls: type, ctx: Any, cfg: Any) -> Any:
    """先按 (context, config) 试，插件若只接受 context 则退化。"""
    if cfg is not None:
        try:
            return star_cls(ctx, cfg)
        except TypeError:
            return star_cls(ctx)
    return star_cls(ctx)


def load_plugin(plugin_dir: Path) -> StarMetadata | None:
    dir_name = plugin_dir.name
    if not _validate_importable_name(dir_name):
        msg = f"目录名 {dir_name!r} 非合法 Python 标识符，请重命名"
        _failed[dir_name] = msg
        logger.error(f"[astrbot_compat] {msg}")
        return None
    if not (plugin_dir / "main.py").exists():
        return None

    meta_raw = _read_metadata(plugin_dir)
    if meta_raw is not None:
        _check_version(meta_raw, dir_name)
    _install_requirements(plugin_dir, dir_name)

    module_name = f"data.plugins.{dir_name}.main"
    try:
        mod = _import_plugin_module(module_name)
    except Exception as e:
        _failed[dir_name] = repr(e)
        logger.exception(f"[astrbot_compat] 插件 {dir_name} import 失败: {e}")
        return None

    md = star_map.get(module_name)
    if md is None:
        logger.warning(f"[astrbot_compat] 插件 {dir_name} 未继承 Star，已跳过")
        return None
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
    md.module = mod
    _apply_extra_metadata(md, meta_raw)

    # 注入到 Star 类，供插件通过 self.name / self.plugin_id 读取（与上游一致）
    with contextlib.suppress(AttributeError, TypeError):
        star_cls.name = md.name
        star_cls.author = md.author
        star_cls.version = md.version
        star_cls.desc = md.desc
        star_cls.plugin_id = md.plugin_id

    schema = load_conf_schema(plugin_dir)
    cfg = None
    if schema:
        try:
            cfg = AstrBotConfig(dir_name, schema)
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {dir_name} 配置初始化失败: {e}")
    md.config = cfg

    from .context import get_context

    try:
        inst = _instantiate(star_cls, get_context(), cfg)
    except Exception as e:
        _failed[dir_name] = repr(e)
        logger.exception(f"[astrbot_compat] 插件 {dir_name} 实例化失败: {e}")
        md.activated = False
        return None
    md.star_cls = inst

    # handler 重绑定：一律靠 module_name 查，绝不靠下标区间（避免 sort 串位）
    own_handlers = star_handlers_registry.get_handlers_by_module_name(module_name)
    for h in own_handlers:
        try:
            raw = h.handler
            if isinstance(raw, functools.partial):
                raw = raw.func
            h.handler = functools.partial(raw, inst)
        except Exception as e:
            logger.warning(
                f"[astrbot_compat] 插件 {dir_name} handler 重绑定失败 {h.handler_name}: {e}",
            )
    md.star_handler_full_names = [hh.handler_full_name for hh in own_handlers]

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
        with contextlib.suppress(OSError):
            plugins_dir.mkdir(parents=True, exist_ok=True)
        return []
    result: list[Path] = []
    try:
        entries = list(plugins_dir.iterdir())
    except OSError as e:
        logger.warning(f"[astrbot_compat] 插件目录 {plugins_dir} 扫描失败: {e}")
        return []
    for p in entries:
        if p.name.startswith((".", "_")):
            continue
        # 目录可能在扫描过程中被删除（并行测试、用户手动清理），is_dir 会抛 OSError
        try:
            if not p.is_dir():
                continue
        except OSError:
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

    with contextlib.suppress(Exception):
        from config.settings import PROJECT_ROOT

        root_str = str(PROJECT_ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)

    # data / data.plugins 是命名空间包，导入系统会缓存目录清单。若 data/plugins/
    # 在本进程启动后才出现新插件目录，不清缓存会 ModuleNotFoundError。
    importlib.invalidate_caches()

    # 让 StarTools.send_message 等类方法拿到上下文
    with contextlib.suppress(Exception):
        from .base import StarTools
        from .context import get_context

        StarTools.initialize(get_context())

    success: list[StarMetadata] = []
    for p in discover_plugins():
        try:
            md = load_plugin(p)
            if md is not None:
                success.append(md)
        except Exception as e:
            logger.exception(f"[astrbot_compat] 插件 {p.name} 加载异常: {e}")
            _failed[p.name] = repr(e)

    tail = f"（失败: {', '.join(_failed.keys())}）" if _failed else ""
    logger.info(
        f"[astrbot_compat] 插件加载完成：成功 {len(success)} 个，失败 {len(_failed)} 个{tail}",
    )
    return success


async def initialize_plugins() -> None:
    """调用每个插件的 initialize()，随后触发加载完成类钩子。"""
    from .context import _MODEL_DEPENDENT_PLUGINS
    from .exceptions import StellaCompatNotSupported
    from .pipeline import emit_hook

    for md in list(star_registry):
        if not md.activated or md.star_cls is None:
            continue
        try:
            await md.star_cls.initialize()
        except StellaCompatNotSupported as e:
            logger.warning(
                f"[astrbot_compat] 插件 {md.plugin_id} 依赖未实现能力 {e}，已标记为受限",
            )
            md.activated = False
            _MODEL_DEPENDENT_PLUGINS.add(md.plugin_id)
            _failed[_failed_key(md, md.root_dir_name)] = f"StellaCompatNotSupported: {e}"
        except Exception as e:
            logger.exception(f"[astrbot_compat] 插件 {md.plugin_id} initialize 失败: {e}")
            md.activated = False
            _failed[_failed_key(md, md.root_dir_name)] = repr(e)

    for md in list(star_registry):
        if md.activated:
            await emit_hook(EventType.OnPluginLoadedEvent, md)
    await emit_hook(EventType.OnAstrBotLoadedEvent)
    await emit_hook(EventType.OnPlatformLoadedEvent)


async def terminate_plugins() -> None:
    from .pipeline import emit_hook

    for md in reversed(list(star_registry)):
        if md.star_cls is None:
            continue
        try:
            await asyncio.wait_for(md.star_cls.terminate(), timeout=5.0)
        # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
        # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接、退化成「异常」分支。
        except asyncio.TimeoutError:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 超时")
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 异常: {e}")
        else:
            with contextlib.suppress(Exception):
                await emit_hook(EventType.OnPluginUnloadedEvent, md)

    with contextlib.suppress(Exception):
        from .context import get_context

        get_context().cancel_tasks()


def get_failed_plugins() -> dict[str, str]:
    return dict(_failed)
