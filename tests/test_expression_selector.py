# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""表达闭环（memory/expression_selector.py）测试：计划 §6.3/§8.1 P4 行。"""

from __future__ import annotations

import json
import sqlite3

import pytest

from core.social.contracts import ConversationScope, DeliveryReceipt, MessageEvidence
from memory import expression_selector as sel
from memory import social_store


@pytest.fixture()
def social_db(tmp_path, monkeypatch):
    from config import settings

    db = tmp_path / "social.db"
    monkeypatch.setattr(settings, "DB_PATH", db)
    from memory import social_schema

    social_schema.ensure_social_schema(db, backup=False)
    monkeypatch.setattr(social_store, "_TABLES_READY", False)
    yield db
    social_store._TABLES_READY = False


G = ConversationScope.for_qq(333)


def _ev(event_id: str, user_id: str = "100") -> str:
    return social_store.record_event(
        MessageEvidence(scope=G, event_id=event_id, platform_message_id=f"pm-{event_id}",
                        user_id=user_id, text_excerpt="占位")
    )


def _ack(turn_id: str) -> None:
    social_store.record_delivery(
        DeliveryReceipt(trace_id="t", turn_id=turn_id, part_index=0, status="acknowledged",
                        platform_message_id=f"pm-{turn_id}", acknowledged_at_utc="2026-09-27T04:00:00.000+00:00",
                        text="x", scope=G)
    )


class TestHarvest:
    def test_candidates_become_evidence_idempotently(self, social_db):
        ev = _ev("e1")
        n1 = sel.note_expression_candidates(G, "这也太离谱了吧，救命", event_id=ev,
                                            author_user="100")
        n2 = sel.note_expression_candidates(G, "这也太离谱了吧，救命", event_id=ev,
                                            author_user="100")
        assert n1 > 0
        assert n2 == 0  # 同一事件不重复计证据
        assets = sqlite3.connect(social_db).execute(
            "SELECT COUNT(*) FROM social_assets WHERE kind='expression'"
        ).fetchone()[0]
        assert assets >= 1

    def test_auto_harvest_never_activates(self, social_db):
        """人格保护红线：自动采集的资产永远 candidate；证据攒够只标记「可人工确认」，
        激活永远需要管理动作。"""
        for i in range(5):
            ev = _ev(f"e{i}", user_id=str(100 + i % 2))
            sel.note_expression_candidates(G, "这也太离谱了吧", event_id=ev,
                                           author_user=str(100 + i % 2))
        # 跨 2 个日期：把一半证据的 observed_at 挪到前一天（门槛要求 3 证据/2 作者/2 日期）
        conn = sqlite3.connect(social_db)
        conn.execute(
            "UPDATE social_asset_evidence SET observed_at_utc='2026-09-26T04:00:00.000+00:00' "
            "WHERE rowid % 2 = 0")
        conn.commit()
        conn.close()
        rows = sqlite3.connect(social_db).execute(
            "SELECT asset_id, status, meta_json FROM social_assets WHERE kind='expression'"
        ).fetchall()
        assert rows
        for _asset_id, status, _meta in rows:
            assert status == "candidate"
        assert sel.refresh_promotable(G, rows[0][0])
        meta = json.loads(sqlite3.connect(social_db).execute(
            "SELECT meta_json FROM social_assets WHERE asset_id=?", (rows[0][0],)
        ).fetchone()[0])
        assert meta["promotable"] is True  # 标记可人工确认，但状态未变


class TestSelect:
    def _activate(self, social_db, content: str, situation: str = "") -> str:
        asset = sel.add_expression_asset(G, content, situation=situation)
        sqlite3.connect(social_db).execute(
            "UPDATE social_assets SET status='active' WHERE asset_id=?", (asset,)
        ).connection.commit()
        return asset

    def test_only_active_selected(self, social_db):
        sel.add_expression_asset(G, "候选表达")
        self._activate(social_db, "激活表达")
        picked = sel.select(G, "随便说点什么")
        assert [p["content"] for p in picked] == ["激活表达"]

    def test_max_two_per_turn(self, social_db):
        for i in range(4):
            self._activate(social_db, f"表达{i}")
        assert len(sel.select(G, "x")) == 2

    def test_recently_used_expression_is_penalized(self, social_db):
        """最近 10 次本群回复用过的表达不再注入（防复读）。"""
        self._activate(social_db, "用过的话")
        _ack("turn-used")
        conn = sqlite3.connect(social_db)
        conn.execute(
            "INSERT INTO social_asset_usage (usage_id, turn_id, asset_id, selected, "
            "injected, created_at_utc) VALUES ('u1', 'turn-used', "
            "(SELECT asset_id FROM social_assets WHERE content='用过的话'), 1, 1, "
            "'2026-09-27T04:00:00.000+00:00')")
        conn.commit()
        conn.close()
        picked = sel.select(G, "x")
        assert all(p["content"] != "用过的话" for p in picked)


