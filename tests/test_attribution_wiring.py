# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""运行链接线测试（整改计划 P1/P5）。

覆盖：ChatContext v6 投影、guard hook 三模式与 split_lines 处置、
typed 检索查询消费、主动合同构建/发送前复核、私聊分享授权入口。
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import nonebot
import pytest

nonebot.init()

from config import settings as settings_mod
from core.context import ChatContext
from core.dialogue_attribution import build_evidence_table, evidence_projection
from memory import pre_processors
from stella_project.plugins.bot_main import ai_gateway as gateway


def _ctx(**kw):
    base = {
        "user_id": 20001, "group_id": 0, "msg_id": 1, "message": "在吗",
        "conversation_kind": "private",
        "conversation_key": "qq:10000:private:20001",
        "bot_id": "10000", "peer_id": "20001", "storage_session_id": -2,
        "identity_revision": 3,
    }
    base.update(kw)
    return ChatContext(**base)


def _evidence():
    table = build_evidence_table(
        [
            {
                "id": 501, "text": "我开发 Stella", "author_id": 3089665724,
                "author_display": "开发者", "object_id": None, "row_id": 501,
                "conversation_key": "g", "timestamp": "",
            }
        ],
        [],
        [],
        max_units=16,
    )
    return evidence_projection(table)


# ── ChatContext v6 投影 ────────────────────────────────────────────────


def test_projection_v5_fields_json_safe():
    ctx = _ctx(
        retrieval_query="候选主题",
        verification_contract={"candidate_id": "c1", "selected_target_user_id": 20001},
        attribution_evidence={"msg_1": {"evidence_id": "msg_1"}},
        attribution_decision={"decision": "pass"},
        reply_disposition="deliver",
    )
    proj = ctx.to_json_projection()
    assert json.loads(json.dumps(proj, ensure_ascii=False)) == proj
    assert proj["projection_schema_version"] == 6
    for name in ("retrieval_query", "verification_contract",
                 "attribution_evidence", "attribution_decision",
                 "reply_disposition", "typed_reply", "retained_evidence_ids",
                 "attribution_risk_context", "delivery_draft", "delivery_plan",
                 "guard_decision", "generation_epoch", "runtime_key"):
        assert name in proj, name


# ── guard hook 三模式 + split_lines 处置 ───────────────────────────────


def _raw_plan(now="哈哈原来如此", ref="msg_501"):
    return (
        '<reply_plan version="2026-10-05.2">'
        f"<now>{now}</now>"
        + (f'<ref id="{ref}"/>' if ref else "")
        + "</reply_plan>"
    )


def _raw_envelope(kind="social", now="哈哈原来如此", ref=None):
    slot = f"<current>{now}</current>" if now else ""
    if ref:
        slot += f'<quote evidence_id="{ref}"/>'
        kind = "quote"
    return (
        '<response version="2026-10-08.1">'
        "<thought></thought><action>NONE</action>"
        f'<reply kind="{kind}">{slot}</reply></response>'
    )


@pytest.mark.asyncio
async def test_guard_off_is_passthrough(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "off", raising=False)
    ctx = _ctx(raw_output=_raw_envelope(), reply="")
    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply == "哈哈原来如此"
    assert out.reply_disposition == ""
    assert out.attribution_decision == {}


@pytest.mark.asyncio
async def test_guard_enforce_renders_author_and_delivers(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "enforce", raising=False)
    ctx = _ctx(
        raw_output=_raw_envelope(ref="msg_501"),
        attribution_evidence=_evidence(), retained_evidence_ids=["msg_501"],
    )
    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply_disposition == "fallback"
    # 服务端渲染：作者边界 + 原话；模型没有自行复述历史
    assert "开发者说过：「我开发 Stella」" in out.reply
    assert out.attribution_decision["decision"] == "fallback"
    assert out.delivery_source_kind == "trusted-server"
    # 分行按处置正常交付
    await gateway.split_lines(out)
    assert out.lines and "我开发 Stella" in out.lines[0]


@pytest.mark.asyncio
async def test_guard_enforce_suppresses_risky_text(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "enforce", raising=False)
    ctx = _ctx(raw_output=_raw_envelope(now="刚才是谁说我脏手来着？"))
    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply_disposition == "suppressed"
    assert out.attribution_decision["decision"] == "reject"
    # split_lines 尊重 suppressed：不产出「......？」默认值
    await gateway.split_lines(out)
    assert out.lines == []


@pytest.mark.asyncio
async def test_guard_shadow_records_but_keeps_delivery(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "shadow", raising=False)
    ctx = _ctx(raw_output=_raw_envelope(now="刚才是谁说我脏手来着？"),
               reply="刚才是谁说我脏手来着？",
               attribution_evidence=_evidence())
    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply == "刚才是谁说我脏手来着？", "shadow 不得改交付"
    assert "risky_pattern" in out.attribution_decision["rejection_reason"]


