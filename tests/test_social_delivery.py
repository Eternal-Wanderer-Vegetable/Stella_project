# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""投递回执闭环（core/social/delivery.py + memory/social_store.py）的行为测试。

覆盖计划 §8.1 投递矩阵：第 1 段成功第 2 段失败 → partial（评估只用已发部分）；
全失败 → 不产生可评估事实；回执幂等落库；平台 ID 反查。
测试使用临时库（monkeypatch config.DB_PATH），假适配器，禁止连接生产机器人。
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from core.social.contracts import (
    AGGREGATE_PARTIAL,
    ConversationScope,
    DeliveryReceipt,
    aggregate_delivery_status,
    delivered_texts,
)
from core.social.delivery import (
    DeliveryPlanError,
    coerce_platform_message_id,
    create_delivery_draft,
    deliver_lines,
    delivery_draft_from_context,
    seal_delivery_plan,
)
from memory import social_store


@pytest.fixture()
def social_db(tmp_path, monkeypatch):
    """每个用例独立的社交旁表库（借 conftest 的 STELLA_HOME 隔离）。"""
    from config import settings

    db = tmp_path / "social.db"
    monkeypatch.setattr(settings, "DB_PATH", db)
    from memory import social_schema

    social_schema.ensure_social_schema(db, backup=False)
    monkeypatch.setattr(social_store, "_TABLES_READY", False)
    yield db
    social_store._TABLES_READY = False


def _rows(db, sql: str) -> list[tuple]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


class FakeAdapter:
    """假平台适配器：可脚本化的成功/失败/返回值。"""

    def __init__(self, fail_at: set[int] | None = None, ids: bool = True):
        self.fail_at = fail_at or set()
        self.ids = ids
        self.sent: list[str] = []

    async def send(self, line: str, part_index: int) -> str | None:
        if part_index in self.fail_at:
            raise RuntimeError(f"adapter down at {part_index}")
        self.sent.append(line)
        return {"message_id": 10000 + part_index} if self.ids else None


SCOPE = ConversationScope.for_qq(123)


async def _run(lines, adapter, scope=SCOPE, trace="t1", turn="n1"):
    plan = _sealed_plan(lines, trace, turn)
    return await deliver_lines(
        plan, scope=scope, trace_id=trace, turn_id=turn, send_one=adapter.send
    )


def _sealed_plan(lines, trace="t1", turn="n1", conversation_key="qq:10001:group:123"):
    draft = create_delivery_draft(
        trace_id=trace, turn_id=turn, source_kind="model",
        protocol_version="test", disposition="deliver",
        conversation_key=conversation_key, segments=list(lines), decision={"status": "allow"},
    )
    return seal_delivery_plan(draft)


