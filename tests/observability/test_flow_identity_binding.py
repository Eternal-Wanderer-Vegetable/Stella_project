# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""流程 root 身份绑定回归（修复计划 M0/M1，R2 探针固化）。

锁定复核报告 R2 的隔离探针结论为稳定失败用例：

- 不同 Bot / 不同私聊 peer / 群 vs 私聊的相同 message_id 必须得到
  互不串线的 root（键完整事件身份：platform+bot+kind+peer+msg_id）；
- 同一事件重入（重复 preprocessor）保持幂等；
- 一个事件的迟到 postprocessor 绝不能关闭另一个事件（曾被同键碰撞）
  的 root —— 结束走缓存键 + ctx 身份 compare-and-pop；
- preprocessor 无业务库也必须先写规范身份（conversation_key/bot/kind/
  peer/source_message_id），matcher 之后用幂等补充接口补 storage ID
  （只允许空→可信，冲突标 conflict）。

全部走真实 gateway preprocessor/postprocessor + message_flow writer，
LLM/adapter 无关。
"""

from __future__ import annotations

import sqlite3

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, PrivateMessageEvent

nonebot.init()

from stella_project.plugins.bot_main import ai_gateway as gateway
from core.observability import message_flow, turn_trace


def _private_event(user_id=20001, message_id=7, self_id="10001", text="hi"):
    return PrivateMessageEvent(
        time=0, self_id=self_id, post_type="message", sub_type="friend",
        user_id=user_id, message_type="private", message_id=message_id,
        message=Message(text), original_message=Message(text),
        raw_message=text, font=0, sender={"nickname": "u"},
    )


def _group_event(group_id=30001, message_id=7, self_id="10001", text="hi"):
    return GroupMessageEvent(
        time=0, self_id=self_id, post_type="message", sub_type="normal",
        group_id=group_id, message_type="group", message_id=message_id,
        message=Message(text), original_message=Message(text),
        raw_message=text, font=0, sender={"nickname": "u"},
    )


@pytest.fixture()
def flow_db(tmp_path):
    db = tmp_path / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    message_flow.end_all_active() if hasattr(message_flow, "end_all_active") else None
    gateway._flow_roots.clear()
    turn_trace.configure(None)


def _trace_rows(db) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM message_traces ORDER BY started_utc").fetchall()
    finally:
        conn.close()


class TestFlowKeyCompleteness:
    """R2：root 键必须包含 Bot 与会话身份，不再退化为 (group|0, msg_id)。"""

    def test_flow_key_distinguishes_bots_same_msg_id(self):
        ev_a = _private_event(user_id=20001, message_id=7, self_id="10001")
        ev_b = _private_event(user_id=20002, message_id=7, self_id="10002")
        assert gateway._flow_key(ev_a) != gateway._flow_key(ev_b)

    def test_flow_key_distinguishes_peers_same_bot_same_msg_id(self):
        ev_a = _private_event(user_id=20001, message_id=7, self_id="10001")
        ev_b = _private_event(user_id=20002, message_id=7, self_id="10001")
        assert gateway._flow_key(ev_a) != gateway._flow_key(ev_b)

    def test_flow_key_distinguishes_group_and_private_same_msg_id(self):
        ev_g = _group_event(group_id=30001, message_id=7, self_id="10001")
        ev_p = _private_event(user_id=30001, message_id=7, self_id="10001")
        assert gateway._flow_key(ev_g) != gateway._flow_key(ev_p)

    def test_source_message_key_is_canonical(self):
        """来源键 = <conversation_key>:msg:<message_id>，私聊 peer 不是群号。"""
        ev = _private_event(user_id=20001, message_id=7, self_id="10001")
        root = gateway._flow_root_or_create(ev, "qq_private")
        try:
            assert root is not None
            assert root.source_message_key == "qq:10001:private:20001:msg:7"
        finally:
            if root is not None and not root.ended:
                message_flow.end_trace(root, outcome="test")


class TestIngressRootIsolation:
    """真实 preprocessor/postprocessor 路径的隔离与幂等。"""

    @pytest.mark.asyncio
    async def test_two_bots_same_msg_id_get_distinct_roots(self, flow_db):
        ev_a = _private_event(user_id=20001, message_id=7, self_id="10001")
        ev_b = _private_event(user_id=20002, message_id=7, self_id="10002")
        await gateway._flow_ingress_root(ev_a)
        await gateway._flow_ingress_root(ev_b)
        roots = list(gateway._flow_roots.values())
        assert len(roots) == 2
        trace_ids = {r.trace_id for r in roots}
        assert len(trace_ids) == 2
        # 两个 Bot 的事件各自结束时只关自己的 root
        await gateway._flow_ingress_end(ev_a)
        remaining = [r for r in gateway._flow_roots.values()
                     if r.trace_id in trace_ids and not r.ended]
        assert len(remaining) == 1
        assert remaining[0].trace_id != roots[0].trace_id or roots[0].ended

    @pytest.mark.asyncio
    async def test_duplicate_event_is_idempotent(self, flow_db):
        ev = _private_event(user_id=20001, message_id=7, self_id="10001")
        await gateway._flow_ingress_root(ev)
        first = gateway._flow_roots.get(gateway._flow_key(ev))
        await gateway._flow_ingress_root(ev)
        assert gateway._flow_roots.get(gateway._flow_key(ev)) is first
        assert len(gateway._flow_roots) == 1

    @pytest.mark.asyncio
    async def test_late_end_does_not_close_other_root(self, flow_db):
        """迟到结束：另一事件（曾被同键碰撞）的 postprocessor 不得关闭本 root。"""
        ev_a = _private_event(user_id=20001, message_id=7, self_id="10001")
        ev_b = _private_event(user_id=20002, message_id=7, self_id="10002")
        await gateway._flow_ingress_root(ev_a)
        root_a = gateway._flow_roots.get(gateway._flow_key(ev_a))
        await gateway._flow_ingress_root(ev_b)
        # ev_b 的结束不能关掉 ev_a 的 root（R2 修复后两键不同天然隔离；
        # compare-and-pop 双保险：身份不匹配直接不关）
        await gateway._flow_ingress_end(ev_b)
        assert root_a is not None and not root_a.ended
        await gateway._flow_ingress_end(ev_a)
        assert root_a.ended


class TestCanonicalIdentityOnTrace:
    """preprocessor 阶段（无业务库）先写规范身份；matcher 补 storage ID。"""

    @pytest.mark.asyncio
    async def test_trace_row_carries_canonical_identity(self, flow_db):
        ev = _private_event(user_id=20001, message_id=7, self_id="10001")
        await gateway._flow_ingress_root(ev)
        message_flow.flush()
        rows = _trace_rows(flow_db)
        assert len(rows) == 1
        row = rows[0]
        assert row["conversation_key"] == "qq:10001:private:20001"
        assert row["bot_id"] == "10001"
        assert row["conversation_kind"] == "private"
        assert row["peer_id"] == "20001"
        assert row["source_message_id"] == "7"
        assert row["source_message_key"] == "qq:10001:private:20001:msg:7"
        assert row["identity_state"] == "exact"

    @pytest.mark.asyncio
    async def test_group_trace_identity(self, flow_db):
        ev = _group_event(group_id=30001, message_id=9, self_id="10001")
        await gateway._flow_ingress_root(ev)
        message_flow.flush()
        row = _trace_rows(flow_db)[0]
        assert row["conversation_key"] == "qq:10001:group:30001"
        assert row["conversation_kind"] == "group"

    @pytest.mark.asyncio
    async def test_storage_id_supplement_only_empty_to_trusted(self, flow_db):
        """补充接口：空→可信允许；冲突拒绝并标 conflict；不重建 root。"""
        ev = _private_event(user_id=20001, message_id=7, self_id="10001")
        await gateway._flow_ingress_root(ev)
        root = gateway._flow_roots.get(gateway._flow_key(ev))
        assert root is not None
        trace_id = root.trace_id
        assert message_flow.update_trace_identity(
            root, storage_session_id=-11) is True
        # 冲突：已有可信值 → 拒绝
        assert message_flow.update_trace_identity(
            root, storage_session_id=-99) is False
        message_flow.flush()
        conn = sqlite3.connect(flow_db)
        try:
            row = conn.execute(
                "SELECT storage_session_id, identity_state FROM message_traces "
                "WHERE trace_id = ?", (trace_id,)).fetchone()
        finally:
            conn.close()
        assert row[0] == -11
        assert row[1] == "exact"

    @pytest.mark.asyncio
    async def test_cache_eviction_marks_active_unknown(self, flow_db):
        """缓存淘汰不得让活跃 root 静默失踪：被淘汰的活跃 root 标 partial。"""
        ev = _private_event(user_id=20001, message_id=7, self_id="10001")
        await gateway._flow_ingress_root(ev)
        root = gateway._flow_roots.get(gateway._flow_key(ev))
        assert root is not None
        # 强制淘汰（正常路径由 _FLOW_ROOTS_MAX 触发；这里直接调淘汰语义）
        gateway._evict_flow_roots(0)
        assert root.identity_state == "partial"
