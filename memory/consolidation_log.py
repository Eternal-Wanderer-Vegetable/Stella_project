# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""整合日志：记录每次记忆整合的运行摘要与 LLM 调用详情，便于可视化管理。

日志文件路径由 CONSOLIDATION_LOG_PATH 配置，默认项目根目录 memory_consolidation_log.md。
"""
from nonebot import logger

from config import CONSOLIDATION_LOG_PATH


def append_consolidation_log(entry: str) -> None:
    """把一段 Markdown 文本追加到整合日志文件。

    参数:
        entry: 要写入的日志片段（调用方自行拼好 Markdown 排版）。
    文件不存在时自动补一个标题头；写入失败仅记录错误，不影响主流程。
    """
    try:
        log_path = CONSOLIDATION_LOG_PATH
        if not log_path.exists():
            log_path.write_text("# 🤖 记忆整合日志\n\n", encoding="utf-8")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.error(f"整合日志写入失败: {e}")