class TestDeliverLines:
    def test_delivery_draft_refuses_unknown_scope_versions(self, monkeypatch):
        from memory import scope_versions

        def unavailable(_keys):
            raise RuntimeError("sqlite unavailable")

        monkeypatch.setattr(scope_versions, "current_versions_strict", unavailable)
        ctx = SimpleNamespace(
            trace_id="scope-trace", turn_id="scope-turn", delivery_source_kind="model",
            reply_disposition="deliver", lines=["safe-looking output"],
            conversation_key="qq:10001:private:7", bot_id="10001", user_id=7,
        )
        draft = delivery_draft_from_context(ctx)
        assert draft["scope_versions_available"] is False
        with pytest.raises(DeliveryPlanError, match="scope version is unavailable"):
            seal_delivery_plan(draft)

    async def test_rejects_unsealed_payload_before_send(self, social_db):
        adapter = FakeAdapter()
        with pytest.raises(DeliveryPlanError):
            await deliver_lines(
                ["未封存文本"], scope=SCOPE, trace_id="t-unsealed",
                turn_id="tn-unsealed", send_one=adapter.send,
            )
        assert adapter.sent == []

    async def test_rejects_plan_mutated_after_seal(self, social_db):
        adapter = FakeAdapter()
        plan = _sealed_plan(["sealed"])
        plan["segments"][0]["text"] = "changed after seal"
        with pytest.raises(ValueError):
            await deliver_lines(
                plan, scope=SCOPE, trace_id="t1", turn_id="n1", send_one=adapter.send,
            )
        assert adapter.sent == []

    async def test_plan_guard_stops_before_next_segment(self, social_db):
        adapter = FakeAdapter()
        checks = iter([True, False])
        receipts = await deliver_lines(
            _sealed_plan(["first", "second"], "t-epoch", "tn-epoch"),
            scope=SCOPE, trace_id="t-epoch", turn_id="tn-epoch",
            send_one=adapter.send, plan_guard=lambda _plan: next(checks),
        )
        assert [r.status for r in receipts] == ["acknowledged"]
        assert adapter.sent == ["first"]

    async def test_plan_and_receipt_digests_are_durable(self, social_db):
        adapter = FakeAdapter()
        plan = _sealed_plan(["linked receipt"], "t-digest", "tn-digest")
        receipts = await deliver_lines(
            plan, scope=SCOPE, trace_id="t-digest", turn_id="tn-digest",
            send_one=adapter.send,
        )
        assert receipts[0].delivery_plan_id == plan["plan_id"]
        assert receipts[0].delivery_plan_digest == plan["digest"]
        assert receipts[0].decision_digest == plan["decision_digest"]
        assert _rows(
            social_db,
            "SELECT plan_digest, decision_digest FROM social_delivery_plans "
            "WHERE turn_id='tn-digest'",
        ) == [(plan["digest"], plan["decision_digest"])]
        assert _rows(
            social_db,
            "SELECT delivery_plan_id, delivery_plan_digest, decision_digest "
            "FROM social_deliveries WHERE turn_id='tn-digest'",
        ) == [(plan["plan_id"], plan["digest"], plan["decision_digest"])]

    async def test_timeout_is_unknown_and_same_turn_cannot_retry(self, social_db):
        plan = _sealed_plan(["may have arrived"], "t-timeout", "tn-timeout")
        attempts = 0

        async def timeout_send(_line, _index):
            nonlocal attempts
            attempts += 1
            raise TimeoutError("platform deadline")

        receipts = await deliver_lines(
            plan, scope=SCOPE, trace_id="t-timeout", turn_id="tn-timeout",
            send_one=timeout_send,
        )
        assert [receipt.status for receipt in receipts] == ["unknown"]
        with pytest.raises(RuntimeError, match="refusing send"):
            await deliver_lines(
                plan, scope=SCOPE, trace_id="t-timeout", turn_id="tn-timeout",
                send_one=timeout_send,
            )
        assert attempts == 1

    async def test_all_acknowledged_with_platform_ids(self, social_db):
        adapter = FakeAdapter()
        receipts = await _run(["第一句", "第二句"], adapter)
        assert [r.status for r in receipts] == ["acknowledged", "acknowledged"]
        assert [r.platform_message_id for r in receipts] == ["10000", "10001"]
        assert delivered_texts(receipts) == ["第一句", "第二句"]
        # 回执已落库（每段一条，短事务）
        rows = _rows(social_db, "SELECT part_index, status, platform_message_id "
                                 "FROM social_deliveries ORDER BY part_index")
        assert rows == [(0, "acknowledged", "10000"), (1, "acknowledged", "10001")]

    async def test_first_ok_second_failed_is_partial_and_stops(self, social_db):
        adapter = FakeAdapter(fail_at={1})
        receipts = await _run(["第一句", "第二句", "第三句"], adapter)
        statuses = [r.status for r in receipts]
        # 第三段没有事实：发送被停止，不产生「未尝试」的回执行
        assert statuses == ["acknowledged", "failed"]
        assert aggregate_delivery_status(statuses) == AGGREGATE_PARTIAL
        assert delivered_texts(receipts) == ["第一句"]
        assert adapter.sent == ["第一句"]

    async def test_all_failed_counts_nothing(self, social_db):
        adapter = FakeAdapter(fail_at={0})
        receipts = await _run(["只有一句"], adapter)
        assert delivered_texts(receipts) == []
        assert aggregate_delivery_status([r.status for r in receipts]) == "failed"

    async def test_send_returns_none_is_still_acknowledged(self, social_db):
        """适配器不回 ID ≠ 没送达：接口接受了就是 accepted，只是没有归因锚点。"""
        adapter = FakeAdapter(ids=False)
        receipts = await _run(["一句"], adapter)
        assert receipts[0].status == "acknowledged"
        assert receipts[0].platform_message_id is None

    async def test_no_scope_skips_persistence(self, tmp_path, social_db):
        adapter = FakeAdapter()
        receipts = await _run(["一句"], adapter, scope=None)
        assert receipts[0].status == "acknowledged"
        # scope=None 不写学习/receipt 行，但最终计划摘要仍然持久化。
        assert _rows(social_db, "SELECT COUNT(*) FROM social_deliveries")[0][0] == 0

    async def test_receipts_are_idempotent_on_replay(self, social_db):
        """重放同 turn 在发网前拒绝，避免重复发送已 ACK 文本。"""
        adapter = FakeAdapter()
        plan = _sealed_plan(["一句"], "t1", "same")
        await deliver_lines(
            plan, scope=SCOPE, trace_id="t1", turn_id="same", send_one=adapter.send,
        )
        adapter2 = FakeAdapter()
        with pytest.raises(RuntimeError, match="refusing send"):
            await deliver_lines(
                plan, scope=SCOPE, trace_id="t1", turn_id="same", send_one=adapter2.send,
            )
        rows = _rows(social_db, "SELECT COUNT(*) FROM social_deliveries")
        assert rows[0][0] == 1
        assert adapter.sent == ["一句"]
        assert adapter2.sent == []


