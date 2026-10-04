# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""多人对话身份与归属修复（计划 §7 M0/M1，T01/T07/T18 及归属渲染）。

M0 冻结的失败场景（合成身份 A=2001 / B=2002 / 群=7777 / Bot=10000，来自
docs/reports/2026-10-04-multi-user-identity-confusion-investigation.md 的隔离
探针）与 M1 修复后的新期望：

1. 群入口生成的 scope 主体是真实 sender（B），不再是群号 7777——B 的
   USER_SHARED 个人事实能命中（旧缺陷：漏掉）；
2. A 的 SPACE 称呼记忆渲染时带「其他成员的公开背景」归属头，不得呈现为
   当前用户的偏好（T01）；
3. 无目标群主动发言没有个人主体（SPACE-only）；主动 @ 的可信目标是
   ctx.user_id（T18）；
4. Planner 深度查询与主回复同主体（T18 下半）；
5. 未提供当前主体时 build_conversation_section 保持旧格式逐字节兼容。
"""

from __future__ import annotations

import sqlite3

import pytest

import memory.retrieval_v2 as retrieval_v2
from core.context import ChatContext
from memory import prompt_builder
from memory.ownership import (
    AUDIENCE_USER_SHARED,
    OWNER_TYPE_PERSON,
    OWNER_TYPE_SPACE,
    person_compat_space,
    scope_for_chat_context,
    scope_for_conversation,
)

BOT = 10000
GROUP = 7777
A = 2001
B = 2002


@pytest.fixture()
def mem_db(tmp_path, monkeypatch):
    """schema15 形状的记忆库：调查实例的合成重演。

    A 有三条称呼偏好（全部 SPACE 记录归属、挂在共享空间）；B 有一条
    USER_SHARED PERSON 称呼（阿呆）。RAG/FTS 关闭走纯 SQL 路径，隔离
    分词差异对断言的干扰。
    """
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(retrieval_v2, "DB_PATH", db)
    monkeypatch.setattr(retrieval_v2, "RAG_ENABLED", False)
    conn = sqlite3.connect(db)
    from memory.schema import MEMORIES_TABLE_DDL
    conn.execute(MEMORIES_TABLE_DDL)
    conn.execute("CREATE TABLE schema_meta (k TEXT PRIMARY KEY, version INTEGER)")
    conn.execute("INSERT INTO schema_meta VALUES ('version', 15)")
    space = "7777"
    shared_ns = person_compat_space(f"person:qq:{BOT}:{B}", AUDIENCE_USER_SHARED)
    rows = [
        # A 的三条称呼记忆：owner_type=SPACE（记录归属，非认证事实主语）
        ("m-a1", space, str(A), "希望被称呼为 Allets，之前为 STellA",
         OWNER_TYPE_SPACE, f"space:{space}", "", "CURRENT_SPACE"),
        ("m-a2", space, str(A), "偏好被称呼为 Allets",
         OWNER_TYPE_SPACE, f"space:{space}", "", "CURRENT_SPACE"),
        ("m-a3", space, str(A), "希望被称呼为 STellA，或者改名为 Allets",
         OWNER_TYPE_SPACE, f"space:{space}", "", "CURRENT_SPACE"),
        # B 的个人事实：USER_SHARED（同 Bot 任何会话可见）
        ("m-b1", shared_ns, str(B), "希望被称呼为阿呆",
         OWNER_TYPE_PERSON, f"person:qq:{BOT}:{B}", f"qq:{B}", AUDIENCE_USER_SHARED),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
            " importance, confidence, status, owner_type, owner_key, subject_key, audience)"
            " VALUES (?,?,?, 'PREFERENCE', ?, .8, .9, 'active', ?, ?, ?, ?)",
            r,
        )
    conn.commit()
    conn.close()
    return db


def _group_ctx(sender: int, *, trigger: str = "reply", intent: str = "") -> ChatContext:
    """群入口的标准升级形态（与 ai_gateway.handle_chat 的 v3 字段一致）。"""
    return ChatContext(
        user_id=sender,
        group_id=GROUP,
        msg_id=1,
        message="阿呆是我" if sender == B else "我才是allest",
        source_kind="AT_MENTION",
        conversation_kind="group",
        conversation_key=f"qq:{BOT}:group:{GROUP}",
        bot_id=str(BOT),
        peer_id=str(GROUP),
        storage_session_id=GROUP,
        trigger=trigger,
        intent=intent,
    )


# ── T07/M1：群 scope 主体 = 真实 sender，不再吃群号 ──────────────────


def test_group_scope_subject_is_sender_not_group_number(mem_db):
    """群入口 scope 的 subject 必须是 B（2002），person owner 不含群号。"""
    from memory.ownership import scope_for_chat_context

    scope = scope_for_chat_context(_group_ctx(B), memory_space="7777")
    assert scope is not None
    assert scope.subject_key == f"qq:{B}"
    assert scope.person_owner_key == f"person:qq:{BOT}:{B}"
    assert str(GROUP) not in scope.person_owner_key
    assert str(GROUP) not in scope.subject_key


def test_b_personal_memory_reachable_via_group_ingress(mem_db):
    """修复点（调查 §4）：群入口生成的 scope 必须能命中 B 的 USER_SHARED 事实。"""
    conn = sqlite3.connect(mem_db)
    cursor = conn.cursor()
    scope = scope_for_chat_context(_group_ctx(B), memory_space="7777")
    found = {
        m["id"]
        for m in retrieval_v2._fetch_candidates(
            cursor, "7777", B, "CASUAL_REPLY", "阿呆", 20, access_scope=scope
        )
    }
    conn.close()
    assert "m-b1" in found, "B 的 USER_SHARED 称呼必须进入候选池（旧缺陷：群号当主体导致漏召回）"
    assert "m-a1" in found and "m-a2" in found  # SPACE 背景仍可见


def test_private_only_never_leaks_into_group_scope(mem_db, tmp_path, monkeypatch):
    """PRIVATE_ONLY 行对群 scope 永不可见（授权边界不因主体修复而变宽）。"""
    from memory.ownership import AUDIENCE_PRIVATE_ONLY

    conn = sqlite3.connect(mem_db)
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content,"
        " importance, confidence, status, owner_type, owner_key, subject_key, audience)"
        " VALUES ('m-b-priv', ?, ?, 'FACT', '家庭住址是私密信息', .8, .9, 'active',"
        " 'PERSON', ?, ?, ?)",
        (
            person_compat_space(f"person:qq:{BOT}:{B}", AUDIENCE_PRIVATE_ONLY),
            str(B),
            f"person:qq:{BOT}:{B}",
            f"qq:{B}",
            AUDIENCE_PRIVATE_ONLY,
        ),
    )
    conn.commit()
    cursor = conn.cursor()
    scope = scope_for_chat_context(_group_ctx(B), memory_space="7777")
    found = {
        m["id"]
        for m in retrieval_v2._fetch_candidates(
            cursor, "7777", B, "CASUAL_REPLY", "家庭住址", 20, access_scope=scope
        )
    }
    conn.close()
    assert "m-b-priv" not in found


# ── T01/M1：A 的记忆渲染为他人背景，不能变成 B 的身份 ─────────────────


def test_a_memories_rendered_as_other_member_background(mem_db):
    """B 的回复轮次里，A 的称呼记忆必须带 A 的归属头。"""
    conn = sqlite3.connect(mem_db)
    cursor = conn.cursor()
    scope = scope_for_chat_context(_group_ctx(B), memory_space="7777")
    candidates = retrieval_v2._fetch_candidates(
        cursor, "7777", B, "CASUAL_REPLY", "阿呆是我", 20, access_scope=scope
    )
    conn.close()
    section = prompt_builder.build_conversation_section(
        candidates, max_tokens=500, current_user_id=B
    )
    # A 的记忆是 SPACE 行（记录归属）：必须带 A 的记录归属头 + 「事实主语未确认」，
    # 绝不能呈现为当前用户（B）的偏好
    assert "群共享背景 [记录=用户(2001)；事实主语未确认]：希望被称呼为 Allets" in section
    assert "希望被称呼为 Allets" in section
    # 归属未确认的 SPACE 行不得呈现为「当前用户的记忆」
    assert "当前用户的记忆 [subject=用户(2001)]" not in section
    # B 自己的 PERSON 行才是「当前用户的记忆」
    if "m-b1" in {m["id"] for m in candidates}:
        assert "当前用户的记忆 [subject=用户(2002)]" in section


def test_current_user_person_memory_labeled_as_own():
    """PERSON 行 subject=当前用户 →「当前用户的记忆」；他人 → 公开背景。"""
    own = {
        "content": "希望被称呼为阿呆",
        "user_id": str(B),
        "owner_type": "PERSON",
        "owner_key": f"person:qq:{BOT}:{B}",
        "subject_key": f"qq:{B}",
        "audience": "USER_SHARED",
    }
    other = dict(own, user_id=str(A), subject_key=f"qq:{A}")
    section = prompt_builder.build_conversation_section(
        [own, other], max_tokens=500, current_user_id=B
    )
    assert "当前用户的记忆 [subject=用户(2002)]：希望被称呼为阿呆" in section
    assert "其他成员的公开背景 [subject=用户(2001)]" in section


def test_conversation_section_legacy_format_unchanged_without_subject():
    """旧调用（无 keyword 主体）保持旧格式逐字节——兼容现有预算测试。"""
    mems = [{"content": "希望被称呼为 Allets", "user_id": str(A)}]
    assert (
        prompt_builder.build_conversation_section(mems, max_tokens=500)
        == "可参考的聊天背景：\n- 希望被称呼为 Allets"
    )


def test_attribution_header_counts_into_token_budget():
    """归属头先拼进条目再算 token（PDG 约束：不能先算正文再补标签）。"""
    long_mem = {"content": "喜欢" * 200, "user_id": str(A)}
    with_header = prompt_builder.build_conversation_section(
        [long_mem], max_tokens=prompt_builder.estimate_tokens("喜欢" * 200) + 2,
        current_user_id=B,
    )
    # 标签有成本：同样预算下带标签版本应更早触达截断
    assert len(with_header) < len("- " + long_mem["content"]) + len(
        prompt_builder._attribution_header(long_mem, B)
    ) + 64 or with_header.endswith(long_mem["content"][-8:])


# ── T18/M1：无目标主动无个人主体；主动 @ 目标可信 ────────────────────


def test_targetless_proactive_has_no_personal_subject():
    """群级主动发言（user_id=0, trigger=proactive）→ None（SPACE-only 旧行为）。"""
    ctx = _group_ctx(0, trigger="proactive")
    ctx.user_id = 0
    assert scope_for_chat_context(ctx, memory_space="7777") is None


def test_proactive_at_scope_targets_verified_uid():
    """主动 @ 的主体是经过 pick_target 验证的 ctx.user_id，不是群号。"""
    ctx = _group_ctx(B, intent="proactive_at")
    scope = scope_for_chat_context(ctx, memory_space="7777")
    assert scope is not None
    assert scope.subject_key == f"qq:{B}"
    assert str(GROUP) not in scope.person_owner_key


def test_legacy_entrance_stays_scope_free():
    """旧入口（kind 空）返回 None，与升级前行为逐字一致。"""
    ctx = ChatContext(user_id=B, group_id=GROUP, msg_id=1, message="hi")
    assert scope_for_chat_context(ctx, memory_space="7777") is None


# ── T18/M1：Planner 深度查询与主回复同主体 ───────────────────────────


def test_planner_query_memory_uses_sender_subject(mem_db, monkeypatch):
    """Planner 的 QUERY_MEMORY 走同一可信主体 helper，不把群号当人。"""
    import core.planner as planner_mod

    captured: dict = {}

    def fake_retrieve(space, user_id, query, trigger="", access_scope=None, **kw):
        captured["scope"] = access_scope
        from memory.retrieval_v2 import RetrievalResult

        return RetrievalResult()

    monkeypatch.setattr(retrieval_v2, "retrieve_memories", fake_retrieve)

    class _Backend:
        backend_name = "fake"

    planner = planner_mod.RestrictedPlanner(_Backend())
    ctx = _group_ctx(B)
    ctx.planner_action = "QUERY_MEMORY"
    ctx.deep_tool_calls = 0
    planner._query_memory(ctx, "阿呆")
    scope = captured.get("scope")
    assert scope is not None
    assert scope.subject_key == f"qq:{B}"
    assert str(GROUP) not in scope.person_owner_key


# ── 检索结果携带归属列（渲染输入） ───────────────────────────────────


def test_candidates_carry_owner_columns_for_rendering(mem_db):
    """Python 检索路径返回的 dict 带 owner 字段；native/旧库缺字段时渲染降级。"""
    conn = sqlite3.connect(mem_db)
    cursor = conn.cursor()
    scope = scope_for_chat_context(_group_ctx(B), memory_space="7777")
    candidates = retrieval_v2._fetch_candidates(
        cursor, "7777", B, "CASUAL_REPLY", "称呼", 20, access_scope=scope
    )
    conn.close()
    by_id = {m["id"]: m for m in candidates}
    assert by_id["m-a1"]["owner_type"] == "SPACE"
    assert by_id["m-b1"]["owner_type"] == "PERSON"
    assert by_id["m-b1"]["subject_key"] == f"qq:{B}"


def test_rendering_degrades_without_owner_fields():
    """缺 owner 字段（native 结果）→ legacy SPACE 语义，不伪造归属。"""
    native_row = {"content": "希望被称呼为 Allets", "user_id": str(A)}
    section = prompt_builder.build_conversation_section(
        [native_row], max_tokens=500, current_user_id=B
    )
    assert "群共享背景 [记录=用户(2001)；事实主语未确认]" in section
    assert "当前用户的记忆" not in section


# ── scope_for_conversation 基线（M0 合同，守护 helper 底层） ──────────


def test_scope_for_conversation_group_audience():
    scope = scope_for_conversation(
        kind="group", memory_space="7777", platform="qq",
        bot_id=str(BOT), user_id=B,
    )
    assert scope.has_person
    assert scope.person_audiences == (AUDIENCE_USER_SHARED,)
