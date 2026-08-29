# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 调度器：应用层资源闸门。

闸门是**端点级的并发上限**，一个资源 = 一个端点槽：

- **本地端点 concurrency=1**：多个请求同时打到同一份模型权重上时，服务端
  （LM Studio 等）不会排队，只会把并发推理挤在一起，让每个请求都变慢、且难以
  定位是谁在抢算力。Semaphore(1) 与改造前的 ``asyncio.Lock`` 逐字等价。
- **在线端点 concurrency=N**：厂商侧本来就并发处理，串行只是浪费；这里的上限
  是为了贴合厂商限流（429），而不是为了保护算力。

资源名即端点槽名（``LOCAL`` / ``ONLINE_CHAT`` / ``ONLINE_MEMORY`` / ``EXTRA``），
由 ``core.llm.registry.gate_of(role)`` 给出。同一资源内按 FIFO 排队；不同资源
之间互不阻塞——纯本地部署下 ``LOCAL``（27B/GPU）与 ``EXTRA``（E4B/CPU）能真正并行，
这正是改造前 chat / consolidation 两把锁分离的意义。

**调用方绝不能同时持有两把闸门**：若某个任务先持 A 闸门、再等 B 闸门（或反之），
就会发生跨资源队头阻塞——资源 A 空闲时却在等资源 B 的队头任务释放，把两条队一起
堵死。这正是 consolidate_group 用独立群级锁把「阶段1」与「阶段2」拆成两个互不
嵌套持有窗口的原因。切到在线端点后后果一样：跨端点持有依旧是队头阻塞。

并发度从 ``registry`` 取（见 :func:`set_concurrency_resolver`）。解析器未安装或
解析失败时一律退回 1——**默认最保守**，把未知资源当独占资源，绝不会因为配置读不到
就放开并发。并发度在资源**首次使用时**固定，改配置需重启（``reset_state()`` 会清空）。
"""

import asyncio
import itertools
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from nonebot import logger

from config import (
    LLM_SCHEDULER_HOLD_WARN_SECONDS,
    LLM_SCHEDULER_PRIORITY_ENABLED,
    LLM_SCHEDULER_QUEUE_WARN_DEPTH,
    LLM_SCHEDULER_WAIT_WARN_SECONDS,
)

# 旧资源标识。**新代码不要用**——请用 ``registry.gate_of(role)``，资源名现在是
# 端点槽名。这两个常量保留只为不破坏外部 import（项目内已无调用点）；用它们
# acquire 会建出一把与任何端点都不对应的独立闸门，起不到串行保护作用。
RESOURCE_CHAT = "chat"
RESOURCE_CONSOLIDATION = "consolidation"

# 优先级（当前未启用，见 acquire 的注释）；数字越小越优先
PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 10

# 并发度解析器：资源名 → 并发上限。由 core.llm.registry 在导入时安装。
_concurrency_resolver: Callable[[str], int] | None = None


def set_concurrency_resolver(resolver: Callable[[str], int] | None) -> None:
    """安装「资源名 → 并发上限」的解析器（由 ``core.llm.registry`` 调用）。

    调度器不直接读端点配置，避免 ``scheduler → registry → settings`` 的导入环，
    也让测试能只替一个函数就改并发度。传 None 恢复「一律 1」。
    """
    global _concurrency_resolver
    _concurrency_resolver = resolver


def _limit_for(resource: str) -> int:
    """取资源的并发上限；无解析器或解析异常时返回 1（最保守）。"""
    if _concurrency_resolver is None:
        return 1
    try:
        return max(1, int(_concurrency_resolver(resource)))
    except Exception as e:  # 配置坏了不该让闸门失效，退回独占
        logger.warning(f"⚠️ [Scheduler] 资源 {resource} 并发度解析失败（{e}），按 1 处理")
        return 1


@dataclass
class _ResourceState:
    """单个资源闸门的运行时状态与统计。"""

    name: str
    # 并发上限；1 时 Semaphore(1) 与改造前的 Lock 逐字等价
    limit: int = 1
    sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    # 当前排队（未获得名额）的任务数，不含持有者
    waiting: int = 0
    # 当前持有者：token → (tag, 持有开始的单调时钟)。并发度 >1 时会有多个，
    # 因此不能像改造前那样用单个 holder 字段——后来者会覆盖前者，
    # 释放统计与告警都会读到错的持有时长。tag 可重复，所以键用递增 token。
    holds: dict[int, tuple[str, float]] = field(default_factory=dict)
    total_acquired: int = 0
    total_wait_seconds: float = 0.0
    total_hold_seconds: float = 0.0
    peak_waiting: int = 0
    peak_holding: int = 0


# 资源名 → 状态；进程内单份
_resources: dict[str, _ResourceState] = {}
# 持有者 token 生成器（进程内唯一即可，不需要跨资源区分）
_hold_tokens = itertools.count()


def _get(resource: str) -> _ResourceState:
    """取指定资源的闸门状态（懒建）。并发度在建时定下，之后不再变。"""
    state = _resources.get(resource)
    if state is None:
        limit = _limit_for(resource)
        state = _ResourceState(name=resource, limit=limit, sem=asyncio.Semaphore(limit))
        _resources[resource] = state
        if limit > 1:
            logger.info(f"[Scheduler] 资源 {resource} 闸门并发度 {limit}")
    return state


def _describe_holders(state: _ResourceState) -> str:
    """当前持有者的可读描述（供告警日志）。"""
    if not state.holds:
        return "（无）"
    now = time.monotonic()
    return "、".join(f"{tag or '-'}({now - since:.1f}s)" for tag, since in state.holds.values())


@asynccontextmanager
async def acquire(
    resource: str, tag: str = "", priority: int = PRIORITY_BACKGROUND
) -> AsyncIterator[None]:
    """排队获取指定资源的一个并发名额，yield 期间占用，退出时自动释放。

    参数:
        resource: 端点槽名，取自 ``core.llm.registry.gate_of(role)``；
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
        logger.warning(
            f"⚠️ [Scheduler] 资源 {resource} 排队深度 {state.waiting}"
            f"（tag={tag or '-'}，并发上限 {state.limit}），"
            f"当前持有者 {_describe_holders(state)}"
        )

    # 排队等待名额
    wait_start = time.monotonic()
    await state.sem.acquire()
    wait_seconds = time.monotonic() - wait_start
    state.total_wait_seconds += wait_seconds
    state.total_acquired += 1
    state.waiting -= 1
    # 持有时长用局部变量记录，finally 不依赖共享状态；holds 里同步登记一份，
    # 供排队者告警读取「谁持有了多久」。
    hold_start = time.monotonic()
    token = next(_hold_tokens)
    state.holds[token] = (tag, hold_start)
    if len(state.holds) > state.peak_holding:
        state.peak_holding = len(state.holds)
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
            # 后端内含 3 次重试（每次超时按端点的 TIMEOUT 计），单次持有上界
            # 远大于一次正常请求；持续超阈值说明不是排队，而是调用本身卡住了。
            logger.warning(
                f"⚠️ [Scheduler] 资源 {resource} 持有 {hold_seconds:.1f}s"
                f"（tag={tag or '-'}，阈值 {LLM_SCHEDULER_HOLD_WARN_SECONDS:.0f}s）"
            )
        state.holds.pop(token, None)
        state.sem.release()


