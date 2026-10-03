# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言闭环观测探针合同（计划 §6.4 / M3 退出条件）。

覆盖：
- participation.observe 全等级（IGNORE/OBSERVE/CANDIDATE/ALLOW）与
  预热/禁用早退都落 ``participation.decision``——「为什么没说」可查询；
- 评分 span ``participation.score_compute`` 分项与 embedding 回退事实；
- tracker ``participation.mode`` slot before/after、streak、backoff
  （``decision._clock`` 注入控制时间，计划 §5）；
- ``proactive_speak_job`` 前置 root：开关关/无 Bot 的退出原因可查；
- 主动 @ 资格（can_at_user 拒绝原因）落 ``proactive.at.preflight``；
- 无候选 / 选中候选落 ``proactive.at.select``（无候选 = noop 有原因）；
- 旁路纪律：探针异常不影响 observe 返回值；无 ctx 时业务等价。

评分用确定性 fake（与 tests/test_participation.py 的 breakdown 构造同法），
只测探针合同，不测评分词表本身。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.observability import message_flow, turn_trace

TABLES_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "participation"


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


@pytest.fixture(scope="module")
def gateway():
    """加载网关模块一次（proactive_speak_job 只在 scheduler 可用时注册）。"""
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    from stella_project.plugins.bot_main import ai_gateway

    return ai_gateway


def make_manager(tmp_path: Path, **kw):
    from memory.participation import ParticipationManager

    m = ParticipationManager(
        tables_dir=TABLES_DIR,
        persist=False,
        jsonl_path=tmp_path / "d.jsonl",
        md_path=tmp_path / "d.md",
        log_level="off",
        **kw,
    )
    m._embedding = False  # 关掉语义通道：embedding_service() → None（fallback 事实）
    return m


def _fake_score(score_value: float):
    """确定性评分替身：observe 的探针合同只依赖 final_score 与等级映射。"""
    from memory.participation.scorer import ScoreBreakdown

    async def fake(state, signals, tables, velocity_level, velocity_count,
                   recent_texts, anchor_sim, now, *,
                   speech_share=None, novelty=None):
        return ScoreBreakdown(
            relevance=0.0, opportunity=0.0, social_opportunity=0.0,
            final_score=score_value,
        )

    return fake


def _faketicks():
    tick = [100.0]

    def _next() -> float:
        v = tick[0]
        tick[0] += 1.0
        return v

    return _next


def _events(db, trace_id: str, node_id: str | None = None,
            kind: str | None = None) -> list[SimpleNamespace]:
    conn = sqlite3.connect(db)
    try:
        sql = ("SELECT kind, node_id, status, reason_code, metrics "
               "FROM flow_events WHERE trace_id=?")
        params: list[str] = [trace_id]
        if node_id:
            sql += " AND node_id=?"
            params.append(node_id)
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    finally:
        conn.close()
    out = []
    for k, n, s, r, m in rows:
        try:
            metrics = json.loads(m) if m else {}
        except json.JSONDecodeError:
            metrics = {}
        out.append(SimpleNamespace(
            kind=k, node_id=n, status=s, reason_code=r, metrics=metrics))
    return out


def _latest_trace(db, root_kind: str):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT trace_id, origin, scope, outcome, status FROM message_traces "
            "WHERE root_kind=? ORDER BY started_utc DESC LIMIT 1",
            (root_kind,)).fetchone()
    finally:
        conn.close()


# ── (a) 消息驱动 participation 全等级 ────────────────────────


