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

资源名即端点槽名（``CHAT`` / ``MEMORY`` / ``VISION``），
由 ``core.llm.registry.gate_of(role)`` 给出。同一资源内按 FIFO 排队；不同资源
之间互不阻塞——纯本地部署下 ``CHAT``（27B/GPU）与 ``MEMORY``（E4B/CPU）能真正并行，
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
import math
import time
from collections import deque
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
from gravitas.contracts import WorkClass

# 旧资源标识。**新代码不要用**——请用 ``registry.gate_of(role)``，资源名现在是
# 端点槽名。这两个常量保留只为不破坏外部 import（项目内已无调用点）；用它们
# acquire 会建出一把与任何端点都不对应的独立闸门，起不到串行保护作用。
RESOURCE_CHAT = "chat"
RESOURCE_CONSOLIDATION = "consolidation"

# 优先级（当前未启用，见 acquire 的注释）；数字越小越优先
PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 10

# Bounded scheduler defaults. These limits apply to waiting tickets only; live
# holders remain governed by the endpoint concurrency configured in registry.
GLOBAL_QUEUE_CAP = 256
RESOURCE_QUEUE_CAP = 64
CONVERSATION_QUEUE_CAP = 1
MAX_TRACKED_RESOURCES = 256
BACKGROUND_AGING_SECONDS = 30.0
MAINTENANCE_AGING_SECONDS = 60.0
_INTERACTIVE_BACKGROUND_CYCLE = (
    WorkClass.INTERACTIVE,
    WorkClass.INTERACTIVE,
    WorkClass.INTERACTIVE,
    WorkClass.INTERACTIVE,
    WorkClass.BACKGROUND,
)

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
    # 并发上限固定在首次使用时解析；不在运行中增大。
    limit: int = 1
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
    waiters: dict[WorkClass, deque["_Waiter"]] = field(
        default_factory=lambda: {kind: deque() for kind in WorkClass}
    )
    next_class_index: int = 0
    rejected_queue_full: int = 0


@dataclass(slots=True)
class _Waiter:
    resource: str
    tag: str
    work_class: WorkClass
    enqueued_at: float
    future: asyncio.Future[int]
    conversation_key: str | None = None
    deadline: float | None = None
    status: str = "queued"
    token: int | None = None
    granted_at: float | None = None
    acquired: bool = False
    released: bool = False


class QueueCapacityError(RuntimeError):
    """A scheduler queue reached a configured bound before admission."""

    reason_code = "scheduler_queue_full"


# 资源名 → 状态；进程内单份
_resources: dict[str, _ResourceState] = {}
# 持有者 token 生成器（进程内唯一即可，不需要跨资源区分）
_hold_tokens = itertools.count()
_queued_conversations: dict[str, int] = {}


