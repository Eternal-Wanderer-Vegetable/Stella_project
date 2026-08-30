# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端包。

两层配置的入口都在这里：

- **构造后端**：``backend_for(ROLE_CHAT)``。全项目只从这一处拿后端实例，
  「换成在线模型」于是变成改 ``.env`` 而不是改六处代码。
- **排队**：``async with acquire(gate_of(ROLE_CHAT), tag=...)``。闸门资源名就是
  端点槽名，因此「哪些角色互相串行」完全由端点绑定决定——两个角色绑同一个槽就
  共用一把闸门，绑不同槽就真正并行。

``chat_llm_lock`` / ``consolidation_llm_lock`` 是旧锁用法的兼容别名，**新代码不要用**：
它们拿不到调用方的用途标签，日志里分不清是哪个群、哪个任务在持有闸门。
"""

from core.llm.registry import (
    ROLE_CHAT,
    ROLE_COMPACT,
    ROLE_CONSOLIDATION,
    ROLE_EXTRACT,
    ROLE_PLUGIN,
    ROLE_ROUTER,
    backend_for,
    embedding_gate,
    endpoint_of,
    fallback_states,
    gate_of,
    role_is_online,
)
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
    "ROLE_CHAT",
    "ROLE_COMPACT",
    "ROLE_CONSOLIDATION",
    "ROLE_EXTRACT",
    "ROLE_PLUGIN",
    "ROLE_ROUTER",
    "acquire",
    "backend_for",
    "chat_llm_lock",
    "consolidation_llm_lock",
    "embedding_gate",
    "endpoint_of",
    "fallback_states",
    "gate_of",
    "role_is_online",
    "snapshot",
]


class _LockAlias:
    """``async with`` 兼容别名：把旧锁用法路由到调度器的 acquire。

    只支持 ``async with``，不提供手动 acquire/release（项目内无此用法，
    且手动调用无法记录持有时长）。

    资源名在**每次进入时**按角色解析，而不是构造时定死：角色绑到哪个端点槽是
    配置决定的，构造时（import 期）解析会把闸门钉在导入顺序上，改配置后仍然
    排在旧闸门上——那种 bug 只在多端点部署下出现，最难查。

    用**栈**记录已进入的上下文——同一个别名有多个调用点会并发重入，
    单个字段存 CM 会被后来者覆盖导致释放错对象。注意必须等 __aenter__
    成功（即真正拿到闸门）之后再入栈：__aenter__ 会因等锁而挂起，若先入栈，
    正在排队任务的 CM 会堆在栈顶，持有者退出时弹错对象、引发
    「asynchronous generator is already running」。
    """

    def __init__(self, role: str, default_tag: str):
        self._role = role
        self._default_tag = default_tag
        self._stack: list = []

    async def __aenter__(self):
        cm = acquire(gate_of(self._role), tag=self._default_tag)
        await cm.__aenter__()
        self._stack.append(cm)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        cm = self._stack.pop()
        return await cm.__aexit__(exc_type, exc, tb)


# 兼容别名：旧代码继续 `async with chat_llm_lock:`；新代码直接用 acquire()
chat_llm_lock = _LockAlias(ROLE_CHAT, "legacy:chat")
consolidation_llm_lock = _LockAlias(ROLE_CONSOLIDATION, "legacy:consolidation")
