读完了三个关键文件（`lm_studio.py`、`pipeline.py`、`core/llm/__init__.py`），embedding 模块的文件名我没猜中（试了 `memory/embedding.py`、`memory/semantic.py` 都不存在）。下面是完整方案，embedding 那部分我按「可选、需你告知文件名」处理。

## 现状清点

`chat_llm_lock` 的 3 处使用：
- `core/pipeline.py:run` —— 包住 `asyncio.wait_for(generate, timeout)`，已记录 `llm_elapsed`
- `memory/session_compact.py:compact_once` —— 包住 `generate`
- `memory/consolidator.py:_extract_candidates` —— 包住 `generate`（M0 新增）

`consolidation_llm_lock` 的 1 处：
- `memory/consolidator.py:_generate` —— 包住 `generate`（M0 收窄后）

`LMStudioBackend` 内部有 3 次重试 + 退避，单次 `generate` 最长可达 120s×3。**这个事实对 scheduler 很重要**：持锁时长的上界不是一次请求，而是三次。M1 的告警阈值要按此设定。

---

# M1 完整方案

## 新建 `core/llm/scheduler.py`

```python
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 资源调度器（模型级串行闸门 + 可观测性）。

为什么需要：LM Studio 不限制并发，多个请求同时打到同一模型会并发推理，
互相拖慢甚至挤爆显存。因此必须在应用层为**每个模型**设一道闸门，
保证「一次只处理一个任务」。

资源划分（与硬件部署一一对应）：
- RESOURCE_CHAT ── GPU 上的主聊天模型（27B）。聊天回复、会话压缩、
  记忆候选提取（阶段2）三类任务共用；
- RESOURCE_CONSOLIDATION ── CPU 上的整合模型（E4B）。整合摘要（阶段1）专用。

两个资源各自串行、彼此并行：调用方**绝不能同时持有两把**，否则一个资源上的
等待会堵住另一个资源上本可立即执行的任务（队头阻塞）。这也是
consolidator.consolidate_group 用独立的群级锁、而不是整段持有资源锁的原因。

排队语义：asyncio.Lock 的等待队列是 FIFO，因此同一资源上的任务严格
「先来后到」，不会饿死。优先级机制（LLM_SCHEDULER_PRIORITY_ENABLED）
默认关闭——开启后交互型任务可插到背景任务之前，但会偏离纯 FIFO。

可观测性（M1 的核心价值）：每次获取都记录等待时长、持有时长与队列深度，
超阈值告警。多群部署下这是判断「延迟来自哪个资源、谁在排队」的唯一手段。
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from nonebot import logger

from config import (
    LLM_SCHEDULER_HOLD_WARN_SECONDS,
    LLM_SCHEDULER_PRIORITY_ENABLED,
    LLM_SCHEDULER_QUEUE_WARN_DEPTH,
    LLM_SCHEDULER_WAIT_WARN_SECONDS,
)

# 资源标识：与实际加载的模型一一对应
RESOURCE_CHAT = "chat"
RESOURCE_CONSOLIDATION = "consolidation"

# 优先级：数字越小越优先（仅在 LLM_SCHEDULER_PRIORITY_ENABLED 时生效）
PRIORITY_INTERACTIVE = 0   # 用户在等：聊天回复
PRIORITY_BACKGROUND = 10   # 后台任务：压缩、提取、整合


@dataclass
class _ResourceState:
    """单个资源的闸门与统计。"""
    name: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # 正在等待获取的任务数（不含持有者）
    waiting: int = 0
    # 当前持有者的 tag 与开始时间，供排查「谁占着不放」
    holder: str = ""
    holder_since: float = 0.0
    # 累计统计
    total_acquired: int = 0
    total_wait_seconds: float = 0.0
    total_hold_seconds: float = 0.0
    peak_waiting: int = 0
    # 优先级模式下的等待者堆（仅在开关打开时使用）
    _priority_waiters: list = field(default_factory=list)


_resources: dict[str, _ResourceState] = {}


def _get(resource: str) -> _ResourceState:
    """取资源状态（懒建）。未知资源名也允许——便于将来加新模型不用改本模块。"""
    state = _resources.get(resource)
    if state is None:
        state = _ResourceState(name=resource)
        _resources[resource] = state
    return state


@asynccontextmanager
async def acquire(
    resource: str,
    tag: str = "",
    priority: int = PRIORITY_BACKGROUND,
):
    """获取某个模型资源的独占权（异步上下文管理器）。

    用法：
        async with acquire(RESOURCE_CHAT, tag=f"reply:{group_id}"):
            reply = await backend.generate(prompt)

    参数:
        resource: RESOURCE_CHAT / RESOURCE_CONSOLIDATION；
        tag: 调用方标识（建议 "用途:群号"），只用于日志与排查；
        priority: 仅在 LLM_SCHEDULER_PRIORITY_ENABLED 开启时生效。

    注意：**绝不要在持有一个资源时去获取另一个资源**——那会让两个模型
    退化为串行。需要跨资源的流程（如两阶段整合）应各自独立持锁。
    """
    state = _get(resource)
    state.waiting += 1
    state.peak_waiting = max(state.peak_waiting, state.waiting)
    queue_depth = state.waiting
    if queue_depth >= LLM_SCHEDULER_QUEUE_WARN_DEPTH:
        logger.warning(
            f"⏳ [Scheduler] 资源 {resource} 排队 {queue_depth} 个"
            f"（当前持有者 {state.holder or '无'}，已持有 "
            f"{time.monotonic() - state.holder_since:.1f}s）；新任务 {tag}"
        )
    else:
        logger.debug(f"⏳ [Scheduler] {tag} 等待 {resource}（队列 {queue_depth}）")

    wait_start = time.monotonic()
    if LLM_SCHEDULER_PRIORITY_ENABLED:
        await _acquire_with_priority(state, priority)
    else:
        await state.lock.acquire()
    waited = time.monotonic() - wait_start
    state.waiting -= 1
    state.total_acquired += 1
    state.total_wait_seconds += waited
    state.holder = tag or "?"
    state.holder_since = time.monotonic()

    if waited >= LLM_SCHEDULER_WAIT_WARN_SECONDS:
        logger.warning(
            f"⏳ [Scheduler] {tag} 等待 {resource} 达 {waited:.1f}s"
            f"（阈值 {LLM_SCHEDULER_WAIT_WARN_SECONDS}s）"
        )
    elif waited > 0.05:
        logger.info(f"▶️ [Scheduler] {tag} 获得 {resource}（等待 {waited:.1f}s）")

    try:
        yield
    finally:
        held = time.monotonic() - state.holder_since
        state.total_hold_seconds += held
        state.holder = ""
        state.holder_since = 0.0
        if held >= LLM_SCHEDULER_HOLD_WARN_SECONDS:
            # LMStudioBackend 内部有 3 次重试（每次超时 120s），
            # 因此单次持有的上界远大于一次正常请求，长持有未必是缺陷，
            # 但需要可见——它直接决定别人等多久。
            logger.warning(
                f"🐢 [Scheduler] {tag} 持有 {resource} 达 {held:.1f}s"
                f"（阈值 {LLM_SCHEDULER_HOLD_WARN_SECONDS}s）"
            )
        else:
            logger.debug(f"✅ [Scheduler] {tag} 释放 {resource}（持有 {held:.1f}s）")
        if LLM_SCHEDULER_PRIORITY_ENABLED:
            _release_with_priority(state)
        else:
            state.lock.release()


async def _acquire_with_priority(state: _ResourceState, priority: int) -> None:
    """优先级获取：空闲则直接拿，否则按 (priority, 序号) 排队。

    序号保证同优先级内仍是 FIFO（不会因优先级相同而乱序或饿死）。
    仅在 LLM_SCHEDULER_PRIORITY_ENABLED 开启时使用。
    """
    import heapq
    import itertools

    if not hasattr(_acquire_with_priority, "_counter"):
        _acquire_with_priority._counter = itertools.count()

    if not state.lock.locked() and not state._priority_waiters:
        await state.lock.acquire()
        return

    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    heapq.heappush(
        state._priority_waiters,
        (priority, next(_acquire_with_priority._counter), fut),
    )
    if not state.lock.locked():
        _wake_next(state)
    await fut


def _wake_next(state: _ResourceState) -> None:
    """唤醒优先级最高的等待者并把锁交给它。"""
    import heapq

    while state._priority_waiters:
        _, _, fut = heapq.heappop(state._priority_waiters)
        if not fut.done():
            # 先占锁再唤醒，避免被别人抢先
            state.lock._locked = True  # noqa: SLF001 - 交接锁所有权
            fut.set_result(None)
            return


def _release_with_priority(state: _ResourceState) -> None:
    """释放并把锁交给下一个等待者（若有）。"""
    if state._priority_waiters:
        state.lock._locked = False  # noqa: SLF001
        _wake_next(state)
    else:
        if state.lock.locked():
            state.lock.release()


def snapshot() -> dict:
    """返回各资源的当前状态与累计统计，供诊断命令/日志使用。

    字段含义：
        waiting        当前排队数
        holder         当前持有者 tag
        held_seconds   当前持有者已持有多久
        acquired       累计获取次数
        avg_wait       平均等待秒数
        avg_hold       平均持有秒数
        peak_waiting   历史最大排队数
    """
    out: dict[str, dict] = {}
    now = time.monotonic()
    for name, s in _resources.items():
        out[name] = {
            "waiting": s.waiting,
            "holder": s.holder,
            "held_seconds": round(now - s.holder_since, 1) if s.holder_since else 0.0,
            "acquired": s.total_acquired,
            "avg_wait": round(s.total_wait_seconds / s.total_acquired, 2) if s.total_acquired else 0.0,
            "avg_hold": round(s.total_hold_seconds / s.total_acquired, 2) if s.total_acquired else 0.0,
            "peak_waiting": s.peak_waiting,
        }
    return out


def reset_state() -> None:
    """清空全部资源状态（供测试使用）。"""
    _resources.clear()
```

