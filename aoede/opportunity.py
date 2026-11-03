# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Aoede 统一机会/时机层（2026-11-03 计划 §6.2，S2-02）。

唯一参与决策管线：廉价硬预检 → 上下文评分（复用 Participation 决策）→
**可取消 debounce 唤醒** → 时机层 SPEAK / WAIT / DROP → 生成与发送前
复核（复用既有管线：自然度 SKIP、去重、话题版本 stale 检查、DeliveryPlan、
逐段回执记账）。

计划要点：
- 每个会话同时最多一个在途机会；新消息推进 context_revision、重置静默
  计时并合并候选，不叠加第二个机会；到 expiry 直接 DROP。
- 旧概率门槛（PROACTIVE_PROB_* 掷骰、固定 MIN_MESSAGES_SINCE_SPOKE=15）
  不前置阻断新路径；600 秒群级冷却保留为内部安全下限。
- 验证 ASK 是机会的一种（受限变体），与其他机会竞争，**无定时优先权**
  （S2-02 起定时任务不再先跑主动 @）。
- debounce/TTL 是内部实验初值（3s/15s），不是用户配置面（S2-03 的
  PROACTIVE_FREQUENCY 是唯一普通用户数值）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from nonebot import logger

# 内部实验初值（计划 §12）：调整必须写入计划合同，不暴露给用户配置。
DEFAULT_DEBOUNCE_SECONDS = 3.0
DEFAULT_TTL_SECONDS = 15.0


@dataclass
class _Opportunity:
    """一个在途机会（每会话一份；标识见 stella_contracts.aoede 契约）。"""

    group_id: int
    context_revision: int = 1
    created_at: float = 0.0
    expires_at: float = 0.0
    kind: str = "CONTRIBUTE"  # CONTRIBUTE / VERIFY_ASK
    decision: Any = None
    bot_ref: Any = None
    trigger_text: str = ""
    parent_trace_id: str = ""
    timer: asyncio.TimerHandle | None = field(default=None, repr=False)
    task: asyncio.Task | None = field(default=None, repr=False)


