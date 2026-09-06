# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Conversation State + Topic 状态机（上游工程方案 §5/§6，实现方案 §1.2）。

每群一份：当前话题（NEW/ACTIVE/COOLING/EXPIRED）、参与者、消息速度窗口、
Stella 发言统计、Candidate 槽位由 decision.py 持有。

话题切换第一版用规则优先：embedding 相似度可用时作为主判据，
不可用（服务未启用/编码失败）退化为「时间间隔 + 参与者变化 + 承接词」。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from memory.participation.buffer import BufferedMessage, MessageBuffer
from memory.participation.signals import topic_shift_hit
from memory.participation.tables import ParticipationTables


class TopicStatus(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    COOLING = "COOLING"
    EXPIRED = "EXPIRED"


# 消息速度档（上游 §23）
VELOCITY_LOW = "LOW"
VELOCITY_MEDIUM = "MEDIUM"
VELOCITY_HIGH = "HIGH"
VELOCITY_VERY_HIGH = "VERY_HIGH"


@dataclass
class Topic:
    """单个话题的生命周期状态。texts 只留最近若干条做相似度与标签。"""

    topic_id: int
    label: str
    status: TopicStatus = TopicStatus.NEW
    started_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    participants: set[int] = field(default_factory=set)
    stella_involved: bool = False
    proactive_speak_count: int = 0
    texts: deque[str] = field(default_factory=lambda: deque(maxlen=16))

    def touch(self, msg: BufferedMessage) -> None:
        self.last_active_at = msg.timestamp
        self.participants.add(msg.sender_id)
        if msg.text.strip():
            self.texts.append(msg.text.strip())
        if self.status in (TopicStatus.NEW, TopicStatus.ACTIVE):
            self.status = TopicStatus.ACTIVE


@dataclass
class StellaSpeakStats:
    """Stella 自己的发言统计（惩罚项数据源，上游 §14）。

    被动应答（被 @ 后回复）与主动插话分开记：被叫到后回答不应该
    获得同等级的「我已经主动说很多话」惩罚。
    """

    last_spoke_at: float = 0.0          # 0 = 从未发言（进程内）
    last_kind: str = ""                 # "passive" | "proactive"
    consecutive_proactive: int = 0      # 连续主动发言次数（被动应答会中断计数）
    recent_topic_labels: deque[str] = field(default_factory=lambda: deque(maxlen=4))

    def note_spoke(self, kind: str, topic_label: str = "", now: float | None = None) -> None:
        now = now if now is not None else time.time()
        self.last_spoke_at = now
        self.last_kind = kind
        if kind == "proactive":
            self.consecutive_proactive += 1
        else:
            self.consecutive_proactive = 0
        if topic_label:
            self.recent_topic_labels.append(topic_label)


@dataclass
class ConversationState:
    """每群的 Conversation State（上游 §5）：不是聊天记录摘要，是当下状态。"""

    group_id: int
    buffer: MessageBuffer
    topic: Topic | None = None
    speak_stats: StellaSpeakStats = field(default_factory=StellaSpeakStats)
    # 群内最近一次 @/回复 Stella 的时间（Current Relevance 的输入之一）
    last_tome_at: float = 0.0

    async def ingest(
        self,
        msg: BufferedMessage,
        tables: ParticipationTables,
        *,
        similarity: Callable[[str, list[str]], "float | None | object"] | None = None,
        next_topic_id: Callable[[int], int] | None = None,
    ) -> Topic:
        """处理一条新消息：判断话题归属并更新状态。返回消息所属话题。

        similarity(text, topic_texts) 是异步回调，返回 await 后为 0~1 或 None
        （embedding 不可用时 None，走规则兜底）。
        """
        switched = await self._should_switch_topic(msg, tables, similarity)
        if switched or self.topic is None or self.topic.status is TopicStatus.EXPIRED:
            # EXPIRED 话题不允许重新激活：相关消息应创建新话题（上游 §6.4）
            tid = next_topic_id(self.group_id) if next_topic_id else int(msg.timestamp)
            self.topic = Topic(
                topic_id=tid,
                label=msg.text.strip()[:12] or f"topic-{tid}",
            )
        self.topic.touch(msg)
        self.buffer.append(msg)
        return self.topic

    async def _should_switch_topic(
        self,
        msg: BufferedMessage,
        tables: ParticipationTables,
        similarity: Callable[[str, list[str]], "float | None | object"] | None,
    ) -> bool:
        topic = self.topic
        if topic is None:
            return False
        text = msg.text.strip()
        if not text:
            return False
        sw = tables.thresholds.topic_switch

        # 规则信号：明确的承接/转移词 → 直接换话题
        if topic_shift_hit(text, tables.signals):
            return True

        # embedding 主判据：与当前话题最近文本的最大相似度低于阈值 → 切换候选
        if similarity is not None and topic.texts:
            sim = await similarity(text, list(topic.texts)[-sw.recent_texts :])
            if sim is not None and sim < sw.similarity_below:
                return True
            if sim is not None:
                return False

        # 规则兜底（embedding 不可用）：闲置超时 + 参与者变化
        idle = msg.timestamp - topic.last_active_at
        if idle > sw.fallback_idle_seconds and msg.sender_id not in topic.participants:
            return True
        return False

    def velocity_level(self, tables: ParticipationTables, now: float | None = None) -> tuple[str, int]:
        """消息速度档位与窗口内原始计数（上游 §23）。"""
        vw = tables.weights.velocity_penalty
        count = self.buffer.count_in_window(vw.window_seconds, now=now)
        if count >= vw.very_high_at:
            return VELOCITY_VERY_HIGH, count
        if count >= vw.high_at:
            return VELOCITY_HIGH, count
        if count >= vw.medium_at:
            return VELOCITY_MEDIUM, count
        return VELOCITY_LOW, count

    def advance_lifecycle(self, tables: ParticipationTables, now: float | None = None) -> str | None:
        """推进话题生命周期（由低频定时任务调用）：ACTIVE→COOLING→EXPIRED。

        返回发生的状态跃变描述（用于日志），无变化返回 None。
        """
        now = now if now is not None else time.time()
        topic = self.topic
        if topic is None:
            return None
        life = tables.thresholds.topic_lifecycle
        idle = now - topic.last_active_at
        if topic.status in (TopicStatus.NEW, TopicStatus.ACTIVE) and idle > life.cooling_after:
            topic.status = TopicStatus.COOLING
            return f"topic {topic.topic_id} → COOLING"
        if topic.status is TopicStatus.COOLING and idle > life.cooling_after + life.expire_after:
            topic.status = TopicStatus.EXPIRED
            return f"topic {topic.topic_id} → EXPIRED"
        return None
