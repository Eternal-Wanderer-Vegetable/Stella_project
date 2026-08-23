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

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_builtin_plugins("echo", "single_session")
nonebot.load_from_toml("pyproject.toml")

from astrbot_compat import initialize_plugins, load_all_plugins, terminate_plugins

# --- 诊断：显式打印插件发现与加载结果（启动期必落盘） ---
import logging as _py_logging

_diag_logger = _py_logging.getLogger("astrbot_compat.boot")
_diag_path = None
try:
    from pathlib import Path as _P

    _diag_path = _P(__file__).resolve().parent / "boot_debug.log"
    _diag_path.write_text("", encoding="utf-8")
except Exception:
    pass

def _diag_log(msg: str) -> None:
    try:
        _py_logging.getLogger("astrbot_compat.boot").warning(msg)
    except Exception:
        pass
    try:
        import nonebot as _nb

        _nb.logger.warning(msg)
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass
    try:
        if _diag_path is not None:
            with open(_diag_path, "a", encoding="utf-8") as _f:
                _f.write(msg + "\n")
    except Exception:
        pass

try:
    from astrbot_compat.loader import discover_plugins, get_failed_plugins
    from config.settings import ASTRBOT_PLUGINS_DIR, PROJECT_ROOT

    _discovered = discover_plugins()
    _diag_log(f"[astrbot_compat][boot] PROJECT_ROOT={PROJECT_ROOT} ASTRBOT_PLUGINS_DIR={ASTRBOT_PLUGINS_DIR} discovered={[p.name for p in _discovered]}")
except Exception as _e:
    _diag_log(f"[astrbot_compat][boot] discover 异常: {_e}")

try:
    _loaded = load_all_plugins()
    from astrbot_compat.loader import get_failed_plugins as _gfp
    from astrbot_compat.registry import star_handlers_registry, star_registry

    _diag_log(f"[astrbot_compat][boot] load_all_plugins -> success={len(_loaded)} failed={_gfp()} registry={len(star_registry)} handlers={len(star_handlers_registry)}")
    for _md in _loaded:
        _diag_log(f"[astrbot_compat][boot]   loaded {_md.plugin_id} handlers={len(_md.star_handler_full_names)}")
    if not _loaded:
        _diag_log(f"[astrbot_compat][boot] 没有加载到插件，discovered={[p.name for p in _discovered]} ASTRBOT_COMPAT_ENABLED={getattr(__import__('config.settings', fromlist=['ASTRBOT_COMPAT_ENABLED']), 'ASTRBOT_COMPAT_ENABLED', 'unknown')}")
except Exception as _e:
    import traceback

    _diag_log(f"[astrbot_compat][boot] load_all_plugins 异常: {_e}\n{traceback.format_exc()}")

driver.on_startup(initialize_plugins)
driver.on_shutdown(terminate_plugins)

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
