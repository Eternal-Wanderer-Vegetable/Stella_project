"""整合日志：记录每次记忆整合的运行摘要与 LLM 调用详情，便于可视化管理。

日志文件路径由 CONSOLIDATION_LOG_PATH 配置，默认项目根目录 memory_consolidation_log.md。
"""
from nonebot import logger

from config import CONSOLIDATION_LOG_PATH


def append_consolidation_log(entry: str) -> None:
    try:
        log_path = CONSOLIDATION_LOG_PATH
        if not log_path.exists():
            log_path.write_text("# 🤖 记忆整合日志\n\n", encoding="utf-8")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    except Exception as e:
        logger.error(f"整合日志写入失败: {e}")
