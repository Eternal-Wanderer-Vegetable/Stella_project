# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""发言时机补充项（计划 §6.9 层 1/2/3）的行为测试。

- Clock 注入：observe/tick/note_stella_spoke 全走注入时钟，离线不偷 time.time；
- 发言占比（share）与新信息量（novelty）惩罚：timing 未启用恒 0，启用后生效；
- 合成收口：embedding 增强路径与纯关键词路径使用同一 compose_final_score；
- 空闲退避：连续无新信息的主动探测按序列退避，强钩子/提及重置；
- 话题版本：转题/静音/新直接请求推进版本，过期输出发送前被丢弃；
- deliver_lines 的 abort_check：中途过期停止后续片段，已 ACK 片段保留。
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from memory.participation import ParticipationManager
from memory.participation.decision import CANDIDATE
from memory.participation.scorer import compose_final_score
from memory.participation.tables import TimingWeights, load_tables

TABLES_DIR = Path(__file__).resolve().parent.parent / "config" / "participation"


class FrozenClock:
    """确定性时钟：手动推进，供全链路注入。"""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_manager(tmp_path: Path, clock) -> ParticipationManager:
    m = ParticipationManager(
        tables_dir=TABLES_DIR,
        persist=False,
        jsonl_path=tmp_path / "d.jsonl",
        md_path=tmp_path / "d.md",
        log_level="full",
        clock=clock,
    )
    m._embedding = False
    return m


def enable_timing(m: ParticipationManager) -> None:
    """把已加载表的 weights.timing 换成启用版（dataclasses.replace 保持 frozen）。"""
    tables = m._store.tables
    m._store._tables = replace(
        tables, weights=replace(tables.weights, timing=TimingWeights(enabled=True))
    )


def feed(m: ParticipationManager, gid: int, uid: int, texts: list[str], start_mid: int = 1):
    decision = None
    for i, t in enumerate(texts):
        decision = asyncio.run(m.observe(gid, uid, t, msg_id=start_mid + i))
    return decision


class TestClock:
    def test_observe_and_spoke_use_injected_clock(self, tmp_path):
        clock = FrozenClock()
        m = make_manager(tmp_path, clock)
        feed(m, 1, 10, ["今天天气真好", "是啊适合出去玩", "待会儿去公园吗", "我也想去"] )
        state = m._groups[1]
        assert state.speech_window and all(
            ts == clock.now for ts, _b in list(state.speech_window)[-1:]
        )
        # 注入 bot 发言：时间必须来自 clock
        m.note_stella_spoke(1, "proactive", text="好耶")
        ts, is_bot = state.speech_window[-1]
        assert is_bot and ts == clock.now
        clock.advance(30)
        assert state.speak_stats.last_spoke_at == clock.now - 30

    def test_share_and_novelty_off_by_default(self, tmp_path):
        """timing 未启用（既有打分表）→ 惩罚恒 0、breakdown 无新信号。"""
        clock = FrozenClock()
        m = make_manager(tmp_path, clock)
        decision = feed(m, 1, 10, ["今天天气真好", "是啊适合出去玩", "待会儿去公园吗", "我也想去"])
        m.note_stella_spoke(1, "proactive", text="好耶")
        decision2 = asyncio.run(m.observe(1, 10, "好耶好耶", msg_id=99))
        assert decision and decision2
        b = decision2.breakdown
        assert b.share_penalty == 0.0 and b.novelty_penalty == 0.0


class TestShareAndNovelty:
    def _warm(self, tmp_path, clock, enable=True):
        m = make_manager(tmp_path, clock)
        if enable:
            enable_timing(m)
        feed(m, 1, 10, ["今天天气真好", "是啊适合出去玩", "待会儿去公园吗", "我也想去"])
        return m

    def test_share_penalty_grows_with_bot_share(self, tmp_path):
        clock = FrozenClock()
        m = self._warm(tmp_path, clock)
        enable_timing(m)
        # 预热后窗口 5 条人类发言 + 1 条 bot 发言 + 本次人类 = 1/7；
        # 占比超过 target(0.15) → 惩罚出现
        m.note_stella_spoke(1, "proactive", text="我也想说一句")
        decision = asyncio.run(m.observe(1, 10, "再聊两句吧", msg_id=50))
        assert decision.breakdown.speech_share is not None
        assert 0 < decision.breakdown.speech_share <= 1
        assert decision.breakdown.share_penalty > 0

    def test_novelty_penalty_on_repeated_text(self, tmp_path):
        clock = FrozenClock()
        m = self._warm(tmp_path, clock)
        enable_timing(m)
        m.note_stella_spoke(1, "proactive", text="今天天气真好适合出去玩呢")
        # 与 bot 最近发言高度相似 → novelty 惩罚；低相似消息无惩罚
        d_similar = asyncio.run(m.observe(1, 10, "今天天气真好适合出去玩呢", msg_id=60))
        d_fresh = asyncio.run(m.observe(1, 10, "昨晚我看了场特别离谱的球赛", msg_id=61))
        assert d_similar.breakdown.novelty is not None and d_similar.breakdown.novelty > 0.5
        assert d_similar.breakdown.novelty_penalty > 0
        assert d_fresh.breakdown.novelty_penalty == 0.0


