# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""回复效果观察与结算（memory/reply_effect_service.py + social_worker.py）测试。

覆盖计划 §8.1 归因/结算矩阵：引用归因、全群目标、多 effect 冲突弃权、
deadline/cap、并发与重启不重复统计、重评撤旧贡献、unknown 不是负反馈。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.social.contracts import ConversationScope, DeliveryReceipt
from memory import reply_effect_service as svc
from memory import social_store, social_worker

# 冻结基准（UTC，过去时刻）：所有回执与 follow-up 的时间都从它推导，
# 窗口判定完全确定。60 秒窗口让跨 effect 交叠的冲突场景可构造。
BASE = datetime(2026, 9, 27, 4, 0, 0, tzinfo=timezone.utc).isoformat(timespec="milliseconds")


def _ts(offset_seconds: float) -> str:
    from core.social.contracts import parse_utc

    return (parse_utc(BASE) + timedelta(seconds=offset_seconds)).isoformat(timespec="milliseconds")


@pytest.fixture()
def social_db(tmp_path, monkeypatch):
    from config import settings

    db = tmp_path / "social.db"
    monkeypatch.setattr(settings, "DB_PATH", db)
    from memory import social_schema

    social_schema.ensure_social_schema(db, backup=False)
    monkeypatch.setattr(social_store, "_TABLES_READY", False)
    # 60 秒观察窗口（比默认短、可交叠），配合冻结基准时间做确定性断言
    monkeypatch.setattr(svc, "REPLY_EFFECT_WINDOW_SECONDS", 60.0)
    yield db
    social_store._TABLES_READY = False


def _rows(db, sql: str, params=()) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _ack_receipt(turn_id: str, part: int, platform_id: str, at: str | None = None) -> None:
    social_store.record_delivery(
        DeliveryReceipt(
            trace_id="t", turn_id=turn_id, part_index=part, status="acknowledged",
            platform_message_id=platform_id,
            acknowledged_at_utc=at or BASE,
            text=f"片段{part}", scope=ConversationScope.for_qq(123),
        )
    )


def _follow_up(event_id: str, *, text: str = "接话", user_id: str = "100",
               reply_to: str | None = None, source_kind: str = "PASSIVE",
               received_at: str | None = None) -> None:
    from core.social.contracts import MessageEvidence

    social_store.record_event(
        MessageEvidence(
            scope=ConversationScope.for_qq(123),
            event_id=event_id,
            platform_message_id=f"msg-{event_id}",
            user_id=user_id,
            source_kind=source_kind,
            reply_to_id=reply_to,
            text_excerpt=text,
            received_at_utc=received_at or _ts(30),
        )
    )


def _open(turn_id: str, *, user_id: int | str = 100, trigger: str = "reply") -> str:
    _ack_receipt(turn_id, 0, f"p-{turn_id}-0")
    effect_id = svc.open_effect(
        group_id=123, user_id=user_id, trigger=trigger, turn_id=turn_id, trace_id="t"
    )
    assert effect_id
    return effect_id


class TestOpenEffect:
    def test_creates_observing_row_and_job(self, social_db):
        effect_id = _open("turn-1")
        rows = _rows(social_db, "SELECT status, target_user_id, window_end_utc "
                                 "FROM social_effects WHERE effect_id=?", (effect_id,))
        assert len(rows) == 1
        assert rows[0][0] == "observing"
        assert rows[0][1] == "100"
        assert rows[0][2] is not None
        jobs = _rows(social_db, "SELECT type, status, dedupe_key FROM social_jobs")
        assert jobs and jobs[0][0] == "resolve_effect" and jobs[0][2] == f"resolve:{effect_id}"

    def test_proactive_group_target_is_null_not_zero(self, social_db):
        """user_id=0（主动群聊）→ target NULL＝全群；绝不再用 0 过滤真实回应。"""
        effect_id = _open("turn-pro", user_id=0, trigger="proactive")
        rows = _rows(social_db, "SELECT target_user_id FROM social_effects "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] is None

    def test_no_acknowledged_delivery_no_effect(self, social_db):
        social_store.record_delivery(
            DeliveryReceipt(trace_id="t", turn_id="turn-failed", part_index=0,
                            status="failed", text="没发出去",
                            scope=ConversationScope.for_qq(123))
        )
        assert svc.open_effect(group_id=123, user_id=100, trigger="reply",
                               turn_id="turn-failed") is None

    def test_same_turn_cannot_open_twice(self, social_db):
        _ack_receipt("turn-dup", 0, "p-dup-0")
        first = svc.open_effect(group_id=123, user_id=100, trigger="reply",
                                turn_id="turn-dup")
        second = svc.open_effect(group_id=123, user_id=100, trigger="reply",
                                 turn_id="turn-dup")
        assert first and second is None


