# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""群黑话理解（memory/jargon_service.py + core/social/context_builder.py）测试。

覆盖计划 §8.1 资产隔离/Prompt 矩阵：同词异群不串义、legacy 无来源不注入、
禁用立即失效、多义不冒充确定义、shadow 只记录不改 prompt、空 social
prompt 字节相同、预算溢出先丢 optional。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.social.contracts import ConversationScope, MessageEvidence
from memory import jargon_service, social_store


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


GROUP_A = ConversationScope.for_qq(111)
GROUP_B = ConversationScope.for_qq(222)


def _ev(event_id: str, group_id: int = 111, user_id: str = "100") -> str:
    return social_store.record_event(
        MessageEvidence(scope=ConversationScope.for_qq(group_id), event_id=event_id,
                        platform_message_id=f"pm-{event_id}", user_id=user_id,
                        text_excerpt="占位")
    )


class TestOccurrence:
    def test_dedup_by_event_id(self, social_db):
        """重复转发/同一消息不增加独立证据。"""
        ev = _ev("e1")
        jargon_service.note_occurrence(GROUP_A, "yyds", event_id=ev, author_user="100")
        jargon_service.note_occurrence(GROUP_A, "yyds", event_id=ev, author_user="100")
        jargon_service.note_occurrence(GROUP_A, "YYDS", event_id=ev, author_user="200")
        asset_id = jargon_service.get_or_create_asset(GROUP_A, "yyds")
        stats = jargon_service.evidence_stats(asset_id)
        assert stats == {"events": 1, "authors": 1}

    def test_same_term_two_groups_are_separate(self, social_db):
        """同词异群分别维护，绝不串义。"""
        ev_a = _ev("ea", group_id=111)
        ev_b = _ev("eb", group_id=222)
        jargon_service.note_occurrence(GROUP_A, "狼人", event_id=ev_a)
        jargon_service.note_occurrence(GROUP_B, "狼人", event_id=ev_b)
        assert jargon_service.get_or_create_asset(GROUP_A, "狼人") != \
            jargon_service.get_or_create_asset(GROUP_B, "狼人")
        matched_b = jargon_service.match_jargon(GROUP_B, "狼人")
        assert matched_b == []  # B 群没有确认词义，只有出现证据


class TestSenses:
    def test_add_sense_idempotent_and_conflict_creates_new(self, social_db):
        first = jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人")
        again = jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人")
        assert first == again  # 同文幂等
        conflict = jargon_service.add_sense(GROUP_A, "狼人", "指夜里活跃的人")
        assert conflict != first  # 语义冲突新增 sense，不覆盖旧义
        rows = [t for t in jargon_service.list_terms(GROUP_A) if t["sense"]]
        assert len(rows) == 2

    def test_unconfirmed_sense_never_matched(self, social_db):
        jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人")
        assert jargon_service.match_jargon(GROUP_A, "他是狼人吧") == []

    def test_confirmed_sense_matched_with_context(self, social_db):
        asset = jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人",
                                         situation="开黑")
        jargon_service.set_sense_status(asset, "active")
        matched = jargon_service.match_jargon(GROUP_A, "他是狼人吧")
        assert len(matched) == 1
        assert matched[0]["definition"] == "指开局就冲的人"
        assert matched[0]["ambiguous"] is False
        assert matched[0]["situation"] == "开黑"

    def test_ambiguous_multi_sense_marks_not_decides(self, social_db):
        s1 = jargon_service.add_sense(GROUP_A, "狼人", "含义一")
        s2 = jargon_service.add_sense(GROUP_A, "狼人", "含义二")
        jargon_service.set_sense_status(s1, "active")
        jargon_service.set_sense_status(s2, "active")
        matched = jargon_service.match_jargon(GROUP_A, "狼人？")
        assert len(matched) == 1
        assert matched[0]["ambiguous"] is True
        assert set(matched[0]["senses"]) == {"含义一", "含义二"}

    def test_disable_takes_effect_immediately(self, social_db):
        asset = jargon_service.add_sense(GROUP_A, "狼人", "含义一")
        jargon_service.set_sense_status(asset, "active")
        assert jargon_service.match_jargon(GROUP_A, "狼人")
        jargon_service.set_sense_status(asset, "disabled")
        assert jargon_service.match_jargon(GROUP_A, "狼人") == []

    def test_legacy_unscoped_never_injected(self, social_db):
        """旧库迁移来的无来源资产（group_id=''）不进任何群的匹配。"""
        conn = sqlite3.connect(social_db)
        conn.execute(
            "INSERT INTO social_assets (asset_id, kind, platform, bot_id, group_id, "
            "content, term, sense, definition, status, created_at_utc, updated_at_utc) "
            "VALUES ('legacy-a', 'jargon', 'legacy', 'legacy', '', '神秘词', '神秘词', "
            "'s1', '旧定义', 'active', '2026-01-01T00:00:00.000+00:00', "
            "'2026-01-01T00:00:00.000+00:00')")
        conn.commit()
        conn.close()
        assert jargon_service.match_jargon(GROUP_A, "神秘词") == []


