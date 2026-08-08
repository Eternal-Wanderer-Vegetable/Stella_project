# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""核心包。

core 包承载与渠道无关的机器人核心逻辑：context（一次聊天的完整运行上下文）、
pipeline（钩子 + LLM 调度的主处理管线）、llm（可替换的 LLM 后端抽象与实现）。
各子模块彼此协作，供 NoneBot 插件层与 memory 层调用。
"""