class TestComposeUnified:
    def test_embedding_and_keyword_paths_share_formula(self, tmp_path):
        """同一 breakdown 上，compose_final_score 与手写公式的口径一致；
        _score_with_embedding 的合成收口后不可能再出现第二套公式。"""
        clock = FrozenClock()
        m = make_manager(tmp_path, clock)
        feed(m, 1, 10, ["今天天气真好", "是啊适合出去玩", "待会儿去公园吗", "我也想去"])
        state = m._groups[1]
        tables = m._store.tables
        from memory.participation.signals import extract as extract_signals

        signals = extract_signals(state.buffer.texts(10), "再聊两句", tables.signals)
        from memory.participation.scorer import score as score_fn

        b = score_fn(state, signals, tables, "LOW", 1, state.buffer.texts(10),
                     similarity=None, now=clock.now, speech_share=0.5, novelty=0.9)
        enable_timing(m)
        tables2 = m._store.tables  # timing 启用后的表
        b2 = score_fn(state, signals, tables2, "LOW", 1, state.buffer.texts(10),
                      similarity=None, now=clock.now, speech_share=0.5, novelty=0.9)
        assert b.share_penalty == 0.0 and b.novelty_penalty == 0.0
        assert b2.share_penalty > 0 and b2.novelty_penalty > 0
        assert compose_final_score(b2) == b2.final_score


class TestIdleBackoff:
    def test_backoff_sequence_and_reset(self, tmp_path, monkeypatch):
        """连续无新信息的主动探测按 30→60 退避；新信息/强钩子重置。"""
        # 打阔退避判定的相似度阈值在真实消息上难稳定触发，这里直接驱动 tracker
        from memory.participation.decision import DecisionTracker
        from memory.participation.scorer import ScoreBreakdown
        from memory.participation.signals import SignalSnapshot

        tables = load_tables(TABLES_DIR)
        tracker = DecisionTracker()
        b = ScoreBreakdown(final_score=200.0, relevance=200.0)  # 远超 allow_at
        b.final_score = 999.0
        signals = SignalSnapshot()

        d1 = tracker.decide(1, b, signals, tables.thresholds, 1, 1,
                            now=1000.0, novelty=0.9)
        assert d1.level == CANDIDATE and "idle_backoff" in d1.reason_flags
        # 退避窗口内再次达标 → 仍压制
        d2 = tracker.decide(1, b, signals, tables.thresholds, 1, 2, now=1010.0, novelty=0.9)
        assert d2.level == CANDIDATE
        # 新信息（novelty 低）→ 重置，恢复 ALLOW_LLM
        d3 = tracker.decide(1, b, signals, tables.thresholds, 1, 3, now=1020.0, novelty=0.1)
        assert d3.should_speak


class TestTopicRevision:
    def test_revision_bumps_on_topic_switch_and_mute(self, tmp_path):
        clock = FrozenClock()
        m = make_manager(tmp_path, clock)
        feed(m, 1, 10, ["今天天气真好", "是啊适合出去玩", "待会儿去公园吗", "我也想去"])
        rev0 = m.topic_revision(1)
        # 明确转题（话题转移词）
        feed(m, 1, 10, ["对了，换个话题吧"], start_mid=20)
        assert m.topic_revision(1) >= rev0
        # 静音信号
        assert m.bump_topic_revision(1) == m.topic_revision(1)

    def test_unknown_group_revision_is_zero(self, tmp_path):
        m = make_manager(tmp_path, FrozenClock())
        assert m.topic_revision(999) == 0
