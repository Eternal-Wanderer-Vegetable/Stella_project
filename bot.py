# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""机器人进程入口。

本模块是 Stella 机器人的启动引导（entrypoint）：负责初始化 NoneBot 框架、
注册 OneBot v11 适配器以连接 NapCat 等机器人端，并加载内置插件与项目中
以 TOML 声明的外部插件，最终启动事件循环。所有聊天处理能力均由 NoneBot
插件（plugins/）及各核心模块（core/、memory/）提供。
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

# 结构化 JSON 日志（供 GUI tail）：必须在任何插件加载/打日志之前注册
from core.logging_sink import setup_json_sink

setup_json_sink()

from astrbot_compat import install_shim

install_shim()

# 版本标记：记下「这份数据被当前版本跑过」。必须在启动早期做，且必须整段容错——
# 它只是给升级判定/破坏性变更提示提供依据（见 config/state.py），坏掉不该拦住启动。
import contextlib as _contextlib

with _contextlib.suppress(Exception):
    from config import PROJECT_ROOT as _PROJECT_ROOT
    from config import STELLA_HOME as _STELLA_HOME
    from config import state as _state
    from memory.schema import SCHEMA_VERSION as _SCHEMA_VERSION

    _TRANSITION = _state.record_run(
        _STELLA_HOME, _PROJECT_ROOT, schema_version=_SCHEMA_VERSION
    )
    if _TRANSITION.is_upgrade or _TRANSITION.is_downgrade:
        print(f"[stella] {_TRANSITION.describe()}", flush=True)

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_builtin_plugins("echo", "single_session")
nonebot.load_from_toml("pyproject.toml")

# --- 诊断：显式打印插件发现与加载结果（启动期必落盘） ---
# 这一段是排查「插件明明放进 data/plugins 却没被加载」的唯一手段：它把发现结果、
# 加载成败与失败原因同时写到 logging、nonebot logger、stdout 与 boot_debug.log 四处，
# 因为启动早期这四条通路里任意一条都可能还没就绪。每一步都单独 try/except：
# 诊断代码自己绝不能让 Bot 起不来。
import contextlib
import logging as _py_logging

from astrbot_compat import initialize_plugins, load_all_plugins, terminate_plugins

_diag_logger = _py_logging.getLogger("astrbot_compat.boot")
_diag_path = None
with contextlib.suppress(Exception):
    # 路径来自配置（默认 LOG_DIR/boot_debug.log）。config 在本行之前已经被
    # core.logging_sink 间接导入过，这里读它是安全的。
    from config.settings import BOOT_DIAG_LOG_PATH

    _diag_path = BOOT_DIAG_LOG_PATH
    _diag_path.parent.mkdir(parents=True, exist_ok=True)
    _diag_path.write_text("", encoding="utf-8")


def _diag_log(msg: str) -> None:
    with contextlib.suppress(Exception):
        _py_logging.getLogger("astrbot_compat.boot").warning(msg)
    with contextlib.suppress(Exception):
        import nonebot as _nb

        _nb.logger.warning(msg)
    with contextlib.suppress(Exception):
        print(msg, flush=True)
    with contextlib.suppress(Exception):
        if _diag_path is not None:
            with _diag_path.open("a", encoding="utf-8") as _f:
                _f.write(msg + "\n")


async def _bootstrap_astrbot_plugins() -> None:
    """在事件循环里装载 AstrBot 插件，随后跑它们的 initialize()。

    **不能在 import 期装**：上游 AstrBot 的插件加载整条链路是异步的，所以插件在
    ``__init__`` 里 ``asyncio.create_task(...)`` 起后台任务是官方插件的常规写法
    （astrbot_plugin_bilibili 就这么写）。import 期没有运行中的事件循环，那种插件
    会以 ``RuntimeError: no running event loop`` 加载失败——用户只能去改插件源码，
    与「现成插件不改源码直接跑」正相反。

    **必须是 async 函数**：同步启动钩子会被 nonebot 丢进线程池执行（``run_sync``），
    那里同样没有运行中的事件循环，等于没修。

    **必须注册在 _bootstrap_capabilities 之前**：启动钩子按注册顺序**串行**执行
    （``nonebot.internal.driver._lifespan.Lifespan._run_lifespan_func``），能力装配
    要读插件登记的工具表。
    """
    try:
        from astrbot_compat.loader import discover_plugins, unextracted_archives
        from config.settings import ASTRBOT_PLUGINS_DIR, PROJECT_ROOT

        _discovered = discover_plugins()
        _diag_log(f"[astrbot_compat][boot] PROJECT_ROOT={PROJECT_ROOT} ASTRBOT_PLUGINS_DIR={ASTRBOT_PLUGINS_DIR} discovered={[p.name for p in _discovered]}")
        _archives = unextracted_archives()
        if _archives:
            _diag_log(f"[astrbot_compat][boot] 插件目录里有未解压的压缩包 {_archives}：压缩包不会被加载，请解压成 <插件目录>/main.py 后重启")
    except Exception as _e:
        _discovered = []
        _diag_log(f"[astrbot_compat][boot] discover 异常: {_e}")

    try:
        _loaded = load_all_plugins()
        from astrbot_compat.loader import get_failed_plugins as _gfp
        from astrbot_compat.registry import star_handlers_registry, star_registry

        _diag_log(f"[astrbot_compat][boot] load_all_plugins -> success={len(_loaded)} failed={_gfp()} registry={len(star_registry)} handlers={len(star_handlers_registry)}")
        for _md in _loaded:
            _diag_log(f"[astrbot_compat][boot]   loaded {_md.plugin_id} dir={_md.root_dir_name} module={_md.module_path} handlers={len(_md.star_handler_full_names)}")
        if not _loaded:
            _diag_log(f"[astrbot_compat][boot] 没有加载到插件，discovered={[p.name for p in _discovered]} ASTRBOT_COMPAT_ENABLED={getattr(__import__('config.settings', fromlist=['ASTRBOT_COMPAT_ENABLED']), 'ASTRBOT_COMPAT_ENABLED', 'unknown')}")
    except Exception as _e:
        import traceback

        _diag_log(f"[astrbot_compat][boot] load_all_plugins 异常: {_e}\n{traceback.format_exc()}")

    await initialize_plugins()


