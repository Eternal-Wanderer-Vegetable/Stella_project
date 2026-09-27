# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""决策阈值状态机（上游工程方案 §18-§21）。

IGNORE / OBSERVE / CANDIDATE / ALLOW_LLM 四级 + Candidate 二次确认：

- 单条消息 80 分**不**立即触发 LLM；进入 CANDIDATE 后等下一条消息重算，
  仍然达标才 ALLOW_LLM（上游 §19，防「看到一句话就抢话」）；
- 强社交钩子（SocialOpportunity 与总分同时达标）允许直通 ALLOW_LLM；
- ParticipationMode 回答「为什么现在说」，只透传给 Context Selector / LLM，
  不负责生成文本（上游 §20）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from memory.participation.scorer import ScoreBreakdown
from memory.participation.signals import SignalSnapshot
from memory.participation.tables import Thresholds

# 决策级别（上游 §18）
IGNORE = "IGNORE"
OBSERVE = "OBSERVE"
CANDIDATE = "CANDIDATE"
ALLOW_LLM = "ALLOW_LLM"

# 空闲退避序列与上限（计划 §6.9 层 2，[assumed] 初值；单位秒）
IDLE_BACKOFF_SEQUENCE = (30.0, 60.0, 120.0, 240.0)
IDLE_BACKOFF_CAP = 300.0

# Participation Mode（上游 §20）
MODE_DIRECT_MENTION = "DIRECT_MENTION"                    # Hard Trigger 路径，不走本层
MODE_DIRECT_RELEVANCE = "DIRECT_RELEVANCE"                # 点名邀请（未 @）
MODE_CONTINUE_EXISTING_CONVERSATION = "CONTINUE_EXISTING_CONVERSATION"
MODE_TOPIC_INTEREST = "TOPIC_INTEREST"
MODE_SOCIAL_HOOK = "SOCIAL_HOOK"


@dataclass
class ParticipationDecision:
    """决策层的最终输出（上游 §21 的 Decision Object）。"""

    group_id: int
    should_speak: bool
    score: float
    level: str                 # IGNORE/OBSERVE/CANDIDATE/ALLOW_LLM
    mode: str                  # ParticipationMode
    topic_id: int | None
    trigger_msg_id: int
    confidence: float          # 0~1：score 与阈值的相对位置
    reason_flags: list[str] = field(default_factory=list)
    breakdown: ScoreBreakdown | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class _CandidateSlot:
    """每群的 Candidate 槽位：记录连续达标的条数（上游 §19）。"""

    streak: int = 0
    topic_id: int | None = None
    since: float = 0.0
    # 空闲退避（计划 §6.9 层 2）：连续「无新信息的主动探测」累计；新相关人类
    # 消息 / 明确提及重置。只抑制主动 ALLOW_LLM，不越任何硬门禁。
    low_novelty_streak: int = 0
    backoff_until: float = 0.0


def decide_mode(
    signals: SignalSnapshot, breakdown: ScoreBreakdown, thresholds: Thresholds
) -> str:
    """由触发原因映射 ParticipationMode（上游 §20）。"""
    if signals.direct_invite:
        return MODE_DIRECT_RELEVANCE
    if breakdown.social_opportunity >= thresholds.strong_hook_direct.social_opportunity_min:
        return MODE_SOCIAL_HOOK
    if breakdown.stella_involved:
        return MODE_CONTINUE_EXISTING_CONVERSATION
    return MODE_TOPIC_INTEREST


class DecisionTracker:
    """每群的阈值状态机（进程内，允许重启丢失 candidate——等价于 Cancel）。"""

    def __init__(self) -> None:
        self._slots: dict[int, _CandidateSlot] = {}

    def decide(
        self,
        group_id: int,
        breakdown: ScoreBreakdown,
        signals: SignalSnapshot,
        thresholds: Thresholds,
        topic_id: int | None,
        trigger_msg_id: int,
        *,
        now: float | None = None,
        novelty: float | None = None,
        is_tome: bool = False,
    ) -> ParticipationDecision:
        score = breakdown.final_score
        now = now if now is not None else time.time()
        slot = self._slots.setdefault(group_id, _CandidateSlot())

        # 名义级别
        if score < thresholds.ignore_below:
            nominal = IGNORE
        elif score < thresholds.candidate_at:
            nominal = OBSERVE
        elif score < thresholds.allow_at:
            nominal = CANDIDATE
        else:
            nominal = ALLOW_LLM

        # Candidate 连续计数
        if score >= thresholds.candidate_at:
            if slot.topic_id != topic_id:
                slot.topic_id = topic_id
                slot.streak = 0
                slot.since = time.time()
            slot.streak += 1
        else:
            slot.streak = 0
            slot.topic_id = topic_id

        # 强钩子直通（上游 §19 末段）
        strong_hook = (
            breakdown.social_opportunity >= thresholds.strong_hook_direct.social_opportunity_min
            and score >= thresholds.strong_hook_direct.score_min
        )

        # 空闲退避（计划 §6.9 层 2）：连续无新信息的主动探测按 30→60→120→240
        # 退避（上限 300）；只压制主动 ALLOW_LLM，强钩子与硬门禁不受影响。
        # 「后台效果的无回应」不进入本计数（不把没回应当拒绝）。
        new_info = novelty is not None and novelty < 0.4
        novel_probe = novelty is not None and novelty >= 0.65
        if strong_hook or is_tome or new_info:
            slot.low_novelty_streak = 0
            slot.backoff_until = 0.0
        in_backoff = now < slot.backoff_until

        level = nominal
        if nominal == ALLOW_LLM:
            if not strong_hook:
                # 二次确认：需要连续 candidate_confirm_messages 条达标
                need = max(1, thresholds.candidate_confirm_messages + 1)
                if slot.streak < need:
                    level = CANDIDATE
            if in_backoff:
                level = CANDIDATE
            elif not strong_hook and novel_probe:
                slot.low_novelty_streak += 1
                idx = min(slot.low_novelty_streak - 1, len(IDLE_BACKOFF_SEQUENCE) - 1)
                backoff = min(IDLE_BACKOFF_SEQUENCE[idx], IDLE_BACKOFF_CAP)
                slot.backoff_until = now + backoff
                level = CANDIDATE  # 本轮退避：不再主动

        should_speak = level == ALLOW_LLM
        # confidence：score 相对 [ignore_below, allow_at] 区间的位置
        span = max(1e-6, thresholds.allow_at - thresholds.ignore_below)
        confidence = max(0.0, min(1.0, (score - thresholds.ignore_below) / span))

        reason_flags = signals.flags()
        if nominal == ALLOW_LLM and level == CANDIDATE and (
            in_backoff or (novel_probe and not strong_hook)
        ):
            reason_flags = [*reason_flags, "idle_backoff"]
        return ParticipationDecision(
            group_id=group_id,
            should_speak=should_speak,
            score=score,
            level=level,
            mode=decide_mode(signals, breakdown, thresholds),
            topic_id=topic_id,
            trigger_msg_id=trigger_msg_id,
            confidence=confidence,
            reason_flags=reason_flags,
            breakdown=breakdown,
        )

    def cancel(self, group_id: int) -> None:
        slot = self._slots.get(group_id)
        if slot is not None:
            slot.streak = 0

    def reset(self) -> None:
        self._slots.clear()
