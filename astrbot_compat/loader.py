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
import shutil
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
# 被热重载摘下来、但新代码没装回去的插件：目录名 -> 插件目录。
# 存在的理由是一次**必然会发生**的操作序列：改代码 → 重载 → 新代码有语法错 → 装不回来。
# 那之后插件已经不在 star_registry 里了，只按「已加载插件」找的话，用户改完错字反而
# 没法再重载——只能重启，而重启正是热重载要省掉的那件事。
_detached: dict[str, Path] = {}

# 热重载**清不掉**的东西。必须出现在重载回复里而不只是文档里：用户看到「重载成功」
# 之后会假定进程状态与重启等价，而这几类残留恰好都不报错，只表现为「改了代码、
# 重载了、旧行为还在」。定位是调试便利，不等于重启。
HOT_RELOAD_CAVEAT = (
    "重载清不掉：裸 asyncio.create_task 起的任务（要走 context.register_task）、"
    "插件起的线程、注册的全局钩子、monkeypatch、第三方库的模块级状态、"
    "已被别处持有的旧实例引用。怀疑状态不干净就重启。"
)

# 群内触发热重载的说法。放在这里而不是 ai_gateway：触发词与它触发的东西写在一处，
# 而且 ai_gateway 的另外两个同优先级 handler（toggle / capability）要拿它做机械互斥。
RELOAD_KEYWORDS = ("重载插件", "重新加载插件", "重载一下插件")
# 插件名的边界字符：空白与常见标点。中文没有词边界，用户会顺手写「重载插件 foo，谢谢」，
# 只按空白切的话插件名会变成「foo，谢谢」——然后报「找不到插件」，而人看不出差在哪。
_RELOAD_SEPARATORS = frozenset(" \t\r\n　,，。．.、;；:：!！?？~～()（）[]【】\"'“”‘’")
# 重载后重算原型向量的后台任务。必须留引用：只有局部变量的话 task 可能在跑完前
# 被 GC 掉（RUF006）。
_WARMUP_TASKS: set[asyncio.Task] = set()


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


# ---------------------------------------------------------------------------
# 热重载（调试用，默认关闭）
#
# 定位是**调试便利，不等于重启**。它能收回 handler、工具、能力声明与 sys.modules
# 里的模块；收不回的那几类见 HOT_RELOAD_CAVEAT，且必须一起说给用户听。
# ---------------------------------------------------------------------------


