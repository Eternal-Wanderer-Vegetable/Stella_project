# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""外置打分表加载器（config/participation/*.toml）。

设计约束（实现方案 §4 补充要求 B）：

- scorer / signals / decision 代码中**不允许出现任何分值常量**——
  权重、阈值、词表、兴趣锚全部来自四个 TOML 文件；
- 加载时做完整性校验（指标齐全、范围合法、词表非空），失败抛
  ``ParticipationTableError`` 并保持上一份可用表不被动（热重载安全性）；
- ``reload()`` 支持运行时热重载：调参改表文件即可，不改代码、不重启进程。

四个文件（默认目录 config/participation/，可用 PARTICIPATION_TABLES_DIR 覆盖）：

- weights.toml     9 项指标的加/减分值与上下限
- thresholds.toml  决策分级阈值 / 二次确认 / 话题生命周期 / 切换判定
- signals.toml     信号词表（开放问句、悬念、认可性回应等）
- topics.toml      长期兴趣锚（关键词 + 兴趣描述文本）
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


class ParticipationTableError(Exception):
    """打分表缺失 / 结构不合法。加载失败时决策层应保持禁用而非崩溃。"""


# ── 数据结构（字段与 TOML 一一对应；缺键 = 配置错误，直接抛） ──


@dataclass(frozen=True)
class RelevanceWeights:
    max: float
    long_term_max: float
    current_max: float
    keyword_hit: float
    embedding_full_at: float
    embedding_zero_at: float


@dataclass(frozen=True)
class OpportunityWeights:
    min: float
    max: float
    open_question: float
    question_to_group: float
    unfinished_expression: float
    answered: float
    plain_statement: float


@dataclass(frozen=True)
class SocialOpportunityWeights:
    max: float
    direct_invite: float
    strong_suspense: float
    strong_emotion: float
    plain_statement: float
    fully_responded: float


@dataclass(frozen=True)
class TopicInvolvementWeights:
    max: float
    involved: float


@dataclass(frozen=True)
class SilenceBonusWeights:
    max: float
    growth_seconds: float


@dataclass(frozen=True)
class RecentSpeechPenaltyWeights:
    max: float
    just_spoke_seconds: float
    just_spoke: float
    consecutive_proactive_each: float
    topic_consecutive_each: float
    passive_discount: float


@dataclass(frozen=True)
class VelocityPenaltyWeights:
    max: float
    window_seconds: float
    medium_at: int
    high_at: int
    very_high_at: int
    low: float
    medium: float
    high: float
    very_high: float


@dataclass(frozen=True)
class RepetitionPenaltyWeights:
    max: float
    per_proactive_in_topic: float
    new_opportunity_relief: float


@dataclass(frozen=True)
class ExpiredPenaltyWeights:
    max: float
    cooling: float
    expired: float


@dataclass(frozen=True)
class Weights:
    relevance: RelevanceWeights
    opportunity: OpportunityWeights
    social_opportunity: SocialOpportunityWeights
    topic_involvement: TopicInvolvementWeights
    silence_bonus: SilenceBonusWeights
    recent_speech_penalty: RecentSpeechPenaltyWeights
    velocity_penalty: VelocityPenaltyWeights
    repetition_penalty: RepetitionPenaltyWeights
    expired_penalty: ExpiredPenaltyWeights


@dataclass(frozen=True)
class StrongHookDirect:
    social_opportunity_min: float
    score_min: float


@dataclass(frozen=True)
class TopicLifecycle:
    cooling_after: float
    expire_after: float


@dataclass(frozen=True)
class TopicSwitch:
    similarity_below: float
    recent_texts: int
    fallback_idle_seconds: float


@dataclass(frozen=True)
class Thresholds:
    ignore_below: float
    candidate_at: float
    allow_at: float
    candidate_confirm_messages: int
    strong_hook_direct: StrongHookDirect
    topic_lifecycle: TopicLifecycle
    topic_switch: TopicSwitch
    warmup_messages: int


