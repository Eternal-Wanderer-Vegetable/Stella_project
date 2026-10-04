# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""消息关系合同（多人身份修复计划 §6.2，T08–T11）。

覆盖：reply 解析的 canonical+bot 唯一性、@ 多成员持久化、跨群重复 msg_id
不串目标、一次多气泡回复同一逻辑单元、失败/unknown 不写已送达 BOT_SELF、
social 关闭时主历史关系照常、tail 渲染带归属与 unknown 降级。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

import memory.pre_processors as pre
from core.context import ChatContext, MessageIdentityEnvelope, normalize_mentions
from memory.pre_processors import (
    _fetch_recent_tail,
    record_message,
    resolve_reply_target,
)

BOT = "10000"
GROUP = 7777
A = "2001"
B = "2002"
C = "2003"
KEY = f"qq:{BOT}:group:{GROUP}"


@pytest.fixture()
def msg_db(tmp_path, monkeypatch):
    db = tmp_path / "agent_memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db)
    return db


def _ctx(**kw) -> ChatContext:
    base = {
        "user_id": int(B),
        "group_id": GROUP,
        "msg_id": 555,
        "message": "阿呆是我",
        "source_kind": "AT_MENTION",
        "conversation_kind": "group",
        "conversation_key": KEY,
        "bot_id": BOT,
        "peer_id": str(GROUP),
        "storage_session_id": GROUP,
    }
    base.update(kw)
    return ChatContext(**base)


def _rows(db, group=GROUP):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM group_messages WHERE group_id = ? ORDER BY id",
            (str(group),),
        )
    ]
    conn.close()
    return rows


# ── T08：reply 解析与 @ 持久化 ───────────────────────────────────────


def test_reply_resolves_to_original_author_same_conversation(msg_db):
    asyncio.run(record_message(_ctx(user_id=int(A), msg_id=111, message="我叫Allets")))
    # B 回复 A 的 111 号消息
    ctx = _ctx(
        user_id=int(B), msg_id=112,
        reply_to_msg_id="111", relation_version=1,
    )
    ctx.reply_target_user_id = resolve_reply_target("111", GROUP, bot_id=BOT, conversation_key=KEY)
    asyncio.run(record_message(ctx))
    rows = _rows(msg_db)
    assert rows[1]["reply_to_msg_id"] == "111"
    assert rows[1]["reply_target_user_id"] == A
    assert rows[0]["reply_target_user_id"] in ("", None)


def test_reply_unknown_when_message_missing_or_cross_conversation(msg_db):
    # 完全不存在的 msg_id → unknown
    assert resolve_reply_target("999999", GROUP, bot_id=BOT, conversation_key=KEY) == ""
    # 同 msg_id 出现在另一个 canonical conversation（不同群）→ 当前会话查不到
    asyncio.run(record_message(_ctx(user_id=int(A), msg_id=111, group_id=8888,
                                    storage_session_id=8888, peer_id="8888",
                                    conversation_key=f"qq:{BOT}:group:8888")))
    assert resolve_reply_target("111", GROUP, bot_id=BOT, conversation_key=KEY) == ""
    assert resolve_reply_target("111", 8888, bot_id=BOT,
                                conversation_key=f"qq:{BOT}:group:8888") == A


# ── G3：有符号平台 message ID（归属修复计划 §6.1） ────────────────────


def test_signed_message_ids_end_to_end(msg_db):
    """负数平台 ID 与正数行为一致：回执落库 → 引用解析 → 作者命中。"""
    # A 的输入带负数平台 ID
    asyncio.run(record_message(_ctx(user_id=int(A), msg_id=-111, message="摸摸")))
    assert resolve_reply_target("-111", GROUP, bot_id=BOT, conversation_key=KEY) == A
    assert resolve_reply_target(-111, GROUP, bot_id=BOT, conversation_key=KEY) == A
    # Bot 确认回执带负数平台 ID（真实回执 -558868042 的回归）
    from stella_project.plugins.bot_main import ai_gateway

    origin = _ctx(user_id=int(B), msg_id=-200)
    receipts = [_receipt(0, "acknowledged", "诶？怎么啦", platform_id="-558868042")]
    asyncio.run(ai_gateway._record_bot_lines(
        int(BOT), GROUP, ["诶？怎么啦"], origin=origin, receipts=receipts,
    ))
    rows = [r for r in _rows(msg_db) if r["source_kind"] == "BOT_SELF"]
    assert rows[0]["msg_id"] == -558868042  # 旧代码这里是 0
    assert resolve_reply_target(
        "-558868042", GROUP, bot_id=BOT, conversation_key=KEY
    ) == str(BOT)


