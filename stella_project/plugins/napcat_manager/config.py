# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""napcat_manager 插件配置模型（NoneBot 插件级配置）。

插件所需的全部运行时参数（NAPCAT_SHELL_PATH、NAPCAT_QQ_ACCOUNT、
NAPCAT_QQ_PASSWORD、看门狗阈值等）统一由项目根 config 模块提供，
这里仅保留一个空 pydantic BaseModel 占位，以满足 NoneBot
get_plugin_config 的结构要求（与 bot_main 保持一致）。
"""

from pydantic import BaseModel


class Config(BaseModel):
    """插件 Config 模型（暂无自定义字段，配置集中在 config/settings.py）。"""