class TestParticipationAllLevels:
    def test_observe_records_all_levels_and_warmup_exit(self, flow_db, tmp_path):
        """四等级 + 预热早退全部落 participation.decision（计划 §3.2/§6.4）。"""
        m = make_manager(tmp_path)
        gid, uid = 2001, 42
        root = message_flow.begin_trace(root_kind="qq_passive", trace_id="obs-1")
        # 前两条：缓冲不足 warmup(3) → 预热早退（也要有事件）
        for i in (1, 2):
            out = asyncio.run(m.observe(
                gid, uid, f"热身{i}", msg_id=i, now=1000.0 + i, flow_ctx=root))
            assert out is None
        # 第三条起进入评分：依次喂 IGNORE/OBSERVE/CANDIDATE/ALLOW 分数
        m._score_with_embedding = _fake_score(10.0)
        assert asyncio.run(m.observe(
            gid, uid, "消息三", msg_id=3, now=1003.0, flow_ctx=root)).level == "IGNORE"
        m._score_with_embedding = _fake_score(40.0)
        assert asyncio.run(m.observe(
            gid, uid, "消息四", msg_id=4, now=1004.0, flow_ctx=root)).level == "OBSERVE"
        m._score_with_embedding = _fake_score(82.0)
        assert asyncio.run(m.observe(
            gid, uid, "消息五", msg_id=5, now=1005.0, flow_ctx=root)).level == "CANDIDATE"
        assert asyncio.run(m.observe(
            gid, uid, "消息六", msg_id=6, now=1006.0, flow_ctx=root)).level == "ALLOW_LLM"
        message_flow.end_trace(root)
        message_flow.flush()

        decisions = _events(flow_db, "obs-1", node_id="participation.decision",
                            kind="decision")
        reasons = [e.reason_code for e in decisions]
        assert reasons[:2] == ["warmup_buffering", "warmup_buffering"]
        assert decisions[0].metrics["buffer_size"] == 1
        assert decisions[0].metrics["warmup_messages"] == 3
        assert reasons[2:] == [
            "below_ignore_threshold", "below_candidate_threshold",
            "candidate_pending_confirmation", "thresholds_passed",
        ]
        levels = [e.metrics["level"] for e in decisions[2:]]
        assert levels == ["IGNORE", "OBSERVE", "CANDIDATE", "ALLOW_LLM"]
        statuses = [e.status for e in decisions[2:]]
        assert statuses == ["skipped", "skipped", "waiting", "succeeded"]
        # 评分 span：每次评分都有 finish 事实；embedding 关闭 → fallback=True
        finishes = _events(flow_db, "obs-1", node_id="participation.score_compute",
                           kind="finish")
        assert len(finishes) == 4
        assert all(e.metrics["embedding_fallback"] is True for e in finishes)
        assert finishes[-1].metrics["final_score"] == 82.0
        assert "velocity_level" in finishes[-1].metrics

    def test_observe_disabled_tables_records_blocked(self, flow_db, tmp_path):
        """打分表不可用（决策层禁用）→ blocked 早退有 reason。"""
        from memory.participation import ParticipationManager

        m = ParticipationManager(
            tables_dir=tmp_path / "no_tables", persist=False,
            jsonl_path=tmp_path / "d.jsonl", md_path=tmp_path / "d.md",
            log_level="off",
        )
        assert not m.enabled
        root = message_flow.begin_trace(root_kind="qq_passive", trace_id="obs-dis")
        out = asyncio.run(m.observe(1, 1, "任何消息", msg_id=1, flow_ctx=root))
        message_flow.end_trace(root)
        message_flow.flush()
        assert out is None
        decisions = _events(flow_db, "obs-dis", node_id="participation.decision",
                            kind="decision")
        assert len(decisions) == 1
        assert decisions[0].status == "blocked"
        assert decisions[0].reason_code == "tables_unavailable"


# ── (b) 决策 tracker：注入时钟 + slot/streak/backoff metrics ──


