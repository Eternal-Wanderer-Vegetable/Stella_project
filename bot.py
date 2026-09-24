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

# WebUI「无壳自重启」的接任侧：若本进程由上一任 Bot 派生（webui 重启按钮），
# 上一任还占着服务端口，必须等它真正退出再继续初始化。必须在任何重活之前；
# 超时照样继续（端口冲突会留下明确错误，好过无声卡死）。见 core/self_restart.py。
try:
    from core.self_restart import wait_for_parent_exit

    if wait_for_parent_exit():
        print("[stella] 接任启动：上一任进程已退出，继续初始化", flush=True)
except Exception as _e:  # 自重启等待绝不能拦住正常启动
    print(f"[stella] 接任等待跳过：{_e}", flush=True)

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

# 某些打包后的 NoneBot 启动路径会在插件 import 期尚未暴露最终 ASGI app。
# 插件侧已经会尽早尝试注册，这里再在所有插件加载完成后补一次，确保 GUI 的
# 启动探测不会因 `/stella/status` 缺失而误判；setup_status_api 本身是幂等的。
# 导入的是模块而非函数：下方 setup_webui 要引用 status_api.collect_status。
try:
    from plugins.bot_main import status_api
except ImportError:
    from stella_project.plugins.bot_main import status_api

status_api.setup_status_api()

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


async def _shutdown_mcp_runtime() -> None:
    """MCP 收尾（方案 §7.8 关闭顺序）：停接受新调用 → 取消在途调用/后台任务 →
    关闭 HTTP 会话 → 终止 stdio 子进程。

    **必须先于 terminate_plugins 执行**（注册顺序即执行顺序）：插件的工具 handler
    还在时先把外部边界收掉，避免插件停机过程中又有新的 MCP 调用发出去。
    """
    try:
        from capability.adapters import mcp as mcp_adapter

        await mcp_adapter.close_mcp_runtime()
    except Exception as _e:
        _diag_log(f"[mcp][shutdown] MCP 层关闭异常（跳过）: {_e}")


driver.on_startup(_bootstrap_astrbot_plugins)
driver.on_shutdown(_shutdown_mcp_runtime)
driver.on_shutdown(terminate_plugins)


async def _bootstrap_local_embedding() -> None:
    """让 OneClick 在 LM Studio 不可用时先准备本地 embedding 服务。"""
    try:
        from config import MEMORY_EMBEDDING_BASE_URL, MEMORY_EMBEDDING_ENABLED

        if not MEMORY_EMBEDDING_ENABLED:
            return
        import asyncio

        from deploy.llama import ensure_local_embedding_service

        result = await asyncio.to_thread(
            ensure_local_embedding_service,
            preferred_url=MEMORY_EMBEDDING_BASE_URL,
        )
        if result.get("ok"):
            _diag_log(
                "[embedding][boot] "
                f"source={result.get('source', 'unknown')} "
                f"endpoint={result.get('endpoint', '')}"
            )
        else:
            _diag_log(
                f"[embedding][boot] 本地 fallback 未就绪: "
                f"{result.get('message', '')}"
            )
    except Exception as exc:
        _diag_log(f"[embedding][boot] 启动 embedding fallback 失败（跳过）: {exc}")


async def _shutdown_local_embedding() -> None:
    """只停止当前 Stella 进程自己启动的本地 llama 服务。"""
    try:
        import asyncio

        from deploy.llama import stop_local_embedding_service

        result = await asyncio.to_thread(stop_local_embedding_service)
        if not result.get("ok"):
            _diag_log(
                f"[embedding][shutdown] 停止本地服务失败: "
                f"{result.get('message', '')}"
            )
    except Exception as exc:
        _diag_log(f"[embedding][shutdown] 停止 embedding fallback 失败（跳过）: {exc}")


driver.on_startup(_bootstrap_local_embedding)
driver.on_shutdown(_shutdown_local_embedding)


async def _shutdown_renderer() -> None:
    """关掉 HTML 渲染用的 Chromium。

    不关会留下孤儿浏览器进程：playwright 启的是独立的 node + chromium 子进程，
    Python 退出不会带走它们，反复重启 Bot 就会攒出一堆几百 MB 的僵尸浏览器。
    """
    with contextlib.suppress(Exception):
        from astrbot_compat.render import shutdown as _render_shutdown

        await _render_shutdown()


driver.on_shutdown(_shutdown_renderer)


