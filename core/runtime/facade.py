# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""RuntimeFacade：统一入口 owner 与轮次执行（计划修订 v2：纯 Python 运行时，§R.5 后唯一引擎）。

- **唯一入口 owner**：每会话一把提交锁 + owner_epoch（reset 递增作废旧上下文）。
- 轮次生命周期：``accepted → prepared → generating → completed|failed|cancelled``，
  投递状态另记（generated ≠ delivered）；独立 JSONL 运行记录（不进记忆库）。
- **执行器为进程内 asyncio**：prepare/finalize 是 M2 的阶段服务；GENERATE 的
  生成就是一次 provider 调用（默认 = 真实 CHAT 角色后端），deadline/cancel
  用 asyncio 原生语义。无跨进程桥、无 Node 依赖（计划 §R.2）。
- 决策语义与 legacy 逐条对齐：DIRECT/SILENT **不执行** finalize（直回/WAIT
  早退，post hooks 不跑、silent 不得被补成兜底）；BUDGET_LIMITED/NO_BACKEND
  本地 finalize 产兜底 lines；provider 异常与超时都按 BC-5 兜底（与 legacy
  pipeline 内部 catch 行为一致），只有取消以异常上抛（调用方需要区分）。
- reset **不取**提交锁：submit 在锁内等待 provider，reset 若在同一把锁后排队
  就永远取消不掉它（§9 预警的锁重入死锁，实施中实际触发过一次）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.context import ChatContext
from core.runtime.turn_service import (
    BUDGET_LIMITED,
    DIRECT,
    GENERATE,
    NO_BACKEND,
    SILENT,
    TurnService,
    pending_system_prompt,
)

DEFAULT_TURN_DEADLINE = 120.0  # 与 WebChat 120s 对齐

# ---- 错误码（保留原协议错误码语义；不再有线协议） ----
E_CANCELLED = "E_CANCELLED"
E_KEY = "E_KEY"


class RuntimeTurnError(RuntimeError):
    """facade 发起的轮次失败（取消/fence），``code`` 为 E_* 常量。

    继承 RuntimeError：chat 路由对 RuntimeError 产出 SSE error 帧
    （Q-2 契约），reset 取消的轮次因此能向面板返回明确错误而非断流。
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


ProviderFn = Any  # async (key: str, prompt: str) -> str


def _detail_on(ctx: ChatContext) -> bool:
    """detailed 档按群显式开启（计划 §6.8）；关闭时只走 metadata 档。"""
    try:
        from core.observability import turn_trace

        return turn_trace.detailed_enabled_for_scope(ctx.trace_scope)
    except Exception:
        return False


def _trace(**kw: Any) -> None:
    """轮次生命周期追踪（计划 §6.8）：旁路写入，任何失败不影响轮次。"""
    try:
        from core.observability import turn_trace

        turn_trace.record_event(**kw)
    except Exception:
        pass


def _flow_ctx(ctx: ChatContext) -> Any:
    """消息流程 context（计划 §6.2）：入口未建 root / 已结束时为 None，
    后续 span/decision 全部空转——观测绝不伪造未发生的事实。"""
    try:
        from core.observability import message_flow

        found = message_flow.flow_of(ctx)
        return None if (found is None or found.ended) else found
    except Exception:
        return None


def _flow_span(fctx: Any, node_id: str, **kw: Any) -> Any:
    """开一个流程 span（fail-open：观测模块不可用时返回空上下文管理器）。"""
    try:
        from core.observability import message_flow

        return message_flow.span(fctx, node_id, **kw)
    except Exception:
        return contextlib.nullcontext()


def _flow_decision(fctx: Any, node_id: str, **kw: Any) -> None:
    try:
        from core.observability import message_flow

        message_flow.decision(fctx, node_id, **kw)
    except Exception:
        pass


def _flow_transition(fctx: Any, *, from_node: str, to_node: str, **kw: Any) -> None:
    """显式边级跳转事实（修复计划 §6.4）：由真实控制边界调用，fail-open。"""
    try:
        from core.observability import message_flow

        message_flow.transition(fctx, from_node=from_node, to_node=to_node, **kw)
    except Exception:
        pass


@dataclass
class KeyState:
    """每会话状态：提交锁 + owner_epoch + 最近轮次 + 在途任务句柄。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    owner_epoch: int = 0
    last_turn_id: str = ""
    inflight: asyncio.Task | None = None
    cancel_requested: bool = False


