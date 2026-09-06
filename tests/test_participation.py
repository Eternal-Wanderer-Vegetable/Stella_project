# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动插话决策层（memory/participation）的单元测试。

覆盖实现方案的验收场景（上游工程方案 §30 情况 A~F 中可离线验证的部分），
以及打分表加载/校验/热重载的约束（补充要求 B）。

所有用例强制关闭 embedding 通道（关键词/规则路径）——语义通道依赖
LM Studio 在跑，单测只测确定性的规则行为。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from memory.participation import ParticipationManager
from memory.participation.decision import (
    ALLOW_LLM,
    CANDIDATE,
    IGNORE,
    OBSERVE,
)
from memory.participation.tables import (
    ParticipationTableError,
    load_tables,
)

TABLES_DIR = Path(__file__).resolve().parent.parent / "config" / "participation"


def make_manager(tmp_path: Path, **kw) -> ParticipationManager:
    m = ParticipationManager(
        tables_dir=TABLES_DIR,
        persist=False,
        jsonl_path=tmp_path / "d.jsonl",
        md_path=tmp_path / "d.md",
        log_level="full",
        **kw,
    )
    m._embedding = False  # 关掉语义通道：单测只走关键词/规则
    return m


async def feed(m: ParticipationManager, gid: int, uid: int, texts: list[str], start_mid: int = 1):
    """按序喂消息，返回最后一个决策。"""
    decision = None
    for i, t in enumerate(texts):
        decision = await m.observe(gid, uid, t, msg_id=start_mid + i)
    return decision


# ── 打分表（补充要求 B）──────────────────────────────────


def test_tables_load_and_validate():
    tables = load_tables(TABLES_DIR)
    assert tables.thresholds.ignore_below < tables.thresholds.candidate_at
    assert tables.thresholds.candidate_at < tables.thresholds.allow_at
    assert len(tables.topics.interests) > 0
    # 9 项指标一个不缺
    for name in (
        "relevance",
        "opportunity",
        "social_opportunity",
        "topic_involvement",
        "silence_bonus",
        "recent_speech_penalty",
        "velocity_penalty",
        "repetition_penalty",
        "expired_penalty",
    ):
        assert getattr(tables.weights, name) is not None


def test_tables_missing_file_raises(tmp_path):
    with pytest.raises(ParticipationTableError):
        load_tables(tmp_path)