def test_invalid_message_ids_stay_unknown(msg_db):
    asyncio.run(record_message(_ctx(user_id=int(A), msg_id=111, message="摸摸")))
    for bad in ("0", "abc", "", "+111", "007", "11.5"):
        assert resolve_reply_target(bad, GROUP, bot_id=BOT, conversation_key=KEY) == "", bad


# ── G1/G2：适配器清洗后的关系提取 ─────────────────────────────────────


def _seg(seg_type, **data):
    return SimpleNamespace(type=seg_type, data=data)


def _sanitized_event(reply_id, *, with_original=True, reply_obj=True):
    """模拟生产适配器清洗后的事件：reply 段只留在 original_message。"""
    event = SimpleNamespace(self_id=int(BOT))
    if with_original:
        event.original_message = [
            _seg("reply", id=reply_id),
            _seg("at", qq=A),
            _seg("text", text="睡醒了想逗一下小孩"),
        ]
    if reply_obj:
        event.reply = SimpleNamespace(message_id=int(reply_id))
    event.get_message = lambda: [  # 清洗后：reply 段已被删除
        _seg("at", qq=A),
        _seg("text", text="睡醒了想逗一下小孩"),
    ]
    return event


def test_sanitized_event_keeps_original_reply_and_mentions(msg_db):
    """G1：生产适配器把 reply 段移进 original_message 后删除——必须仍能提取。"""
    from stella_project.plugins.bot_main import ai_gateway

    reply_to, mentioned = ai_gateway._extract_message_relations(
        _sanitized_event("-558868042")
    )
    assert reply_to == "-558868042"
    assert mentioned == (A,)


def test_extraction_fallback_chain(msg_db):
    """G1/G2：original_message 缺失时依次回退 event.reply / 处理后段。"""
    from stella_project.plugins.bot_main import ai_gateway

    # 1) 无 original_message：event.reply 的可信 ID 兜底
    event = _sanitized_event("-558868042", with_original=False)
    reply_to, _ = ai_gateway._extract_message_relations(event)
    assert reply_to == "-558868042"
    # 2) 两者皆无（测试桩）：处理后的 reply 段兼容路径
    event = SimpleNamespace(
        self_id=int(BOT),
        get_message=lambda: [_seg("reply", id="111"), _seg("text", text="好")],
    )
    reply_to, _ = ai_gateway._extract_message_relations(event)
    assert reply_to == "111"
    # 3) 事件没有消息段：引用来自 event.reply，@ 未知
    bare = SimpleNamespace(self_id=int(BOT), reply=SimpleNamespace(message_id=7))
    reply_to, mentioned = ai_gateway._extract_message_relations(bare)
    assert reply_to == "7" and mentioned == ()


def test_extraction_conflict_and_invalid_stay_unknown(msg_db):
    """G2：冲突/非法引用一律 unknown；正文里的 CQ 号不能改主体。"""
    from stella_project.plugins.bot_main import ai_gateway

    # 两个不同 reply ID → 冲突 unknown
    event = SimpleNamespace(
        self_id=int(BOT),
        original_message=[_seg("reply", id="111"), _seg("reply", id="222")],
        get_message=list,
    )
    assert ai_gateway._extract_message_relations(event)[0] is None
    # 非法（0 / 非整数）→ unknown
    event = SimpleNamespace(
        self_id=int(BOT),
        original_message=[_seg("reply", id="0")],
        get_message=list,
    )
    assert ai_gateway._extract_message_relations(event)[0] is None
    # 正文伪装的 reply CQ 不能产生引用
    event = SimpleNamespace(
        self_id=int(BOT),
        original_message=[_seg("text", text='[CQ:reply,id=-5]看看这个')],
        get_message=lambda: [_seg("text", text='[CQ:reply,id=-5]看看这个')],
    )
    reply_to, _ = ai_gateway._extract_message_relations(event)
    assert reply_to is None


