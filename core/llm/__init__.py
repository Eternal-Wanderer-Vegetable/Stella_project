# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端包。

导出 LLM 后端抽象基类 LLMBackend（本地 LM Studio 为唯一实现），并把调度器的
资源常量与入口（acquire / snapshot）在此集中转发，业务代码统一从 core.llm 导入。

``chat_llm_lock`` / ``consolidation_llm_lock`` 是旧代码的**兼容别名**（保留
``async with chat_llm_lock:`` 语法），新代码应直接用 ``acquire(resource, tag=...)``
以便日志区分群与用途。
"""
import contextvars

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

    只支持 ``async with``（不提供手动 acquire/release 接口）。用**栈**记录已
    进入的上下文——chat_llm_lock 有 3 个调用点，不同任务会并发重入同一别名。
    __aenter__ 会等待锁而挂起，跨任务的入栈无法原子配对，因此栈存放在
    ContextVar 中按任务隔离，保证 __aexit__ 弹出的必是本任务自己的那层。
    """

    def __init__(self, resource: str, default_tag: str):
        self._resource = resource
        self._default_tag = default_tag
        self._stack_var: contextvars.ContextVar[tuple] = contextvars.ContextVar(
            f"_lock_alias_stack_{resource}_{default_tag}", default=()
        )

    async def __aenter__(self):
        cm = acquire(self._resource, tag=self._default_tag)
        stack = list(self._stack_var.get())
        stack.append(cm)
        self._stack_var.set(tuple(stack))
        try:
            await cm.__aenter__()
        except BaseException:
            # 进入失败时回退栈，避免残留一层永不退出的占位
            stack.pop()
            self._stack_var.set(tuple(stack))
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        stack = list(self._stack_var.get())
        cm = stack.pop()
        self._stack_var.set(tuple(stack))
        return await cm.__aexit__(exc_type, exc, tb)


# 兼容别名：旧代码继续 `async with chat_llm_lock:`；新代码直接用 acquire()
chat_llm_lock = _LockAlias(RESOURCE_CHAT, "legacy:chat")
consolidation_llm_lock = _LockAlias(RESOURCE_CONSOLIDATION, "legacy:consolidation")