@pytest.mark.asyncio
async def test_guard_enforce_fallback_keeps_clean_now_on_bad_reference(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "enforce", raising=False)
    ctx = _ctx(raw_output=_raw_envelope(ref="msg_missing"))
    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply_disposition == "fallback"
    assert "哈哈原来如此" not in out.reply
    assert out.attribution_decision["rejection_reason"] == "invalid_references"


@pytest.mark.asyncio
async def test_current_correction_routes_through_server_ack_template(monkeypatch):
    monkeypatch.setattr(settings_mod, "REPLY_ATTRIBUTION_GUARD_MODE", "enforce", raising=False)
    monkeypatch.setattr(pre_processors, "_recent_trusted_messages", lambda _ctx: [])
    monkeypatch.setattr(
        pre_processors,
        "_current_corrections",
        lambda ctx: [{
            "id": 7, "author_id": ctx.user_id, "author_display": "当前用户",
            "text": "我不是在学代码", "conversation_key": ctx.conversation_key,
            "source_row_id": 7, "polarity": "negative",
        }],
    )
    ctx = _ctx(
        user_id=20001,
        raw_output=(
            '<response version="2026-10-08.1"><thought>不得输出的诊断</thought>'
            '<action>NONE</action><reply kind="correction"><ack/></reply></response>'
        ),
    )
    ctx.attribution_evidence = pre_processors.build_attribution_evidence(ctx)
    assert ctx.attribution_risk_context["signal_codes"] == ["current_correction"]
    assert ctx.attribution_risk_context["supporting_evidence_ids"] == ["correction_7"]

    await gateway.parse_output(ctx)
    out = await gateway.attribution_guard_hook(ctx)
    assert out.reply_disposition == "fallback"
    assert out.attribution_decision["rejection_reason"] == "server_current_correction_template"
    assert out.reply == "抱歉，刚才是我搞混了，当前用户说得对。"
    assert "不得输出的诊断" not in out.reply


# ── typed 检索查询 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_user_context_v2_prefers_typed_query(monkeypatch, tmp_path):
    captured = {}

    def _fake_retrieve(**kw):
        captured["query"] = kw.get("query")
        return SimpleNamespace(
            mode="CASUAL_REPLY", conversation_memories=[],
            behavior_constraints=[], trace={},
        )

    monkeypatch.setattr(settings_mod, "MEMORY_EMBEDDING_ENABLED", False, raising=False)
    import memory.retrieval_v2 as rv2

    monkeypatch.setattr(rv2, "retrieve_memories", _fake_retrieve)
    ctx = _ctx(message="【任务】请向目标确认某背景", retrieval_query="开发 Stella 的经历")
    await pre_processors._build_user_context_v2(ctx)
    assert captured["query"] == "开发 Stella 的经历"

    ctx2 = _ctx(message="普通消息", retrieval_query="")
    await pre_processors._build_user_context_v2(ctx2)
    assert captured["query"] == "普通消息", "无 typed 查询时回退 ctx.message"


# ── 主动合同 ───────────────────────────────────────────────────────────