## 改 `core/llm/__init__.py`

把两把裸锁变成 scheduler 的薄封装，**保持名字不变**，老调用点零改动：

```python
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""LLM 后端包。

导出 LLM 后端抽象基类 LLMBackend（本地 LM Studio 为唯一实现），
并把两个模型资源的串行闸门统一交给 core.llm.scheduler 管理。

chat_llm_lock / consolidation_llm_lock 是 scheduler 的**兼容别名**：
沿用原有 `async with xxx_lock:` 写法即可，但内部已带排队/等待/持有的
可观测性。新代码建议直接用 scheduler.acquire(resource, tag=...)，
以便在日志里区分是哪个群、哪种用途在排队。
"""

from core.llm.scheduler import (
    RESOURCE_CHAT,
    RESOURCE_CONSOLIDATION,
    acquire,
    snapshot,
)


class _LockAlias:
    """把 scheduler.acquire 包装成可 `async with` 的对象（兼容旧写法）。

    只支持 `async with`，不支持 acquire()/release() 手动调用——
    项目内没有那种用法，且手动调用无法记录持有时长。
    """

    def __init__(self, resource: str, default_tag: str):
        self._resource = resource
        self._default_tag = default_tag
        self._stack: list = []

    async def __aenter__(self):
        cm = acquire(self._resource, tag=self._default_tag)
        self._stack.append(cm)
        return await cm.__aenter__()

    async def __aexit__(self, exc_type, exc, tb):
        cm = self._stack.pop()
        return await cm.__aexit__(exc_type, exc, tb)


# 聊天主链路锁：GPU 上的 27B（聊天回复 / 会话压缩 / 候选提取共用）
chat_llm_lock = _LockAlias(RESOURCE_CHAT, "legacy:chat")
# 记忆整合锁：CPU 上的 E4B（整合摘要）
consolidation_llm_lock = _LockAlias(RESOURCE_CONSOLIDATION, "legacy:consolidation")

__all__ = [
    "RESOURCE_CHAT",
    "RESOURCE_CONSOLIDATION",
    "acquire",
    "chat_llm_lock",
    "consolidation_llm_lock",
    "snapshot",
]
```