class TestDecisionTrackerObservability:
    def test_injected_clock_drives_backoff_window(self, monkeypatch):
        """计划 §5：decision._clock 注入后，退避窗口随注入时间开合。"""
        import memory.participation.decision as decision_mod
        from memory.participation.scorer import ScoreBreakdown
        from memory.participation.signals import SignalSnapshot
        from memory.participation.tables import load_tables

        clock = {"now": 1000.0}
        monkeypatch.setattr(decision_mod, "_clock", lambda: clock["now"])
        tracker = decision_mod.DecisionTracker()
        thresholds = load_tables(TABLES_DIR).thresholds
        bd = ScoreBreakdown(relevance=82.0, opportunity=10.0,
                            social_opportunity=0.0, final_score=82.0)
        # 连续达标 → 二次确认后 ALLOW
        assert tracker.decide(1, bd, SignalSnapshot(), thresholds, 1, 1).level == "CANDIDATE"
        assert tracker.decide(1, bd, SignalSnapshot(), thresholds, 1, 2).should_speak
        # 高新颖探测 → 进入退避（now + 30，注入时钟可预算）
        clock["now"] = 2000.0
        d3 = tracker.decide(1, bd, SignalSnapshot(), thresholds, 1, 3, novelty=0.7)
        assert d3.level == "CANDIDATE"
        # 退避期内（2030 之前）→ 保持沉默
        clock["now"] = 2020.0
        assert tracker.decide(1, bd, SignalSnapshot(), thresholds, 1, 4,
                              novelty=0.7).level == "CANDIDATE"
        # 退避期满 → 按序列升到 60s 新退避
        clock["now"] = 2031.0
        d5 = tracker.decide(1, bd, SignalSnapshot(), thresholds, 1, 5, novelty=0.7)
        assert d5.level == "CANDIDATE"
        assert d5.reason_flags.count("idle_backoff") == 1

    def test_decide_slot_metrics_visible_in_mode_decision(self, flow_db, tmp_path):
        """participation.mode 事件携带 slot before/after、streak、backoff_until。"""
        m = make_manager(tmp_path)
        gid, uid = 2002, 42
        text = "今天天气真的很不错适合出去玩"
        root = message_flow.begin_trace(root_kind="qq_passive", trace_id="dec-1")
        m._score_with_embedding = _fake_score(82.0)
        # 前两条为预热；第三条首次评分（streak 1 → 二次确认中）
        asyncio.run(m.observe(gid, uid, text, msg_id=1, now=998.0, flow_ctx=root))
        asyncio.run(m.observe(gid, uid, text, msg_id=2, now=999.0, flow_ctx=root))
        assert asyncio.run(m.observe(
            gid, uid, text, msg_id=3, now=1000.0, flow_ctx=root)).level == "CANDIDATE"
        # Stella 刚说过同一句话 → novelty=1.0 ≥ 0.65 → 名义 ALLOW 被退避压制
        m.note_stella_spoke(gid, "proactive", now=1000.5, text=text)
        d2 = asyncio.run(m.observe(
            gid, uid, text, msg_id=4, now=1001.0, flow_ctx=root))
        assert d2.level == "CANDIDATE" and not d2.should_speak
        message_flow.end_trace(root)
        message_flow.flush()

        modes = _events(flow_db, "dec-1", node_id="participation.mode",
                        kind="decision")
        assert len(modes) == 2
        assert [e.metrics["streak_before"] for e in modes] == [0, 1]
        assert [e.metrics["streak"] for e in modes] == [1, 2]
        assert modes[0].metrics["backoff_until"] == 0.0
        # 第二条：退避进入，backoff_until = now(1001) + 30
        assert modes[1].metrics["backoff_until"] == pytest.approx(1031.0)
        assert modes[1].metrics["low_novelty_streak"] == 1
        assert "topic_revision" in modes[1].metrics


# ── (c) 定时主动预检 root：前置退出有原因 ────────────────────