class TestCoercePlatformMessageId:
    def test_onebot_dict(self):
        assert coerce_platform_message_id({"message_id": 12345}) == "12345"

    def test_plain_int(self):
        assert coerce_platform_message_id(42) == "42"

    def test_none_and_garbage(self):
        assert coerce_platform_message_id(None) is None
        assert coerce_platform_message_id("ok") is None
        assert coerce_platform_message_id(True) is None


class TestStrictScopeVersions:
    def test_reads_versions_and_fails_when_table_is_missing(self, tmp_path, monkeypatch):
        from config import settings
        from memory.scope_versions import current_versions_strict

        db = tmp_path / "scope-versions.db"
        monkeypatch.setattr(settings, "DB_PATH", db)
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "CREATE TABLE memory_scope_versions "
                "(scope_key TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at TEXT)"
            )
            conn.execute(
                "INSERT INTO memory_scope_versions(scope_key, version) VALUES ('owner:a', 4)"
            )
            conn.commit()
        finally:
            conn.close()
        assert current_versions_strict(["owner:a", "owner:missing"]) == {
            "owner:a": 4, "owner:missing": 0,
        }
        conn = sqlite3.connect(db)
        try:
            conn.execute("DROP TABLE memory_scope_versions")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(RuntimeError, match="versions are unavailable"):
            current_versions_strict(["owner:a"])


class TestLookup:
    async def test_find_delivery_by_platform_id(self, social_db):
        adapter = FakeAdapter()
        await _run(["被引用的那句"], adapter, turn="turn-a")
        found = social_store.find_delivery_by_platform_id("10000")
        assert found is not None and found["turn_id"] == "turn-a"
        assert social_store.find_delivery_by_platform_id("missing") is None

    def test_deliveries_for_turn_ordered(self, social_db):
        for i, text in enumerate(["a", "b", "c"]):
            social_store.record_delivery(
                DeliveryReceipt(trace_id="t", turn_id="x", part_index=i,
                                status="acknowledged", text=text, scope=SCOPE)
            )
        data = social_store.deliveries_for_turn("x")
        assert [d["text"] for d in data] == ["a", "b", "c"]


