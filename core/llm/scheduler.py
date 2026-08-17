# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 调度器：应用层资源闸门。

LM Studio 本身**不限并发**：多个请求同时打到同一个模型上时，服务端不会排队，
只会把并发推理挤在一起，让每个请求都变慢、且难以定位是谁在抢算力。因此
应用层必须为共享模型加闸门——这是本模块存在的意义。

两种资源各自独立：
- ``chat``：主聊天模型（27B），由聊天回复、会话压缩、候选提取共享；
- ``consolidation``：整合模型（E4B），由两阶段整合的阶段1 使用。
同一资源内的任务按 FIFO 严格串行；不同资源之间互不阻塞、可真正并行。

**调用方绝不能同时持有两把闸门**：若某个任务先持 consolidation 锁、再等
chat 锁（或反之），就会发生跨模型队头阻塞——资源 A 空闲时却在等资源 B 的
队头任务释放，把两条队一起堵死。这正是 consolidate_group 用独立群级锁把
「E4B 阶段1」与「27B 阶段2」拆成两个互不嵌套持有窗口的原因。
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from nonebot import logger

from config import (
    LLM_SCHEDULER_HOLD_WARN_SECONDS,
    LLM_SCHEDULER_PRIORITY_ENABLED,
    LLM_SCHEDULER_QUEUE_WARN_DEPTH,
    LLM_SCHEDULER_WAIT_WARN_SECONDS,
)

# 资源标识：主聊天模型（27B）与整合模型（E4B）
RESOURCE_CHAT = "chat"
RESOURCE_CONSOLIDATION = "consolidation"

# 优先级（当前未启用，见 acquire 的注释）；数字越小越优先
PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 10


@dataclass
class _ResourceState:
    """单个资源闸门的运行时状态与统计。"""

    name: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 当前排队（未获得锁）的任务数，不含持有者
    waiting: int = 0
    # 当前持有者 tag（空串表示空闲）
    holder: str = ""
    # 持有开始的单调时钟（monotonic），空闲时为 None
    holder_since: float | None = None
    total_acquired: int = 0
    total_wait_seconds: float = 0.0
    total_hold_seconds: float = 0.0
    peak_waiting: int = 0


# 资源名 → 状态；进程内单份
_resources: dict[str, _ResourceState] = {}


def _get(resource: str) -> _ResourceState:
    """取指定资源的闸门状态（懒建）。"""
    state = _resources.get(resource)
    if state is None:
        state = _ResourceState(name=resource)
        _resources[resource] = state
    return state


@asynccontextmanager
async def acquire(
    resource: str, tag: str = "", priority: int = PRIORITY_BACKGROUND
) -> AsyncIterator[None]:
    """排队获取指定资源，yield 期间独占该资源，退出时自动释放。

    参数:
        resource: RESOURCE_CHAT / RESOURCE_CONSOLIDATION 之一（可扩展）；
        tag: 调用方用途标签（如 ``reply:263402786``），写进日志与告警；
        priority: 交互优先级。**尚未实现**——优先级排队未启用时一律按 FIFO
            处理，仅打一条 debug。理由：先用 snapshot() 积累真实排队数据，
            再决定是否偏离 FIFO，避免凭猜测引入复杂调度。
    """
    state = _get(resource)
    if LLM_SCHEDULER_PRIORITY_ENABLED and priority != PRIORITY_BACKGROUND:
        logger.debug(
            f"[Scheduler] 优先级排队未启用（tag={tag or '-'}，"
            f"priority={priority}），按 FIFO 处理"
        )

    # 入队：排队深度统计与峰值
    state.waiting += 1
    if state.waiting > state.peak_waiting:
        state.peak_waiting = state.waiting
    if state.waiting >= LLM_SCHEDULER_QUEUE_WARN_DEPTH:
        held = (time.monotonic() - state.holder_since) if state.holder_since else 0.0
        logger.warning(
            f"⚠️ [Scheduler] 资源 {resource} 排队深度 {state.waiting}"
            f"（tag={tag or '-'}），当前持有者 {state.holder or '（无）'} 已持有 {held:.1f}s"
        )

    # 排队等待锁
    wait_start = time.monotonic()
    await state.lock.acquire()
    wait_seconds = time.monotonic() - wait_start
    state.total_wait_seconds += wait_seconds
    state.total_acquired += 1
    state.waiting -= 1
    state.holder = tag
    # 持有时长用局部变量记录，finally 不依赖共享状态（holder_since 可能被
    # 其他路径改写）；holder_since 仍同步写入，供排队者告警读取持有时长。
    hold_start = time.monotonic()
    state.holder_since = hold_start
    if wait_seconds > LLM_SCHEDULER_WAIT_WARN_SECONDS:
        logger.warning(
            f"⚠️ [Scheduler] 资源 {resource} 排队等待 {wait_seconds:.1f}s 才获得"
            f"（tag={tag or '-'}，阈值 {LLM_SCHEDULER_WAIT_WARN_SECONDS:.0f}s）"
        )
    try:
        yield
    finally:
        hold_seconds = time.monotonic() - hold_start
        state.total_hold_seconds += hold_seconds
        if hold_seconds > LLM_SCHEDULER_HOLD_WARN_SECONDS:
            # 后端（LMStudioBackend）内含 3 次重试（每次 timeout 120s），
            # 单次持有上界远大于一次正常请求；持续超阈值说明不是排队，
            # 而是调用本身卡住了。
            logger.warning(
                f"⚠️ [Scheduler] 资源 {resource} 持有 {hold_seconds:.1f}s"
                f"（tag={tag or '-'}，阈值 {LLM_SCHEDULER_HOLD_WARN_SECONDS:.0f}s）"
            )
        state.holder = ""
        state.holder_since = None
        state.lock.release()


def snapshot() -> dict:
    """导出每个资源的当前状态与累计统计（供可观测性 / 调优）。

    每个资源返回：waiting / holder / held_seconds / acquired / avg_wait /
    avg_hold / peak_waiting。
    """
    return {
        name: {
            "waiting": state.waiting,
            "holder": state.holder or None,
            "held_seconds": (
                time.monotonic() - state.holder_since if state.holder_since else 0.0
            ),
            "acquired": state.total_acquired,
            "avg_wait": (
                state.total_wait_seconds / state.total_acquired if state.total_acquired else 0.0
            ),
            "avg_hold": (
                state.total_hold_seconds / state.total_acquired if state.total_acquired else 0.0
            ),
            "peak_waiting": state.peak_waiting,
        }
        for name, state in _resources.items()
    }


def reset_state() -> None:
    """清空全部闸门状态（测试用）。"""
    _resources.clear()