class TestContextSlot:
    def _ctx(self, group_id: int = 111, message: str = "他真是狼人"):
        from core.context import ChatContext

        return ChatContext(user_id=100, group_id=group_id, msg_id=1,
                           message=message, trigger="reply")

    def test_off_mode_returns_empty_and_no_usage(self, social_db, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "SOCIAL_MODE", "off")
        from core.social.context_builder import build_social_block

        text, selection = build_social_block(self._ctx(), baseline_prompt="x", system_prompt="")
        assert text == "" and selection.empty

    def test_shadow_records_selection_but_never_injects(self, social_db, monkeypatch):
        from config import settings

        asset = jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人")
        jargon_service.set_sense_status(asset, "active")
        monkeypatch.setattr(settings, "SOCIAL_MODE", "shadow")
        from core.social.context_builder import build_social_block

        ctx = self._ctx()
        ctx.turn_id = "turn-shadow"
        text, selection = build_social_block(ctx, baseline_prompt="x", system_prompt="")
        assert text == ""  # shadow 只记录候选决策，不修改实际 prompt
        assert selection.jargon
        usage = sqlite3.connect(social_db).execute(
            "SELECT selected, injected FROM social_asset_usage WHERE turn_id='turn-shadow'"
        ).fetchall()
        assert usage == [(1, 0)]

    def test_active_injects_definition_block(self, social_db, monkeypatch):
        from config import settings

        asset = jargon_service.add_sense(GROUP_A, "狼人", "指开局就冲的人")
        jargon_service.set_sense_status(asset, "active")
        monkeypatch.setattr(settings, "SOCIAL_MODE", "active")
        from core.social.context_builder import build_social_block

        ctx = self._ctx()
        ctx.turn_id = "turn-active"
        text, selection = build_social_block(ctx, baseline_prompt="x", system_prompt="")
        assert "本群黑话" in text and "指开局就冲的人" in text
        assert selection.injected_jargon
        usage = sqlite3.connect(social_db).execute(
            "SELECT injected FROM social_asset_usage WHERE turn_id='turn-active'"
        ).fetchall()
        assert usage == [(1,)]

    def test_prompt_bytes_unchanged_when_social_empty(self, social_db, monkeypatch):
        """空 social → 既有 prompt 字节不变（计划 §8.1 Prompt 行回归锚）。"""
        from config import settings

        monkeypatch.setattr(settings, "SOCIAL_MODE", "active")
        from core.runtime.turn_service import _compose_prompt

        ctx = self._ctx()
        base = _compose_prompt("上下文内容", ctx)
        same = _compose_prompt("上下文内容", ctx, social_text="")
        assert base == same

    def test_budget_overflow_drops_optional_first(self, social_db, monkeypatch):
        """近满预算：低分条目整条丢弃，绝不半条截断、不超 SOCIAL_BUDGET_TOKENS。"""
        from config import settings

        monkeypatch.setattr(settings, "SOCIAL_MODE", "active")
        monkeypatch.setattr(settings, "LLM_CONTEXT_WINDOW_TOKENS", 8192)
        from core.social import context_builder as cb

        entries = [
            {"term": f"词{i}", "definition": f"定义{i}" * 30, "confidence": i / 10,
             "asset_id": f"a{i}"}
            for i in range(10)
        ]
        selection = cb.SocialSelection()
        text, _used = cb._fit_entries(entries, cb._render_jargon, 100, "jargon", selection)
        assert len(text) > 0
        assert len(selection.dropped) >= 5  # 低分端整条丢弃
        for d in selection.dropped:
            assert d["reason"] in ("budget", "no_budget")