@dataclass
class TurnRecord:
    """一次轮次的运行记录（独立存储，不进记忆库）。"""

    turn_id: str
    key: str
    owner_epoch: int
    outcome: str
    state: str
    started_at: float
    trace_id: str = ""  # 接入入口创建的追踪 ID（社交闭环贯通用，计划 §6.1）
    finished_at: float | None = None
    detail: dict[str, Any] | None = None


class RuntimeStore:
    """JSONL append-only 运行记录；文件损坏只影响历史读取，不阻断运行。"""

    def __init__(self, path: Path):
        self._path = path

    def record(self, rec: TurnRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec.__dict__, ensure_ascii=False) + "\n")
        except Exception:
            pass


async def _pipeline_provider(
    pipeline: "TurnService", key: str, prompt: str, ctx: ChatContext
) -> str:
    """默认 provider：**传入管线自身的 LLM 后端**（生产装配下即 CHAT 角色后端）。

    系统提示词取 prepare_turn 暂存在 ctx 上的那份（经 system_prompt_resolver
    按空间解析过）。生成不传它，人格、长度上限与 XML 输出格式约束就全部
    失效（2026-09-27 缺陷：facade 生成丢系统提示词，回复超长且无结构）。

    不经旧 Pipeline 编排，也不引入额外注册表查询——测试用 stub 管线时,
    脚本化后端因此自然生效。"""
    return await pipeline._llm.generate(prompt, pending_system_prompt(ctx))  # type: ignore[union-attr]


