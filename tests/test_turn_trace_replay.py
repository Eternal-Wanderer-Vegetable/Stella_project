# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""请求追踪与回放（core/observability）测试：计划 §6.8/§8.1。

覆盖：阶段事件贯通、detailed 按群开关、敏感字段清理、单条截断完整性
标记、容量/保留期清理、只读桩红线、不完整 trace 拒绝完整回放。
测试注入独立临时 trace 库，绝不触碰 STELLA_HOME 的真实诊断库。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.observability import replay, turn_trace


@pytest.fixture()
def trace_db(tmp_path, monkeypatch):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    turn_trace.configure(None)


def _turn(turn_id: str = "t-1", trace_id: str = "r-1", scope: str = "qq:123") -> None:
    turn_trace.record_event(trace_id=trace_id, turn_id=turn_id, stage="ingress",
                            status="accepted", scope=scope)
    turn_trace.record_event(trace_id=trace_id, turn_id=turn_id, stage="budget",
                            status="ok", scope=scope)


class TestRecording:
    def test_events_recorded_and_listed(self, trace_db):
        _turn()
        data = turn_trace.list_turns()
        assert data["total"] == 1
        assert data["items"][0]["turn_id"] == "t-1"
        assert data["items"][0]["events"] == 2

    def test_sensitive_keys_redacted(self, trace_db):
        """密钥/令牌样例永不出现在快照；任意对象只留类型名。"""
        turn_trace.record_event(
            trace_id="r", turn_id="t", stage="prepare",
            detailed={
                "Authorization": "Bearer super-secret",
                "api_key": "sk-123",
                "nested": {"token": "abc", "safe": "正文"},
                "bot": object(),
            },
        )
        conn = sqlite3.connect(trace_db)
        payload = conn.execute(
            "SELECT payload FROM trace_events WHERE turn_id='t'"
        ).fetchone()[0]
        conn.close()
        assert "super-secret" not in payload
        assert "sk-123" not in payload and "abc" not in payload
        assert "正文" in payload
        assert "object" in payload

    def test_oversized_payload_marked_incomplete(self, trace_db, monkeypatch):
        """单条超限截断 → payload_truncated 标记 + complete=0（拒绝完整回放）。"""
        monkeypatch.setattr(turn_trace, "MAX_EVENT_PAYLOAD_BYTES", 512)
        turn_trace.record_event(
            trace_id="r", turn_id="t-big", stage="prepare",
            detailed={"blob": "x" * 4000},
        )
        timeline = turn_trace.turn_timeline("t-big")
        assert timeline["events"][0]["payload_truncated"] is True
        assert timeline["events"][0]["complete"] is False
        assert timeline["replayable"] is False

    def test_failure_is_silent_bypass(self, trace_db, monkeypatch):
        """trace 库不可写时记录失败静默——旁路纪律，绝不阻断轮次。"""
        import sqlite3 as _sq

        def boom():
            raise _sq.OperationalError("locked")

        monkeypatch.setattr(turn_trace, "_connect", boom)
        turn_trace.record_event(trace_id="r", turn_id="t", stage="ingress")  # 不抛出


class TestDetailedGate:
    def test_detailed_only_for_enabled_scopes(self, trace_db, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "SOCIAL_TRACE_DETAIL_SCOPES", "123,456")
        assert turn_trace.detailed_enabled_for_scope("123")
        assert not turn_trace.detailed_enabled_for_scope("789")
        assert not turn_trace.detailed_enabled_for_scope("")


class TestReplay:
    def test_offline_replay_matches_frozen_snapshot(self, trace_db):
        from core.context_budget import fit_prompt_to_window

        user_prompt = "用户输入" * 50
        # 快照值直接取自真实预算管线（与生产写入同源）
        budgeted = fit_prompt_to_window(
            user_prompt, "系统提示", context_window_tokens=8192,
            output_reserve_tokens=512, safety_tokens=64,
        )
        original = {
            "system_prompt": "系统提示",
            "user_prompt": user_prompt,
            "budget_tokens": budgeted.budget_tokens,
            "estimated_tokens": budgeted.estimated_tokens,
            "truncated": budgeted.truncated,
            "context_window_tokens": 8192,
            "output_reserve_tokens": 512,
            "safety_tokens": 64,
        }
        report = replay.replay_budget_decision(
            original, trace_id="r-1", turn_id="t-1", scope="qq:123"
        )
        assert report.verdict == "match"
        assert report.parent_trace_id == "r-1" and report.replay_id

    def test_incomplete_trace_refuses_full_replay(self, trace_db):
        """只有 metadata 的 trace：仅可浏览，绝不补查今天的记忆伪造当时输入。"""
        report = replay.replay_budget_decision(
            {"system_prompt": ""}, trace_id="r-2", turn_id="t-2"
        )
        assert report.verdict == "browsable_only"
        assert report.notes

    def test_stubs_forbid_all_side_effects(self):
        """provider/工具/发送器/记忆/学习桩一旦被调用立即失败（零副作用红线）。"""
        stubs = replay.ReadOnlyStubs()
        for name in ("provider", "tool", "sender", "memory_write", "learning"):
            with pytest.raises(replay.ReplaySideEffectError):
                getattr(stubs, name)()

    def test_webui_replay_reports_browsable_only(self, trace_db):
        from webui.services import trace as trace_service

        _turn("t-web", scope="qq:9")
        result = trace_service.replay_turn("t-web")
        assert result["verdict"] == "browsable_only"
        assert any("仅可浏览" in n for n in result["notes"])

    def test_webui_replay_missing_turn(self, trace_db):
        from webui.services import trace as trace_service

        with pytest.raises(ValueError):
            trace_service.replay_turn("missing")


class TestPrune:
    def test_retention_and_capacity(self, trace_db, monkeypatch):
        from datetime import datetime, timedelta, timezone

        turn_trace.list_turns()  # 触发 schema 初始化

        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="milliseconds")
        conn = sqlite3.connect(trace_db)
        conn.execute(
            "INSERT INTO trace_events (trace_id, turn_id, scope, ts_utc, stage) "
            "VALUES ('r-old', 't-old', 'qq:1', ?, 'ingress')", (old,))
        conn.execute(
            "INSERT INTO trace_events (trace_id, turn_id, scope, ts_utc, stage, payload) "
            "VALUES ('r-new', 't-new', 'qq:1', ?, 'ingress', '{}')",
            (datetime.now(timezone.utc).isoformat(timespec="milliseconds"),))
        conn.commit()
        conn.close()
        out = turn_trace.prune()
        assert out["metadata"] >= 1
        remaining = turn_trace.list_turns()
        assert all(item["turn_id"] != "t-old" for item in remaining["items"])