class OpportunityManager:
    """每群一份在途机会；合并、去抖、到期丢弃，绝不叠加第二条。

    时钟全部单调（进程内等待），expiry 判定同样用单调时刻——墙钟回退
    不影响等待语义（持久化预算在 S2-03 的 AoedeBudgetPort，落库走 UTC）。
    """

    def __init__(
        self,
        *,
        debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock=None,
    ):
        import time as _time

        self._debounce = float(debounce_seconds)
        self._ttl = float(ttl_seconds)
        self._clock = clock or _time.monotonic
        self._inflight: dict[int, _Opportunity] = {}
        self._context_revision: dict[int, int] = {}

    # ── 预检（廉价硬门禁；旧概率/条数门槛不在此处） ──
    def _preflight_blocked_reason(self, group_id: int) -> str:
        from aoede.gate import in_wakeup_grace, is_muted, is_sleeping
        from config import PROACTIVE_ENABLED

        if not PROACTIVE_ENABLED:
            return "proactive_disabled"
        if is_muted(group_id):
            return "muted"
        if is_sleeping():
            return "sleep_window"
        if in_wakeup_grace(group_id):
            return "wakeup_grace"
        return ""

    def _cooldown_blocked(self, group_id: int) -> bool:
        """内部安全下限：600 秒群级冷却（与 S2-03 R≤6 相容）。"""
        from aoede.controller import get_proactive

        return get_proactive().in_cooldown(group_id)

    # ── 入口：一条消息带来的机会 ──
    def submit(
        self,
        group_id: int,
        decision,
        *,
        bot_ref=None,
        trigger_text: str = "",
        parent_trace_id: str = "",
    ) -> str:
        """评分层命中后的统一入口。返回动作：created/merged/replaced/dropped。

        新消息推进 context_revision；已有在途机会时合并（刷新触发证据、
        重置静默计时，**保留原 expiry**——机会窗口不因刷屏而无限延长）。
        """
        blocked = self._preflight_blocked_reason(group_id)
        if blocked:
            return f"dropped:{blocked}"
        now = self._clock()
        self._context_revision[group_id] = (
            self._context_revision.get(group_id, 0) + 1
        )
        inflight = self._inflight.get(group_id)
        if inflight is not None:
            if inflight.expires_at <= now:
                self._drop(group_id, "expired_before_merge")
            else:
                inflight.context_revision = self._context_revision[group_id]
                inflight.decision = decision
                inflight.trigger_text = trigger_text or inflight.trigger_text
                self._rearm_debounce(inflight, now)
                return "merged"
        opportunity = _Opportunity(
            group_id=group_id,
            context_revision=self._context_revision[group_id],
            created_at=now,
            expires_at=now + self._ttl,
            kind="CONTRIBUTE",
            decision=decision,
            bot_ref=bot_ref,
            trigger_text=trigger_text,
            parent_trace_id=parent_trace_id,
        )
        self._inflight[group_id] = opportunity
        self._rearm_debounce(opportunity, now)
        return "created"

    # ── 验证 ASK：与其他机会竞争（无定时优先权） ──
    def submit_verification(self, group_id: int, bot_ref=None) -> str:
        """定时任务不再直接抢占发言：验证 ASK 作为一种机会提交。

        已有在途机会时不叠加（同一会话唯一在途）；冷却内不提交。
        """
        blocked = self._preflight_blocked_reason(group_id)
        if blocked:
            return f"dropped:{blocked}"
        if self._cooldown_blocked(group_id):
            return "dropped:cooldown"
        if group_id in self._inflight:
            return "dropped:inflight"
        now = self._clock()
        opportunity = _Opportunity(
            group_id=group_id,
            context_revision=self._context_revision.get(group_id, 0),
            created_at=now,
            expires_at=now + self._ttl,
            kind="VERIFY_ASK",
            bot_ref=bot_ref,
        )
        self._inflight[group_id] = opportunity
        self._rearm_debounce(opportunity, now)
        return "created"

    # ── 取消：转题/静音/新直接请求撤销在途机会 ──
    def cancel(self, group_id: int, reason: str) -> bool:
        opportunity = self._inflight.pop(group_id, None)
        if opportunity is None:
            return False
        if opportunity.timer is not None:
            opportunity.timer.cancel()
            opportunity.timer = None
        logger.info(
            f"⏹️ [Aoede] 群 {group_id} 机会已取消（{reason}，"
            f"revision={opportunity.context_revision}）"
        )
        return True

    def cancel_all(self, reason: str) -> int:
        return sum(1 for gid in list(self._inflight) if self.cancel(gid, reason))

    # ── 恢复：定时任务只做有界唤醒（重启后 timer 丢失的在途机会） ──
    def recover_group(self, group_id: int, bot_ref=None) -> str:
        opportunity = self._inflight.get(group_id)
        if opportunity is None:
            return "none"
        if opportunity.expires_at <= self._clock():
            self._drop(group_id, "expired_on_recover")
            return "dropped"
        if opportunity.timer is None and opportunity.task is None:
            self._rearm_debounce(opportunity, self._clock())
            return "rearmed"
        return "alive"

    # ── 内部 ──
    def _rearm_debounce(self, opportunity: _Opportunity, now: float) -> None:
        if opportunity.timer is not None:
            opportunity.timer.cancel()
        loop = asyncio.get_running_loop()
        opportunity.timer = loop.call_later(
            self._debounce, self._fire, opportunity.group_id
        )

    def _fire(self, group_id: int) -> None:
        opportunity = self._inflight.get(group_id)
        if opportunity is None:
            return
        opportunity.timer = None
        if opportunity.expires_at <= self._clock():
            self._drop(group_id, "expired_at_fire")
            return
        if self._cooldown_blocked(group_id):
            self._drop(group_id, "cooldown")
            return
        opportunity.task = asyncio.create_task(self._speak(opportunity))

    def _drop(self, group_id: int, reason: str) -> None:
        opportunity = self._inflight.pop(group_id, None)
        if opportunity is not None and opportunity.timer is not None:
            opportunity.timer.cancel()

    async def _speak(self, opportunity: _Opportunity) -> None:
        group_id = opportunity.group_id
        # 竞态复核：机会可能刚被取消/转题
        if self._inflight.get(group_id) is not opportunity:
            return
        self._inflight.pop(group_id, None)
        from aoede.host import get_host

        try:
            host = get_host()
        except RuntimeError:
            logger.warning(f"⚠️ [Aoede] 群 {group_id} 宿主未装配，机会丢弃")
            return
        # 持久预算（S2-03，计划 §6.5）：原子 reserve 先于生成/发送；同一
        # 会话的 CONTRIBUTE 与 VERIFY_ASK 共用一桶；R=0 → 一律拒绝；store
        # 不可用 fail closed。发送结算：at_user 的 bool 可信（False=无任何
        # 已发片段 → release）；插话路径回执结算在 speak 内部完成，这里
        # 保守 resolve_unknown（消耗，不自动退款）。
        from aoede.budget import (
            ProactiveBudgetStore,
            budget_scope_key,
            new_operation_id,
        )
        from config import PROACTIVE_FREQUENCY

        store = ProactiveBudgetStore(host.db_path())
        scope_key = budget_scope_key(opportunity.bot_ref, group_id)
        operation_id = new_operation_id()
        reservation = store.reserve(
            scope_key,
            operation_id,
            frequency_per_hour=float(PROACTIVE_FREQUENCY),
            kind=opportunity.kind,
        )
        if not reservation.granted:
            logger.info(
                f"⏳ [Aoede] 群 {group_id} 机会因预算未放行（{reservation.reason}，"
                f"R={float(PROACTIVE_FREQUENCY)}）"
            )
            return
        try:
            if opportunity.kind == "VERIFY_ASK":
                from aoede.verification.service import proactive_at_user

                bot = _resolve_bot(host, opportunity.bot_ref)
                if bot is None:
                    store.release(operation_id)
                    return
                delivered = await proactive_at_user(host, bot, group_id)
                if delivered:
                    store.commit(operation_id)
                else:
                    store.release(operation_id)
                return
            if opportunity.decision is None:
                store.release(operation_id)
                return
            await host.proactive_speak_for_group(
                opportunity.bot_ref,
                group_id,
                intent=f"participation_{getattr(opportunity.decision, 'mode', '')}",
                instruction=_instruction_for(opportunity.decision),
                skip_dice=True,
                decision=opportunity.decision,
                evidence=_evidence_for(host, opportunity),
                parent_trace_id=opportunity.parent_trace_id,
            )
            store.resolve_unknown(operation_id)
        except Exception as e:
            logger.warning(f"⚠️ [Aoede] 群 {group_id} 机会执行异常: {e}")
            store.resolve_unknown(operation_id)