class RuntimeFacade:
    """统一 submit/cancel/drain/reset/health；持有唯一入口互斥策略。"""

    def __init__(
        self,
        *,
        provider: ProviderFn | None = None,
        store: RuntimeStore | None = None,
        default_deadline: float = DEFAULT_TURN_DEADLINE,
    ) -> None:
        # provider 缺省 = 传入管线自身的 LLM 后端（见 _pipeline_provider）
        self._provider: ProviderFn = provider
        self._store = store
        self._default_deadline = default_deadline
        self._keys: dict[str, KeyState] = {}

    # ---- 生命周期（进程内执行器：无子进程，保持调用面不变） ----

    async def start(self) -> dict[str, Any]:
        return self.health()

    async def stop(self) -> None:
        for state in self._keys.values():
            if state.inflight is not None and not state.inflight.done():
                state.cancel_requested = True
                state.inflight.cancel()

    def health(self) -> dict[str, Any]:
        return {
            "mode": "native",
            "keys": sorted(self._keys),
            "inflight": sum(1 for s in self._keys.values() if s.inflight and not s.inflight.done()),
        }

    # ---- 内部 ----

    def _key_state(self, key: str) -> KeyState:
        found = self._keys.get(key)
        if found is None:
            found = KeyState()
            self._keys[key] = found
        return found

    def _record(self, **kw: Any) -> None:
        if self._store is not None:
            self._store.record(TurnRecord(**kw))

    async def _ensure_epoch(self, state: KeyState) -> int:
        if state.owner_epoch == 0:
            state.owner_epoch = 1
        return state.owner_epoch

    def delivery_is_current(self, key: str, turn_id: str, owner_epoch: int) -> bool:
        """同步发送围栏：只允许当前未复位、未被新轮次取代的输出继续发送。"""
        state = self._keys.get(key)
        return bool(
            state is not None
            and state.last_turn_id == turn_id
            and state.owner_epoch == owner_epoch
        )

    # ---- 轮次提交 ----

    async def submit_turn(
        self,
        key: str,
        pipeline: TurnService,
        ctx: ChatContext,
        *,
        deadline: float | None = None,
    ) -> ChatContext:
        """完整轮次：prepare → 决策分流 → （GENERATE）进程内生成 → finalize。"""
        state = self._key_state(key)
        async with state.lock:
            fctx = _flow_ctx(ctx)
            turn_id = uuid.uuid4().hex
            state.last_turn_id = turn_id
            started = time.time()
            # 身份贯通：trace_id 缺失时补一个（入口未建的静默路径也可追溯）；
            # turn_id 写回 ctx，投递回执与效果观察用它关联本轮（计划 §6.1）。
            with _flow_span(fctx, "turn.identity"):
                if not ctx.trace_id:
                    ctx.trace_id = uuid.uuid4().hex
                ctx.turn_id = turn_id
            epoch_before = await self._ensure_epoch(state)
            ctx.runtime_key = key
            ctx.generation_epoch = epoch_before
            self._record(
                turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=epoch_before,
                outcome="", state="accepted", started_at=started,
            )
            _trace(
                trace_id=ctx.trace_id, turn_id=turn_id, stage="ingress",
                status="accepted", scope=ctx.trace_scope, started_at=started,
                versions={"projection": ctx.PROJECTION_SCHEMA_VERSION},
                detailed={"key": key, "user_id": ctx.user_id,
                          "trigger": ctx.trigger, "intent": ctx.intent}
                if _detail_on(ctx) else None,
            )
            with _flow_span(fctx, "turn.prepare"):
                plan = await pipeline.prepare_turn(ctx)
            # fence：prepare 期间发生 reset → 本轮作废（epoch 已被推进）
            if state.owner_epoch != epoch_before:
                self._record(
                    turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=epoch_before,
                    outcome="cancelled", state="cancelled", started_at=started,
                    finished_at=time.time(), detail={"reason": "reset during prepare"},
                )
                _trace(trace_id=ctx.trace_id, turn_id=turn_id, stage="prepare",
                       status="cancelled", reason_code="reset_during_prepare",
                       scope=ctx.trace_scope, started_at=started)
                _flow_decision(fctx, "turn.cancel", status="cancelled",
                               reason_code="reset_during_prepare")
                _flow_transition(fctx, from_node="turn.prepare",
                                 to_node="turn.cancel", relation_kind="condition",
                                 status="cancelled")
                raise RuntimeTurnError(E_CANCELLED, "prepare 期间发生 reset，本轮作废")
            self._record(
                turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                outcome=plan.outcome, state="prepared", started_at=started,
            )
            _trace(
                trace_id=ctx.trace_id, turn_id=turn_id, stage="prepare",
                status=plan.outcome, scope=ctx.trace_scope, started_at=started,
                metrics={"llm_call_count": ctx.llm_call_count},
            )

            if plan.outcome == GENERATE:
                ctx.delivery_source_kind = "model"
                prompt = ctx.prompt_log
                provider = self._provider or _pipeline_provider
                state.cancel_requested = False
                _flow_transition(fctx, from_node="turn.prepare", to_node="turn.generate")
                # 与 legacy generate_reply 同口径：进入生成即计一次调用、记耗时
                # （prepare 的调用上限守卫与 thought 日志的「耗时」字段都依赖它们）。
                ctx.llm_call_count += 1
                gen_started = time.monotonic()
                gen_span = _flow_span(fctx, "turn.generate")
                gen_span.__enter__()
                task = asyncio.create_task(provider(key, prompt) if self._provider
                                           else _pipeline_provider(pipeline, key, prompt, ctx))
                state.inflight = task
                try:
                    text = await asyncio.wait_for(
                        task, timeout=deadline or self._default_deadline
                    )
                except asyncio.TimeoutError:
                    # 有界失败：deadline 按 legacy 超时语义兜底（BC-5），不悬挂
                    gen_span.__exit__(asyncio.TimeoutError, None, None)
                    _flow_decision(fctx, "turn.timeout", status="timed_out",
                                   reason_code="provider_deadline")
                    _flow_transition(fctx, from_node="turn.generate",
                                     to_node="turn.timeout", relation_kind="condition",
                                     status="timed_out")
                    ctx.llm_elapsed = time.monotonic() - gen_started
                    ctx.delivery_source_kind = "trusted-server-fallback"
                    ctx.raw_output = "<thought>卡顿了一下</thought><action>NONE</action><reply>......？</reply>"
                    self._record(
                        turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                        outcome=plan.outcome, state="deadline_fallback",
                        started_at=started, finished_at=time.time(),
                    )
                    _trace(trace_id=ctx.trace_id, turn_id=turn_id,
                           stage="model_attempt", status="deadline_fallback",
                           reason_code="timeout", attempt=1,
                           metrics={"elapsed": ctx.llm_elapsed},
                           scope=ctx.trace_scope, started_at=started)
                    return await pipeline.finalize_turn(ctx)
                except asyncio.CancelledError:
                    gen_span.__exit__(asyncio.CancelledError, None, None)
                    if state.cancel_requested:
                        self._record(
                            turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                            outcome="cancelled", state="cancelled", started_at=started,
                            finished_at=time.time(),
                        )
                        _trace(trace_id=ctx.trace_id, turn_id=turn_id,
                               stage="model_attempt", status="cancelled",
                               reason_code="cancel_requested", attempt=1,
                               scope=ctx.trace_scope, started_at=started)
                        _flow_decision(fctx, "turn.cancel", status="cancelled",
                                       reason_code="cancel_requested")
                        _flow_transition(fctx, from_node="turn.generate",
                                         to_node="turn.cancel", relation_kind="condition",
                                         status="cancelled")
                        raise RuntimeTurnError(E_CANCELLED, "轮次已被取消") from None
                    _flow_decision(fctx, "turn.cancel", status="cancelled",
                                   reason_code="external_cancel")
                    _flow_transition(fctx, from_node="turn.generate",
                                     to_node="turn.cancel", relation_kind="condition",
                                     status="cancelled")
                    raise  # 外部取消（调用方断开等）：原样传播
                except Exception as e:
                    # provider 异常：与 legacy pipeline 内部 catch 一致（BC-5）——
                    # 兜底而非上抛，不让异常击穿消息链路
                    gen_span.__exit__(type(e), e, e.__traceback__)
                    _flow_decision(fctx, "turn.error", status="failed",
                                   reason_code="provider_error")
                    _flow_transition(fctx, from_node="turn.generate",
                                     to_node="turn.error", relation_kind="condition",
                                     status="failed")
                    ctx.llm_elapsed = time.monotonic() - gen_started
                    ctx.delivery_source_kind = "trusted-server-fallback"
                    ctx.raw_output = "<thought>系统异常</thought><action>NONE</action><reply>......？</reply>"
                    self._record(
                        turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                        outcome=plan.outcome, state="provider_fallback",
                        started_at=started, finished_at=time.time(),
                    )
                    _trace(trace_id=ctx.trace_id, turn_id=turn_id,
                           stage="model_attempt", status="provider_fallback",
                           reason_code="provider_error", attempt=1,
                           metrics={"elapsed": ctx.llm_elapsed},
                           scope=ctx.trace_scope, started_at=started)
                    return await pipeline.finalize_turn(ctx)
                finally:
                    state.inflight = None
                gen_span.__exit__(None, None, None)
                _flow_transition(fctx, from_node="turn.generate",
                                 to_node="turn.generated")
                _flow_decision(fctx, "turn.generated", status="succeeded",
                               metrics={"elapsed_ms": round(
                                   (time.monotonic() - gen_started) * 1000.0, 1)})
                ctx.llm_elapsed = time.monotonic() - gen_started
                ctx.raw_output = str(text)
                self._record(
                    turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                    outcome=plan.outcome, state="completed", started_at=started,
                    finished_at=time.time(),
                )
                _trace(trace_id=ctx.trace_id, turn_id=turn_id,
                       stage="model_attempt", status="completed", attempt=1,
                       metrics={"elapsed": ctx.llm_elapsed},
                       scope=ctx.trace_scope, started_at=started,
                       detailed={"prompt_chars": len(prompt),
                                 "output_chars": len(ctx.raw_output)}
                       if _detail_on(ctx) else None)
                return await pipeline.finalize_turn(ctx)

            if plan.outcome in (DIRECT, SILENT):
                # 与 legacy 直回/WAIT 早退语义一致——不执行 finalize
                # （post hooks 不跑，silent 不得被补成兜底 lines）；生命周期照记。
                if plan.outcome == DIRECT:
                    from core.social.delivery import delivery_draft_from_context

                    ctx.delivery_draft = delivery_draft_from_context(ctx)
                else:
                    ctx.delivery_draft = {}
                ctx.delivery_plan = {}
                _flow_decision(fctx, "turn.direct_silent", status="skipped",
                               reason_code=plan.outcome)
                self._record(
                    turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                    outcome=plan.outcome, state="completed", started_at=started,
                    finished_at=time.time(),
                )
                return plan.ctx

            # BUDGET_LIMITED / NO_BACKEND：本地路径（无生成），仍产兜底 lines
            if plan.outcome in (BUDGET_LIMITED, NO_BACKEND):
                ctx.delivery_source_kind = "trusted-server-fallback"
            _flow_decision(fctx, "turn.fallback", status="blocked",
                           reason_code=plan.outcome)
            if plan.outcome == BUDGET_LIMITED:
                ctx.llm_backend = pipeline._llm.backend_name  # type: ignore[union-attr]
            self._record(
                turn_id=turn_id, key=key, trace_id=ctx.trace_id, owner_epoch=state.owner_epoch,
                outcome=plan.outcome, state="completed_local", started_at=started,
                finished_at=time.time(),
            )
            return await pipeline.finalize_turn(ctx)

    # ---- 取消 / 复位 / 排空 ----

    async def cancel_turn(self, key: str, turn_id: str | None = None) -> None:
        """取消在途轮次；``turn_id`` 缺省时取消该会话最近提交的一轮。

        刻意不取提交锁（见模块 docstring 的 reset 死锁说明）。
        """
        state = self._key_state(key)
        if turn_id is None:
            turn_id = state.last_turn_id
        task = state.inflight
        if task is None or task.done():
            return
        if turn_id and state.last_turn_id != turn_id:
            return
        state.cancel_requested = True
        task.cancel()

    async def reset_session(self, key: str) -> None:
        """取消在途轮次 + epoch 递增作废旧上下文（fence）。

        native 执行器无 Core 会话历史可清；消息库/整合状态的清理仍由调用方
        （WebChat reset 路由）负责，本方法只做运行时侧的 fence。
        """
        state = self._key_state(key)
        await self.cancel_turn(key)
        state.owner_epoch += 1
        self._record(
            turn_id="", key=key, owner_epoch=state.owner_epoch,
            outcome="reset", state="reset", started_at=time.time(),
            finished_at=time.time(),
        )

    async def drain(self) -> int:
        """等待全部在途轮次收尾（优雅关闭路径），返回仍未结束的数量。"""
        tasks = [s.inflight for s in self._keys.values() if s.inflight and not s.inflight.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=30.0)
        return sum(1 for s in self._keys.values() if s.inflight and not s.inflight.done())


# ---- 进程级共享 facade（gateway / chat_ingress 共用同一 owner 面） ----

_shared_facade: "RuntimeFacade | None" = None


def peek_shared_facade() -> "RuntimeFacade | None":
    """只读窥探：返回已创建的共享 facade，不触发懒创建（状态面用）。"""
    return _shared_facade


def get_shared_facade() -> RuntimeFacade:
    """进程内共享 facade（懒创建）；provider 默认走真实 CHAT 角色后端。"""
    global _shared_facade
    if _shared_facade is None:
        from config import STELLA_HOME

        runtime_dir = Path(STELLA_HOME) / "runtime"
        _shared_facade = RuntimeFacade(store=RuntimeStore(runtime_dir / "turns.jsonl"))
    return _shared_facade


async def ensure_shared_facade_started() -> RuntimeFacade:
    """兼容入口（原 Node handshake；进程内执行器无启动动作）。"""
    return get_shared_facade()