class TestProactiveTimerRoot:
    def test_disabled_timer_records_preflight_reason(self, flow_db, gateway,
                                                     monkeypatch):
        """计划 §6.4：root 在前置 return 之前创建——开关关也有可查询原因。"""
        monkeypatch.setattr(gateway, "PROACTIVE_ENABLED", False)
        asyncio.run(gateway.proactive_speak_job())
        message_flow.flush()
        row = _latest_trace(flow_db, "proactive_timer")
        assert row is not None
        assert row[1] == "timer" and row[2] == "qq:timer"
        assert row[3] == "disabled"
        events = _events(flow_db, row[0], node_id="proactive.timer.preflight",
                         kind="decision")
        assert events and events[0].reason_code == "proactive_disabled"

    def test_no_bot_timer_records_preflight_reason(self, flow_db, gateway,
                                                   monkeypatch):
        """无可用 Bot → preflight decision + root outcome=no_bot。"""
        monkeypatch.setattr(gateway, "PROACTIVE_ENABLED", True)

        def _no_bot():
            raise RuntimeError("测试环境无 Bot")

        monkeypatch.setattr("nonebot.get_bot", _no_bot)
        asyncio.run(gateway.proactive_speak_job())
        message_flow.flush()
        row = _latest_trace(flow_db, "proactive_timer")
        assert row is not None
        assert row[3] == "no_bot"
        events = _events(flow_db, row[0], node_id="proactive.timer.preflight",
                         kind="decision")
        assert events and events[0].reason_code == "no_bot"


# ── (d)/(e) 主动 @ 资格与选择 ────────────────────────────────


