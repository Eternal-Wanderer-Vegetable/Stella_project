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

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_builtin_plugins("echo", "single_session")
nonebot.load_from_toml("pyproject.toml")

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
