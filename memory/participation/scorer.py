# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Participation Scorer（上游工程方案 §7-§17）。

9 项指标加权求和 → 0~100 分。本模块**不含任何分值常量**：
所有数值来自 config/participation/weights.toml（经 tables.Weights 传入）。

评分不调用 LLM（上游 §26）：纯本地规则 + 可选 embedding 相似度。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from memory.participation.signals import SignalSnapshot
from memory.participation.state import (
    VELOCITY_HIGH,
    VELOCITY_VERY_HIGH,
    ConversationState,
    TopicStatus,
)
from memory.participation.tables import ParticipationTables, TopicAnchors

# 相似度回调：返回 0~1 或 None（embedding 不可用时）
SimilarityFn = Callable[[str, str], "float | None"]


@dataclass
class ScoreBreakdown:
    """单次评分的全部分项（可观测性日志的字段来源，上游 §29）。"""

    relevance: float = 0.0
    opportunity: float = 0.0
    social_opportunity: float = 0.0
    topic_involvement: float = 0.0
    silence_bonus: float = 0.0
    recent_speech_penalty: float = 0.0
    velocity_penalty: float = 0.0
    repetition_penalty: float = 0.0
    expired_penalty: float = 0.0
    final_score: float = 0.0
    velocity_level: str = "LOW"
    velocity_count: int = 0
    topic_status: str = "NEW"
    stella_involved: bool = False
    seconds_since_spoke: float | None = None

    def as_dict(self) -> dict[str, float | str | bool | None]:
        return {
            "relevance": round(self.relevance, 1),
            "opportunity": round(self.opportunity, 1),
            "social_opportunity": round(self.social_opportunity, 1),
            "topic_involvement": round(self.topic_involvement, 1),
            "silence_bonus": round(self.silence_bonus, 1),
            "recent_speech_penalty": round(self.recent_speech_penalty, 1),
            "velocity_penalty": round(self.velocity_penalty, 1),
            "repetition_penalty": round(self.repetition_penalty, 1),
            "expired_penalty": round(self.expired_penalty, 1),
            "final_score": round(self.final_score, 1),
            "velocity_level": self.velocity_level,
            "velocity_count": self.velocity_count,
            "topic_status": self.topic_status,
            "stella_involved": self.stella_involved,
            "seconds_since_spoke": (
                round(self.seconds_since_spoke, 1) if self.seconds_since_spoke is not None else None
            ),
        }


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _relevance(
    state: ConversationState,
    recent_texts: list[str],
    anchors: TopicAnchors,
    weights: ParticipationTables,
    similarity: SimilarityFn | None,
) -> float:
    """Relevance = Long-Term（兴趣锚）+ Current（最近参与过的话题），上游 §8。"""
    w = weights.weights.relevance
    corpus = " ".join(recent_texts[-6:])
    if not corpus.strip():
        return 0.0

    long_term = 0.0
    joined = corpus.lower()
    best_sim: float | None = None
    for anchor in anchors.interests:
        if any(k in joined for k in anchor.keywords):
            long_term = max(long_term, w.keyword_hit)
        if similarity is not None and anchor.description:
            sim = similarity(corpus, anchor.description)
            if sim is not None and (best_sim is None or sim > best_sim):
                best_sim = sim
    # embedding 相似度线性映射到 [embedding_zero_at, embedding_full_at] → [0, long_term_max]
    if best_sim is not None:
        if best_sim <= w.embedding_zero_at:
            scaled = 0.0
        elif best_sim >= w.embedding_full_at:
            scaled = w.long_term_max
        else:
            t = (best_sim - w.embedding_zero_at) / (w.embedding_full_at - w.embedding_zero_at)
            scaled = t * w.long_term_max
        long_term = max(long_term, scaled)
    long_term = _clamp(long_term, 0.0, w.long_term_max)

    # Current Relevance：Stella 最近参与过的话题标签再次出现
    current = 0.0
    recent_labels = {label.lower() for label in state.speak_stats.recent_topic_labels}
    if recent_labels:
        for anchor in anchors.interests:
            if anchor.label.lower() in recent_labels and any(
                k in joined for k in anchor.keywords
            ):
                current = w.current_max
                break

    return _clamp(long_term + current, 0.0, w.max)


def _opportunity(signals: SignalSnapshot, weights: ParticipationTables) -> float:
    """Opportunity：取命中的最高档信号（上游 §9/§10）。"""
    w = weights.weights.opportunity
    if signals.open_question:
        value = w.open_question
    elif signals.unfinished:
        value = w.unfinished_expression
    elif signals.suspense:
        # 悬念钩子本质是「话说了个头、等人接」（§10.2 的未完成表达），
        # 语义上同样存在社交空位——只是措辞不像问句
        value = w.unfinished_expression
    elif signals.question_to_group:
        value = w.question_to_group
    elif signals.answered:
        value = w.answered
    else:
        value = w.plain_statement
    return _clamp(value, w.min, w.max)


def _social_opportunity(signals: SignalSnapshot, weights: ParticipationTables) -> float:
    """SocialOpportunity：与话题无关、但存在社交钩子（上游 §11）。"""
    w = weights.weights.social_opportunity
    if signals.direct_invite:
        value = w.direct_invite
    elif signals.suspense:
        value = w.strong_suspense
    elif signals.strong_emotion:
        value = w.strong_emotion
    elif signals.fully_responded:
        value = w.fully_responded
    else:
        value = w.plain_statement
    return _clamp(value, min(0.0, w.fully_responded), w.max)