@pytest.fixture()
def proactive_db(tmp_path, monkeypatch):
    db = tmp_path / "proactive.db"
    monkeypatch.setattr(gateway, "DB_PATH", db)
    conn = sqlite3.connect(db)
    from memory.evidence_contract import ASSESSMENT_VERSION, source_digest
    from memory.schema import (
        MEMORY_CANDIDATES_TABLE_DDL,
        MEMORY_CLAIM_LINKS_TABLE_DDL,
        MEMORY_EVIDENCE_TABLE_DDL,
        create_memory_scope_versions_table,
    )

    conn.execute(MEMORY_CANDIDATES_TABLE_DDL)
    conn.execute(MEMORY_EVIDENCE_TABLE_DDL)
    conn.execute(MEMORY_CLAIM_LINKS_TABLE_DDL)
    create_memory_scope_versions_table(conn)
    conn.execute(
        """CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT,
            source_kind TEXT, timestamp TEXT, msg_id TEXT, conversation_key TEXT,
            bot_id TEXT, reply_to_msg_id TEXT, reply_target_user_id TEXT,
            mentioned_user_ids_json TEXT, logical_message_id TEXT, part_index INTEGER,
            origin_msg_id TEXT, reply_recipient_user_id TEXT
        )"""
    )
    uid, bot_id, group_id = "3559802578", "10000", "900"
    content = "我喜欢红中"
    conv_key = f"qq:{bot_id}:group:{group_id}"
    owner_key, fact_key, evidence_id, source_id = (
        "space:900", "claim:v1:cand9", "evidence:cand9", 501
    )
    snapshot = {
        "id": source_id, "group_id": group_id, "user_id": uid,
        "content": content, "source_kind": "AT_MENTION", "timestamp": "",
        "msg_id": "platform-501", "conversation_key": conv_key,
        "bot_id": bot_id, "reply_to_msg_id": "", "reply_target_user_id": "",
        "mentioned_user_ids_json": "", "logical_message_id": "", "part_index": 0,
        "origin_msg_id": "", "reply_recipient_user_id": "",
    }
    digest = source_digest(snapshot)
    provenance = {
        "assessment_version": ASSESSMENT_VERSION,
        "verification_status": "accepted", "claim_key": fact_key,
        "recording_author_key": f"qq:{uid}", "fact_object_key": f"qq:{uid}",
        "predicate_key": "preference.general", "canonical_value": "红中",
        "polarity": "positive", "statement_kind": "explicit_preference",
        "exact_support_span": content, "conversation_key": conv_key,
        "source_id": source_id, "source_snapshot": snapshot,
    }
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, confidence, importance, status, "
        "owner_type, owner_key, subject_key, audience, fact_key, source_conversation_key) "
        "VALUES ('cand9', '900', ?, 'PREFERENCE', ?, 0.7, 0.8, 'OBSERVING', 'SPACE', ?, '', "
        "'CURRENT_SPACE', ?, ?)",
        (uid, content, owner_key, fact_key, conv_key),
    )
    conn.execute(
        "INSERT INTO group_messages "
        "(id, group_id, user_id, content, source_kind, timestamp, msg_id, conversation_key, "
        "bot_id, reply_to_msg_id, reply_target_user_id, mentioned_user_ids_json, "
        "logical_message_id, part_index, origin_msg_id, reply_recipient_user_id) "
        "VALUES (?, ?, ?, ?, 'AT_MENTION', '', ?, ?, ?, '', '', '', '', 0, '', '')",
        (source_id, group_id, uid, content, "platform-501", conv_key, bot_id),
    )
    conn.execute(
        "INSERT INTO memory_evidence "
        "(id, owner_type, owner_key, subject_key, audience, fact_key, source_conversation_key, "
        "source_row_id, candidate_id, fact_subject_key, source_digest, verification_status, "
        "provenance_json) VALUES (?, 'SPACE', ?, '', 'CURRENT_SPACE', ?, ?, ?, 'cand9', ?, ?, "
        "'accepted', ?)",
        (evidence_id, owner_key, fact_key, conv_key, source_id, f"qq:{uid}", digest,
         json.dumps(provenance, ensure_ascii=False, separators=(",", ":"))),
    )
    conn.execute(
        "INSERT INTO memory_claim_links "
        "(id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key, "
        "projection_slot, projection_version, slot_digest, status) "
        "VALUES ('link-candidate', ?, ?, 'CURRENT_SPACE', 'memory_candidate', 'cand9', ?, "
        "'candidate', 1, ?, 'active')",
        (evidence_id, owner_key, fact_key, digest),
    )
    conn.execute(
        "INSERT INTO memory_claim_links "
        "(id, evidence_id, owner_key, audience, entity_type, entity_id, claim_key, "
        "projection_slot, projection_version, slot_digest, status) "
        "VALUES ('link-state', ?, ?, 'CURRENT_SPACE', 'claim_state', ?, ?, 'eligibility', 1, ?, 'active')",
        (evidence_id, owner_key, fact_key, fact_key, digest),
    )
    conn.commit()
    yield conn
    conn.close()


def test_proactive_contract_rejects_cross_subject(proactive_db):
    digest = proactive_db.execute(
        "SELECT source_digest FROM memory_evidence WHERE id = 'evidence:cand9'"
    ).fetchone()[0]
    target = SimpleNamespace(user_id=176403822, nickname="某人", candidate_id="cand9",
                             candidate_content="我喜欢红中", skip_subject="candidate:cand9",
                             owner_type="SPACE", owner_key="space:900",
                             audience="CURRENT_SPACE", fact_key="claim:v1:cand9",
                             fact_subject_key="qq:176403822",
                             source_conversation_key="qq:10000:group:900",
                             source_bot_id="10000", evidence_ids=("evidence:cand9",),
                             source_row_ids=(501,), source_digests=(digest,),
                             captured_scope_versions={"space:900": 0, "global": 0})
    contract, _variant, reason = gateway._build_proactive_contract(900, target)
    assert contract is None and reason == "subject_not_target"


