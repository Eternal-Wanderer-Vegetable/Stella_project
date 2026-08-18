# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""优雅停止：等待在途后台任务收尾。

独立成模块是为了可测——ai_gateway 依赖 NoneBot 运行时无法在纯测试环境
import，而等待逻辑值得单测（曾经整合被中途 kill 导致 checkpoint 与消息表
不一致的教训）。
"""

from __future__ import annotations

import asyncio

from nonebot import logger


async def wait_for_tasks(
    reply_tasks: set[asyncio.Task],
    pending_tasks: list[asyncio.Task],
    grace_seconds: float,
) -> None:
    """取消回应检测任务，并在 ``grace_seconds`` 内等整合/压缩任务收尾。

    三类在途任务：主动 @ 的回应检测（``reply_tasks``，纯 sleep、无副作用，
    直接取消）；整合与会话压缩（``pending_tasks``，必须等——中途退出会让
    整合那批消息的候选丢失：checkpoint 未推进，下次重跑不会坏数据，但白跑
    一次 LLM）。

    超时上界取 ``grace_seconds``：LLM 单次调用最长可达 120s×3 次重试，无限
    等待会让「停止」按钮看起来卡死。超时后放弃等待并告警。
    """
    for task in tuple(reply_tasks):
        task.cancel()
    reply_tasks.clear()

    if not pending_tasks:
        return
    logger.info(
        f"[Shutdown] 等待 {len(pending_tasks)} 个在途后台任务收尾"
        f"（上限 {grace_seconds:.0f}s）..."
    )
    _done, pending = await asyncio.wait(pending_tasks, timeout=grace_seconds)
    if pending:
        logger.warning(
            f"[Shutdown] 超时，仍有 {len(pending)} 个任务未完成，放弃等待"
        )
    else:
        logger.info("[Shutdown] 在途任务已全部完成")
