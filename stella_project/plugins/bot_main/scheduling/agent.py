# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""有界 Agent 运行器：调度任务的后台模型/工具执行（计划 §6.6）。

刻意**不复用** ``astrbot_compat.llm.agent.run_tool_loop``（GitNexus 影响面
HIGH：它被 provider request / COMES / probe / context agent 四处共享，且总在
执行全局钩子——PDG 结论：``hooks=None`` 只免 per-run 钩子，免不了全局钩子）。
本运行器是独立的最小循环：

- **无事件**：工具经 :meth:`FunctionTool.call` 直呼（MCP 工具本就不依赖事件），
  绝不构造 NoneBot/AstrBot 事件，不碰 COMES；
- **无钩子**：不注册、不触发任何 agent 钩子与插件事件（有测试钉住）；
- **四重上限**：墙钟 deadline、模型轮数、逻辑工具调用数、输出字符数；
- **显式允许清单**：只解析任务策略里列出的工具名，解析不到/指纹漂移即剔除；
  动态工具发现在结构上不可能发生（本模块不调用任何 tools/list）。

provider 闸门**不在**本模块获取：provider 的 ``text_chat`` 内部自取既有端点
闸门（计划 §5），这里再包一层 acquire 就是双重持有（队头阻塞）。本模块只做
逻辑调用计数与预算预检（ ``usage_check`` 注入，默认读 ``budget_blocked``）。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from astrbot_compat.llm.entities import (
    AssistantMessageSegment,
    ProviderRequest,
    ToolCallsResult,
)
from astrbot_compat.llm.message import ToolCallMessageSegment
from astrbot_compat.llm.tool import FunctionTool, ToolSet

# 必须写 asyncio.TimeoutError 而不是内置 TimeoutError：Python 3.10 下两者是
# 不相干的类（3.11 起才合并），写内置的在 3.10 上漏接（与 agent.py 同款注释）。

DEFAULT_TOOL_TIMEOUT_SECONDS = 60.0


class TaskCancelledError(Exception):
    """取消检查点抛出：任务被暂停/取消或修订过期，立即放弃本轮。"""


@dataclass(slots=True)
class AgentRunLimits:
    """一次运行的四重上限（默认值取 Task 行上的配置，实例化时由调用方填充）。"""

    max_model_rounds: int = 4
    max_tool_calls: int = 8
    wall_clock_seconds: float = 300.0
    output_max_chars: int = 1200
    tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS


@dataclass(slots=True)
class AgentOutcome:
    """运行结果。``status`` 取值见 :class:`RunState` 语义：

    - ``completed``：有产出（text 可能为空——空文本由投递层按 notification
      mode 判 silent）；
    - ``failed``：provider/工具不可用、轮数耗尽不收敛等；
    - ``timeout``：墙钟超时；
    - ``cancelled``：取消检查点命中。

    ``denied_tools`` 记录「模型想调但被拒/被剔除」的工具名与原因（观测用，
    不含参数与返回内容）。
    """

    status: str
    text: str = ""
    model_rounds: int = 0
    tool_calls: int = 0
    error: str = ""
    output_truncated: bool = False
    denied_tools: list[str] = field(default_factory=list)


# provider 解析：返回带 ``text_chat`` 的 provider；None = 没有可用 provider
ProviderResolver = Callable[[], Awaitable[Any | None]]
# 工具解析：按**策略里显式列出的名字**解析；None = 不在清单/不可用/未批准
ToolResolver = Callable[[str], Awaitable[FunctionTool | None]]
# 取消检查点：命中时抛 :class:`TaskCancelledError`（运行时提供实现）
CancelCheck = Callable[[], Awaitable[None]]
# 预算预检：返回 None 放行，返回字符串 = 拒绝原因
UsageCheck = Callable[[], str | None]


