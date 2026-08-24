# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Comes：工具执行层（方案第 12 节）。

对外只暴露两个入口：

- ``execute(task, event=...)``：执行单个任务；
- ``execute_all(tasks, event=...)``：并发执行一组无依赖的任务。

实现见 ``executor``（Capability → Provider → Tool）与 ``summarizer``
（Result.data → Result.summary）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from capability.comes.executor import execute
from capability.registry import CapabilityRegistry
from core.tasks import Result, ResultStatus, Task


def _logger():
    from nonebot import logger

    return logger


async def execute_all(
    tasks: list[Task],
    *,
    event: Any,
    target: CapabilityRegistry | None = None,
    tool_manager=None,
) -> list[Result]:
    """并发执行一组**互不依赖**的任务，按传入顺序返回结果。

    带依赖的任务组应先经 ``core.tasks.TaskGraph.topological_order()`` 分层，
    再逐层调用本函数——本函数不解释 ``dependencies``。

    ``return_exceptions=True``：一个任务炸了不能让其它任务的结果一起丢。
    ``execute`` 本身已经吞掉所有异常，这里是第二道保险（比如 gather 自身被取消）。
    """
    if not tasks:
        return []

    gathered = await asyncio.gather(
        *(
            execute(task, event=event, target=target, tool_manager=tool_manager)
            for task in tasks
        ),
        return_exceptions=True,
    )

    results: list[Result] = []
    for task, item in zip(tasks, gathered, strict=False):
        if isinstance(item, Result):
            results.append(item)
            continue
        _logger().warning(f"⚠️ [Comes] 任务 {task.task_id} 未能返回结果: {item!r}")
        results.append(
            Result(
                task_id=task.task_id,
                status=ResultStatus.FAILED,
                summary="",
                metadata={"capability": task.capability, "reason": f"未返回结果: {item!r}"},
            ),
        )
    return results


__all__ = ["execute", "execute_all"]