async def _shutdown_clear_pid() -> None:
    """优雅退出时清掉自己的 PID/manifest 记录（仅当记录指向本进程）。

    deploy stop 会清，但 WebUI 重启、终端 Ctrl+C 这类不经 deploy 的退出
    不会——残留的 PID 号随后被系统复用给无关进程，``deploy start`` 就会
    误判「实例已在运行」而永远拒启（2026-09-24 实测：撞上 QQ 的
    crashpad_handler）。
    """
    import os

    try:
        from deploy import process as _deploy_process

        if _deploy_process.read_pid() == os.getpid():
            _deploy_process.clear_pid()
            _deploy_process.clear_manifest()
    except Exception:
        pass


driver.on_shutdown(_shutdown_clear_pid)

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

    MCP（``MCP_ENABLED=true`` 时）：先启动 Manager（连接 + 初始发现），再装
    Provider Runtime，最后才 bootstrap——顺序错了 ``routable`` 统计就会漏掉 MCP
    Provider 的真实可用性（方案 §7.8）。MCP 启动失败只告警：它坏掉的后果是
    「MCP 工具这轮不可用」，Bot 与其余能力照常。

    失败只告警：能力层是增量功能，装配不上的后果应该是「这次没有工具能力」，
    而不是 Bot 起不来。
    """
    # MCP 先行（方案 §7.8 的启动顺序）：Manager 起来 → Runtime 接线 → bootstrap。
    # 全程容错：MCP 是增量能力，整层失败不能拖垮 capability 装配。
    try:
        from capability.adapters import mcp as mcp_adapter

        mcp_adapter.reset_mcp_sync()
        states = await mcp_adapter.start_mcp_runtime()
        if states:
            _diag_log(f"[mcp][boot] MCP Server 初始状态: {states}")
        mcp_adapter.install_mcp_runtime()
        mcp_adapter.sync_mcp_providers()
    except Exception as _e:
        import traceback

        _diag_log(f"[mcp][boot] MCP 层启动失败（跳过）: {_e}\n{traceback.format_exc()}")

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

    # 知识库能力（KNOWLEDGE_ENABLED 时）：native backend + knowledge.search 声明。
    # 与 MCP 同性质——增量能力，装配失败只告警，Bot 照常起。
    try:
        from capability.adapters.knowledge import install_knowledge_capability

        _diag_log(f"[knowledge][boot] 知识库能力装配: {install_knowledge_capability()}")
    except Exception as _e:
        import traceback

        _diag_log(f"[knowledge][boot] 知识库能力装配失败（跳过）: {_e}\n{traceback.format_exc()}")

    # Skills 运行时（SKILLS_ENABLED 时，plan §6.5）：插件能力准备之后、
    # Router 预热之前建立 catalog 快照。失败只告警——Skills 是增量功能，
    # 装配不上的后果是「这层不存在」，绝不是 Bot 起不来。
    try:
        from config import SKILLS_ENABLED as _SKILLS_ON
        from skills import runtime as _skills_runtime

        if _SKILLS_ON:
            _rt = _skills_runtime.build_runtime()
            if _rt is not None:
                _skills_runtime.install(_rt)
                _diag_log(f"[skills][boot] 技能运行时装配: {_rt.status()}")
        else:
            _diag_log("[skills][boot] SKILLS_ENABLED=false，Skills 层未装配")
    except Exception as _e:
        import traceback

        _diag_log(f"[skills][boot] Skills 运行时装配失败（跳过）: {_e}\n{traceback.format_exc()}")

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

# WebUI（v2 面板）：必须是**最后一个** startup 钩子——挂载发生在 lifespan
# 末尾，SPA catch-all（Mount "/"）因此排在 OneBot WS 与 /stella/status 之后。
# Starlette 按注册顺序匹配路由，顺序即安全边界（tests/webui/test_webui_mount.py
# 钉死四类路径共存）。挂载失败只告警不拖垮 Bot（与 status_api 同一取向）。
try:
    from webui.mount import setup_webui
except ImportError:
    _diag_log("[webui][boot] webui 包缺失（依赖未装齐或打包不全），管理面未启用")
else:
    # 宿主注入 v1 状态聚合（webui 不反向 import bot_main，依赖方向见
    # webui/status_source.py）；status_api 已在上方完成双路径导入
    setup_webui(status_source=status_api.collect_status)

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