driver.on_startup(_bootstrap_astrbot_plugins)
driver.on_shutdown(terminate_plugins)


async def _shutdown_renderer() -> None:
    """关掉 HTML 渲染用的 Chromium。

    不关会留下孤儿浏览器进程：playwright 启的是独立的 node + chromium 子进程，
    Python 退出不会带走它们，反复重启 Bot 就会攒出一堆几百 MB 的僵尸浏览器。
    """
    with contextlib.suppress(Exception):
        from astrbot_compat.render import shutdown as _render_shutdown

        await _render_shutdown()


driver.on_shutdown(_shutdown_renderer)

# Router 原型预热任务的引用。留着只为防 GC（见 _bootstrap_capabilities），跑完自动清空。
_WARMUP_TASK = None


async def _bootstrap_capabilities() -> None:
    """装配能力注册表：先读 config/capabilities/*.toml，再自动派生剩余插件工具。

    **必须注册在 initialize_plugins 之后**：``@llm_tool`` 装饰器在插件 import 期
    就登记了工具，但插件也可以在自己的 ``initialize()`` 里调 ``add_llm_tools``。
    先跑就会漏掉后者，而那表现为「插件装了但 Stella 路由不到它」——不报错，
    只是功能静默缺失。

    装配完在**后台**预热 Router 的原型向量：不预热的话首条被路由的消息要现场
    编码全部能力的语料（声明里每个能力 4~6 句），等待时间直接落在那个用户头上，
    而且外面套着 ROUTER_TIMEOUT。放后台是因为启动不该等它——预热失败的后果
    只是首条消息慢一点。

    装配前先给注册表装上**工具存活探针**（``install_tool_probe``）：声明可以指向一个
    没装的插件的工具（出厂自带的 ``config/capabilities/entertainment.toml`` 就是这样，
    等你装了 bilibili 插件才点亮），那种能力必须不进路由候选集，否则一个插件都没装的
    部署会把出厂声明当成自己的能力答出去。**必须在 ``bootstrap()`` 之前**，否则它回的
    ``routable`` 统计是装探针前的旧答案——而那行日志正是排查这件事时第一个看的东西。

    失败只告警：能力层是增量功能，装配不上的后果应该是「这次没有工具能力」，
    而不是 Bot 起不来。
    """
    try:
        from capability.adapters.astrbot import bootstrap, install_tool_probe

        if not install_tool_probe():
            _diag_log("[capability][boot] 工具存活探针未装上：本次不校验声明指向的工具存不存在")
        stats = bootstrap()
        _diag_log(f"[capability][boot] 能力装配完成: {stats}")
    except Exception as _e:
        import traceback

        _diag_log(f"[capability][boot] 能力装配失败（跳过）: {_e}\n{traceback.format_exc()}")
        return

    try:
        from config import CAPABILITY_ROUTER_ENABLED, ROUTER_SEMANTIC_ENABLED

        if not (CAPABILITY_ROUTER_ENABLED and ROUTER_SEMANTIC_ENABLED):
            return
        import asyncio as _asyncio

        from capability.router.semantic import warmup

        async def _warm() -> None:
            n = await warmup()
            _diag_log(f"[capability][boot] Router 原型预热完成: {n} 个")

        # 必须留引用：只有局部变量的话 task 可能在跑完前被 GC 掉（RUF006）
        global _WARMUP_TASK
        _WARMUP_TASK = _asyncio.create_task(_warm())
        _WARMUP_TASK.add_done_callback(lambda _t: globals().__setitem__("_WARMUP_TASK", None))
    except Exception as _e:
        _diag_log(f"[capability][boot] Router 原型预热未启动（跳过）: {_e}")


driver.on_startup(_bootstrap_capabilities)

SERVER = None  # 供 ai_gateway 哨兵触发时取 uvicorn Server 实例（Driver.run 不落地）


if __name__ == "__main__":
    import uvicorn

    cfg = driver.config
    # 照搬 nonebot/drivers/fastapi.py 的 LOGGING_CONFIG，保证日志链路一致
    _LOGGING_CONFIG = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "nonebot.log.LoguruHandler",
            },
        },
        "loggers": {
            "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.access": {
                "handlers": ["default"],
                "level": "INFO",
            },
        },
    }
    SERVER = uvicorn.Server(
        uvicorn.Config(
            nonebot.get_asgi(),
            host=str(cfg.host),
            port=cfg.port,
            log_config=_LOGGING_CONFIG,
            # 必须保留：uvicorn 默认无界等待在途连接关闭。NapCat 反向 WS 若不主动 close，
            # 优雅停止会挂死并退化到 CTRL_BREAK / 硬杀，在途记忆整合就丢了。重构勿删。
            timeout_graceful_shutdown=5,
        )
    )
    SERVER.run()