def _instruction_for(decision) -> str:
    from aoede.service import (
        _PARTICIPATION_DEFAULT_INSTRUCTION,
        _PARTICIPATION_INSTRUCTIONS,
    )

    return _PARTICIPATION_INSTRUCTIONS.get(
        getattr(decision, "mode", ""), _PARTICIPATION_DEFAULT_INSTRUCTION
    )


def _evidence_for(host, opportunity: _Opportunity):
    from aoede.service import build_participation_evidence

    try:
        manager = host.get_participation_manager()
        snapshot = manager.snapshot(opportunity.group_id)
    except Exception:
        snapshot = {}
    return build_participation_evidence(
        opportunity.decision, opportunity.trigger_text, snapshot
    )


def _resolve_bot(host, bot_ref):
    if host.resolve_background_bot is None:
        return None
    try:
        from stella_project.plugins.bot_main.transport_delivery import (
            resolve_background_bot,
        )

        return resolve_background_bot(bot_ref)
    except Exception:
        return None


# ── 进程级单例 ─────────────────────────────────────────────
_manager: OpportunityManager | None = None


def get_opportunity_manager() -> OpportunityManager:
    """进程级单例：每会话唯一在途机会由同一实例裁决。"""
    global _manager
    if _manager is None:
        _manager = OpportunityManager()
    return _manager


def reset_opportunity_manager_for_tests() -> None:
    """清空单例并取消全部在途机会（测试隔离用）。"""
    global _manager
    if _manager is not None:
        _manager.cancel_all("reset_for_tests")
    _manager = None


__all__ = [
    "DEFAULT_DEBOUNCE_SECONDS",
    "DEFAULT_TTL_SECONDS",
    "OpportunityManager",
    "get_opportunity_manager",
    "reset_opportunity_manager_for_tests",
]