def parse_reload_command(text: str) -> str | None:
    """把「@Stella 重载插件 astrbot_plugin_x」解析成插件名；不是重载命令返回 None。

    与 ``capability.inventory.is_query_text`` 同一个用意：三个 handler
    （toggle / capability / reload）在 ai_gateway 里同优先级且都 ``block=True``，
    NoneBot 会把它们一起跑，所以互斥必须是**机械的**——由一个函数说了算，而不是
    指望三张词表刚好不重叠。判据放在这里，ai_gateway 启动期再拿它跑一遍自检。
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    for phrase in RELOAD_KEYWORDS:
        index = stripped.find(phrase)
        if index < 0:
            continue
        rest = stripped[index + len(phrase) :]
        # 先吃掉名字前的分隔符，再一路读到下一个分隔符为止。
        # 「重载插件 foo 顺便安静一下」只取 foo，剩下的话不该被当成插件名的一部分。
        start = 0
        while start < len(rest) and rest[start] in _RELOAD_SEPARATORS:
            start += 1
        end = start
        while end < len(rest) and rest[end] not in _RELOAD_SEPARATORS:
            end += 1
        name = rest[start:end]
        if name:
            return name
    return None


def hot_reload_enabled() -> bool:
    """热重载总开关。读不到配置时按**关闭**处理（宁关勿开）。"""
    try:
        from config.settings import ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED

        return bool(ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED)
    except Exception:
        return False


def find_loaded_plugin(name: str) -> StarMetadata | None:
    """按目录名找已加载插件；找不到再按插件显示名找一次。

    两条都认是因为触发面是**人在群里打字**：用户看到的是 `boot_debug.log` 里的
    目录名，也可能是「你能做什么」里列出的插件名，逼他分清这两者没有意义。
    目录名优先——它唯一，显示名不保证。
    """
    target = (name or "").strip()
    if not target:
        return None
    for md in list(star_registry):
        if md.root_dir_name == target:
            return md
    for md in list(star_registry):
        if md.name == target:
            return md
    return None


def _plugin_package(md: StarMetadata) -> str:
    """插件包路径：``data.plugins.foo.main`` → ``data.plugins.foo``。"""
    return md.module_path.rpartition(".")[0]


def plugin_handlers(md: StarMetadata) -> list:
    """这个插件登记的全部 handler，**含定义在子模块里的**。

    只按 ``md.module_path`` 精确匹配是不够的：handler 完全可以定义在插件包的子模块
    （`data.plugins.foo.commands`）里，`base.py::_resolve_plugin_dir_name` 正为此做了
    前缀匹配。漏掉它们的后果是重载后旧 handler 还挂在注册表上，同一条指令被响应两次。

    公开而不是私有：``capability.inventory`` 要按插件分组列出指令与工具，而
    「哪些 handler 属于这个插件」的判据只能有一处，两处各写一遍必然漂移。
    """
    pkg = _plugin_package(md)
    prefix = f"{pkg}." if pkg else ""
    return [
        h
        for h in list(star_handlers_registry)
        if h.handler_module_path == md.module_path
        or (prefix and h.handler_module_path.startswith(prefix))
    ]


def tool_names_of(handlers: list) -> list[str]:
    """这批 handler 里注册的函数工具名。

    取名规则照 ``filters._register_llm_tool``：``@llm_tool("别名")`` 会把别名写进
    ``extras_configs['tool_name']``，没写别名时工具名就是函数名。工具表本身不记
    「谁注册了我」，所以「这个工具属于哪个插件」只能从 handler 侧反推——热重载靠它
    摘工具，插件清单靠它分组，两处共用这一份。
    """
    names: list[str] = []
    for h in handlers:
        if h.event_type != EventType.OnCallingFuncToolEvent:
            continue
        name = str(h.extras_configs.get("tool_name") or h.handler_name or "")
        if name and name not in names:
            names.append(name)
    return names


def _release_capabilities(tool_names: list[str]) -> int:
    """摘掉这些工具所属的能力并释放归属，返回摘了几条能力。

    **必须同时清 ``_claimed_tools``**（``registry.unregister`` 已经这么做了，这里对
    没有能力却仍被认领的工具再补一刀）：归属表不清的话，工具会永远被一个已不存在的
    能力认领着，而 ``_claim`` 是先到先得，于是重载后插件重新注册的声明**抢不到自己的
    工具**——不报错，只表现为「重载完就路由不到了」。

    能力层的重建交给随后的 ``bootstrap()``：用户层/出厂层的声明可能把本插件的工具和
    别的工具编在同一条能力里，那条能力整体被摘掉之后要靠三层重跑才补得回来。
    """
    if not tool_names:
        return 0
    try:
        from capability.registry import registry as capability_registry
    except Exception as e:  # pragma: no cover - capability 层不可用时降级
        logger.warning(f"[astrbot_compat] 能力注册表不可用，跳过能力摘除: {e}")
        return 0

    removed = 0
    for name in tool_names:
        owner = capability_registry.claimed_by(name)
        if owner and capability_registry.unregister(owner):
            removed += 1
        capability_registry.release_tool(name)
    return removed


def _purge_modules(pkg: str) -> int:
    """把插件包及其全部子模块从 ``sys.modules`` 里摘掉，返回摘了几个。

    不摘的话 ``import`` 直接命中缓存，重载等于什么都没做——这是热重载最容易「看起来
    成功了其实没生效」的一步。
    """
    if not pkg:
        return 0
    doomed = [m for m in list(sys.modules) if m == pkg or m.startswith(f"{pkg}.")]
    for m in doomed:
        sys.modules.pop(m, None)
    return len(doomed)


def _purge_bytecode_cache(plugin_dir: Path) -> int:
    """删掉插件目录下的 ``__pycache__``，返回删了几个目录。

    不删的话热重载有一个**静默失效**的窗口：``.pyc`` 的有效性只按源文件的
    「mtime 整秒 + 字节数」判定，所以「同一秒内改了一个字符」这种编辑
    （调试时改常量、改开关，恰恰最常见）会命中旧字节码——重载报成功，跑的还是旧代码。
    这正是热重载最难自证的一类问题，为一次几毫秒的目录删除不值得留着。

    删不掉只记 debug：那时最坏也就是退回上面那个窗口，不该让重载失败。
    """
    removed = 0
    try:
        caches = [p for p in plugin_dir.rglob("__pycache__") if p.is_dir()]
    except OSError:
        return 0
    for cache in caches:
        try:
            shutil.rmtree(cache)
        except OSError as e:
            logger.debug(f"[astrbot_compat] 清理 {cache} 失败（跳过）: {e}")
        else:
            removed += 1
    return removed


def _detach_plugin(md: StarMetadata, plugin_dir: Path) -> dict[str, int]:
    """把一个插件从各处注册表上完整摘下来。返回各项计数（供日志与回复）。

    顺序有讲究：先摘 handler（工具名要从它们反推），再摘工具与能力，最后摘模块与
    元数据。反过来的话工具名就无从取得了。
    """
    handlers = plugin_handlers(md)
    tool_names = tool_names_of(handlers)

    for h in handlers:
        with contextlib.suppress(Exception):
            star_handlers_registry.remove(h)

    with contextlib.suppress(Exception):
        from .llm.tool import llm_tools

        for name in tool_names:
            llm_tools.remove_tool(name)

    capabilities = _release_capabilities(tool_names)

    pkg = _plugin_package(md)
    modules = _purge_modules(pkg)
    caches = _purge_bytecode_cache(plugin_dir)

    for path, meta in list(star_map.items()):
        if meta is md or path == md.module_path or (pkg and path.startswith(f"{pkg}.")):
            star_map.pop(path, None)
    if md in star_registry:
        star_registry.remove(md)

    _loaded_dirs.discard(md.root_dir_name)
    _failed.pop(md.root_dir_name, None)
    if md.root_dir_name:
        # 记住「它原本在哪」，好让新代码装不回来时还能按目录名再试一次（见 _detached）
        _detached[md.root_dir_name] = plugin_dir
    for alias, owner_dir in list(_alias_dirs.items()):
        with contextlib.suppress(OSError):
            if owner_dir == plugin_dir or owner_dir.resolve() == plugin_dir.resolve():
                _alias_dirs.pop(alias, None)

    return {
        "handlers": len(handlers),
        "tools": len(tool_names),
        "capabilities": capabilities,
        "modules": modules,
        "pycache": caches,
    }


def _plugin_dir_of(md: StarMetadata) -> Path | None:
    """插件在磁盘上的目录。由模块 ``__file__`` 反推，拼路径只作兜底。

    反推而不是拼 ``ASTRBOT_PLUGINS_DIR / root_dir_name``：目录名不合法或插件目录被
    配置到项目外时插件是按文件路径挂载的，拼出来的路径不一定对（而这一步错了会
    重载出一个**别的**插件）。
    """
    main_file = getattr(md.module, "__file__", None)
    if main_file:
        with contextlib.suppress(OSError):
            return Path(main_file).resolve().parent
    if md.root_dir_name:
        candidate = _plugins_dir() / md.root_dir_name
        with contextlib.suppress(OSError):
            if candidate.is_dir():
                return candidate
    return None


async def _terminate_one(md: StarMetadata) -> None:
    """跑插件的 terminate（5s 超时），随后取消它登记过的后台任务。

    异常与超时都只告警不中断：**卸载必须继续走完**。半途停下会留下一个既没摘干净、
    也没重新装上的状态——比彻底不重载更糟，因为那时 handler 已经摘了一半。
    """
    if md.star_cls is not None:
        try:
            await asyncio.wait_for(md.star_cls.terminate(), timeout=5.0)
        # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
        # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接。
        except asyncio.TimeoutError:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 超时，继续卸载")
        except Exception as e:
            logger.warning(f"[astrbot_compat] 插件 {md.plugin_id} terminate 异常，继续卸载: {e}")
        else:
            with contextlib.suppress(Exception):
                from .pipeline import emit_hook

                await emit_hook(EventType.OnPluginUnloadedEvent, md)

    with contextlib.suppress(Exception):
        from .context import get_context

        pkg = _plugin_package(md)
        cancelled = get_context().cancel_tasks(pkg)
        if cancelled:
            logger.info(f"[astrbot_compat] 插件 {md.root_dir_name} 已取消 {cancelled} 个登记任务")


def _rebuild_capabilities() -> dict[str, int]:
    """重跑三层声明 + 自动派生，并让 Router 的原型缓存跟着失效。

    走 ``bootstrap()`` 整条重跑而不是只补这一个插件的那层：能力是**跨插件**的（一条
    用户声明完全可以把两个插件的工具编在一起），只补一层补不回被整条摘掉的那些。
    ``register`` 是合并语义、``skip_claimed`` 只跳已被认领的，所以重跑是幂等的。

    ``registry.version`` 在这个过程里必然自增，``router/semantic`` 的原型缓存据此
    自动失效（已有机制），随后的 ``warmup()`` 只是把重算挪到后台。
    """
    from capability.adapters.astrbot import bootstrap

    return bootstrap()


def _schedule_warmup() -> None:
    """后台重算 Router 原型向量。失败只是首条消息多等一会儿，绝不影响重载结论。"""
    try:
        from config.settings import CAPABILITY_ROUTER_ENABLED, ROUTER_SEMANTIC_ENABLED

        if not (CAPABILITY_ROUTER_ENABLED and ROUTER_SEMANTIC_ENABLED):
            return
        from capability.router.semantic import warmup

        task = asyncio.ensure_future(warmup())
        # 必须留引用：只有局部变量的话 task 可能在跑完前被 GC 掉（RUF006）
        _WARMUP_TASKS.add(task)
        task.add_done_callback(_WARMUP_TASKS.discard)
    except Exception as e:
        logger.debug(f"[astrbot_compat] 重载后原型预热未启动（跳过）: {e}")


async def reload_plugin(dir_name: str) -> StarMetadata | None:
    """重新加载一个插件。失败返回 ``None``，原因进 ``get_failed_plugins()``。

    步骤：``terminate`` → 摘 handler / 工具 / 能力 / 模块 / 字节码 → 重新 ``load_plugin``
    + ``initialize`` → 重跑能力装配 + 后台预热。

    也接受**上一次重载没装回来**的插件（新代码有语法错时会落到这个状态）：那时前半段
    已经没什么可摘的，直接从加载开始。见 ``_detached``。

    **这不等于重启。** 清不掉的东西见 ``HOT_RELOAD_CAVEAT``，调用方有义务把那段话
    转达给触发重载的人。受 ``ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED`` 控制（默认关闭）：
    它会执行插件代码的重新 import，比只读查询大一档，不该在没人明确打开时可用。
    """
    if not hot_reload_enabled():
        logger.warning(
            "[astrbot_compat] 热重载未启用（ASTRBOT_PLUGIN_HOT_RELOAD_ENABLED=false），已拒绝",
        )
        return None

    md = find_loaded_plugin(dir_name)
    if md is not None:
        key = md.root_dir_name or dir_name
        plugin_dir = _plugin_dir_of(md)
    else:
        key = (dir_name or "").strip()
        plugin_dir = _detached.get(key)
        if plugin_dir is None:
            logger.warning(f"[astrbot_compat] 找不到已加载的插件 {dir_name!r}，无法重载")
            return None
        logger.info(f"[astrbot_compat] 插件 {key} 上次没装回来，这次从加载开始")

    if plugin_dir is None or not plugin_dir.is_dir():
        _failed[key] = f"插件目录不存在或不可读: {plugin_dir}"
        logger.warning(f"[astrbot_compat] 插件 {key} 的目录不可用，无法重载: {plugin_dir}")
        return None

    logger.info(f"[astrbot_compat] 开始重载插件 {key}（{plugin_dir}）")
    if md is not None:
        await _terminate_one(md)
        detached = _detach_plugin(md, plugin_dir)
        logger.info(f"[astrbot_compat] 插件 {key} 已卸载: {detached}")
    else:
        # 半路重来：模块与字节码上次已经摘过，但改完源码后字节码可能又被写回来了。
        # 包名走 _module_package 而不是拼目录名：目录名不合法时插件是按文件路径挂载的
        # （GitHub ZIP 的 -master 后缀就是），拼出来的名字对不上。
        _purge_modules(_module_package(plugin_dir)[0])
        _purge_bytecode_cache(plugin_dir)

    # 目录清单可能在本进程启动之后变过（改文件、加子模块），不清缓存会 import 到旧的
    importlib.invalidate_caches()
    try:
        fresh = load_plugin(plugin_dir)
    except Exception as e:
        _failed[key] = repr(e)
        logger.exception(f"[astrbot_compat] 插件 {key} 重载时加载失败: {e}")
        return None
    if fresh is None:
        # load_plugin 已经把原因写进 _failed（import 失败 / 没有 Star 子类 / 实例化失败）
        _failed.setdefault(key, "重新加载失败，原因见启动日志")
        logger.warning(f"[astrbot_compat] 插件 {key} 重载失败: {_failed.get(key)}")
        return None

    try:
        if fresh.star_cls is not None:
            await fresh.star_cls.initialize()
    except Exception as e:
        # initialize 失败的插件在上游是「标记为未激活」，不是「回滚到旧版本」——
        # 旧模块已经从 sys.modules 里摘掉了，也没有可回滚的东西。照 initialize_plugins
        # 的处理：标记失败并让它不参与分发，用户改完代码可以再重载一次。
        fresh.activated = False
        _failed[key] = repr(e)
        logger.exception(f"[astrbot_compat] 插件 {key} 重载后 initialize 失败: {e}")
        return None

    stats = _rebuild_capabilities()
    _schedule_warmup()
    # 装回来了，「上次没装回来」的记录就该销掉
    _detached.pop(key, None)
    if fresh.root_dir_name:
        _detached.pop(fresh.root_dir_name, None)
    logger.info(f"[astrbot_compat] 插件 {key} 重载完成，能力装配: {stats}")
    return fresh


def plugin_source_stamp(md: StarMetadata) -> float:
    """插件目录里源码与声明的最新 mtime。读不到时返回 0。

    只看 ``*.py`` 与 ``capability.toml``：这两类改了才需要重载，而插件的数据目录、
    渲染缓存、日志会一直在变，把它们算进来等于每轮都重载一次。
    """
    plugin_dir = _plugin_dir_of(md)
    if plugin_dir is None:
        return 0.0
    newest = 0.0
    try:
        for path in plugin_dir.rglob("*"):
            if path.name != "capability.toml" and path.suffix != ".py":
                continue
            with contextlib.suppress(OSError):
                newest = max(newest, path.stat().st_mtime)
    except OSError:
        return 0.0
    return newest


def plugin_source_stamps() -> dict[str, float]:
    """全部已加载插件的源码 mtime 快照，供 watch 模式比对。"""
    return {
        md.root_dir_name: plugin_source_stamp(md)
        for md in list(star_registry)
        if md.root_dir_name
    }