def _get(resource: str) -> _ResourceState:
    """取指定资源的闸门状态（懒建）。并发度在建时定下，之后不再变。"""
    state = _resources.get(resource)
    if state is None:
        if len(_resources) >= MAX_TRACKED_RESOURCES:
            raise QueueCapacityError("scheduler resource capacity reached")
        limit = _limit_for(resource)
        state = _ResourceState(name=resource, limit=limit)
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
    resource: str,
    tag: str = "",
    priority: int = PRIORITY_BACKGROUND,
    *,
    work_class: WorkClass | str | None = None,
    deadline: float | None = None,
    conversation_key: str | None = None,
) -> AsyncIterator[None]:
    """排队获取指定资源的一个并发名额，yield 期间占用，退出时自动释放。

    参数:
        resource: 端点槽名，取自 ``core.llm.registry.gate_of(role)``；
        tag: 调用方用途标签（如 ``reply:263402786``），写进日志与告警；
        priority: 兼容旧优先级参数；显式 ``work_class`` 优先。
        work_class: 交互、后台或维护工作类别，类内 FIFO。
        deadline: 可选的 monotonic 绝对等待截止时间。
        conversation_key: 可选的可信会话键；同会话最多一张排队交互票据。
    """
    if (
        not isinstance(resource, str)
        or not resource
        or resource != resource.strip()
        or len(resource) > 128
        or any(ord(char) < 32 or ord(char) == 127 for char in resource)
    ):
        raise ValueError("resource must be a non-empty trimmed string")
    if (
        not isinstance(tag, str)
        or len(tag) > 128
        or any(ord(char) < 32 or ord(char) == 127 for char in tag)
    ):
        raise ValueError("tag must be a bounded diagnostic label")
    state = _get(resource)
    normalized_class = _work_class(work_class, priority)
    if deadline is not None:
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise ValueError("deadline must be a finite monotonic timestamp")
        deadline = float(deadline)
        if not math.isfinite(deadline):
            raise ValueError("deadline must be a finite monotonic timestamp")
    if conversation_key is not None and (
        not isinstance(conversation_key, str)
        or not conversation_key
        or conversation_key != conversation_key.strip()
        or len(conversation_key) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in conversation_key)
    ):
        raise ValueError("conversation_key must be a bounded trimmed string")

    now = time.monotonic()
    if deadline is not None and deadline <= now:
        raise TimeoutError("scheduler admission deadline expired")
    loop = asyncio.get_running_loop()
    waiter = _Waiter(
        resource=resource,
        tag=tag,
        work_class=normalized_class,
        enqueued_at=now,
        future=loop.create_future(),
        conversation_key=(
            conversation_key if normalized_class is WorkClass.INTERACTIVE else None
        ),
        deadline=deadline,
    )
    _enqueue(state, waiter)
    _dispatch(state, now)
    try:
        if deadline is None:
            token = await waiter.future
        else:
            remaining = max(0.0, deadline - time.monotonic())
            token = await asyncio.wait_for(waiter.future, timeout=remaining)
    except BaseException:
        _cancel_waiter(state, waiter)
        raise

    # If cancellation raced with a completed future, the handler above returns
    # its already granted ticket. Count it only after the waiter resumes.
    if waiter.status != "granted" or waiter.token != token:
        _cancel_waiter(state, waiter)
        raise RuntimeError("scheduler ticket was not granted")
    waiter.acquired = True
    wait_seconds = max(0.0, (waiter.granted_at or time.monotonic()) - waiter.enqueued_at)
    state.total_wait_seconds += wait_seconds
    state.total_acquired += 1
    if wait_seconds > LLM_SCHEDULER_WAIT_WARN_SECONDS:
        logger.warning(
            f"⚠️ [Scheduler] 资源 {resource} 排队等待 {wait_seconds:.1f}s 才获得"
            f"（tag={tag or '-'}，阈值 {LLM_SCHEDULER_WAIT_WARN_SECONDS:.0f}s）"
        )
    try:
        yield
    finally:
        _release_waiter(state, waiter)


def _work_class(work_class: WorkClass | str | None, priority: int) -> WorkClass:
    if work_class is not None:
        try:
            return work_class if isinstance(work_class, WorkClass) else WorkClass(work_class)
        except ValueError as exc:
            raise ValueError(f"unsupported work class: {work_class!r}") from exc
    if LLM_SCHEDULER_PRIORITY_ENABLED and priority == PRIORITY_INTERACTIVE:
        return WorkClass.INTERACTIVE
    return WorkClass.BACKGROUND


def _enqueue(state: _ResourceState, waiter: _Waiter) -> None:
    global_waiting = sum(item.waiting for item in _resources.values())
    if global_waiting >= GLOBAL_QUEUE_CAP or state.waiting >= RESOURCE_QUEUE_CAP:
        state.rejected_queue_full += 1
        raise QueueCapacityError("scheduler queue capacity reached")
    if waiter.conversation_key is not None and (
        _queued_conversations.get(waiter.conversation_key, 0)
        >= CONVERSATION_QUEUE_CAP
    ):
        state.rejected_queue_full += 1
        raise QueueCapacityError("conversation already has a pending interactive request")
    state.waiters[waiter.work_class].append(waiter)
    state.waiting += 1
    if waiter.conversation_key is not None:
        _queued_conversations[waiter.conversation_key] = (
            _queued_conversations.get(waiter.conversation_key, 0) + 1
        )
    state.peak_waiting = max(state.peak_waiting, state.waiting)
    if state.waiting >= LLM_SCHEDULER_QUEUE_WARN_DEPTH:
        logger.warning(
            f"⚠️ [Scheduler] 资源 {state.name} 排队深度 {state.waiting}"
            f"（tag={waiter.tag or '-'}，并发上限 {state.limit}），"
            f"当前持有者 {_describe_holders(state)}"
        )


