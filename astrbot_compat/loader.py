# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""插件发现与加载器。"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import importlib
import importlib.machinery
import importlib.util
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

# 插件模块统一挂在这个包下面。目录名合法时就是它自己，不合法时是归一化后的名字。
_PKG_PREFIX = "data.plugins"
# 压缩包丢进插件目录是最常见的「装了却没被发现」，启动诊断要把它点出来
_ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz")

_loaded_dirs: set[str] = set()
_failed: dict[str, str] = {}
# 归一化后的包名 -> 提供它的插件目录，用来发现「两个目录归一化后同名」
_alias_dirs: dict[str, Path] = {}


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


def _sanitize_module_name(dir_name: str) -> str:
    """把目录名归一化成一个合法的模块名。

    最常见的不合法目录名来自 GitHub 的「Download ZIP」：解出来的目录叫
    `astrbot_plugin_x-master` / `-main`，而连字符不能出现在模块名里。上游
    AstrBot 是 git clone 装插件所以撞不到，手动装则几乎必然撞到。
    """
    # 逐字符判断能否出现在标识符里。用 "x" + ch 而不是 ch.isalnum()：既能放过
    # 中文等合法的非 ASCII 标识符字符，也能拦住 "²" 这类 isalnum 为真却非法的字符。
    body = "".join(ch if f"x{ch}".isidentifier() else "_" for ch in dir_name)
    name = body.strip("_") or "plugin"
    if not name.isidentifier():  # 首字符是数字
        name = f"p_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def _short_digest(text: str) -> str:
    """稳定的短摘要，仅用于给重名的模块名去重（与安全无关）。"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]


def _default_plugins_dir() -> Path:
    """``<程序目录>/data/plugins``——**能被 ``import data.plugins.X`` 找到的那个位置**。

    刻意锚在程序目录而不是 ``ASTRBOT_PLUGINS_DIR``：这个函数只服务
    ``_is_default_location``，而「能不能按包路径 import」取决于目录是否在 sys.path
    的项目根下，与用户把插件目录配到哪里无关。2026-08-27 起用户数据目录可能整体在
    程序目录之外（STELLA_HOME），那种情况下**所有**插件都只能按文件路径挂载。
    """
    try:
        from config.settings import PROJECT_ROOT

        return PROJECT_ROOT / "data" / "plugins"
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "plugins"


def _is_default_location(plugin_dir: Path) -> bool:
    """插件是否就放在 `<PROJECT_ROOT>/data/plugins/` 下。

    只有这里的插件才能靠 `import data.plugins.<目录名>` 找到；目录被配置到
    别处（ASTRBOT_PLUGINS_DIR）时必须按文件路径挂载。
    """
    try:
        return plugin_dir.parent.resolve() == _default_plugins_dir().resolve()
    except OSError:
        return False


def _pkg_name_is_taken(pkg: str, plugin_dir: Path) -> bool:
    """归一化后的模块名是否已经归别的插件目录所有。"""
    owner = _alias_dirs.get(pkg)
    if owner is not None and owner != plugin_dir:
        return True
    # 同一个插件目录下若真有一个叫这个名字的插件（如同时存在 foo 与 foo-main），
    # 这个模块名归它，归一化的那个换名字，免得互相顶替。
    sibling = plugin_dir.parent / pkg.rpartition(".")[2]
    try:
        return sibling != plugin_dir and sibling.is_dir()
    except OSError:
        return False


def _module_package(plugin_dir: Path) -> tuple[str, bool]:
    """算出插件包的模块名，以及是否需要按文件路径挂载。"""
    dir_name = plugin_dir.name
    if _validate_importable_name(dir_name) and _is_default_location(plugin_dir):
        return f"{_PKG_PREFIX}.{dir_name}", False
    base = _sanitize_module_name(dir_name)
    pkg = f"{_PKG_PREFIX}.{base}"
    if _pkg_name_is_taken(pkg, plugin_dir):
        pkg = f"{_PKG_PREFIX}.{base}_{_short_digest(dir_name)}"
    return pkg, True


def _mounted_at(mod: Any, plugin_dir: Path) -> bool:
    for raw in list(getattr(mod, "__path__", ()) or ()):
        with contextlib.suppress(OSError, ValueError, TypeError):
            if Path(raw).resolve() == plugin_dir.resolve():
                return True
    return False


def _mount_plugin_package(pkg: str, plugin_dir: Path) -> Any:
    """把插件目录挂成 `pkg` 这个包，让 main.py 与插件内部的相对导入都能工作。

    目录名不合法（或插件目录被配置到项目外）时，`import data.plugins.<目录名>`
    这条路根本走不通，只能自己按文件路径建包：`__path__` 指回真实目录，插件里的
    `from .x import y` / `from ..y import z` 就照常由导入系统解析。
    """
    mounted = sys.modules.get(pkg)
    if mounted is not None:
        if not _mounted_at(mounted, plugin_dir):
            raise ImportError(
                f"模块名 {pkg} 已被 {getattr(mounted, '__path__', None)} 占用，"
                f"请重命名插件目录 {plugin_dir.name}",
            )
        _alias_dirs[pkg] = plugin_dir
        return mounted

    # 父包（命名空间包）先就位，`from data.plugins import <name>` 这种写法才成立
    with contextlib.suppress(ImportError):
        importlib.import_module(_PKG_PREFIX)

    search = [str(plugin_dir.resolve())]
    init = plugin_dir / "__init__.py"
    if init.is_file():
        spec = importlib.util.spec_from_file_location(
            pkg,
            init,
            submodule_search_locations=search,
        )
    else:
        # 没有 __init__.py 的插件目录：建个只有 __path__ 的空包，不执行任何代码
        spec = importlib.machinery.ModuleSpec(pkg, None, is_package=True)
        spec.submodule_search_locations = search
    if spec is None:
        raise ImportError(f"无法为插件目录 {plugin_dir} 构造模块 {pkg}")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg] = mod
    _alias_dirs[pkg] = plugin_dir
    if spec.loader is not None:
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            # 半初始化的包留在 sys.modules 里会让下次加载拿到空壳
            sys.modules.pop(pkg, None)
            _alias_dirs.pop(pkg, None)
            raise
    parent = sys.modules.get(_PKG_PREFIX)
    if parent is not None:
        setattr(parent, pkg.rpartition(".")[2], mod)
    return mod


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


def _import_failure_reason(exc: Exception, plugin_dir: Path, pkg: str) -> str:
    """把 import 失败翻译成一句能照着做的话。

    插件缺第三方依赖是最常见的加载失败（AstrBot 核心自带 aiohttp 等库，插件
    往往不写进自己的 requirements.txt），而 `ModuleNotFoundError("No module
    named 'aiohttp'")` 这种 repr 落到日志里，用户不知道下一步该干什么。
    """
    if not isinstance(exc, ModuleNotFoundError):
        return repr(exc)
    missing = exc.name or ""
    # 缺的是插件自己的模块：那是插件内部的导入写错了，不是缺依赖
    if not missing or missing == pkg or missing.startswith(f"{pkg}."):
        return repr(exc)
    req = plugin_dir / "requirements.txt"
    if req.is_file():
        return f"缺少依赖模块 {missing!r}；执行 pip install -r \"{req}\" 装齐插件依赖后重启"
    return (
        f"缺少依赖模块 {missing!r}；执行 pip install {missing} 后重启"
        f"（PyPI 包名可能与模块名不同，以插件文档为准）"
    )


def _instantiate_failure_reason(exc: Exception) -> str:
    """插件构造失败的说明。缺事件循环单独说，因为它只可能是调用方的问题。"""
    if isinstance(exc, RuntimeError) and "no running event loop" in str(exc):
        return (
            f"插件构造函数需要运行中的事件循环（如 asyncio.create_task）：{exc!r}。"
            f"load_all_plugins() 必须在事件循环内调用，见 bot.py 的启动钩子"
        )
    return repr(exc)


def load_plugin(plugin_dir: Path) -> StarMetadata | None:
    dir_name = plugin_dir.name
    if not (plugin_dir / "main.py").exists():
        return None

    pkg, needs_mount = _module_package(plugin_dir)
    if needs_mount:
        try:
            _mount_plugin_package(pkg, plugin_dir)
        except Exception as e:
            _failed[dir_name] = repr(e)
            logger.exception(f"[astrbot_compat] 插件目录 {dir_name} 挂载为 {pkg} 失败: {e}")
            return None
        if pkg != f"{_PKG_PREFIX}.{dir_name}":
            logger.info(
                f"[astrbot_compat] 目录名 {dir_name!r} 不是合法模块名"
                f"（GitHub ZIP 常见的 -master/-main 后缀即是），已按 {pkg} 加载",
            )

    meta_raw = _read_metadata(plugin_dir)
    if meta_raw is not None:
        _check_version(meta_raw, dir_name)
    _install_requirements(plugin_dir, dir_name)

    module_name = f"{pkg}.main"
    try:
        mod = _import_plugin_module(module_name)
    except Exception as e:
        _failed[dir_name] = _import_failure_reason(e, plugin_dir, pkg)
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
        _failed[dir_name] = _instantiate_failure_reason(e)
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


def _plugins_dir() -> Path:
    try:
        from config.settings import ASTRBOT_PLUGINS_DIR

        return ASTRBOT_PLUGINS_DIR
    except Exception:
        return _default_plugins_dir()


def discover_plugins() -> list[Path]:
    plugins_dir = _plugins_dir()
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


def unextracted_archives() -> list[str]:
    """插件目录里没解压的压缩包文件名。

    「插件放进去了却 discovered=[]」十次有九次是这个：下载下来的 zip 直接丢进
    data/plugins/ 而没有解压。启动诊断把它打出来，用户不用猜。
    """
    plugins_dir = _plugins_dir()
    found: list[str] = []
    try:
        entries = list(plugins_dir.iterdir())
    except OSError:
        return found
    for p in entries:
        if p.suffix.lower() not in _ARCHIVE_SUFFIXES:
            continue
        try:
            if p.is_file():
                found.append(p.name)
        except OSError:
            continue
    return sorted(found)


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
