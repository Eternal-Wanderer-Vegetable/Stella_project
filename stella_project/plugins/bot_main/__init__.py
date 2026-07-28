from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="yaya_ai_bot",
    description="纯净 AI 聊天机器人（基于 PI Agent + TypeScript 记忆系统）",
    usage="@Bot 即可开始聊天",
    config=Config,
)

config = get_plugin_config(Config)

# 仅注册 AI 网关与看门狗模块
from . import ai_gateway, watchdog
