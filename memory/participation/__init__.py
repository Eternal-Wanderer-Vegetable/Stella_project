# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动插话决策层（Participation Decision Layer）。

对外唯一入口是 ``get_participation_manager()``。设计见
design_docs/Stella_主动插话机制工程方案.md（上游架构）与
design_docs/Stella_主动插话机制实现方案.md（落地映射）。

分层（上游 §2）：

    group_silent_listener（priority 0，唯一逐条看到所有群消息的位置）
        → manager.observe()            消息进入
            → buffer.ingest            MessageBuffer + 话题归属
            → state.ingest             ConversationState / Topic 状态机
            → signals.extract          词表信号识别
            → scorer.score             9 项指标打分（零 LLM）
            → tracker.decide           IGNORE/OBSERVE/CANDIDATE/ALLOW_LLM
        → observability                全字段落日志/落库
        → ALLOW_LLM 时由 ai_gateway 复用 _proactive_speak_for_group 执行

本层不发送消息、不调用 LLM、不修改 @ 触发链路（上游原则 1/7/8）。
"""
from __future__ import annotations

import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from nonebot import logger

from memory.participation.buffer import BufferedMessage, MessageBuffer
from memory.participation.decision import (
    ALLOW_LLM,
    CANDIDATE,
    OBSERVE,
    DecisionTracker,
    ParticipationDecision,
)
from memory.participation.observability import (
    log_decision,
    record_to_db,
)
from memory.participation.scorer import (
    compose_final_score,
    ngram_jaccard,
)
from memory.participation.scorer import (
    score as score_message,
)
from memory.participation.signals import extract as extract_signals
from memory.participation.state import ConversationState
from memory.participation.tables import ParticipationTableError, TableStore

__all__ = [
    "BufferedMessage",
    "ParticipationManager",
    "ParticipationTableError",
    "get_participation_manager",
]


# ── 流程观测探针（计划 §6.4 消息驱动 participation 全等级）──────────
# 旁路纪律：ctx 为 None（观测未接入）或任何异常都不影响决策业务；
# metrics 只记 id/计数/阈值/score 数值，不记消息原文（计划 §6.1 隐私）。


def _flow_probe(ctx, node_id: str, **kw) -> None:
    """发一条 decision 事件；观测通道整体 fail-open。"""
    if ctx is None:
        return
    try:
        from core.observability import message_flow

        message_flow.decision(ctx, node_id, **kw)
    except Exception:
        pass


def _flow_probe_span(ctx, node_id: str, **kw):
    """开观测 span；失败返回 None（调用方跳过 finish，业务照常）。"""
    if ctx is None:
        return None
    try:
        from core.observability import message_flow

        return message_flow.span(ctx, node_id, **kw)
    except Exception:
        return None


class ParticipationManager:
    """每群一份 ConversationState（LRU），串起 buffer → state → score → decision。"""

    def __init__(
        self,
        tables_dir: Path | None = None,
        *,
        persist: bool = True,
        buffer_size: int = 200,
        max_groups: int = 64,
        jsonl_path: Path | None = None,
        md_path: Path | None = None,
        log_level: str = "full",
        clock: "Callable[[], float] | None" = None,
    ):
        # 延迟导入 config：benchmark/单测可注入独立路径
        if tables_dir is None:
            from config import PARTICIPATION_TABLES_DIR

            tables_dir = Path(PARTICIPATION_TABLES_DIR)
        if jsonl_path is None or md_path is None:
            from config import (
                PARTICIPATION_DECISION_LOG_PATH,
                PARTICIPATION_MD_LOG_PATH,
            )

            jsonl_path = jsonl_path or PARTICIPATION_DECISION_LOG_PATH
            md_path = md_path or PARTICIPATION_MD_LOG_PATH

        self._store = TableStore(tables_dir)
        self._persist = persist
        self._buffer_size = buffer_size
        self._max_groups = max_groups
        self._jsonl_path = Path(jsonl_path)
        self._md_path = Path(md_path)
        self._log_level = log_level

        self._groups: OrderedDict[int, ConversationState] = OrderedDict()
        self._tracker = DecisionTracker()
        self._topic_seq: dict[int, int] = {}  # group_id -> 已分配 topic_id 上限
        self._embedding = None  # 懒初始化（见 _embedding_service）
        # 注入时钟（计划 §6.9 层 1）：observe/tick/note_stella_spoke 全部走
        # 同一个 clock——离线回放与 benchmark 注入冻结时钟，绝不偷用 time.time。
        self._clock = clock or time.time

        self._load_tables_or_disable()

    # ── 打分表 ─────────────────────────────────────────

    def _load_tables_or_disable(self) -> None:
        try:
            tables = self._store.load()
            logger.info(
                f"📊 [参与评分] 打分表加载成功（{len(tables.topics.interests)} 个兴趣锚）"
            )
        except ParticipationTableError as e:
            # 打分表坏 = 决策层不可用，但不拖垮 bot 启动
            logger.error(f"❌ [参与评分] 打分表加载失败，决策层禁用: {e}")

    def reload_tables(self) -> tuple[bool, str]:
        """热重载打分表（管理员命令 / 调参流程）。失败保留旧表。"""
        ok, msg = self._store.reload()
        if ok:
            logger.success(f"📊 [参与评分] {msg}")
        else:
            logger.error(f"❌ [参与评分] 热重载失败（保留旧表）: {msg}")
        return ok, msg

    @property
    def enabled(self) -> bool:
        """打分表可用即视为决策层可用。"""
        return self._store.tables is not None

    # ── embedding（可选，懒初始化 + 静默降级） ──────────

    def _embedding_service(self):
        if self._embedding is not None:
            return self._embedding or None
        try:
            from config import (
                MEMORY_EMBEDDING_BASE_URL,
                MEMORY_EMBEDDING_MODEL,
                MEMORY_EMBEDDING_TIMEOUT,
            )
            from memory.embeddings import EmbeddingService

            svc = EmbeddingService(
                MEMORY_EMBEDDING_BASE_URL,
                MEMORY_EMBEDDING_MODEL,
                MEMORY_EMBEDDING_TIMEOUT,
            )
            self._embedding = svc if (MEMORY_EMBEDDING_BASE_URL or "").strip() else False
        except Exception:
            self._embedding = False
        return self._embedding or None

    async def _async_similarity(self, text: str, other: str) -> float | None:
        svc = self._embedding_service()
        if svc is None:
            return None
        try:
            from memory.embeddings import cosine_similarity

            a = await svc.embed(text)
            b = await svc.embed(other)
            if a is None or b is None:
                return None
            return cosine_similarity(a, b)
        except Exception:
            return None

    # ── 群状态管理 ──────────────────────────────────────

    def _state_for(self, group_id: int) -> ConversationState:
        state = self._groups.get(group_id)
        if state is None:
            state = ConversationState(group_id=group_id, buffer=MessageBuffer(self._buffer_size))
            self._groups[group_id] = state
        # LRU 触碰
        self._groups.move_to_end(group_id)
        # 超限释放：最旧的群直接丢弃（内存态，丢弃等价于重启，可接受）
        while len(self._groups) > self._max_groups:
            old_gid, _ = self._groups.popitem(last=False)
            logger.debug(f"[参与评分] 群 {old_gid} 状态超限释放（LRU）")
        return state

    def _next_topic_id(self, group_id: int) -> int:
        self._topic_seq[group_id] = self._topic_seq.get(group_id, 0) + 1
        return self._topic_seq[group_id]

    # ── 对外主入口 ──────────────────────────────────────

    async def observe(
        self,
        group_id: int,
        user_id: int,
        text: str,
        *,
        msg_id: int = 0,
        reply_to: int | None = None,
        mentioned_users: tuple[int, ...] = (),
        is_tome: bool = False,
        has_image: bool = False,
        has_emoji: bool = False,
        message_type: str = "text",
        now: float | None = None,
        flow_ctx=None,
    ) -> ParticipationDecision | None:
        """处理一条被动群消息；返回决策（不可评分时返回 None）。

        Hard Trigger（@/回复/点名）的消息**不调用本方法**——那是
        handle_chat 的职责（上游原则 7）。is_tome 仅用于 Current Relevance
        的时间戳记录。

        ``flow_ctx``：调用方显式传入的消息 root 观测上下文（计划 §6.2
        拒绝 ambient 传播）；None 时探针全部空转，业务等价。
        """
        tables = self._store.tables
        if tables is None:
            # 计划 §3.2/§6.4：禁用/无表早退也必须可查询，不能只展示
            # 触发说话的样本——否则「为什么没说」永远查不到证据。
            _flow_probe(flow_ctx, "participation.decision", status="blocked",
                        reason_code="tables_unavailable",
                        metrics={"group_id": group_id})
            return None
        now = now if now is not None else self._clock()
        state = self._state_for(group_id)
        # 逻辑发言记账（share 分母）：人类消息一条 = 一次逻辑发言
        state.note_speech(now, is_bot=False, text=text)

        msg = BufferedMessage(
            timestamp=now,
            sender_id=user_id,
            text=text,
            msg_id=msg_id,
            reply_to=reply_to,
            mentioned_users=mentioned_users,
            has_image=has_image,
            has_emoji=has_emoji,
            message_type=message_type,
        )
        if is_tome:
            state.last_tome_at = now

        # 话题归属（embedding 相似度主判据 + 规则兜底）
        async def _sim(text_: str, texts_: list[str]) -> float | None:
            svc = self._embedding_service()
            if svc is None or not texts_:
                return None
            best: float | None = None
            for t in texts_[-tables.thresholds.topic_switch.recent_texts :]:
                sim = await self._async_similarity(text_, t)
                if sim is not None and (best is None or sim > best):
                    best = sim
            return best

        topic = await state.ingest(msg, tables, similarity=_sim, next_topic_id=self._next_topic_id)

        # 热身：缓冲不足时不评分（信息量不够，避免开局乱插话）
        if len(state.buffer) < tables.thresholds.warmup_messages:
            # 计划 §6.4：预热早退也是决策事实（buffer/阈值计数，不含原文）
            _flow_probe(flow_ctx, "participation.decision", status="skipped",
                        reason_code="warmup_buffering",
                        metrics={
                            "group_id": group_id,
                            "buffer_size": len(state.buffer),
                            "warmup_messages": tables.thresholds.warmup_messages,
                        })
            return None

        recent_texts = state.buffer.texts(10)
        signals = extract_signals(recent_texts, text, tables.signals)
        velocity_level, velocity_count = state.velocity_level(tables, now=now)
        signals.high_velocity = velocity_level in ("HIGH", "VERY_HIGH")

        # Relevance 的 embedding 相似度（对兴趣锚描述文本）
        async def _anchor_sim(text_: str, desc: str) -> float | None:
            return await self._async_similarity(text_, desc)

        # 发言占比与新信息量（计划 §6.9 层 2）：纯本地计算，零模型调用
        tw = getattr(tables.weights, "timing", None)
        share = state.speech_share(tw.share_window_seconds, now=now) if tw is not None else None
        novelty = (
            max(
                (
                    ngram_jaccard(text, bot_text, tw.ngram_size)
                    for bot_text in state.recent_bot_texts
                ),
                default=0.0,
            )
            if tw is not None and state.recent_bot_texts
            else None
        )
        # 评分观测（计划 §6.4）：span 包住统一评分调用，metrics 记分项与
        # embedding 回退事实（布尔与数值，不含任何原文）。
        embedding_available = self._embedding_service() is not None
        score_span = _flow_probe_span(
            flow_ctx, "participation.score_compute",
            summary="统一评分（关键词 + embedding 增强或回退）",
        )
        breakdown = await self._score_with_embedding(
            state, signals, tables, velocity_level, velocity_count, recent_texts,
            _anchor_sim, now, speech_share=share, novelty=novelty,
        )
        if score_span is not None:
            with contextlib.suppress(Exception):
                score_span.finish(status="succeeded", metrics={
                    "final_score": round(breakdown.final_score, 1),
                    "velocity_level": breakdown.velocity_level,
                    "velocity_count": breakdown.velocity_count,
                    "speech_share": (
                        round(breakdown.speech_share, 3)
                        if breakdown.speech_share is not None else None),
                    "novelty": (
                        round(breakdown.novelty, 3)
                        if breakdown.novelty is not None else None),
                    # embedding 服务缺席/失败时评分为关键词回退（§6.9 层 2）
                    "embedding_fallback": not embedding_available,
                })

        # slot before（计划 §6.4 决策 tracker 观测）：decide 前后槽位快照。
        # 注意槽位是可变对象——before 必须在 decide 前取**值**，否则读到 after。
        _slot = self._tracker._slots.get(group_id)
        slot_before = (
            (_slot.streak, _slot.backoff_until, _slot.low_novelty_streak)
            if _slot is not None else (0, 0.0, 0)
        )
        decision = self._tracker.decide(
            group_id, breakdown, signals, tables.thresholds, topic.topic_id, msg_id,
            now=now, novelty=novelty, is_tome=False,
        )
        slot_after = self._tracker._slots.get(group_id)

        # 全等级决策事件（计划 §6.4 表「消息驱动 participation」）：四等级
        # IGNORE/OBSERVE/CANDIDATE/ALLOW 全部落 participation.decision，
        # reason_code 记实际退出原因（为什么没说与为什么说同表可查）。
        if decision.level == ALLOW_LLM:
            level_status, level_reason = "succeeded", "thresholds_passed"
        elif decision.level == CANDIDATE:
            level_status = "waiting"
            level_reason = (
                "idle_backoff" if "idle_backoff" in decision.reason_flags
                else "candidate_pending_confirmation")
        elif decision.level == OBSERVE:
            level_status, level_reason = "skipped", "below_candidate_threshold"
        else:  # IGNORE
            level_status, level_reason = "skipped", "below_ignore_threshold"
        _flow_probe(
            flow_ctx, "participation.decision", status=level_status,
            reason_code=level_reason,
            metrics={
                "level": decision.level,
                "mode": decision.mode,
                "score": round(decision.score, 1),
                "confidence": round(decision.confidence, 2),
                "topic_id": decision.topic_id,
                "msg_id": decision.trigger_msg_id,
            },
        )
        # tracker 槽位观测（计划 §5/§6.4）：slot before/after、streak、
        # backoff_until 与话题版本，回答「为什么现在说/为什么还不说」。
        _flow_probe(
            flow_ctx, "participation.mode", status="succeeded",
            metrics={
                "streak_before": slot_before[0],
                "streak": slot_after.streak if slot_after else 0,
                "backoff_until_before": slot_before[1],
                "backoff_until": slot_after.backoff_until if slot_after else 0.0,
                "low_novelty_streak": (
                    slot_after.low_novelty_streak if slot_after else 0),
                "topic_revision": self.topic_revision(group_id),
                "mode": decision.mode,
                "level": decision.level,
            },
        )

        # 可观测性（loguru + JSONL + MD；落库在 persist 开启时）
        log_decision(
            decision,
            state,
            jsonl_path=self._jsonl_path,
            md_path=self._md_path,
            configured_level=self._log_level,
            event="decision_allow" if decision.should_speak else "decision",
        )
        if self._persist and decision.level in ("CANDIDATE", ALLOW_LLM):
            record_to_db(decision, group_id)

        if topic.status.value in ("COOLING", "EXPIRED"):
            pass  # 状态持久化交给 tick()，避免每条消息写库

        return decision

    async def _score_with_embedding(
        self, state, signals, tables, velocity_level, velocity_count, recent_texts,
        anchor_sim, now, *, speech_share=None, novelty=None,
    ):
        """scorer.score 的异步包装：先用关键词打分，再用 embedding 增强 Relevance。

        任一通道失败都静默保留另一通道的结果——embedding 缺席不拖低关键词分。
        最终分合成统一走 scorer.compose_final_score（计划 §6.9：与关闭 embedding
        的路径共用同一公式）。
        """
        breakdown = score_message(
            state, signals, tables, velocity_level, velocity_count, recent_texts,
            similarity=None, now=now, speech_share=speech_share, novelty=novelty,
        )
        try:
            corpus = " ".join(recent_texts[-6:])
            if not corpus.strip():
                return breakdown
            best: float | None = None
            for anchor in tables.topics.interests:
                if not anchor.description:
                    continue
                sim = await anchor_sim(corpus, anchor.description)
                if sim is not None and (best is None or sim > best):
                    best = sim
            if best is None:
                return breakdown

            w = tables.weights.relevance
            if best <= w.embedding_zero_at:
                scaled = 0.0
            elif best >= w.embedding_full_at:
                scaled = w.long_term_max
            else:
                t = (best - w.embedding_zero_at) / (w.embedding_full_at - w.embedding_zero_at)
                scaled = t * w.long_term_max

            # 拆回 long-term / current 两部分：long-term 取关键词与 embedding 较大者
            long_term_old = min(breakdown.relevance, w.long_term_max)
            current_old = breakdown.relevance - long_term_old
            breakdown.relevance = max(0.0, min(w.max, max(long_term_old, scaled) + current_old))

            breakdown.final_score = compose_final_score(breakdown)
        except Exception:
            pass
        breakdown.final_score = compose_final_score(breakdown)
        return breakdown

    # ── Stella 自己的发言记账（惩罚项输入） ─────────────

    def note_stella_spoke(
        self, group_id: int, kind: str = "proactive", *, now: float | None = None,
        text: str = "",
    ) -> None:
        """ai_gateway 在**确认送达**后调用：kind = passive（被 @ 回复）/ proactive。

        上游 §14：被叫到后回答不应该获得与主动插话同等级的惩罚。
        ``text`` 传入已发首段（多段算一次）：新信息量（novelty）的比对语料；
        ``now`` 缺省走注入时钟，绝不直接 time.time（计划 §6.9 层 1）。
        """
        state = self._groups.get(group_id)
        if state is None:
            return
        now = now if now is not None else self._clock()
        state.note_speech(now, is_bot=True, text=text)
        topic_label = state.topic.label if state.topic else ""
        state.speak_stats.note_spoke(kind, topic_label, now=now)
        if state.topic is not None and kind == "proactive":
            state.topic.proactive_speak_count += 1
            state.topic.stella_involved = True
        elif state.topic is not None:
            state.topic.stella_involved = True

    # ── 话题版本（计划 §6.9 层 3：过期主动输出发送前检查） ──

    def topic_revision(self, group_id: int) -> int:
        """当前话题版本号；群无状态视为 0。"""
        state = self._groups.get(group_id)
        return state.topic_revision if state else 0

    def bump_topic_revision(self, group_id: int) -> int:
        """显式推进话题版本（静音/撤销/新直接请求等取消信号）。返回新版本。"""
        state = self._state_for(group_id)
        return state.bump_topic_revision()

    # ── 定时推进（COOLING→EXPIRED，由 ai_gateway 挂 APScheduler） ──

    def tick(self) -> list[str]:
        """推进所有群的话题生命周期并持久化；返回跃变描述（日志用）。"""
        tables = self._store.tables
        if tables is None:
            return []
        changes: list[str] = []
        for group_id, state in list(self._groups.items()):
            change = state.advance_lifecycle(tables, now=self._clock())
            if change:
                changes.append(f"群 {group_id} {change}")
        if self._persist and changes:
            self._persist_topics()
        return changes

    def _persist_topics(self) -> None:
        """把各群当前话题状态 UPSERT 到 participation_topics（失败静默）。"""
        try:
            import sqlite3

            from config import DB_PATH
            from memory.schema import create_participation_topics_table

            conn = sqlite3.connect(DB_PATH)
            try:
                create_participation_topics_table(conn)
                with conn:
                    for gid, state in self._groups.items():
                        topic = state.topic
                        if topic is None:
                            continue
                        conn.execute(
                            "INSERT INTO participation_topics (group_id, topic_id, label, status,"
                            " started_at, last_active_at, stella_involved, speak_count)"
                            " VALUES (?,?,?,?,?,?,?,?)"
                            " ON CONFLICT(group_id, topic_id) DO UPDATE SET"
                            " status=excluded.status, last_active_at=excluded.last_active_at,"
                            " stella_involved=excluded.stella_involved,"
                            " speak_count=excluded.speak_count",
                            (
                                str(gid),
                                topic.topic_id,
                                topic.label,
                                topic.status.value,
                                datetime_iso(topic.started_at),
                                datetime_iso(topic.last_active_at),
                                int(topic.stella_involved),
                                topic.proactive_speak_count,
                            ),
                        )
            finally:
                conn.close()
        except Exception as e:  # pragma: no cover
            logger.debug(f"[参与评分] participation_topics 持久化失败（跳过）: {e}")

    # ── 观测辅助 ────────────────────────────────────────

    def log_event(
        self,
        decision: ParticipationDecision,
        event: str,
        *,
        reason: str = "",
    ) -> None:
        """记录 ALLOW_LLM 之后的生成/发送生命周期事件。"""
        state = self._groups.get(decision.group_id)
        if state is None:
            return
        log_decision(
            decision,
            state,
            jsonl_path=self._jsonl_path,
            md_path=self._md_path,
            configured_level=self._log_level,
            event=event,
            event_reason=reason,
        )

    def snapshot(self, group_id: int | None = None) -> dict:
        """给 status API / benchmark 用的群状态快照。"""
        groups = {}
        items = [(group_id, self._groups[group_id])] if group_id in self._groups else list(self._groups.items())
        for gid, state in items:
            topic = state.topic
            tables = self._store.tables
            if tables is not None:
                velocity_level, velocity_count = state.velocity_level(tables)
            else:  # pragma: no cover - disabled manager has no live state
                velocity_level, velocity_count = "UNKNOWN", 0
            recent_messages = [
                {
                    "msg_id": msg.msg_id,
                    "sender_id": msg.sender_id,
                    "text": msg.text.strip()[:160],
                }
                for msg in state.buffer.tail(6)
                if msg.text.strip()
            ]
            groups[str(gid)] = {
                "topic_id": topic.topic_id if topic else None,
                "label": topic.label if topic else "",
                "status": topic.status.value if topic else "NONE",
                "participants": sorted(topic.participants) if topic else [],
                "stella_involved": bool(topic.stella_involved) if topic else False,
                "stella_last_spoke_at": state.speak_stats.last_spoke_at or None,
                "buffer_size": len(state.buffer),
                "velocity_level": velocity_level,
                "velocity_count": velocity_count,
                "recent_messages": recent_messages,
            }
        return {"enabled": self.enabled, "groups": groups}


def datetime_iso(ts: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


# ── 全局单例 ────────────────────────────────────────────

_manager: ParticipationManager | None = None


def get_participation_manager() -> ParticipationManager:
    global _manager
    if _manager is None:
        from config import (
            PARTICIPATION_BUFFER_SIZE,
            PARTICIPATION_LOG_LEVEL,
            PARTICIPATION_MAX_GROUPS,
        )

        _manager = ParticipationManager(
            buffer_size=PARTICIPATION_BUFFER_SIZE,
            max_groups=PARTICIPATION_MAX_GROUPS,
            log_level=PARTICIPATION_LOG_LEVEL,
        )
    return _manager


def reset_manager_for_tests() -> None:
    """清空单例（测试隔离用）。"""
    global _manager
    _manager = None
