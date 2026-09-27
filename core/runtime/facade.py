# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""RuntimeFacade：Cortico 运行时的 Python 统一入口（计划 §6.4 / M3）。

- **唯一入口 owner**：每会话一把锁 + owner_epoch。同会话轮次串行（互斥与
  legacy 的群锁同界）；epoch 在 reset 时递增，旧 epoch 的提交被 host 拒绝。
- 轮次生命周期：``accepted → preparing → generating|direct|silent → finalizing
  → completed|failed|cancelled``；投递状态另记（generated ≠ delivered）。
- 领域阶段复用 :class:`~core.runtime.turn_service.TurnService`（M2 提取）：
  prepare/finalize 留在 Python，生成的最终 prompt 以投影交 Core fork；
  DIRECT/SILENT 经上游 turn-policy 零 provider 结束；BUDGET_LIMITED/
  NO_BACKEND 是 Python 本地路径（不产生 Core 轮次，与 legacy 行为一致）。
- 独立运行记录：JSONL append（``STELLA_HOME/runtime/turns.jsonl``），
  与原记忆库完全隔离，可回退读取。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.context import ChatContext
from core.runtime.bridge import BridgeBroken, NodeBridge
from core.runtime.contracts import (
    E_DEADLINE,
    E_HOST_GONE,
    M_SESSION_ENSURE,
    M_SESSION_RESET,
    M_TURN_CANCEL,
    M_TURN_SUBMIT,
    ProtocolError,
)
from core.runtime.turn_service import (
    BUDGET_LIMITED,
    DIRECT,
    GENERATE,
    SILENT,
    TurnService,
)

DEFAULT_TURN_DEADLINE = 120.0  # 与 WebChat 120s 对齐


@dataclass
class KeyState:
    """每会话状态：入口互斥锁 + owner_epoch（reset 递增，旧 owner 被拒）。"""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    owner_epoch: int = 0
    last_turn_id: str = ""


@dataclass
class TurnRecord:
    """一次轮次的运行记录（独立存储，不进记忆库）。"""

    turn_id: str
    key: str
    owner_epoch: int
    outcome: str
    state: str
    started_at: float
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


