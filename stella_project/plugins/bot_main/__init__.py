# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""bot_main 插件包入口（NoneBot 插件）。

组装插件元信息，并挂载两个核心子模块：
- ai_gateway：AI 对话网关——Pipeline 装配、@ 触发回复、主动发言、定时任务；
- watchdog：NapCat 消息流看门狗，负责链路中断检测与自动重启。

导入本文件即注册上述监听器（NoneBot 会在插件加载时触发）。
"""

from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata

from .config import Config

# 声明给 NoneBot / 用户看到的插件描述信息
__plugin_meta__ = PluginMetadata(
    name="yaya_ai_bot",
    description="纯净 AI 聊天机器人（基于 PI Agent + TypeScript 记忆系统）",
    usage="@Bot 即可开始聊天",
    config=Config,
)

# 读取插件级配置（实际由项目中全局 Config 提供各字段）
config = get_plugin_config(Config)

# 仅注册 AI 网关与看门狗模块
from . import ai_gateway, watchdog