class TestNeutralReceipts:
    """修复计划 §6.3（M2）：scope=None + 明确规范身份 → 会话中立回执。

    中立行可查询（流程页输出），但 learning_eligible=0：永远不进群学习、
    不被引用归因反查命中。scope=None 且无身份的旧合同保留（不落库）。
    """

    def _private_ref(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            conversation_key="qq:10001:private:20001",
            conversation_kind="private",
            peer_id="20001",
            storage_session_id=-11,
            bot_id="10001",
        )

    async def test_private_ref_persists_neutral_receipt(self, social_db):
        adapter = FakeAdapter()
        receipts = await deliver_lines(
            _sealed_plan(["私聊第一段"], "t-priv", "tn-priv", "qq:10001:private:20001"),
            scope=None, trace_id="t-priv", turn_id="tn-priv",
            send_one=adapter.send, receipt_conversation=self._private_ref(),
        )
        assert receipts[0].status == "acknowledged"
        rows = _rows(social_db, "SELECT group_id, learning_eligible, "
                                 "conversation_key, conversation_kind, peer_id, "
                                 "storage_session_id FROM social_deliveries")
        assert len(rows) == 1
        group_id, eligible, conv_key, kind, peer, storage = rows[0]
        assert group_id == "", "中立行绝不能带群号"
        assert eligible == 0
        assert (conv_key, kind, peer, storage) == (
            "qq:10001:private:20001", "private", "20001", -11)

    async def test_no_scope_without_ref_still_skips(self, social_db):
        """原 scope=None 合同保留：无明确身份不落库。"""
        adapter = FakeAdapter()
        await deliver_lines(
            _sealed_plan(["一句"], "t-skip", "tn-skip", "qq:test:private:none"),
            scope=None, trace_id="t-skip", turn_id="tn-skip",
            send_one=adapter.send,
        )
        assert _rows(social_db, "SELECT COUNT(*) FROM social_deliveries") == [(0,)]

    async def test_incomplete_identity_does_not_persist(self, social_db):
        """身份不完整（缺 conversation_kind）= 不明确合法：退回不落库。"""
        from types import SimpleNamespace

        adapter = FakeAdapter()
        await deliver_lines(
            _sealed_plan(["一句"], "t-bad", "tn-bad", "qq:10001:private:20001"),
            scope=None, trace_id="t-bad", turn_id="tn-bad",
            send_one=adapter.send,
            receipt_conversation=SimpleNamespace(
                conversation_key="qq:10001:private:20001"),
        )
        assert _rows(social_db, "SELECT COUNT(*) FROM social_deliveries") == [(0,)]

    async def test_neutral_receipt_not_attribution_visible(self, social_db):
        """中立回执对旧仅 ID 反查不可见；歧义（同 ID 多行）返回 None。"""
        from types import SimpleNamespace

        adapter = FakeAdapter()
        await deliver_lines(
            _sealed_plan(["私聊段"], "t-p2", "tn-p2", "qq:10001:private:20001"),
            scope=None, trace_id="t-p2", turn_id="tn-p2",
            send_one=adapter.send,
            receipt_conversation=SimpleNamespace(
                conversation_key="qq:10001:private:20001",
                conversation_kind="private", peer_id="20001",
                storage_session_id=-11),
        )
        # 平台 ID 只有私聊中立行持有：学习口径反查必须 None
        assert social_store.find_delivery_by_platform_id("10000") is None

    async def test_scope_none_neutral_receipt_can_be_ambiguous(self, social_db):
        """同平台 ID 出现在两个群回执 → 反查 None（不猜第一行）。"""
        social_store.record_delivery(DeliveryReceipt(
            trace_id="t", turn_id="a", part_index=0, status="acknowledged",
            text="x", platform_message_id="900",
            scope=ConversationScope.for_qq(1, bot_id="10001")))
        social_store.record_delivery(DeliveryReceipt(
            trace_id="t", turn_id="b", part_index=0, status="acknowledged",
            text="x", platform_message_id="900",
            scope=ConversationScope.for_qq(2, bot_id="10002")))
        assert social_store.find_delivery_by_platform_id("900") is None
        # scoped 反查仍可精确命中
        found = social_store.find_delivery_by_platform_id(
            "900", scope=ConversationScope.for_qq(1, bot_id="10001"))
        assert found is not None and found["turn_id"] == "a"