@dataclass(frozen=True)
class SignalWords:
    # 开放问题
    open_question_keywords: tuple[str, ...]
    question_suffixes: tuple[str, ...]
    question_tails: tuple[str, ...]
    question_words: tuple[str, ...]
    # 未完成表达
    unfinished_suffixes: tuple[str, ...]
    unfinished_teasers: tuple[str, ...]
    # 悬念 / 情绪 / 认可 / 低信息量 / 承接 / 直接邀请
    suspense_keywords: tuple[str, ...]
    emotion_keywords: tuple[str, ...]
    acknowledgment_keywords: tuple[str, ...]
    low_info_keywords: tuple[str, ...]
    low_info_max_length: int
    topic_shift_keywords: tuple[str, ...]
    invite_name_variants: tuple[str, ...]
    invite_patterns: tuple[str, ...]


@dataclass(frozen=True)
class InterestAnchor:
    label: str
    keywords: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class TopicAnchors:
    interests: tuple[InterestAnchor, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ParticipationTables:
    """四个打分表的内存映像（整体不可变，热重载 = 原子替换整个对象）。"""
    weights: Weights
    thresholds: Thresholds
    signals: SignalWords
    topics: TopicAnchors


# ── 校验辅助 ──


def _require(data: dict[str, Any], section: str) -> dict[str, Any]:
    value = data.get(section)
    if not isinstance(value, dict):
        raise ParticipationTableError(f"打分表缺少 [{section}] 段")
    return value


def _get(data: dict[str, Any], key: str, *, section: str = ""):
    if key not in data:
        where = f"{section}.{key}" if section else key
        raise ParticipationTableError(f"打分表缺少键: {where}")
    return data[key]


def _num(data: dict[str, Any], key: str) -> float:
    value = _get(data, key)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ParticipationTableError(f"打分表键 {key} 不是数字: {value!r}") from None


def _words(data: dict[str, Any], key: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    value = _get(data, key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ParticipationTableError(f"打分表键 {key} 不是字符串列表")
    words = tuple(v.lower() for v in value if v.strip())
    if not words and not allow_empty:
        raise ParticipationTableError(f"打分表词表 {key} 为空（至少需要一个词）")
    return words


def _check_range(low: float, high: float, what: str) -> None:
    if low > high:
        raise ParticipationTableError(f"打分表范围非法（{what}）: {low} > {high}")


# ── 各文件解析 ──


def _load_weights(data: dict[str, Any]) -> Weights:
    rel = _require(data, "relevance")
    relevance = RelevanceWeights(
        max=_num(rel, "max"),
        long_term_max=_num(rel, "long_term_max"),
        current_max=_num(rel, "current_max"),
        keyword_hit=_num(rel, "keyword_hit"),
        embedding_full_at=_num(rel, "embedding_full_at"),
        embedding_zero_at=_num(rel, "embedding_zero_at"),
    )
    _check_range(relevance.embedding_zero_at, relevance.embedding_full_at, "relevance.embedding")

    opp = _require(data, "opportunity")
    opportunity = OpportunityWeights(
        min=_num(opp, "min"),
        max=_num(opp, "max"),
        open_question=_num(opp, "open_question"),
        question_to_group=_num(opp, "question_to_group"),
        unfinished_expression=_num(opp, "unfinished_expression"),
        answered=_num(opp, "answered"),
        plain_statement=_num(opp, "plain_statement"),
    )
    _check_range(opportunity.min, opportunity.max, "opportunity")

    soc = _require(data, "social_opportunity")
    social = SocialOpportunityWeights(
        max=_num(soc, "max"),
        direct_invite=_num(soc, "direct_invite"),
        strong_suspense=_num(soc, "strong_suspense"),
        strong_emotion=_num(soc, "strong_emotion"),
        plain_statement=_num(soc, "plain_statement"),
        fully_responded=_num(soc, "fully_responded"),
    )

    inv = _require(data, "topic_involvement")
    involvement = TopicInvolvementWeights(max=_num(inv, "max"), involved=_num(inv, "involved"))

    sil = _require(data, "silence_bonus")
    silence = SilenceBonusWeights(max=_num(sil, "max"), growth_seconds=_num(sil, "growth_seconds"))

    rsp = _require(data, "recent_speech_penalty")
    recent = RecentSpeechPenaltyWeights(
        max=_num(rsp, "max"),
        just_spoke_seconds=_num(rsp, "just_spoke_seconds"),
        just_spoke=_num(rsp, "just_spoke"),
        consecutive_proactive_each=_num(rsp, "consecutive_proactive_each"),
        topic_consecutive_each=_num(rsp, "topic_consecutive_each"),
        passive_discount=_num(rsp, "passive_discount"),
    )

    vel = _require(data, "velocity_penalty")
    velocity = VelocityPenaltyWeights(
        max=_num(vel, "max"),
        window_seconds=_num(vel, "window_seconds"),
        medium_at=int(_num(vel, "medium_at")),
        high_at=int(_num(vel, "high_at")),
        very_high_at=int(_num(vel, "very_high_at")),
        low=_num(vel, "low"),
        medium=_num(vel, "medium"),
        high=_num(vel, "high"),
        very_high=_num(vel, "very_high"),
    )
    _check_range(velocity.medium_at, velocity.high_at, "velocity.medium/high_at")
    _check_range(velocity.high_at, velocity.very_high_at, "velocity.high/very_high_at")

    rep = _require(data, "repetition_penalty")
    repetition = RepetitionPenaltyWeights(
        max=_num(rep, "max"),
        per_proactive_in_topic=_num(rep, "per_proactive_in_topic"),
        new_opportunity_relief=_num(rep, "new_opportunity_relief"),
    )

    exp = _require(data, "expired_penalty")
    expired = ExpiredPenaltyWeights(
        max=_num(exp, "max"),
        cooling=_num(exp, "cooling"),
        expired=_num(exp, "expired"),
    )

    return Weights(
        relevance=relevance,
        opportunity=opportunity,
        social_opportunity=social,
        topic_involvement=involvement,
        silence_bonus=silence,
        recent_speech_penalty=recent,
        velocity_penalty=velocity,
        repetition_penalty=repetition,
        expired_penalty=expired,
    )


def _load_thresholds(data: dict[str, Any]) -> Thresholds:
    hook_raw = _require(data, "strong_hook_direct")
    hook = StrongHookDirect(
        social_opportunity_min=_num(hook_raw, "social_opportunity_min"),
        score_min=_num(hook_raw, "score_min"),
    )
    life_raw = _require(data, "topic_lifecycle")
    lifecycle = TopicLifecycle(
        cooling_after=_num(life_raw, "cooling_after"),
        expire_after=_num(life_raw, "expire_after"),
    )
    switch_raw = _require(data, "topic_switch")
    switch = TopicSwitch(
        similarity_below=_num(switch_raw, "similarity_below"),
        recent_texts=int(_num(switch_raw, "recent_texts")),
        fallback_idle_seconds=_num(switch_raw, "fallback_idle_seconds"),
    )
    thresholds = Thresholds(
        ignore_below=_num(data, "ignore_below"),
        candidate_at=_num(data, "candidate_at"),
        allow_at=_num(data, "allow_at"),
        candidate_confirm_messages=int(_num(data, "candidate_confirm_messages")),
        strong_hook_direct=hook,
        topic_lifecycle=lifecycle,
        topic_switch=switch,
        warmup_messages=int(_num(data, "warmup_messages")),
    )
    _check_range(thresholds.ignore_below, thresholds.candidate_at, "thresholds.ignore/candidate")
    _check_range(thresholds.candidate_at, thresholds.allow_at, "thresholds.candidate/allow")
    if lifecycle.expire_after <= 0 or lifecycle.cooling_after <= 0:
        raise ParticipationTableError("topic_lifecycle 时间必须为正数")
    return thresholds


def _load_signals(data: dict[str, Any]) -> SignalWords:
    oq = _require(data, "open_question")
    unf = _require(data, "unfinished")
    sus = _require(data, "suspense")
    emo = _require(data, "emotion")
    ack = _require(data, "acknowledgment")
    low = _require(data, "low_information")
    shift = _require(data, "topic_shift")
    inv = _require(data, "direct_invite")
    return SignalWords(
        open_question_keywords=_words(oq, "keywords"),
        question_suffixes=_words(oq, "question_suffixes", allow_empty=True),
        question_tails=_words(oq, "question_tails", allow_empty=True),
        question_words=_words(oq, "question_words", allow_empty=True),
        unfinished_suffixes=_words(unf, "suffixes", allow_empty=True),
        unfinished_teasers=_words(unf, "teasers", allow_empty=True),
        suspense_keywords=_words(sus, "keywords"),
        emotion_keywords=_words(emo, "keywords", allow_empty=True),
        acknowledgment_keywords=_words(ack, "keywords", allow_empty=True),
        low_info_keywords=_words(low, "keywords", allow_empty=True),
        low_info_max_length=int(_num(low, "max_length")),
        topic_shift_keywords=_words(shift, "keywords", allow_empty=True),
        invite_name_variants=_words(inv, "name_variants", allow_empty=True),
        invite_patterns=_words(inv, "invite_patterns", allow_empty=True),
    )


def _load_topics(data: dict[str, Any]) -> TopicAnchors:
    raw_list = data.get("interests")
    if not isinstance(raw_list, list) or not raw_list:
        raise ParticipationTableError("topics.toml 缺少 [[interests]]（至少一个兴趣锚）")
    anchors: list[InterestAnchor] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ParticipationTableError(f"topics.toml interests[{i}] 不是表")
        label = str(_get(item, "label"))
        keywords = _words(item, "keywords")
        anchors.append(
            InterestAnchor(label=label, keywords=keywords, description=str(item.get("description", "")))
        )
    return TopicAnchors(interests=tuple(anchors))


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ParticipationTableError(f"打分表文件不存在: {path}")
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ParticipationTableError(f"打分表 TOML 解析失败（{path.name}）: {e}") from e


def load_tables(tables_dir: Path) -> ParticipationTables:
    """从目录加载四个打分表并做完整性校验；任何问题抛 ParticipationTableError。"""
    return ParticipationTables(
        weights=_load_weights(_read_toml(tables_dir / "weights.toml")),
        thresholds=_load_thresholds(_read_toml(tables_dir / "thresholds.toml")),
        signals=_load_signals(_read_toml(tables_dir / "signals.toml")),
        topics=_load_topics(_read_toml(tables_dir / "topics.toml")),
    )


class TableStore:
    """线程安全的打分表持有者：启动加载 + 热重载（失败保留旧表）。"""

    def __init__(self, tables_dir: Path):
        self._dir = tables_dir
        self._lock = threading.Lock()
        self._tables: ParticipationTables | None = None
        self._last_error: str = ""

    @property
    def tables(self) -> ParticipationTables | None:
        with self._lock:
            return self._tables

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def load(self) -> ParticipationTables:
        """首次加载：失败向上抛（调用方决定禁用决策层）。"""
        tables = load_tables(self._dir)
        with self._lock:
            self._tables = tables
            self._last_error = ""
        return tables

    def reload(self) -> tuple[bool, str]:
        """热重载：失败保留旧表并返回错误说明（绝不打断运行中的评分）。"""
        try:
            tables = load_tables(self._dir)
        except ParticipationTableError as e:
            with self._lock:
                self._last_error = str(e)
            return False, str(e)
        with self._lock:
            self._tables = tables
            self._last_error = ""
        return True, "打分表已重载"