def _remove_queued(state: _ResourceState, waiter: _Waiter) -> bool:
    if waiter.status != "queued":
        return False
    queue = state.waiters[waiter.work_class]
    try:
        queue.remove(waiter)
    except ValueError:
        return False
    waiter.status = "cancelled"
    state.waiting -= 1
    if waiter.conversation_key is not None:
        remaining = _queued_conversations.get(waiter.conversation_key, 0) - 1
        if remaining > 0:
            _queued_conversations[waiter.conversation_key] = remaining
        else:
            _queued_conversations.pop(waiter.conversation_key, None)
    return True


def _dispatch(state: _ResourceState, now: float) -> None:
    while len(state.holds) < state.limit and state.waiting:
        waiter = _next_waiter(state, now)
        if waiter is None:
            return
        if waiter.deadline is not None and waiter.deadline <= now:
            waiter.status = "expired"
            state.waiting -= 1
            if waiter.conversation_key is not None:
                remaining = _queued_conversations.get(waiter.conversation_key, 0) - 1
                if remaining > 0:
                    _queued_conversations[waiter.conversation_key] = remaining
                else:
                    _queued_conversations.pop(waiter.conversation_key, None)
            if not waiter.future.done():
                waiter.future.set_exception(
                    TimeoutError("scheduler admission deadline expired")
                )
            continue
        state.waiting -= 1
        if waiter.conversation_key is not None:
            remaining = _queued_conversations.get(waiter.conversation_key, 0) - 1
            if remaining > 0:
                _queued_conversations[waiter.conversation_key] = remaining
            else:
                _queued_conversations.pop(waiter.conversation_key, None)
        waiter.status = "granted"
        waiter.granted_at = now
        waiter.token = next(_hold_tokens)
        state.holds[waiter.token] = (waiter.tag, now)
        state.peak_holding = max(state.peak_holding, len(state.holds))
        waiter.future.set_result(waiter.token)


def _next_waiter(state: _ResourceState, now: float) -> _Waiter | None:
    background = state.waiters[WorkClass.BACKGROUND]
    maintenance = state.waiters[WorkClass.MAINTENANCE]
    if background and now - background[0].enqueued_at >= BACKGROUND_AGING_SECONDS:
        return background.popleft()
    if maintenance and now - maintenance[0].enqueued_at >= MAINTENANCE_AGING_SECONDS:
        return maintenance.popleft()
    for _ in range(len(_INTERACTIVE_BACKGROUND_CYCLE)):
        work_class = _INTERACTIVE_BACKGROUND_CYCLE[state.next_class_index]
        state.next_class_index = (state.next_class_index + 1) % len(
            _INTERACTIVE_BACKGROUND_CYCLE
        )
        queue = state.waiters[work_class]
        if queue:
            return queue.popleft()
    if maintenance:
        return maintenance.popleft()
    return None


def _cancel_waiter(state: _ResourceState, waiter: _Waiter) -> None:
    if _remove_queued(state, waiter):
        if not waiter.future.done():
            waiter.future.cancel()
        _dispatch(state, time.monotonic())
        return
    if waiter.status == "granted":
        _release_waiter(state, waiter)


def _release_waiter(state: _ResourceState, waiter: _Waiter) -> None:
    if waiter.released:
        return
    waiter.released = True
    token = waiter.token
    if token is None:
        return
    hold = state.holds.pop(token, None)
    waiter.status = "released"
    if hold is None:
        return
    held_since = hold[1]
    hold_seconds = max(0.0, time.monotonic() - held_since)
    if waiter.acquired:
        state.total_hold_seconds += hold_seconds
        if hold_seconds > LLM_SCHEDULER_HOLD_WARN_SECONDS:
            logger.warning(
                f"⚠️ [Scheduler] 资源 {state.name} 持有 {hold_seconds:.1f}s"
                f"（tag={waiter.tag or '-'}，阈值 {LLM_SCHEDULER_HOLD_WARN_SECONDS:.0f}s）"
            )
    _dispatch(state, time.monotonic())


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
            "rejected_queue_full": state.rejected_queue_full,
        }
    return out


def reset_state() -> None:
    """清空全部闸门状态（测试用）。并发度会在下次使用时重新解析。"""
    _resources.clear()
    _queued_conversations.clear()