class TestRealConversationRefNeutralReceipt:
    """验收报告 H1：真实 ConversationRef（字段名 kind/platform/bot_id）经过
    deliver_lines → record_delivery 的完整链路必须落中立回执。

    旧实现读 conversation_kind（SimpleNamespace 形状），真实 ref 字段缺失
    → 身份被清空 → scope=None 时不落库——真实库 20/20 私聊「已发送、无
    回执」即此断点。本组用例用生产工厂对象覆盖该形状。
    """

    def _real_ref(self):
        from core.conversation import qq_private_ref

        return qq_private_ref("10001", 20001, storage_session_id=-11)

    async def test_real_ref_persists_neutral_receipt(self, social_db):
        adapter = FakeAdapter()
        receipts = await deliver_lines(
            _sealed_plan(["私聊第一段"], "t-real", "tn-real", "qq:10001:private:20001"),
            scope=None, trace_id="t-real", turn_id="tn-real",
            send_one=adapter.send, receipt_conversation=self._real_ref(),
        )
        assert receipts[0].status == "acknowledged"
        rows = _rows(social_db, "SELECT platform, bot_id, group_id, "
                                 "learning_eligible, conversation_key, "
                                 "conversation_kind, peer_id, storage_session_id "
                                 "FROM social_deliveries")
        assert len(rows) == 1, "真实 ref 必须落中立回执（H1 断点）"
        (platform, bot_id, group_id, eligible, conv_key, kind, peer,
         storage) = rows[0]
        assert (platform, bot_id) == ("qq", "10001"), "中立行保留平台/Bot 归属"
        assert group_id == "" and eligible == 0
        assert (conv_key, kind, peer, storage) == (
            "qq:10001:private:20001", "private", "20001", -11)

    async def test_real_ref_failed_segment_still_persisted(self, social_db):
        """失败片段同样有中立存档事实（部分发送场景）。"""
        adapter = FakeAdapter(fail_at={1})
        await deliver_lines(
            _sealed_plan(["第一段", "第二段"], "t-rf", "tn-rf", "qq:10001:private:20001"),
            scope=None, trace_id="t-rf", turn_id="tn-rf",
            send_one=adapter.send, receipt_conversation=self._real_ref(),
        )
        rows = _rows(social_db, "SELECT part_index, status FROM social_deliveries "
                                "ORDER BY part_index")
        assert rows == [(0, "acknowledged"), (1, "failed")]

    async def test_real_ref_never_attribution_visible(self, social_db):
        """中立回执对学习口径反查不可见（platform/bot 归属不改变 eligibility）。"""
        adapter = FakeAdapter()
        await deliver_lines(
            _sealed_plan(["私聊段"], "t-ra", "tn-ra", "qq:10001:private:20001"),
            scope=None, trace_id="t-ra", turn_id="tn-ra",
            send_one=adapter.send, receipt_conversation=self._real_ref(),
        )
        assert social_store.find_delivery_by_platform_id("10000") is None
        assert social_store.deliveries_for_turn("tn-ra", learning_eligible=True) == []