def snapshot() -> dict:
    """导出每个资源的当前状态与累计统计（供可观测性 / 调优）。

    每个资源返回：limit / holding / holders / waiting / holder / held_seconds /
    acquired / avg_wait / avg_hold / peak_waiting / peak_holding。

    ``holders`` 是当前持有者 tag 列表（并发度 >1 时可能多个）；``holder`` 与
    ``held_seconds`` 保留为**单值摘要**（持有最久的那个），这样既兼容
    「一次只有一个持有者」的旧读法，又不会在并发端点上给出误导性的数字。
    """
    now = time.monotonic()
    out = {}
    for name, state in _resources.items():
        oldest = min((since for _, since in state.holds.values()), default=None)
        out[name] = {
            "limit": state.limit,
            "holding": len(state.holds),
            "holders": sorted(tag or "-" for tag, _ in state.holds.values()),
            "waiting": state.waiting,
            "holder": (
                "、".join(sorted(tag or "-" for tag, _ in state.holds.values())) or None
            ),
            "held_seconds": (now - oldest) if oldest is not None else 0.0,
            "acquired": state.total_acquired,
            "avg_wait": (
                state.total_wait_seconds / state.total_acquired if state.total_acquired else 0.0
            ),
            "avg_hold": (
                state.total_hold_seconds / state.total_acquired if state.total_acquired else 0.0
            ),
            "peak_waiting": state.peak_waiting,
            "peak_holding": state.peak_holding,
        }
    return out


def reset_state() -> None:
    """清空全部闸门状态（测试用）。并发度会在下次使用时重新解析。"""
    _resources.clear()
