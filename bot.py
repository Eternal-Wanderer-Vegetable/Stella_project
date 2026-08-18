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

if __name__ == "__main__":
    nonebot.run()