class TestAttribution:
    def test_quote_of_delivered_segment_is_direct(self, social_db):
        effect_id = _open("turn-a")
        _follow_up("e1", reply_to="p-turn-a-0")
        assert svc.resolve_effect(effect_id) == "resolved"
        rows = _rows(social_db, "SELECT attribution FROM social_effect_evidence "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] == "direct"

    def test_interleaved_bot_reply_does_not_steal_direct(self, social_db):
        """两次 bot 回复交错后用户引用第一条：只有第一条 direct。"""
        first = _open("turn-old")
        _ack_receipt("turn-new", 0, "p-turn-new-0", at=_ts(50))
        from memory.reply_effect_service import open_effect

        second = open_effect(group_id=123, user_id=100, trigger="reply", turn_id="turn-new")
        assert second
        # 事件落在两个窗口的交叠段，且引用的是第一轮的片段
        _follow_up("e-quote", reply_to="p-turn-old-0", received_at=_ts(55))
        assert svc.resolve_effect(first) == "resolved"
        assert svc.resolve_effect(second) == "resolved"
        rows = dict(
            _rows(social_db, "SELECT effect_id, attribution FROM social_effect_evidence "
                             "WHERE event_id='e-quote'")
        )
        assert rows[first] == "direct"
        assert rows[second] == "ambiguous"

    def test_at_mention_is_probable(self, social_db):
        effect_id = _open("turn-b")
        _follow_up("e2", source_kind="AT_MENTION")
        svc.resolve_effect(effect_id)
        rows = _rows(social_db, "SELECT attribution FROM social_effect_evidence "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] == "probable"

    def test_target_user_first_follow_up_is_weak(self, social_db):
        effect_id = _open("turn-c", user_id=200)
        _follow_up("e3", user_id="200")
        svc.resolve_effect(effect_id)
        rows = _rows(social_db, "SELECT attribution FROM social_effect_evidence "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] == "weak"

    def test_other_user_without_reference_is_ambiguous(self, social_db):
        effect_id = _open("turn-d", user_id=200)
        _follow_up("e4", user_id="999")
        svc.resolve_effect(effect_id)
        rows = _rows(social_db, "SELECT attribution FROM social_effect_evidence "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] == "ambiguous"


class TestSettlement:
    def test_no_response_is_not_negative(self, social_db):
        effect_id = _open("turn-silent")
        assert svc.resolve_effect(effect_id) == "resolved"
        dims = _rows(social_db, "SELECT meta_json FROM social_effects WHERE effect_id=?",
                     (effect_id,))[0][0]
        import json

        assert json.loads(dims)["reception"] == "uncertain"
        metrics = dict(
            _rows(social_db, "SELECT metric, delta FROM social_aggregate_events "
                             "WHERE effect_id=?", (effect_id,))
        )
        assert metrics["no_observed_response"] == 1.0
        assert metrics["engagement_responded_events"] == 0.0

    def test_correction_and_reception_metrics(self, social_db):
        effect_id = _open("turn-corr")
        _follow_up("e-corr", text="你说错了，不是这样", reply_to="p-turn-corr-0")
        svc.resolve_effect(effect_id)
        metrics = dict(
            _rows(social_db, "SELECT metric, delta FROM social_aggregate_events "
                             "WHERE effect_id=?", (effect_id,))
        )
        assert metrics["reception_corrected"] == 1.0
        assert metrics["engagement_responded_events"] == 1.0

    def test_double_resolve_counts_once(self, social_db):
        """计划 HIGH 风险：结算必须幂等——两路同时到达只计一次。"""
        effect_id = _open("turn-idem")
        _follow_up("e-i1", reply_to="p-turn-idem-0")
        assert svc.resolve_effect(effect_id) == "resolved"
        assert svc.resolve_effect(effect_id) == "already_resolved"
        rows = _rows(social_db, "SELECT COUNT(*) FROM social_aggregate_events "
                                "WHERE effect_id=?", (effect_id,))
        assert rows[0][0] == 3  # responded_events / responded_users / no_observed_response

    def test_reevaluation_withdraws_old_version(self, social_db):
        effect_id = _open("turn-reeval")
        _follow_up("e-r1", reply_to="p-turn-reeval-0")
        assert svc.resolve_effect(effect_id, evaluation_version="r1") == "resolved"
        # 升级评估版本重评：旧版本贡献同事务撤回，不跨版本叠加
        assert svc.resolve_effect(effect_id, evaluation_version="r2") == "resolved"
        versions = _rows(social_db, "SELECT DISTINCT evaluation_version "
                                    "FROM social_aggregate_events WHERE effect_id=?",
                         (effect_id,))
        assert [v[0] for v in versions] == ["r2"]

    def test_capped_window_is_visible(self, social_db, monkeypatch):
        monkeypatch.setattr(svc, "MAX_FOLLOW_UP_EVENTS", 3)
        effect_id = _open("turn-cap")
        for i in range(5):
            _follow_up(f"e-cap-{i}", text=f"刷屏{i}")
        svc.resolve_effect(effect_id)
        obs = _rows(social_db, "SELECT observation FROM social_effects WHERE effect_id=?",
                    (effect_id,))[0][0]
        assert obs == "capped"  # capped 不装作观察完整