def schema_fingerprint(schema: Any) -> str:
    """工具 schema 的稳定指纹（canonical JSON 的 sha256 前 16 位）。

    管理员批准工具时可把当时的指纹记进策略（``tool_fingerprints``）；运行时
    漂移 → 视为未批准（服务端改了参数语义，静默放行等于未授权的调用面）。
    """
    canonical = json.dumps(schema or {}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _default_usage_check() -> str | None:
    from core.llm.usage_store import budget_blocked

    return budget_blocked("chat")


class ScheduledAgentRunner:
    """每个调度库一个实例即可（无状态；依赖经构造注入以便替换与测试）。"""

    def __init__(
        self,
        *,
        provider_resolver: ProviderResolver,
        tool_resolver: ToolResolver,
        cancel_check: CancelCheck | None = None,
        usage_check: UsageCheck | None = None,
    ) -> None:
        self._provider_resolver = provider_resolver
        self._tool_resolver = tool_resolver
        self._cancel_check = cancel_check
        self._usage_check = usage_check or _default_usage_check

    async def run(
        self,
        *,
        task_id: str,
        run_id: str,
        objective: str,
        policy: dict,
        context_text: str,
        limits: AgentRunLimits,
        cancel_check: CancelCheck | None = None,
    ) -> AgentOutcome:
        """执行一次 Agent 任务。**绝不抛异常**：一切失败都折进 outcome。

        ``cancel_check``：运行期注入的取消检查点（运行时按运行/任务当前状态
        判定），与构造期传入的检查点并存。
        """
        try:
            return await asyncio.wait_for(
                self._run_inner(
                    task_id=task_id,
                    run_id=run_id,
                    objective=objective,
                    policy=policy,
                    context_text=context_text,
                    limits=limits,
                    cancel_check=cancel_check,
                ),
                timeout=max(limits.wall_clock_seconds, 1.0),
            )
        except TaskCancelledError:
            return AgentOutcome(status="cancelled")
        except asyncio.TimeoutError:
            return AgentOutcome(status="timeout", error="wall_clock_exceeded")
        except Exception as e:  # 兜底：调度链路不允许后台异常冒泡
            return AgentOutcome(status="failed", error=f"{type(e).__name__}: {e}")

    # ── 内部 ─────────────────────────────────────────────
    async def _run_inner(
        self,
        *,
        task_id: str,
        run_id: str,
        objective: str,
        policy: dict,
        context_text: str,
        limits: AgentRunLimits,
        cancel_check: CancelCheck | None = None,
    ) -> AgentOutcome:
        denied: list[str] = []
        extra_check = cancel_check or self._cancel_check

        async def checkpoint() -> None:
            await self._checkpoint()
            if extra_check is not None:
                await extra_check()

        budget_reason = self._safe_usage_check()
        if budget_reason:
            return AgentOutcome(status="failed", error=f"budget_blocked: {budget_reason}")

        provider = await self._provider_resolver()
        if provider is None or not hasattr(provider, "text_chat"):
            return AgentOutcome(status="failed", error="provider_unavailable")

        tool_set, denied = await self._resolve_tools(policy)
        if policy.get("tools") and tool_set.empty():
            # 管理员配了工具但一个都解析不出来：显式失败而不是静默裸跑
            return AgentOutcome(
                status="failed", error="tools_unavailable", denied_tools=denied
            )

        await checkpoint()

        req = ProviderRequest(
            prompt=_build_user_content(objective, context_text),
            session_id=f"scheduling:{task_id}:{run_id}",
            system_prompt=_SYSTEM_PROMPT,
        )
        if req.prompt:
            req.contexts = [await req.assemble_context()]

        outcome = AgentOutcome(status="failed", error="max_model_rounds")
        for _round in range(max(limits.max_model_rounds, 1)):
            await checkpoint()
            outcome.model_rounds = _round + 1
            resp = await provider.text_chat(
                session_id=req.session_id,
                func_tool=tool_set if not tool_set.empty() else None,
                contexts=req.contexts,
                system_prompt=req.system_prompt,
                tool_calls_result=req.tool_calls_result,
                model=req.model,
            )
            if not resp.tools_call_name:
                text = (resp.completion_text or "").strip()
                if len(text) > limits.output_max_chars:
                    text = text[: limits.output_max_chars]
                    outcome.output_truncated = True
                outcome.status = "completed"
                outcome.text = text
                outcome.error = ""
                outcome.denied_tools = denied
                return outcome

            if tool_set.empty():
                # 模型没有可用工具却要调工具：回喂错误让它直接作答
                req.append_tool_calls_result(
                    ToolCallsResult(
                        AssistantMessageSegment(
                            content=resp.completion_text or None,
                            tool_calls=resp.to_openai_tool_calls_model(),
                        ),
                        [
                            _tool_message(
                                _arg(resp.tools_call_ids, i),
                                name,
                                "error: 没有可用的工具，请直接根据已知信息作答",
                            )
                            for i, name in enumerate(resp.tools_call_name)
                        ],
                    )
                )
                continue

            blocks: list[ToolCallMessageSegment] = []
            for idx, name in enumerate(resp.tools_call_name):
                call_id = _arg(resp.tools_call_ids, idx)
                raw_args = _arg(resp.tools_call_args, idx) or {}
                if outcome.tool_calls >= limits.max_tool_calls:
                    outcome.error = "max_tool_calls"
                    outcome.denied_tools = denied
                    return outcome
                tool = tool_set.get_tool(name)
                if tool is None:
                    denied.append(f"{name}:not_allowed")
                    blocks.append(
                        _tool_message(
                            call_id,
                            name,
                            f"error: 工具 {name} 不在允许清单中。可用工具: "
                            f"{tool_set.names() or '（无）'}",
                        )
                    )
                    continue
                await checkpoint()
                outcome.tool_calls += 1
                content = await _execute_tool(tool, raw_args, limits.tool_timeout_seconds)
                blocks.append(_tool_message(call_id, name, content))
            req.append_tool_calls_result(
                ToolCallsResult(
                    AssistantMessageSegment(
                        content=resp.completion_text or None,
                        tool_calls=resp.to_openai_tool_calls_model(),
                    ),
                    blocks,
                )
            )
        outcome.denied_tools = denied
        return outcome

    async def _resolve_tools(self, policy: dict) -> tuple[ToolSet, list[str]]:
        tool_set = ToolSet()
        denied: list[str] = []
        fingerprints = policy.get("tool_fingerprints") or {}
        for name in policy.get("tools") or []:
            try:
                tool = await self._tool_resolver(str(name))
            except Exception:
                tool = None
            if tool is None:
                denied.append(f"{name}:unavailable")
                continue
            expected = fingerprints.get(str(name))
            if expected and schema_fingerprint(getattr(tool, "parameters", {})) != expected:
                denied.append(f"{name}:schema_drift")
                continue
            tool_set.add_tool(tool)
        return tool_set, denied

    async def _checkpoint(self) -> None:
        if self._cancel_check is None:
            return
        await self._cancel_check()

    def _safe_usage_check(self) -> str | None:
        try:
            return self._usage_check()
        except Exception:
            return None  # 预检查挂了不放行为失败：provider 调用仍受端点闸门保护


def _arg(seq: list | None, idx: int) -> Any:
    return seq[idx] if seq and idx < len(seq) else ""


def _tool_message(call_id: str, name: str, content: str) -> ToolCallMessageSegment:
    return ToolCallMessageSegment(tool_call_id=call_id, name=name, content=content)


async def _execute_tool(tool: FunctionTool, args: dict, timeout: float) -> str:
    """受限执行：无事件、无钩子、超时受控；结果归一为回喂文本（已脱敏）。"""
    try:
        result = tool.call(None, **dict(args or {}))
        if inspect.isawaitable(result):
            result = await result
        result = await asyncio.wait_for(
            _drain(result), timeout=max(timeout, 1.0)
        )
    except asyncio.TimeoutError:
        return f"error: tool {tool.name} timed out after {timeout}s"
    except Exception as e:
        return f"error: tool {tool.name} failed: {e}"
    if isinstance(result, str) and result:
        return result
    if result is None:
        return "error: 工具没有返回内容"
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


async def _drain(result: Any) -> Any:
    """消费 asyncgen 返回值（MCP 工具不会流式，这里只为契约完整）。"""
    if inspect.isasyncgen(result):
        last = None
        async for item in result:
            last = item
        return last
    return result


def _build_user_content(objective: str, context_text: str) -> str:
    parts = [f"请完成这个预约任务：{objective}"]
    if context_text:
        parts.append(f"群近期上下文（仅供参考）：\n{context_text}")
    parts.append(
        "直接输出要发送到群里的简短内容（1~3 句，口语自然，不要自称 AI，"
        "不要编造没有的消息）。如果没有值得发的内容，只输出空。"
    )
    return "\n\n".join(parts)


_SYSTEM_PROMPT = (
    "你是 Stella，正在执行一个用户预约的定时任务。你的输出会被原样发送到群聊。"
    "遵守目标即可，不要闲聊，不要暴露任务机制。"
)

__all__ = [
    "DEFAULT_TOOL_TIMEOUT_SECONDS",
    "AgentOutcome",
    "AgentRunLimits",
    "ScheduledAgentRunner",
    "TaskCancelledError",
    "schema_fingerprint",
]