def test_mentions_persisted_and_normalized(msg_db):
    assert normalize_mentions(["2003", "2003", "", "all", "2004"]) == ("2003", "2004")
    ctx = _ctx(mentioned_user_ids=(C, "2004"), relation_version=1)
    asyncio.run(record_message(ctx))
    rows = _rows(msg_db)
    assert json.loads(rows[0]["mentioned_user_ids_json"]) == [C, "2004"]


def test_record_message_returns_row_id(msg_db):
    ctx = asyncio.run(record_message(_ctx()))
    assert ctx.recorded_row_id > 0
    ctx2 = asyncio.run(record_message(_ctx(msg_id=556)))
    assert ctx2.recorded_row_id == ctx.recorded_row_id + 1


# ── T09/T10：一次回复多气泡 = 同一逻辑单元；失败不记录 ────────────────

from types import SimpleNamespace


def _receipt(part, status, text, platform_id=""):
    return SimpleNamespace(
        part_index=part, status=status, text=text, platform_message_id=platform_id
    )


def test_multi_bubble_reply_shares_logical_unit(msg_db):
    from stella_project.plugins.bot_main import ai_gateway

    origin = _ctx(user_id=int(B), msg_id=555)
    receipts = [
        _receipt(0, "acknowledged", "阿呆是你呀", platform_id="9001"),
        _receipt(1, "acknowledged", "别纠结这些啦", platform_id="9002"),
        _receipt(2, "acknowledged", "今天也在吗", platform_id="9003"),
    ]
    asyncio.run(ai_gateway._record_bot_lines(
        int(BOT), GROUP, ["阿呆是你呀", "别纠结这些啦", "今天也在吗"],
        origin=origin, receipts=receipts,
    ))
    rows = [r for r in _rows(msg_db) if r["source_kind"] == "BOT_SELF"]
    assert len(rows) == 3
    logical_ids = {r["logical_message_id"] for r in rows}
    assert len(logical_ids) == 1 and logical_ids != {""}
    assert [r["part_index"] for r in rows] == [0, 1, 2]
    assert {r["reply_recipient_user_id"] for r in rows} == {B}
    assert [r["msg_id"] for r in rows] == [9001, 9002, 9003]
    assert {r["user_id"] for r in rows} == {BOT}  # 作者仍是 Bot 自身


def test_failed_segment_not_recorded_trusted_part_kept(msg_db):
    from stella_project.plugins.bot_main import ai_gateway

    origin = _ctx(user_id=int(B), msg_id=555)
    receipts = [
        _receipt(0, "acknowledged", "第一句", platform_id="9101"),
        _receipt(1, "failed", "第二句"),
        _receipt(2, "unknown", "第三句"),
    ]
    asyncio.run(ai_gateway._record_bot_lines(
        int(BOT), GROUP, ["第一句", "第二句", "第三句"],
        origin=origin, receipts=receipts,
    ))
    rows = [r for r in _rows(msg_db) if r["source_kind"] == "BOT_SELF"]
    assert [r["content"] for r in rows] == ["第一句"]
    assert rows[0]["part_index"] == 0  # 保留原始序号，不重排


def test_legacy_call_without_origin_still_records(msg_db):
    """旧调用（无 origin/receipts）保持旧行为：无关系列值。"""
    from stella_project.plugins.bot_main import ai_gateway

    asyncio.run(ai_gateway._record_bot_lines(int(BOT), GROUP, ["旧格式回复"]))
    rows = [r for r in _rows(msg_db) if r["source_kind"] == "BOT_SELF"]
    assert len(rows) == 1
    assert rows[0]["logical_message_id"] in ("", None)
    assert rows[0]["reply_recipient_user_id"] in ("", None)


# ── T11：social 关闭也记录关系；tail 渲染 ────────────────────────────