def _provision_candidates(db: Path, rows: list[tuple]) -> None:
    """建最小 memory_candidates 表并插入行（列首为共享空间归属）。"""
    conn = sqlite3.connect(db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT,
            user_id TEXT,
            type TEXT,
            content TEXT,
            confidence REAL,
            status TEXT
        )
    """)
    conn.executemany(
        "INSERT OR REPLACE INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, confidence, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


class TestProactiveAtSelection:
    @pytest.fixture()
    def pt_env(self, tmp_path, monkeypatch):
        import memory.proactive as proactive
        import memory.proactive_state as proactive_state
        import memory.proactive_target as pt

        db = tmp_path / "ps.db"
        monkeypatch.setattr(proactive_state, "DB_PATH", db)
        monkeypatch.setattr(pt, "DB_PATH", db)
        monkeypatch.setattr(proactive.time, "monotonic", _faketicks())
        controller = proactive.ProactiveController()
        monkeypatch.setattr(pt, "get_proactive", lambda: controller)
        return SimpleNamespace(pt=pt, proactive=proactive, controller=controller,
                               db=db)

    def test_quota_rejection_reason_lands_on_at_preflight(self, flow_db, pt_env,
                                                          monkeypatch):
        """(d) can_at_user 拒绝原因（配额）落到 at.preflight。"""
        from memory.proactive_state import record_at

        pt = pt_env.pt
        monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BASE", 1)
        monkeypatch.setattr(pt, "PROACTIVE_AT_QUOTA_BONUS_MAX", 0)
        monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)
        pt_env.controller.record_message(1, 2001)
        record_at(1, 2001)  # 用掉当日配额 1/1
        root = message_flow.begin_trace(root_kind="proactive_timer",
                                        trace_id="at-pf")
        assert pt.pick_target(1, flow_ctx=root, instance_key="grp:1") is None
        message_flow.end_trace(root)
        message_flow.flush()

        preflight = _events(flow_db, "at-pf", node_id="proactive.at.preflight",
                            kind="decision")
        mine = [e for e in preflight if e.metrics.get("user_id") == 2001]
        assert mine and mine[0].status == "blocked"
        assert "配额已满" in mine[0].reason_code
        # 无任何候选事件里也没有「选中」
        assert not _events(flow_db, "at-pf", node_id="proactive.at.select",
                           kind="succeeded")

    def test_no_candidate_records_select_reason(self, flow_db, pt_env):
        """(e) 有合格用户但无可验证候选 → at.select skipped 带原因。"""
        pt = pt_env.pt
        pt_env.controller.record_message(1, 2001)
        root = message_flow.begin_trace(root_kind="proactive_timer",
                                        trace_id="at-none")
        assert pt.pick_target(1, flow_ctx=root, instance_key="grp:1") is None
        message_flow.end_trace(root)
        message_flow.flush()

        preflight = _events(flow_db, "at-none", node_id="proactive.at.preflight",
                            kind="decision")
        mine = [e for e in preflight if e.metrics.get("user_id") == 2001]
        assert mine and mine[0].status == "succeeded"  # 资格通过也逐项落事实
        select = _events(flow_db, "at-none", node_id="proactive.at.select",
                         kind="decision")
        assert select
        assert select[-1].status == "skipped"
        assert "无可验证" in select[-1].reason_code
        assert select[-1].metrics["eligible"] == 1

    def test_selection_records_chosen_candidate(self, flow_db, pt_env):
        """选中候选 → at.select succeeded 携带 user/candidate/confidence。"""
        from config.spaces import resolve_space

        pt = pt_env.pt
        pt_env.controller.record_message(1, 2001)
        _provision_candidates(pt_env.db, [
            ("cand-1", resolve_space(1), "2001", "FACT", "他的显卡是5080",
             0.8, "OBSERVING"),
        ])
        root = message_flow.begin_trace(root_kind="proactive_timer",
                                        trace_id="at-sel")
        target = pt.pick_target(1, flow_ctx=root, instance_key="grp:1")
        message_flow.end_trace(root)
        message_flow.flush()
        assert target is not None and target.candidate_id == "cand-1"
        select = _events(flow_db, "at-sel", node_id="proactive.at.select",
                         kind="decision")
        assert select[-1].status == "succeeded"
        assert select[-1].metrics["user_id"] == 2001
        assert select[-1].metrics["candidate_id"] == "cand-1"
        assert select[-1].metrics["confidence"] == pytest.approx(0.8)


# ── (f) 旁路纪律 ─────────────────────────────────────────────


class TestProbeBypass:
    def test_probe_exceptions_never_break_observe(self, flow_db, tmp_path,
                                                  monkeypatch):
        """观测通道全挂 → observe 仍返回原决策、不上抛（计划 §6.4 旁路纪律）。"""
        from core.observability import message_flow as mf

        def boom(*args, **kwargs):
            raise RuntimeError("观测注入故障")

        monkeypatch.setattr(mf, "decision", boom)
        monkeypatch.setattr(mf, "span", boom)
        m = make_manager(tmp_path)
        gid, uid = 3001, 7
        root = message_flow.begin_trace(root_kind="qq_passive", trace_id="bypass-1")
        asyncio.run(m.observe(gid, uid, "热身一", msg_id=1, now=1000.0,
                              flow_ctx=root))
        asyncio.run(m.observe(gid, uid, "热身二", msg_id=2, now=1001.0,
                              flow_ctx=root))
        m._score_with_embedding = _fake_score(40.0)
        d = asyncio.run(m.observe(gid, uid, "消息三", msg_id=3, now=1002.0,
                                  flow_ctx=root))
        message_flow.end_trace(root)
        message_flow.flush()
        assert d is not None and d.level == "OBSERVE" and not d.should_speak

    def test_observe_without_flow_ctx_is_business_equivalent(self, tmp_path):
        """无观测上下文（flow_ctx=None）→ 探针空转，业务结果等价。"""
        m = make_manager(tmp_path)
        gid, uid = 3002, 7
        m._score_with_embedding = _fake_score(40.0)
        assert asyncio.run(m.observe(gid, uid, "热身一", msg_id=1, now=1000.0)) is None
        assert asyncio.run(m.observe(gid, uid, "热身二", msg_id=2, now=1001.0)) is None
        d = asyncio.run(m.observe(gid, uid, "消息三", msg_id=3, now=1002.0))
        assert d is not None and d.level == "OBSERVE" and not d.should_speak