def _silence_bonus(state: ConversationState, weights: ParticipationTables, now: float) -> float:
    """SilenceBonus：随沉默时长线性增长、封顶（上游 §13）。只能作辅助因素。"""
    w = weights.weights.silence_bonus
    last = state.speak_stats.last_spoke_at
    if last <= 0:
        return w.max  # 从未发言（进程内）视为拿满
    elapsed = max(0.0, now - last)
    if w.growth_seconds <= 0:
        return w.max
    return _clamp(elapsed / w.growth_seconds * w.max, 0.0, w.max)


def _recent_speech_penalty(state: ConversationState, weights: ParticipationTables, now: float) -> float:
    """RecentSpeechPenalty：防抢话核心（上游 §14）。被动应答按折扣计入。"""
    w = weights.weights.recent_speech_penalty
    stats = state.speak_stats
    penalty = 0.0
    if stats.last_spoke_at > 0:
        elapsed = now - stats.last_spoke_at
        if elapsed < w.just_spoke_seconds:
            penalty += w.just_spoke
        else:
            # 冷却衰减：just_spoke 随时间线性衰减到 0（在 just_spoke_seconds ~ 4x 之间）
            decay_window = w.just_spoke_seconds * 4
            if elapsed < decay_window:
                penalty += w.just_spoke * (1 - (elapsed - w.just_spoke_seconds) / decay_window)
    penalty += stats.consecutive_proactive * w.consecutive_proactive_each
    if state.topic is not None:
        penalty += state.topic.proactive_speak_count * w.topic_consecutive_each
    if stats.last_kind == "passive" and stats.consecutive_proactive == 0:
        penalty *= w.passive_discount
    return _clamp(penalty, 0.0, w.max)


def _repetition_penalty(
    state: ConversationState, signals: SignalSnapshot, weights: ParticipationTables
) -> float:
    """RepetitionPenalty：同一话题内反复发言的惩罚（上游 §15）。"""
    w = weights.weights.repetition_penalty
    topic = state.topic
    if topic is None or topic.proactive_speak_count <= 0:
        return 0.0
    penalty = topic.proactive_speak_count * w.per_proactive_in_topic
    if signals.open_question or signals.suspense or signals.direct_invite:
        penalty -= w.new_opportunity_relief
    return _clamp(penalty, 0.0, w.max)


def score(
    state: ConversationState,
    signals: SignalSnapshot,
    tables: ParticipationTables,
    velocity_level: str,
    velocity_count: int,
    recent_texts: list[str],
    *,
    similarity: SimilarityFn | None = None,
    now: float | None = None,
) -> ScoreBreakdown:
    """计算一次完整评分。不抛异常；embedding 回调失败时静默降级为关键词。"""
    now = now if now is not None else time.time()
    if similarity is not None:
        _wrapped = similarity
    else:
        _wrapped = None  # type: ignore[assignment]

    try:
        relevance = _relevance(state, recent_texts, tables.topics, tables, _wrapped)
    except Exception:
        relevance = _relevance(state, recent_texts, tables.topics, tables, None)

    w = tables.weights
    breakdown = ScoreBreakdown(
        relevance=relevance,
        opportunity=_opportunity(signals, tables),
        social_opportunity=_social_opportunity(signals, tables),
        topic_involvement=(
            w.topic_involvement.involved
            if (state.topic is not None and state.topic.stella_involved)
            else 0.0
        ),
        silence_bonus=_silence_bonus(state, tables, now),
        recent_speech_penalty=_recent_speech_penalty(state, tables, now),
        velocity_penalty={
            "LOW": w.velocity_penalty.low,
            "MEDIUM": w.velocity_penalty.medium,
            "HIGH": w.velocity_penalty.high,
            "VERY_HIGH": w.velocity_penalty.very_high,
        }.get(velocity_level, w.velocity_penalty.low),
        repetition_penalty=_repetition_penalty(state, signals, tables),
        expired_penalty=(
            w.expired_penalty.cooling
            if state.topic is not None and state.topic.status is TopicStatus.COOLING
            else w.expired_penalty.expired
            if state.topic is not None and state.topic.status is TopicStatus.EXPIRED
            else 0.0
        ),
    )
    breakdown.velocity_level = velocity_level
    breakdown.velocity_count = velocity_count
    breakdown.topic_status = state.topic.status.value if state.topic else "NONE"
    breakdown.stella_involved = bool(state.topic is not None and state.topic.stella_involved)
    if state.speak_stats.last_spoke_at > 0:
        breakdown.seconds_since_spoke = now - state.speak_stats.last_spoke_at

    positives = (
        breakdown.relevance
        + breakdown.opportunity
        + breakdown.social_opportunity
        + breakdown.topic_involvement
        + breakdown.silence_bonus
    )
    negatives = (
        breakdown.recent_speech_penalty
        + breakdown.velocity_penalty
        + breakdown.repetition_penalty
        + breakdown.expired_penalty
    )
    breakdown.final_score = _clamp(positives - negatives, 0.0, 100.0)
    return breakdown