def test_proactive_contract_accepts_subject_and_gates_output(proactive_db):
    digest = proactive_db.execute(
        "SELECT source_digest FROM memory_evidence WHERE id = 'evidence:cand9'"
    ).fetchone()[0]
    target = SimpleNamespace(user_id=3559802578, nickname="Nox", candidate_id="cand9",
                             candidate_content="我喜欢红中", skip_subject="candidate:cand9",
                             owner_type="SPACE", owner_key="space:900",
                             audience="CURRENT_SPACE", fact_key="claim:v1:cand9",
                             fact_subject_key="qq:3559802578",
                             source_conversation_key="qq:10000:group:900",
                             source_bot_id="10000", evidence_ids=("evidence:cand9",),
                             source_row_ids=(501,), source_digests=(digest,),
                             captured_scope_versions={"space:900": 0, "global": 0})
    contract, variant, reason = gateway._build_proactive_contract(900, target)
    assert reason == ""
    assert contract is not None and contract.selected_target_user_id == 3559802578
    assert contract.recording_author_id == 3559802578
    assert contract.source_row_ids == [501]
    assert variant is not None and "红中" in variant.filled_question

    ok, why = gateway._validate_proactive_output(
        contract, variant, "", [variant.filled_question])
    assert ok, why
    ok, why = gateway._validate_proactive_output(
        contract, variant, "", ["你平时会叫别人红中吗？"])
    assert not ok and why == "output_not_variant"


# ── 私聊分享授权入口 ───────────────────────────────────────────────────


@pytest.fixture()
def sharing_env(tmp_path, monkeypatch):
    db = tmp_path / "share.db"
    monkeypatch.setattr(gateway, "DB_PATH", db)
    monkeypatch.setattr(settings_mod, "PERSONAL_MEMORY_SHARE_ENABLED", True, raising=False)
    conn = sqlite3.connect(db)
    # 规范 DDL（复制 SQL 会逐列 SELECT，残缺表会炸——与生产同形）
    from memory import schema as schema_mod
    from memory.personal_sharing import (
        create_sharing_authorization_table,
        create_sharing_copies_table,
    )
    from memory.pre_processors import _GROUP_MESSAGES_V16_DDL

    conn.execute(schema_mod.MEMORIES_TABLE_DDL)
    conn.execute(schema_mod.MEMORY_CANDIDATES_TABLE_DDL)
    conn.execute(schema_mod.MEMORY_SCOPE_VERSIONS_TABLE_DDL)
    conn.execute(_GROUP_MESSAGES_V16_DDL)
    conn.execute(
        "ALTER TABLE memory_candidates ADD COLUMN verification_contract_json TEXT"
    )
    create_sharing_authorization_table(conn)
    create_sharing_copies_table(conn)
    conn.execute(
        "INSERT INTO group_messages (id, user_id, content, source_kind,"
        " conversation_key, bot_id) VALUES (77, '20001',"
        " '以后在群里也记得我们CP的关系', 'PRIVATE_DIRECT',"
        " 'qq:10000:private:20001', '10000')"
    )
    conn.execute(
        "INSERT INTO memory_candidates (id, owner_key, subject_key, audience,"
        " fact_key, status, type, content) VALUES ('cf1',"
        " 'person:qq:10000:20001', 'qq:20001', 'PRIVATE_ONLY',"
        " 'fk_cp', 'ACTIVE', 'relation', '用户20001与Lumi是CP')"
    )
    conn.commit()
    yield conn
    conn.close()


def test_sharing_ingress_creates_bound_grant(sharing_env):
    ctx = _ctx(message="以后在群里也记得我们CP的关系", recorded_row_id=77)
    gateway._maybe_personal_sharing(ctx)
    row = sharing_env.execute(
        "SELECT status, source_message_row_id, owner_key FROM personal_memory_sharing"
    ).fetchone()
    assert row is not None
    assert row[0] == "active"
    assert row[1] == 77
    assert row[2] == "person:qq:10000:20001"


def test_sharing_ingress_disabled_is_noop(sharing_env, monkeypatch):
    monkeypatch.setattr(settings_mod, "PERSONAL_MEMORY_SHARE_ENABLED", False, raising=False)
    ctx = _ctx(message="以后在群里也记得我们CP的关系", recorded_row_id=77)
    gateway._maybe_personal_sharing(ctx)
    assert sharing_env.execute(
        "SELECT COUNT(*) FROM personal_memory_sharing").fetchone()[0] == 0


def test_sharing_ingress_ignores_plain_chat(sharing_env):
    ctx = _ctx(message="我在群里玩游戏", recorded_row_id=77)
    gateway._maybe_personal_sharing(ctx)
    assert sharing_env.execute(
        "SELECT COUNT(*) FROM personal_memory_sharing").fetchone()[0] == 0