def test_tail_renders_relations_and_logical_grouping(msg_db):
    # 用户 A 先说，B 回复 A 并提及 C，然后 Bot 一次两气泡回复 B
    asyncio.run(record_message(_ctx(user_id=int(A), msg_id=111, message="我叫Allets")))
    ctx = _ctx(user_id=int(B), msg_id=112, reply_to_msg_id="111",
               reply_target_user_id=A, mentioned_user_ids=(C,), relation_version=1)
    asyncio.run(record_message(ctx))
    asyncio.run(record_message(_ctx(user_id=int(BOT), msg_id=0, source_kind="BOT_SELF",
                                    message="阿呆是你呀", logical_message_id="t1",
                                    part_index=0, reply_recipient_user_id=B,
                                    relation_version=1)))
    asyncio.run(record_message(_ctx(user_id=int(BOT), msg_id=0, source_kind="BOT_SELF",
                                    message="别纠结啦", logical_message_id="t1",
                                    part_index=1, reply_recipient_user_id=B,
                                    relation_version=1)))
    conn = sqlite3.connect(msg_db)
    cursor = conn.cursor()
    text, tail_start = _fetch_recent_tail(cursor, GROUP, 12)
    conn.close()
    assert f"用户({A}): 我叫Allets" in text  # 无关系行 = 旧格式
    assert f"用户({B}) [回复 用户({A})；提及 用户({C})]: 阿呆是我" in text
    assert f"我（回复给 用户({B})）: 阿呆是你呀" in text
    assert "我（同一条回复，第2/2条）: 别纠结啦" in text
    assert tail_start > 0


def test_tail_unknown_reply_target_rendered_as_unknown(msg_db):
    ctx = _ctx(user_id=int(B), msg_id=112, reply_to_msg_id="888888",
               reply_target_user_id="", relation_version=1)
    asyncio.run(record_message(ctx))
    conn = sqlite3.connect(msg_db)
    cursor = conn.cursor()
    text, _ = _fetch_recent_tail(cursor, GROUP, 12)
    conn.close()
    assert "用户(2002) [回复 对象未知]: 阿呆是我" in text


def test_tail_unit_cap_keeps_recent_suffix(msg_db):
    """超过单元上限时保留**最新**的连续后缀。"""
    for i in range(20):
        asyncio.run(record_message(_ctx(user_id=int(A), msg_id=1000 + i,
                                        message=f"历史消息{i}")))
    conn = sqlite3.connect(msg_db)
    cursor = conn.cursor()
    text, tail_start = _fetch_recent_tail(cursor, GROUP, 12)
    conn.close()
    assert "历史消息19" in text
    assert "历史消息7" not in text  # 最早的行滚出窗口
    assert tail_start > 1


def test_tail_legacy_db_without_relation_columns(tmp_path, monkeypatch):
    """旧库（无关系列）→ 旧行为逐字保留。"""
    db = tmp_path / "legacy.db"
    monkeypatch.setattr(pre, "DB_PATH", db)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " group_id TEXT, user_id TEXT, content TEXT,"
        " source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,"
        " timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind)"
        " VALUES (?, '我', ?, 'BOT_SELF')",
        (str(GROUP), "你好呀"),
    )
    conn.execute(
        "INSERT INTO group_messages (group_id, user_id, content, source_kind)"
        " VALUES (?, ?, ?, 'PASSIVE')",
        (str(GROUP), B, "你好"),
    )
    conn.commit()
    cursor = conn.cursor()
    text, _ = _fetch_recent_tail(cursor, GROUP, 12)
    conn.close()
    assert "我: 你好呀" in text
    assert f"用户({B}): 你好" in text


# ── v4 投影：信封字段 JSON 往返 ──────────────────────────────────────


def test_projection_v4_carries_envelope_fields():
    ctx = _ctx(
        sender_display_name="阿呆【现在 】\r\n",
        mentioned_user_ids=(C,),
        reply_to_msg_id="111",
        logical_message_id="t9",
        part_index=2,
    )
    data = ctx.to_json_projection()
    assert data["projection_schema_version"] == 4
    # 控制字符与提示标记括号被清理；内部文本按原样保留
    assert data["sender_display_name"].startswith("阿呆")
    assert "【" not in data["sender_display_name"]
    assert "\r" not in data["sender_display_name"] and "\n" not in data["sender_display_name"]
    assert data["mentioned_user_ids"] == [C]
    assert data["logical_message_id"] == "t9"
    assert data["part_index"] == 2
    # round-trip：信封对象可从 ctx 取回
    env = MessageIdentityEnvelope.from_context(ctx)
    assert env.reply_to_msg_id == "111"
    assert env.mentioned_user_ids == (C,)