注意 `_LockAlias` 用 list 存 CM 以支持重入调用（同一别名对象被多处并发 `async with`）。这是必需的——`chat_llm_lock` 有 3 个调用点。

## 改 `config/settings.py`

在「本地 LLM（LM Studio）」段之后新增：

```python
# ---------- LLM 资源调度（模型级串行闸门） ----------
# LM Studio 不限制并发，多请求同时打到同一模型会并发推理、互相拖慢。
# 因此每个模型一道闸门，一次只处理一个任务（见 core/llm/scheduler.py）。
# 两个资源（27B / E4B）彼此并行，各自内部严格 FIFO。
#
# 等待超过该秒数则告警：多群部署下这是发现「某个模型过载」的主要手段。
# 实测阶段2 候选提取占用 27B 约 20 秒（1617 prompt tokens + 280 生成
# @19 tok/s），因此 30 秒意味着「前面已经排了一个以上的后台任务」。
LLM_SCHEDULER_WAIT_WARN_SECONDS = _env_float("LLM_SCHEDULER_WAIT_WARN_SECONDS", 30.0)
# 单次持有超过该秒数则告警。LMStudioBackend 内部有 3 次重试（每次超时 120s），
# 因此持有上界远大于一次正常请求；90 秒足以覆盖正常生成，又能抓住卡死。
LLM_SCHEDULER_HOLD_WARN_SECONDS = _env_float("LLM_SCHEDULER_HOLD_WARN_SECONDS", 90.0)
# 排队深度达到该值即告警（含正在等待、不含持有者）
LLM_SCHEDULER_QUEUE_WARN_DEPTH = _env_int("LLM_SCHEDULER_QUEUE_WARN_DEPTH", 3)
# 优先级排队：开启后交互型任务（用户在等回复）可插到后台任务之前。
# **默认关闭**——它偏离「纯先来后到」。单群下无必要；多群部署且实测
# @ 回复被后台任务拖慢时再打开。后台任务有界（每群最多 1 个在途），
# 因此开启后也不会饿死。
LLM_SCHEDULER_PRIORITY_ENABLED = _env("LLM_SCHEDULER_PRIORITY_ENABLED", "false").lower() in ("true", "1", "yes")
```

