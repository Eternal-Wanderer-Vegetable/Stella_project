# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""ConversationManager 与 sp：落在独立表，与记忆系统隔离。"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from astrbot_compat.conversation import ConversationManager

UMO = "aiocqhttp:GroupMessage:263402786"


@pytest.fixture
def cm(llm_db) -> ConversationManager:
    return ConversationManager()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- 基本 CRUD


def test_new_conversation_returns_uuid(cm):
    cid = _run(cm.new_conversation(UMO))
    assert len(cid) == 36
    assert _run(cm.get_curr_conversation_id(UMO)) == cid


def test_platform_id_parsed_from_umo(cm):
    cid = _run(cm.new_conversation(UMO))
    conv = _run(cm.get_conversation(UMO, cid))
    assert conv.platform_id == "aiocqhttp"
    assert conv.user_id == UMO


def test_history_is_a_json_string(cm):
    """上游 Conversation.history 是字符串，插件到处 json.loads 它。"""
    cid = _run(cm.new_conversation(UMO, content=[{"role": "user", "content": "hi"}]))
    conv = _run(cm.get_conversation(UMO, cid))
    assert isinstance(conv.history, str)
    assert json.loads(conv.history) == [{"role": "user", "content": "hi"}]


def test_update_conversation(cm):
    cid = _run(cm.new_conversation(UMO))
    _run(
        cm.update_conversation(
            UMO,
            cid,
            history=[{"role": "user", "content": "q"}],
            title="标题",
            persona_id="p1",
            token_usage=42,
        ),
    )
    conv = _run(cm.get_conversation(UMO, cid))
    assert conv.title == "标题"
    assert conv.persona_id == "p1"
    assert conv.token_usage == 42
    assert json.loads(conv.history)[0]["content"] == "q"


def test_update_without_cid_uses_current(cm):
    cid = _run(cm.new_conversation(UMO))
    _run(cm.update_conversation(UMO, history=[{"role": "user", "content": "x"}]))
    conv = _run(cm.get_conversation(UMO, cid))
    assert json.loads(conv.history)[0]["content"] == "x"


def test_add_message_pair(cm):
    cid = _run(cm.new_conversation(UMO))
    _run(cm.add_message_pair(cid, {"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}))
    conv = _run(cm.get_conversation(UMO, cid))
    assert [m["role"] for m in json.loads(conv.history)] == ["user", "assistant"]


def test_add_message_pair_on_missing_conversation(cm):
    with pytest.raises(ValueError, match="not found"):
        _run(cm.add_message_pair("nope", {}, {}))


def test_get_conversation_create_if_not_exists(cm):
    conv = _run(cm.get_conversation(UMO, "不存在", create_if_not_exists=True))
    assert conv is not None
    assert _run(cm.get_conversation(UMO, "不存在")) is None


def test_switch_conversation(cm):
    first = _run(cm.new_conversation(UMO))
    second = _run(cm.new_conversation(UMO))
    _run(cm.switch_conversation(UMO, first))
    assert _run(cm.get_curr_conversation_id(UMO)) == first
    assert second != first


def test_delete_conversation_clears_current(cm):
    cid = _run(cm.new_conversation(UMO))
    _run(cm.delete_conversation(UMO, cid))
    assert _run(cm.get_conversation(UMO, cid)) is None
    assert _run(cm.get_curr_conversation_id(UMO)) is None


def test_delete_by_user(cm):
    _run(cm.new_conversation(UMO))
    _run(cm.new_conversation(UMO))
    _run(cm.delete_conversations_by_user_id(UMO))
    assert _run(cm.get_conversations(UMO)) == []


def test_get_conversations_sorted_and_filtered(cm):
    _run(cm.new_conversation(UMO))
    _run(cm.new_conversation("aiocqhttp:FriendMessage:1"))
    assert len(_run(cm.get_conversations())) == 2
    assert len(_run(cm.get_conversations(UMO))) == 1
    assert len(_run(cm.get_conversations(platform_id="aiocqhttp"))) == 2


def test_human_readable_context(cm):
    cid = _run(
        cm.new_conversation(
            UMO,
            content=[{"role": "user", "content": "问"}, {"role": "assistant", "content": "答"}],
        ),
    )
    lines, pages = _run(cm.get_human_readable_context(UMO, cid))
    assert lines == ["user: 问", "assistant: 答"]
    assert pages == 1


def test_session_deleted_callback(cm):
    seen = []

    async def cb(umo):
        seen.append(umo)

    cm.register_on_session_deleted(cb)
    cid = _run(cm.new_conversation(UMO))
    _run(cm.delete_conversation(UMO, cid))
    assert seen == [UMO]


# ---------------------------------------------------------------- 隔离性


def test_lives_in_its_own_table(cm, llm_db):
    _run(cm.new_conversation(UMO))
    with sqlite3.connect(llm_db) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # 只碰兼容层自己的表，绝不碰记忆系统
    assert "astrbot_conversations" in tables
    assert "memories" not in tables
    assert "group_messages" not in tables


def test_current_conversation_survives_restart(llm_db):
    """当前会话 id 存在 sp 里，换个 manager 实例仍读得到。"""
    first = ConversationManager()
    cid = _run(first.new_conversation(UMO))

    from astrbot_compat import preferences as pref_mod

    pref_mod.sp.reset_cache()
    second = ConversationManager()
    assert _run(second.get_curr_conversation_id(UMO)) == cid


# ---------------------------------------------------------------- sp


def test_sp_async_roundtrip(llm_db):
    from astrbot_compat.preferences import sp

    _run(sp.put_async("umo", "g1", "k", {"a": 1}))
    assert _run(sp.get_async("umo", "g1", "k")) == {"a": 1}
    sp.reset_cache()
    assert _run(sp.get_async("umo", "g1", "k")) == {"a": 1}
    _run(sp.remove_async("umo", "g1", "k"))
    assert _run(sp.get_async("umo", "g1", "k", "dft")) == "dft"


def test_sp_session_and_global(llm_db):
    from astrbot_compat.preferences import sp

    _run(sp.session_put(UMO, "flag", True))
    assert _run(sp.session_get(UMO, "flag")) is True
    _run(sp.global_put("g", 1))
    assert _run(sp.global_get("g")) == 1


def test_sp_sync_api_has_different_arg_order(llm_db):
    """同步版是 (key, default, scope, scope_id)，异步版是 (scope, scope_id, key, default)。

    这是上游的历史包袱，插件按它写代码，不能"修正"。
    """
    from astrbot_compat.preferences import sp

    sp.put("k", "v", scope="plugin", scope_id="demo")
    assert sp.get("k", None, "plugin", "demo") == "v"
    assert _run(sp.get_async("plugin", "demo", "k")) == "v"


def test_sp_range_get(llm_db):
    from astrbot_compat.preferences import sp

    _run(sp.put_async("umo", "g1", "a", 1))
    _run(sp.put_async("umo", "g1", "b", 2))
    prefs = _run(sp.range_get_async("umo", "g1"))
    assert {p.key for p in prefs} == {"a", "b"}


def test_sp_none_key_returns_list(llm_db):
    from astrbot_compat.preferences import sp

    _run(sp.session_put(UMO, "x", 1))
    out = _run(sp.session_get(UMO, None))
    assert isinstance(out, list)


def test_sp_rejects_none_key(llm_db):
    from astrbot_compat.preferences import sp

    with pytest.raises(ValueError, match="key"):
        _run(sp.put_async("umo", "g", None, 1))
