# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Capability 层接入 Pipeline 的前置钩子。

管线钩子按 priority **降序**执行。接入后的顺序：

```
50  build_context           # 不变，始终执行（这是对话上下文，不是「记忆检索」）
45  activate_capabilities   # Router 判定 → 并行 {Memory 检索, Comes 执行}
```

``build_user_context`` 的独立注册被本钩子**接管**：方案第 17 节要求 Memory 与
Comes 并行，而两个独立钩子只能串行，必须收进同一个 ``gather``。

## 关于并行的诚实说明

纯本地部署下 Comes 的 LLM 调用与 Memory 的 embedding 编码落在同一把闸门上
（前者 ``gate_of(ROLE_CHAT)``、后者 ``embedding_gate()`` 解析到同一个本地槽），
两者的**模型调用**仍会 FIFO 串行（见 docs/architecture.md 的资源闸门一节）。
``gather`` 拿到的是真实收益的那部分：Memory 的 SQL/FTS 查询与 Comes 的 HTTP
等待互相重叠。这不是假并行，但也不是两块 GPU。

## 记忆门控默认关闭

``ROUTER_GATE_MEMORY=false`` 时，Router 照常判定、照常写日志，但记忆检索仍
无条件执行。Router 误判 ``memory=False`` 会让 Stella 当轮悄悄丢失长期记忆——
不抛异常、不影响回复，只是「它突然不记得你了」，与 2026-08-17 那次 AT_MENTION
全为 0 的缺陷同一类型（静默、难察觉、后果严重）。先用 router benchmark 量出
准确率再打开。
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.context import ChatContext
from core.tasks import Result, Task, TaskType, next_task_id

# 本钩子的注册优先级。必须小于 build_context(50)——短期上下文（摘要 + 尾巴）
# 是对话素材，与「要不要检索长期记忆」无关，永远该先组装好。
HOOK_PRIORITY = 45


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 router/semantic.py）。"""
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


# ============================================================
# 任务构造
# ============================================================


def build_tool_tasks(route: Any, message: str) -> list[Task]:
    """把 Router 的能力命中转成 ``tool.execute`` 任务。

    ``objective`` 直接用用户原话：它就是语义层的任务目标，而且是最忠实的版本。
    在这里改写（比如提炼成「查询天气」）只会丢信息——用户说的是「东京明天」，
    提炼后城市和日期就没了，Comes 反而要去猜。方案第 4 节要求 objective 属于
    语义层，用户原话完全满足；它不该是「调用 weather_api()」这种执行指令。
    """
    tasks: list[Task] = []
    for hit in getattr(route, "capabilities", None) or []:
        tasks.append(
            Task(
                task_id=next_task_id(),
                type=TaskType.TOOL_EXECUTE,
                capability=hit.capability_id,
                objective=message,
                constraints={"router_score": hit.score},
            ),
        )
    return tasks


# ============================================================
# 两条并行分支
# ============================================================


async def _retrieve_memory(ctx: ChatContext) -> None:
    """Memory 分支：走既有的 build_user_context，逻辑一行不改（方案第 14 节）。"""
    from memory.pre_processors import build_user_context

    await build_user_context(ctx)


async def _run_comes(ctx: ChatContext, route: Any) -> None:
    """Comes 分支：构造受限事件 → 执行任务 → 写回 summaries。"""
    tasks = build_tool_tasks(route, ctx.message)
    if not tasks:
        return

    event = await _build_astr_event(ctx)
    if event is None:
        _logger().info("🔧 [Comes] 无可用事件对象，跳过工具执行（主动发言路径属正常）")
        return

    from capability.comes import execute_all

    results: list[Result] = await execute_all(tasks, event=event)
    ctx.task_results = list(results)
    # 只有 ok 且有摘要的结果才进 prompt。失败的任务不告知 Stella——
    # 它不该向用户解释某个工具报了什么错，那是运维信息不是聊天素材。
    ctx.tool_summaries = [r.summary for r in results if r.ok and r.summary]


async def _build_astr_event(ctx: ChatContext) -> Any:
    """从平台原始句柄构造 AstrMessageEvent；缺句柄或兼容层未启用时返回 None。

    工具 handler 普遍依赖真实 event（发消息、取群号、调 OneBot API），
    构造不出等价替身，所以拿不到就干脆不执行。
    """
    if ctx.raw_event is None or ctx.bot is None:
        return None
    if not _settings().ASTRBOT_COMPAT_ENABLED:
        return None
    try:
        from astrbot_compat.events import build_event

        return await build_event(ctx.raw_event, ctx.bot)
    except Exception as e:
        _logger().warning(f"⚠️ [Comes] 构造事件失败，跳过工具执行: {e}")
        return None


# ============================================================
# 钩子本体
# ============================================================


async def activate_capabilities(ctx: ChatContext) -> ChatContext:
    """Router 判定 + 并行激活 Memory / Comes。**绝不抛异常。**

    这是聊天主链路上的钩子。任何异常都必须被吞掉：能力层是增量功能，
    它坏掉的后果应该是「这轮没用上工具」，而不是「Stella 不说话了」。
    """
    s = _settings()

    try:
        from capability.router import route as route_request

        route = await route_request(ctx.message, intent=ctx.intent, trigger=ctx.trigger)
    except Exception as e:
        # route() 内部已有全套降级，走到这里说明 import 或更底层出了问题
        from capability.router.types import default_route

        _logger().warning(f"⚠️ [Router] 路由入口异常，降级为 chat+memory: {e}")
        route = default_route(f"路由入口异常: {e}")
    ctx.route = route

    jobs: list[Any] = []
    labels: list[str] = []

    # 记忆检索：门控默认关闭（见模块 docstring）
    if route.memory or not s.ROUTER_GATE_MEMORY:
        jobs.append(_retrieve_memory(ctx))
        labels.append("memory")
    else:
        _logger().info("🧠 [Router] 判定无需长期记忆，跳过检索（ROUTER_GATE_MEMORY=true）")

    # 工具执行
    if route.tool and s.COMES_ENABLED:
        jobs.append(_run_comes(ctx, route))
        labels.append("comes")

    if not jobs:
        return ctx

    # return_exceptions=True：一条分支炸了不能拖掉另一条。
    # 记忆挂了这轮就少几条记忆，工具挂了这轮就没有工具结果，两者都不该中断回复。
    outcomes = await asyncio.gather(*jobs, return_exceptions=True)
    for label, outcome in zip(labels, outcomes, strict=False):
        if isinstance(outcome, BaseException):
            _logger().warning(f"⚠️ [Capability] {label} 分支异常（已跳过）: {outcome!r}")

    if ctx.tool_summaries:
        _logger().info(
            f"🔧 [Comes] 本轮 {len(ctx.tool_summaries)} 条工具结果将进入 prompt",
        )
    return ctx


def register(pipeline: Any) -> None:
    """把本钩子注册到管线。

    调用方**不要再单独注册 build_user_context**——它已被 activate_capabilities
    接管（否则记忆检索会跑两遍：一次串行、一次在 gather 里）。
    """
    pipeline.register_pre_hook(activate_capabilities, priority=HOOK_PRIORITY)


__all__ = [
    "HOOK_PRIORITY",
    "activate_capabilities",
    "build_tool_tasks",
    "register",
]
