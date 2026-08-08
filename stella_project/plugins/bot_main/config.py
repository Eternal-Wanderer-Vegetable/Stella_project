# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""bot_main 插件配置模型（NoneBot 插件级配置）。

目前插件本身没有需要自定义的配置项：插件运行所需的全部配置
（如 ALLOWED_GROUPS、SEND_INTERVAL、LM_STUDIO 地址、各种开关）都来自
项目根 config 模块的全局配置，因此这里仅保留一个空的 pydantic BaseModel 占位，
以满足 NoneBot get_plugin_config 的结构要求。
"""

from pydantic import BaseModel


class Config(BaseModel):
    """插件 Config 模型（暂无自定义字段）。"""
