# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Comes：负责执行任务的工具代理（方案第 12 节）。

```
Capability → 找 Provider → 调 Tool → 返回 Result
```

Comes **不负责**理解用户、判断意图、管理人格。它只拿到一个语义层的
``objective``（「查询东京明天天气」），自己决定用哪个 Provider、填什么参数。

## 上下文隔离（方案第 3.1 节的核心）

Comes 用一个**受限 agent** 驱动工具，请求里只有三样东西：

```
COMES_SYSTEM_PROMPT（一句执行器人格）
+ task.objective（一句任务目标）
+ 本次命中能力的 1~3 个工具 schema
```

没有 Stella 的人格，没有聊天上下文，没有其它插件的工具。反过来 Stella 只拿到
``Result.summary``，看不到任何工具 schema、也看不到工具原始返回。两侧的上下文
彻底不共享——这正是整个升级方案要解决的问题。

## 复用而非重写

工具循环用 ``astrbot_compat.llm.agent.run_tool_loop``：它已经实现了参数过滤
（模型会编出 schema 外的参数，直接传给插件会 TypeError）、超时、异步生成器归一、
以及插件依赖的全套生命周期钩子。这些行为是上游多轮实测对齐出来的，重写一定漏。

Comes 只换两样：更小的 ToolSet，和自己的 system prompt。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from capability.comes import summarizer
from capability.registry import (
    KIND_ASTRBOT_TOOL,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry
from core.tasks import Result, ResultStatus, Task


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 router/semantic.py）。"""
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


def _failed(task: Task, reason: str, **meta: Any) -> Result:
    """构造一个失败结果。summary 留空——Stella 不该向用户解释内部故障。"""
    return Result(
        task_id=task.task_id,
        status=ResultStatus.FAILED,
        data=None,
        summary="",
        metadata={"capability": task.capability, "reason": reason, **meta},
    )


# ============================================================
# Provider → ToolSet
# ============================================================


def resolve_tools(
    providers: list[CapabilityProvider],
    tool_manager=None,
) -> tuple[Any, list[str]]:
    """把 provider 列表解析成一个只含它们的 ToolSet。

    返回 ``(ToolSet, 找不到的工具名)``。工具找不到是常态而非异常：
    声明文件里写了 provider 但对应插件没装 / 没启用时就会这样，
    此时应带着剩下的工具继续跑，而不是整个任务失败。
    """
    from astrbot_compat.llm.tool import ToolSet

    manager = tool_manager
    if manager is None:
        from astrbot_compat.llm.tool import llm_tools

        manager = llm_tools

    tool_set = ToolSet()
    missing: list[str] = []
    for provider in providers:
        if provider.kind != KIND_ASTRBOT_TOOL:
            # 其它 kind（MCP / API / native）本轮不实现，见 registry 的 KIND_* 注释
            missing.append(f"{provider.tool_name}({provider.kind} 暂不支持)")
            continue
        tool = manager.get_tool(provider.tool_name)
        if tool is None or not tool.active:
            missing.append(provider.tool_name)
            continue
        tool_set.add_tool(tool)
    return tool_set, missing


def _required_params(tool: Any) -> list[str]:
    """工具 schema 里的必填参数名。"""
    params = getattr(tool, "parameters", None) or {}
    required = params.get("required") or []
    return [str(name) for name in required] if isinstance(required, list) else []


def can_direct_call(tool_set: Any) -> bool:
    """能否跳过 LLM 直接调工具。

    条件：只有一个工具，且它没有必填参数。此时模型唯一能做的就是「调它、不带参数」，
    那一次 27B 往返纯属浪费，且模型还有概率编出多余参数或干脆不调。
    """
    if len(tool_set.tools) != 1:
        return False
    return not _required_params(tool_set.tools[0])


# ============================================================
# 执行
# ============================================================


def _collect_outputs(req: Any) -> list[tuple[str, str]]:
    """从 ProviderRequest 上累积的工具调用结果里取出 ``[(工具名, 输出), ...]``。

    ``run_tool_loop`` 每一轮都会 ``append_tool_calls_result``，所以这里能拿到
    全部轮次的工具原始返回——它就是 ``Result.data``。
    """
    raw = getattr(req, "tool_calls_result", None)
    if not raw:
        return []
    from astrbot_compat.llm.entities import ToolCallsResult

    groups = [raw] if isinstance(raw, ToolCallsResult) else list(raw)
    outputs: list[tuple[str, str]] = []
    for group in groups:
        for block in getattr(group, "tool_calls_result", None) or []:
            outputs.append(
                (str(getattr(block, "name", "") or ""), str(getattr(block, "content", "") or "")),
            )
    return outputs


def _status_for(outputs: list[tuple[str, str]], stopped: bool) -> ResultStatus:
    """按方案第 5 节判定状态——工具调用成功不代表任务成功。"""
    if stopped:
        return ResultStatus.CANCELLED
    if not outputs:
        # 模型一个工具都没调：它认为不需要，或没理解目标。都算任务没完成。
        return ResultStatus.FAILED
    failures = sum(1 for _, content in outputs if summarizer.is_error(content))
    if failures == 0:
        return ResultStatus.SUCCESS
    if failures == len(outputs):
        return ResultStatus.FAILED
    return ResultStatus.PARTIAL


async def _direct_call(task: Task, tool: Any, event: Any, timeout: float) -> list[tuple[str, str]]:
    """无参直调：绕过 LLM 直接执行工具，返回与 _collect_outputs 同形状的输出。"""
    from astrbot_compat.llm.agent import execute_tool

    content = await execute_tool(tool, event, dict(task.input or {}), timeout)
    return [(tool.name, content)]


async def _agent_call(
    task: Task,
    tool_set: Any,
    event: Any,
    session_id: str,
) -> tuple[str, list[tuple[str, str]]]:
    """受限 agent 调用：返回 ``(agent 的结论文本, 工具输出列表)``。"""
    from astrbot_compat.llm.agent import run_tool_loop
    from astrbot_compat.llm.entities import ProviderRequest
    from astrbot_compat.llm.manager import get_provider_manager

    s = _settings()
    provider = get_provider_manager().provider
    if provider is None:
        raise RuntimeError("LLM 未启用（ASTRBOT_LLM_ENABLED=false），Comes 无法驱动工具")

    req = ProviderRequest(
        prompt=_build_objective_prompt(task),
        session_id=session_id,
        func_tool=tool_set,
        system_prompt=s.COMES_SYSTEM_PROMPT,
    )
    resp = await run_tool_loop(
        provider,
        req,
        event,
        max_steps=s.COMES_MAX_TOOL_STEPS,
        tool_timeout=s.COMES_TOOL_TIMEOUT,
    )
    return (getattr(resp, "completion_text", "") or ""), _collect_outputs(req)


def _build_objective_prompt(task: Task) -> str:
    """把 objective 与已知槽位拼成给受限 agent 的一句任务描述。

    带上 ``task.input`` 是有价值的：Router 若已经从消息里认出了城市名，
    直接给出来比让模型再猜一遍更准。
    """
    objective = (task.objective or "").strip() or f"执行能力 {task.capability}"
    if not task.input:
        return objective
    slots = "，".join(f"{k}={v}" for k, v in task.input.items())
    return f"{objective}\n已知信息：{slots}"


def _record_health(
    providers: list[CapabilityProvider],
    outputs: list[tuple[str, str]],
) -> None:
    """按工具级别的成败更新 provider 健康度。

    只对**本次真的被调用过**的工具记账：模型没选中的 provider 既不算成功也不算失败，
    给它记账会让「一直没被选中」慢慢累积成退避。

    退避的意义：一个插件依赖的外部 API 挂了之后，它每次都会占掉一次 27B 往返再失败。
    连续失败到阈值后暂时把它摘掉，能力的其它 provider（如果有）就能顶上。
    """
    s = _settings()
    by_tool = {p.tool_name: p for p in providers if p.tool_name}
    called = [name for name, _ in outputs if name in by_tool]
    if not called:
        return

    failed = {name for name, content in outputs if summarizer.is_error(content)}
    for name in set(called):
        provider = by_tool.get(name)
        if provider is None:
            continue
        if name in failed:
            if provider.mark_failure(
                s.COMES_PROVIDER_FAILURE_THRESHOLD,
                s.COMES_PROVIDER_RECOVER_SECONDS,
            ):
                _logger().warning(
                    f"⚠️ [Comes] provider {provider.provider_id} 连续失败 "
                    f"{provider.failures} 次，暂时退避 "
                    f"{s.COMES_PROVIDER_RECOVER_SECONDS:.0f}s",
                )
        else:
            provider.mark_success()


async def execute(
    task: Task,
    *,
    event: Any,
    target: CapabilityRegistry | None = None,
    tool_manager=None,
) -> Result:
    """执行一个 ``tool.execute`` 任务。**任何情况下都返回 Result，绝不抛异常。**

    参数:
        task: 待执行任务，``capability`` 必填；
        event: AstrMessageEvent。工具 handler 内部会用 ``event.send`` /
            ``event.bot.call_action``，必须是真实事件对象；
        target: 能力注册表，缺省用模块级单例；
        tool_manager: 工具注册表（测试注入点），缺省用 ``llm_tools``。
    """
    s = _settings()
    reg = target if target is not None else _default_registry
    started = time.monotonic()

    if not s.COMES_ENABLED:
        return _failed(task, "Comes 未启用")
    if event is None:
        # 工具 handler 普遍依赖 event（发消息、取群号、调 OneBot API），没有它无法执行
        return _failed(task, "缺少事件对象，无法执行工具")

    capability = reg.get(task.capability)
    if capability is None:
        return _failed(task, f"能力 {task.capability} 未注册")

    providers = capability.enabled_providers()
    if not providers:
        return _failed(task, f"能力 {task.capability} 没有可用 provider")

    tool_set, missing = resolve_tools(providers, tool_manager)
    if missing:
        _logger().warning(
            f"⚠️ [Comes] 能力 {task.capability} 的部分工具不可用（插件未装/未启用）: {missing}",
        )
    if tool_set.empty():
        return _failed(task, f"能力 {task.capability} 的工具全部不可用", missing=missing)

    used_direct = False
    try:
        if s.COMES_DIRECT_CALL_NO_ARGS and can_direct_call(tool_set):
            used_direct = True
            completion = ""
            outputs = await asyncio.wait_for(
                _direct_call(task, tool_set.tools[0], event, s.COMES_TOOL_TIMEOUT),
                timeout=s.COMES_TASK_TIMEOUT,
            )
        else:
            completion, outputs = await asyncio.wait_for(
                _agent_call(task, tool_set, event, _session_of(event)),
                timeout=s.COMES_TASK_TIMEOUT,
            )
    # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
    # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接。
    except asyncio.TimeoutError:
        _logger().warning(f"⚠️ [Comes] 任务 {task.task_id} 超时（{s.COMES_TASK_TIMEOUT}s）")
        return _failed(
            task,
            f"任务超时（{s.COMES_TASK_TIMEOUT}s）",
            elapsed=round(time.monotonic() - started, 3),
        )
    except Exception as e:
        _logger().exception(f"❌ [Comes] 任务 {task.task_id} 执行异常")
        return _failed(
            task,
            f"执行异常: {e}",
            elapsed=round(time.monotonic() - started, 3),
        )

    stopped = bool(getattr(event, "is_stopped", lambda: False)())
    status = _status_for(outputs, stopped)
    elapsed = time.monotonic() - started
    _record_health(providers, outputs)

    # summary 只在任务成功时产出。这条不变量必须由 Result 自己保证，
    # 而不是靠每个消费方记得先查 .ok：
    # 任务失败时 completion 往往是受限 agent 的自言自语（「我觉得不用查」），
    # 它会被 _tool_result_section 冠上「刚刚查到的信息（真实数据）」的标题送给
    # Stella，于是 Stella 把执行器的嘟囔当成事实转述给用户。
    # 失败时模型说了什么留在 metadata 里，够排查用。
    if status in (ResultStatus.SUCCESS, ResultStatus.PARTIAL):
        summary = summarizer.summarize(completion, outputs, s.COMES_SUMMARY_MAX_CHARS)
        # 工具跑了、也没报错，但没有可转述的内容（典型是工具直接给用户发了图片）。
        # 不算失败，但 Stella 拿不到素材。
        if not summary:
            _logger().info(
                f"🔧 [Comes] 任务 {task.task_id}（{task.capability}）执行成功但无可转述内容",
            )
    else:
        summary = ""

    result = Result(
        task_id=task.task_id,
        status=status,
        data=outputs,
        summary=summary,
        metadata={
            "capability": task.capability,
            "tools": tool_set.names(),
            "direct_call": used_direct,
            "steps": len(outputs),
            "missing": missing,
            "elapsed": round(elapsed, 3),
            # 失败时保留模型原话，供排查「它为什么没调工具」
            **({} if status in (ResultStatus.SUCCESS, ResultStatus.PARTIAL) else {
                "model_text": (completion or "")[:200],
            }),
        },
    )
    _logger().info(
        f"🔧 [Comes] {task.capability} → {status.value} "
        f"({elapsed * 1000:.0f}ms, {'直调' if used_direct else 'agent'}, "
        f"{len(outputs)} 次工具调用) summary={summary[:60]!r}",
    )
    return result


def _session_of(event: Any) -> str:
    """取事件的会话标识，供 provider 记账；取不到就用空串。"""
    try:
        return str(event.unified_msg_origin or "")
    except Exception:
        return ""


__all__ = ["can_direct_call", "execute", "resolve_tools"]