class RuntimeFacade:
    """统一 submit/cancel/drain/reset/health；持有唯一入口互斥策略。"""

    def __init__(
        self,
        bridge: NodeBridge,
        *,
        store: RuntimeStore | None = None,
        default_deadline: float = DEFAULT_TURN_DEADLINE,
    ) -> None:
        self._bridge = bridge
        self._store = store
        self._default_deadline = default_deadline
        self._keys: dict[str, KeyState] = {}

    # ---- 生命周期 ----

    async def start(self) -> dict[str, Any]:
        return await self._bridge.start()

    async def stop(self) -> None:
        await self._bridge.stop()

    def health(self) -> dict[str, Any]:
        return {
            "mode": "cortico",
            "broken": self._bridge.broken is not None,
            "hello": self._bridge.hello_info,
            "keys": sorted(self._keys),
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

    # ---- 轮次提交 ----

    async def submit_turn(
        self,
        key: str,
        pipeline: TurnService,
        ctx: ChatContext,
        *,
        deadline: float | None = None,
    ) -> ChatContext:
        """完整新链路的一次轮次：prepare(Python) → Core fork → finalize(Python)。

        provider.respond 的处理函数在 bridge 构造时以 ``provider_handler``
        注入（最终 prompt → Python 侧真实 LLM 后端 → 文本）。
        """
        state = self._key_state(key)
        async with state.lock:
            turn_id = uuid.uuid4().hex
            state.last_turn_id = turn_id
            started = time.time()
            self._record(
                turn_id=turn_id, key=key, owner_epoch=state.owner_epoch,
                outcome="", state="accepted", started_at=started,
            )
            plan = await pipeline.prepare_turn(ctx)
            self._record(
                turn_id=turn_id, key=key, owner_epoch=state.owner_epoch,
                outcome=plan.outcome, state="prepared", started_at=started,
            )

            if plan.outcome == GENERATE:
                owner_epoch = await self._ensure_epoch(key, state)
                projection = [{"role": "user", "text": ctx.prompt_log}]
                params: dict[str, Any] = {
                    "key": key,
                    "turn_id": turn_id,
                    "owner_epoch": owner_epoch,
                    "deadline_ms": int((deadline or self._default_deadline) * 1000),
                    "decision": {"kind": "generate"},
                    "projection": projection,
                }
                try:
                    resp = await self._bridge.request(M_TURN_SUBMIT, params, timeout=(deadline or self._default_deadline) + 15.0)
                except ProtocolError as e:
                    if e.code == E_DEADLINE:
                        # 有界失败：deadline 按 legacy 超时语义兜底（BC-5），不悬挂
                        ctx.raw_output = "<thought>卡顿了一下</thought><action>NONE</action><reply>......？</reply>"
                        return await pipeline.finalize_turn(ctx)
                    self._record(
                        turn_id=turn_id, key=key, owner_epoch=owner_epoch,
                        outcome="failed", state="failed", started_at=started,
                        finished_at=time.time(), detail={"code": e.code, "message": str(e)},
                    )
                    raise
                except BridgeBroken as e:
                    self._record(
                        turn_id=turn_id, key=key, owner_epoch=owner_epoch,
                        outcome="failed", state="failed", started_at=started,
                        finished_at=time.time(), detail={"code": E_HOST_GONE, "message": str(e)},
                    )
                    raise
                ctx.raw_output = str(resp.get("text", ""))
                return await pipeline.finalize_turn(ctx)
            if plan.outcome == DIRECT:
                owner_epoch = await self._ensure_epoch(key, state)
                await self._bridge.request(
                    M_TURN_SUBMIT,
                    {
                        "key": key, "turn_id": turn_id, "owner_epoch": owner_epoch,
                        "deadline_ms": int((deadline or self._default_deadline) * 1000),
                        "decision": {"kind": "direct", "text": ctx.reply},
                        "projection": [],
                    },
                    timeout=(deadline or self._default_deadline) + 15.0,
                )
            elif plan.outcome == SILENT:
                owner_epoch = await self._ensure_epoch(key, state)
                await self._bridge.request(
                    M_TURN_SUBMIT,
                    {
                        "key": key, "turn_id": turn_id, "owner_epoch": owner_epoch,
                        "deadline_ms": int((deadline or self._default_deadline) * 1000),
                        "decision": {"kind": "silent"},
                        "projection": [],
                    },
                    timeout=(deadline or self._default_deadline) + 15.0,
                )
            else:
                # BUDGET_LIMITED / NO_BACKEND：Python 本地路径（无 Core 轮次）
                self._record(
                    turn_id=turn_id, key=key, owner_epoch=state.owner_epoch,
                    outcome=plan.outcome, state="local", started_at=started,
                    finished_at=time.time(),
                )
                if plan.outcome == BUDGET_LIMITED:
                    ctx.llm_backend = pipeline._llm.backend_name  # type: ignore[union-attr]
                    return await pipeline.finalize_turn(ctx)
                return await pipeline.finalize_turn(ctx)
            # DIRECT / SILENT：与 legacy 直回/WAIT 早退语义一致——不执行 finalize
            #（post hooks 不跑，不得把 silent 补成兜底 lines）；Core 侧的 submit
            # 仅作轮次生命周期记录（turnPolicy 零 provider 结束）。
            return plan.ctx

    async def _ensure_epoch(self, key: str, state: KeyState) -> int:
        if state.owner_epoch == 0:
            resp = await self._bridge.request(M_SESSION_ENSURE, {"key": key})
            state.owner_epoch = int(resp.get("owner_epoch", 0))
        return state.owner_epoch

    # ---- 取消 / 复位 / 排空 ----

    async def cancel_turn(self, key: str, turn_id: str | None = None) -> None:
        """取消在途轮次；``turn_id`` 缺省时取消该会话最近提交的一轮。"""
        if turn_id is None:
            state = self._key_state(key)
            turn_id = state.last_turn_id
            if not turn_id:
                return
        await self._bridge.request(M_TURN_CANCEL, {"key": key, "turn_id": turn_id}, timeout=5.0)

    async def reset_session(self, key: str) -> None:
        """先 fence/cancel 在途轮次，再清 Core 会话历史；epoch 递增拒旧 owner。

        刻意**不取**提交锁：submit 在锁内等待 provider 回程，reset 若在同一把
        锁后排队就永远取消不掉它（锁重入死锁，计划 §9 预警的失败形态）。
        host 侧 cancel/epoch 校验本身按 key 独立；reset 与并发 submit 的竞争
        结果是后者收到一次 E_KEY（有界失败），新提交用新 epoch 正常进行。
        """
        state = self._key_state(key)
        await self._bridge.request(M_SESSION_RESET, {"key": key, "owner_epoch": state.owner_epoch}, timeout=15.0)
        resp = await self._bridge.request(M_SESSION_ENSURE, {"key": key})
        state.owner_epoch = int(resp.get("owner_epoch", state.owner_epoch + 1))

    async def drain(self) -> int:
        resp = await self._bridge.request("runtime.drain", {}, timeout=45.0)
        return int(resp.get("pending", 0))


# ---- 进程级共享 facade（M4：gateway / chat_ingress 共用同一 owner 面） ----

_shared_facade: "RuntimeFacade | None" = None
_shared_started = False


def default_host_config() -> dict[str, Any]:
    """host 侧 CoreConfig（LLM 由 bridge 注入，provider 仅占位；模型名取真实 CHAT 绑定）。"""
    from config import LLM_ROLE_CHAT_MODEL

    model = (LLM_ROLE_CHAT_MODEL or "").strip() or "stella"
    return {
        "displayName": "Stella",
        "providers": {
            "stella": {
                "kind": "openai-responses-compat",
                "baseUrl": "http://127.0.0.1.invalid",
                "spec": {"model": model, "thinking": False},
            }
        },
        "activeProvider": "stella",
        "batching": {"quietGapMs": 2500, "minBatchAgeMs": 0, "maxBatchAgeMs": 15000, "maxBatchSize": 100},
        "context": {"maxTokens": 128000, "keepRatio": 0.3333, "softRatio": 0.85, "firstTurn": False, "keepPastThinking": True},
        "logging": {"file": "debug", "console": "info", "areas": ""},
        "loop": {"softCap": 8, "hardCap": 16},
    }


def get_shared_facade() -> RuntimeFacade:
    """进程内共享 facade（懒创建）；provider 回程走真实 CHAT 角色后端。"""
    global _shared_facade
    if _shared_facade is None:
        from config import STELLA_HOME
        from core.llm import ROLE_CHAT, backend_for
        from core.runtime.bridge import provider_prompt_text

        async def _provider_handler(params: dict[str, Any]) -> dict[str, Any]:
            prompt = provider_prompt_text(params)
            backend = backend_for(ROLE_CHAT)
            text = await backend.generate(prompt)
            return {"text": text}

        runtime_dir = Path(STELLA_HOME) / "runtime"
        bridge = NodeBridge(
            provider_handler=_provider_handler,
            host_config=default_host_config(),
            data_root=runtime_dir / "sessions",
        )
        _shared_facade = RuntimeFacade(bridge, store=RuntimeStore(runtime_dir / "turns.jsonl"))
    return _shared_facade


async def ensure_shared_facade_started() -> "RuntimeFacade":
    """首用前启动（handshake）；幂等。"""
    global _shared_started
    facade = get_shared_facade()
    if not _shared_started:
        await facade.start()
        _shared_started = True
    return facade