class TestAppliedAndFeedback:
    def test_mark_applied_only_on_real_match(self, social_db):
        asset = sel.add_expression_asset(G, "救命")
        _ack("turn-apply")
        conn = sqlite3.connect(social_db)
        conn.execute(
            "INSERT INTO social_asset_usage (usage_id, turn_id, asset_id, selected, "
            "injected, created_at_utc) VALUES ('u2', 'turn-apply', ?, 1, 1, "
            "'2026-09-27T04:00:00.000+00:00')", (asset,))
        conn.commit()
        conn.close()
        assert sel.mark_applied("turn-apply", ["救命啊这个"]) == 1
        assert sel.mark_applied("turn-apply", ["毫无关系"]) == 0
        # applied 落账
        applied = sqlite3.connect(social_db).execute(
            "SELECT applied FROM social_asset_usage WHERE usage_id='u2'"
        ).fetchone()[0]
        assert applied == 1

    def test_negative_feedback_quarantines_applied_asset(self, social_db):
        """applied 且被纠正/拒绝 → quarantine（保留证据可复核）。"""
        import uuid as _uuid

        asset = sel.add_expression_asset(G, "不合适的话")
        effect_id = _uuid.uuid4().hex
        conn = sqlite3.connect(social_db)
        conn.execute("UPDATE social_assets SET status='active' WHERE asset_id=?", (asset,))
        conn.execute(
            "INSERT INTO social_effects (effect_id, turn_id, status, created_at_utc) "
            "VALUES (?, 'turn-neg', 'resolved', '2026-09-27T04:00:00.000+00:00')", (effect_id,))
        conn.execute(
            "UPDATE social_effects SET meta_json=? WHERE effect_id=?",
            (json.dumps({"reception": "corrected"}), effect_id))
        conn.execute(
            "INSERT INTO social_asset_usage (usage_id, turn_id, asset_id, selected, "
            "injected, applied, effect_id, created_at_utc) VALUES "
            "('u3', 'turn-neg', ?, 1, 1, 1, ?, '2026-09-27T04:00:00.000+00:00')",
            (asset, effect_id))
        conn.commit()
        conn.close()
        assert sel.handle_effect_feedback(effect_id) is True
        status = sqlite3.connect(social_db).execute(
            "SELECT status FROM social_assets WHERE asset_id=?", (asset,)
        ).fetchone()[0]
        assert status == "quarantined"

    def test_positive_effect_never_quarantines(self, social_db):
        import uuid as _uuid

        asset = sel.add_expression_asset(G, "正常的话")
        effect_id = _uuid.uuid4().hex
        conn = sqlite3.connect(social_db)
        conn.execute("UPDATE social_assets SET status='active' WHERE asset_id=?", (asset,))
        conn.execute(
            "INSERT INTO social_effects (effect_id, turn_id, status, meta_json, created_at_utc) "
            "VALUES (?, 'turn-pos', 'resolved', ?, '2026-09-27T04:00:00.000+00:00')",
            (effect_id, json.dumps({"reception": "neutral"})))
        conn.execute(
            "INSERT INTO social_asset_usage (usage_id, turn_id, asset_id, selected, "
            "injected, applied, effect_id, created_at_utc) VALUES "
            "('u4', 'turn-pos', ?, 1, 1, 1, ?, '2026-09-27T04:00:00.000+00:00')",
            (asset, effect_id))
        conn.commit()
        conn.close()
        assert sel.handle_effect_feedback(effect_id) is False
        status = sqlite3.connect(social_db).execute(
            "SELECT status FROM social_assets WHERE asset_id=?", (asset,)
        ).fetchone()[0]
        assert status == "active"
