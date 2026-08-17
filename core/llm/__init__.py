# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端包。

闸门统一由 ``core.llm.scheduler`` 管理：两种资源（chat=27B /
consolidation=E4B）各自 FIFO、彼此并行。``chat_llm_lock`` /
``consolidation_llm_lock`` 是兼容别名，新代码应直接用
``acquire(resource, tag=...)`` 以便日志区分群与用途。
"""

from core.llm.scheduler import (
    PRIORITY_BACKGROUND,
    PRIORITY_INTERACTIVE,
    RESOURCE_CHAT,
    RESOURCE_CONSOLIDATION,
    acquire,
    snapshot,
)

__all__ = [
    "PRIORITY_BACKGROUND",
    "PRIORITY_INTERACTIVE",
    "RESOURCE_CHAT",
    "RESOURCE_CONSOLIDATION",
    "acquire",
    "chat_llm_lock",
    "consolidation_llm_lock",
    "snapshot",
]


class _LockAlias:
    """``async with`` 兼容别名：把旧锁用法路由到调度器的 acquire。

    只支持 ``async with``，不提供手动 acquire/release（项目内无此用法，
    且手动调用无法记录持有时长）。

    用**栈**记录已进入的上下文——chat_llm_lock 有多个调用点会并发重入，
    单个字段存 CM 会被后来者覆盖导致释放错对象。注意必须等 __aenter__
    成功（即真正拿到闸门）之后再入栈：__aenter__ 会因等锁而挂起，若先入栈，
    正在排队任务的 CM 会堆在栈顶，持有者退出时弹错对象、引发
    「asynchronous generator is already running」。
    """

    def __init__(self, resource: str, default_tag: str):
        self._resource = resource
        self._default_tag = default_tag
        self._stack: list = []

    async def __aenter__(self):
        cm = acquire(self._resource, tag=self._default_tag)
        await cm.__aenter__()
        self._stack.append(cm)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        cm = self._stack.pop()
        return await cm.__aexit__(exc_type, exc, tb)


# 兼容别名：旧代码继续 `async with chat_llm_lock:`；新代码直接用 acquire()
chat_llm_lock = _LockAlias(RESOURCE_CHAT, "legacy:chat")
consolidation_llm_lock = _LockAlias(RESOURCE_CONSOLIDATION, "legacy:consolidation")