## 三处调用点改用显式 tag（可选但推荐）

老别名能跑，但日志里全是 `legacy:chat`，多群下分不清谁在排队。建议顺手改：

**`core/pipeline.py`** —— import 改为：

```python
from core.llm import RESOURCE_CHAT, acquire
```

调用处：

```python
                # 模型级闸门：聊天回复与压缩/提取共用 GPU 上的 27B，必须串行
                async with acquire(RESOURCE_CHAT, tag=f"reply:{ctx.group_id}",
                                   priority=PRIORITY_INTERACTIVE):
```

（`PRIORITY_INTERACTIVE` 需从 `core.llm.scheduler` 导入，或在 `core/llm/__init__.py` 的 `__all__` 里一并导出——建议导出，我在上面的 `__init__.py` 里没列，请补上 `PRIORITY_INTERACTIVE` 和 `PRIORITY_BACKGROUND`。）

**`memory/session_compact.py`**：

```python
from core.llm import RESOURCE_CHAT, acquire
...
            async with acquire(RESOURCE_CHAT, tag=f"compact:{group_id}"):
                result = await _get_backend().generate(prompt)
```

**`memory/consolidator.py`** 两处：

```python
        async with acquire(RESOURCE_CONSOLIDATION, tag=f"consolidate:{group_id}"):
            result = await backend.generate(prompt)
```

```python
            async with acquire(RESOURCE_CHAT, tag=f"extract:{group_id}"):
                result = await backend.generate(prompt)
```

（`_extract_candidates` 需要 `group_id` 参数才能打 tag——签名加一个 `group_id: int`，调用处传入。）

---

## 两个待确认项

**1. embedding 纳管** —— 我没找到 embedding 的实现文件（试了 `memory/embedding.py`、`memory/semantic.py`）。`MEMORY_EMBEDDING_ENABLED` 打开后 `/v1/embeddings` 会打同一个 27B 实例且不持锁，绕过闸门。请告诉我文件名，我给出改动；或者因为它默认关闭，先记进 M6 文档的已知问题，等你真要开 embedding 时再处理。我倾向**现在就修**，因为一旦忘了这茬、将来开启 embedding 会出现难查的性能问题。

**2. 优先级实现的取舍** —— 上面 `_acquire_with_priority` 直接操作了 `state.lock._locked`（私有属性），这不干净，但为了「锁的所有权直接交接、不经过竞争」是最简做法。替代方案是完全不用 `asyncio.Lock`、改用 `asyncio.Semaphore(1)` + 自己维护堆，代码更长但无私有属性依赖。因为这条路径**默认关闭**，我倾向先接受当前写法并加注释说明；你要是介意，我改成后者。

确认这两点后你就可以落地 M1（建议 commit message：`feat: 新增 LLM 资源调度器（模型级串行+队列可观测性）`）。