class TestWorker:
    def test_tick_resolves_due_effect(self, social_db):
        effect_id = _open("turn-job")
        _follow_up("e-j1", reply_to="p-turn-job-0")
        # 补偿 sweep：窗口已过但没有作业（模拟重启丢任务）→ tick 补作业并结算
        jobs = _rows(social_db, "SELECT COUNT(*) FROM social_jobs WHERE status='pending'")
        assert jobs[0][0] == 1  # open_effect 已带作业
        stats = social_worker.tick()
        assert stats["done"] == 1
        status = _rows(social_db, "SELECT status FROM social_effects WHERE effect_id=?",
                       (effect_id,))[0][0]
        assert status == "resolved"

    def test_sweep_recreates_missing_job(self, social_db):
        effect_id = _open("turn-lostjob")
        _rows(social_db, "DELETE FROM social_jobs")  # 模拟作业行丢失/重启窗口
        assert social_worker.tick()["done"] == 1
        status = _rows(social_db, "SELECT status FROM social_effects WHERE effect_id=?",
                       (effect_id,))[0][0]
        assert status == "resolved"

    def test_lease_expires_and_requeues_with_backoff(self, social_db, monkeypatch):
        """lease 过期可重领；重试上限后 dead 终态可见。"""
        calls = {"n": 0}

        def flaky(payload):
            calls["n"] += 1
            return False  # 永远失败

        social_worker.register_handler("flaky", flaky)
        social_worker.enqueue_job("flaky", dedupe_key="flaky:1")
        assert social_worker.run_due_jobs()["retry"] == 1
        # 未到期（退避中）不领取
        assert social_worker.run_due_jobs()["claimed"] == 0
        # 模拟时间流逝越过退避：重领（attempts=2）仍失败 → dead 终态
        from core.social.contracts import parse_utc, utc_now_iso

        later = (parse_utc(utc_now_iso()) + timedelta(seconds=120)).isoformat(timespec="milliseconds")
        assert social_worker.run_due_jobs(now_iso=later)["dead"] == 1
        assert calls["n"] == 2

    def test_expired_lease_is_reclaimed(self, social_db, monkeypatch):
        """结算中崩溃（lease 过期）→ 重启后可重领，效果只结算一次。"""
        effect_id = _open("turn-crash")
        _follow_up("e-c1", reply_to="p-turn-crash-0")
        # 模拟崩溃：手工把作业置为 running 且 lease 已过期
        conn = sqlite3.connect(social_db)
        conn.execute("UPDATE social_jobs SET status='running', "
                     "lease_until_utc='2000-01-01T00:00:00.000+00:00', attempts=1")
        conn.commit()
        conn.close()
        assert social_worker.tick()["done"] == 1
        agg = _rows(social_db, "SELECT COUNT(*) FROM social_aggregate_events "
                               "WHERE effect_id=?", (effect_id,))
        assert agg[0][0] == 3  # 崩溃重领不重复累加

    def test_queue_limit_rejects_and_is_visible(self, social_db, monkeypatch):
        monkeypatch.setattr(social_worker, "QUEUE_LIMIT", 1)
        assert social_worker.enqueue_job("x", dedupe_key="a")
        assert not social_worker.enqueue_job("x", dedupe_key="b")  # 满载丢弃+计数

    def test_legacy_unverifiable_never_resolved(self, social_db):
        conn = sqlite3.connect(social_db)
        conn.execute(
            "INSERT INTO social_effects (effect_id, turn_id, status, assessable, "
            "created_at_utc) VALUES ('legacy-x', 'legacy-turn-x', 'legacy_unverifiable', "
            "0, '2026-01-01T00:00:00.000+00:00')")
        conn.commit()
        conn.close()
        assert svc.resolve_effect("legacy-x") == "legacy_unverifiable"
        assert _rows(social_db, "SELECT COUNT(*) FROM social_aggregate_events "
                                "WHERE effect_id='legacy-x'")[0][0] == 0