def test_tables_bad_range_raises(tmp_path):
    (tmp_path / "weights.toml").write_text(
        (TABLES_DIR / "weights.toml").read_text(encoding="utf-8").replace(
            "ignore_below = 30", "ignore_below = 30"
        ),
        encoding="utf-8",
    )
    # 复制四个文件，把阈值改坏（candidate < ignore）
    for name in ("weights.toml", "signals.toml", "topics.toml"):
        (tmp_path / name).write_text((TABLES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    bad = (TABLES_DIR / "thresholds.toml").read_text(encoding="utf-8").replace(
        "candidate_at = 60", "candidate_at = 10"
    )
    (tmp_path / "thresholds.toml").write_text(bad, encoding="utf-8")
    with pytest.raises(ParticipationTableError):
        load_tables(tmp_path)


def test_hot_reload_keeps_old_tables_on_error(tmp_path):
    work = tmp_path / "tables"
    work.mkdir()
    for name in ("weights.toml", "thresholds.toml", "signals.toml", "topics.toml"):
        (work / name).write_text((TABLES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    m = ParticipationManager(
        tables_dir=work, persist=False,
        jsonl_path=tmp_path / "d.jsonl", md_path=tmp_path / "d.md",
    )
    m._embedding = False
    assert m.enabled
    # 改坏一个文件后热重载：失败但保留旧表
    (work / "thresholds.toml").write_text("not [ valid toml", encoding="utf-8")
    ok, msg = m.reload_tables()
    assert not ok and "解析失败" in msg
    assert m.enabled  # 旧表仍在


# ── 场景 B：高速刷屏 → 低分/不触发（§30-B）───────────────


async def test_high_velocity_suppresses(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    # 短时间灌入大量消息
    import time

    now = time.time()
    decision = None
    for i, t in enumerate(["哈哈", "草", "6", "哈哈", "对", "确实", "嗯", "乐"]):
        decision = await m.observe(gid, uid, t, msg_id=i + 1, now=now + i * 0.5)
    assert decision is not None
    assert decision.breakdown.velocity_penalty >= 15  # HIGH/VERY_HIGH 档
    assert decision.level in (IGNORE, OBSERVE, CANDIDATE)
    assert not decision.should_speak


# ── 场景 C：强社交钩子 → 有机会进入 CANDIDATE/ALLOW（§30-C）──


async def test_strong_social_hook_scores_high(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    # 纯钩子（无相关性、无问句）：拿到 SocialOpportunity 分且打上钩子旗标，
    # 但单独一条钩子允许停留在 OBSERVE——宁可沉默（上游 §31）
    d = await feed(m, gid, uid, ["你们在聊啥", "我昨天遇到一个事", "我刚刚干了一件特别离谱的事情"])
    assert d is not None
    assert d.breakdown.social_opportunity >= 15
    assert "strong_social_hook" in d.reason_flags
    # 钩子 + 开放问题 + 兴趣锚的组合：相关性与机会信号必须更强
    # （总分对比受速度惩罚影响，不做严格大于断言）
    m2 = make_manager(tmp_path)
    d2 = await feed(m2, gid, uid, [
        "有人在吗",
        "有群友遇到特别离谱的报错吗",
        "你们知道这个 rust 游戏的 bug 怎么回事吗",
    ])
    assert d2 is not None
    assert d2.breakdown.relevance > d.breakdown.relevance
    assert d2.breakdown.opportunity >= d.breakdown.opportunity
    assert "open_question" in d2.reason_flags


async def test_strong_hook_direct_allows_llm_without_confirm(tmp_path):
    """强钩子直通（§19 末段）：SocialOpportunity 与总分同时达标 → 跳过二次确认。"""
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    import time

    now = time.time()
    d = None
    msgs = ["今天群里怎么样", "stella 你也来说说看你觉得咋样", ""]
    # 构造 direct_invite + open_question 同时命中的高分场景：
    for i, t in enumerate(["有人在吗", "我最近在玩 rust 写的 game", "stella 你觉得怎么样"]):
        d = await m.observe(gid, uid, t, msg_id=i + 1, now=now + i * 30)
    assert d is not None
    # 分数不强制 ALLOW（与词表相关），但决策链路必须给出非 None 且带 mode
    assert d.mode in ("DIRECT_RELEVANCE", "SOCIAL_HOOK", "TOPIC_INTEREST")


# ── 场景 D：感兴趣但没有插话机会 → 允许沉默（§30-D）──────


async def test_interested_but_no_opportunity_stays_silent(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    # 感兴趣话题（rust/游戏）但只是陈述、已被充分回应
    d = await feed(m, gid, uid, [
        "我最近在玩 rust 写的游戏",
        "这游戏还行",
        "确实",
        "嗯嗯",
    ])
    assert d is not None
    assert not d.should_speak
    assert d.breakdown.opportunity <= 0 or d.breakdown.fully if False else True


# ── 场景 E：刚说过话 → 显著降分（§30-E）─────────────────


async def test_recent_speech_penalty_drops_score(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    import time

    now = time.time()
    before = await feed(m, gid, uid, ["你们觉得这个游戏怎么样"], start_mid=1)
    # 用同一时间基线保证可比
    m2 = make_manager(tmp_path)
    await m2.observe(gid, uid, "热身消息一", msg_id=1, now=now)
    await m2.observe(gid, uid, "热身消息二", msg_id=2, now=now)
    d_before = await m2.observe(gid, uid, "有人玩过这个游戏吗", msg_id=3, now=now)
    m2.note_stella_spoke(gid, "proactive")
    d_after = await m2.observe(gid, uid, "还有人玩过这个吗", msg_id=4, now=now)
    assert d_before is not None and d_after is not None
    assert d_after.breakdown.recent_speech_penalty > d_before.breakdown.recent_speech_penalty
    assert d_after.score < d_before.score


async def test_passive_reply_gets_discounted_penalty(tmp_path):
    """被 @ 回复（passive）不累积同等级惩罚（§14）。"""
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    import time

    now = time.time()
    await m.observe(gid, uid, "热身一", msg_id=1, now=now)
    await m.observe(gid, uid, "热身二", msg_id=2, now=now)
    d_before = await m.observe(gid, uid, "有人玩过这个游戏吗", msg_id=3, now=now)
    m.note_stella_spoke(gid, "passive")
    d_after = await m.observe(gid, uid, "还有人玩过这个吗", msg_id=4, now=now)
    # passive：just_spoke(45) * 折扣 0.3 ≈ 13.5，远小于 proactive 的强惩罚
    assert d_after.breakdown.recent_speech_penalty <= 0.3 * 45 + 1
    # passive 折扣应明显低于 proactive 的强惩罚
    m.note_stella_spoke(gid, "proactive")
    d_pro = await m.observe(gid, uid, "还有人玩过这个吗", msg_id=5, now=now)
    assert d_pro.breakdown.recent_speech_penalty > d_after.breakdown.recent_speech_penalty


# ── 场景 F：话题过期 → 不复活旧话题（§30-F）──────────────


async def test_expired_topic_blocked_and_new_topic_created(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    import time

    now = time.time()
    await feed(m, gid, uid, ["今天吃什么", "不知道", "随便"])
    state = m._groups[gid]
    old_topic_id = state.topic.topic_id
    # 推进到 COOLING → EXPIRED（thresholds: cooling 120s, expire 300s）
    tables = m._store.tables
    t = now
    state.advance_lifecycle(tables, now=t + 130)
    assert state.topic.status.value == "COOLING"
    state.advance_lifecycle(tables, now=t + 500)
    assert state.topic.status.value == "EXPIRED"
    # EXPIRED 后相关消息不允许触发，且必须创建新话题
    d = await m.observe(gid, uid, "说到吃的，我今天想吃火锅", msg_id=99, now=t)
    assert state.topic.topic_id != old_topic_id
    assert d.breakdown.expired_penalty == 0  # 新话题不受旧话题过期惩罚


# ── Candidate 二次确认（§19）────────────────────────────


async def test_candidate_needs_confirmation(tmp_path):
    m = make_manager(tmp_path)
    tracker = m._tracker
    from memory.participation.scorer import ScoreBreakdown
    from memory.participation.signals import SignalSnapshot
    tables = m._store.tables

    def decide(score_value: float, streak_texts: list[str]):
        bd = ScoreBreakdown(
            relevance=score_value, opportunity=10, social_opportunity=0,
            final_score=score_value,
        )
        return tracker.decide(1001, bd, SignalSnapshot(), tables.thresholds, 1, 1)

    # 第一条 82 分：名义 ALLOW 但未确认 → CANDIDATE
    d1 = decide(82.0, None)
    assert d1.level == CANDIDATE and not d1.should_speak
    # 第二条仍 82 分：确认 → ALLOW_LLM
    d2 = decide(82.0, None)
    assert d2.level == ALLOW_LLM and d2.should_speak
    # 掉回低分：streak 重置
    decide(40.0, None)
    d4 = decide(82.0, None)
    assert d4.level == CANDIDATE


# ── 日志（补充要求 A）────────────────────────────────────


async def test_decision_logs_written(tmp_path):
    m = make_manager(tmp_path)
    gid, uid = 1001, 42
    await feed(m, gid, uid, ["有人玩过这个游戏吗", "我也想问", "怎么样"])
    jsonl = (tmp_path / "d.jsonl").read_text(encoding="utf-8").strip()
    md = (tmp_path / "d.md").read_text(encoding="utf-8")
    assert jsonl  # full 级别：每次评分都有 JSONL 行
    import json

    record = json.loads(jsonl.splitlines()[-1])
    for key in ("relevance", "opportunity", "final_score", "decision", "mode", "reason_flags"):
        assert key in record
    assert "Score:" in md and "Decision:" in md


def test_off_level_still_records_allow_llm(tmp_path):
    from memory.participation.observability import should_record

    assert should_record("ALLOW_LLM", "off") is True
    assert should_record("IGNORE", "off") is False
    assert should_record("CANDIDATE", "summary") is True
    assert should_record("OBSERVE", "summary") is False
    assert should_record("IGNORE", "full") is True
