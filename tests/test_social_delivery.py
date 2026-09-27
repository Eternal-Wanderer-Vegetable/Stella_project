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

import pytest

from core.social.contracts import (
    AGGREGATE_PARTIAL,
    ConversationScope,
    DeliveryReceipt,
    aggregate_delivery_status,
    delivered_texts,
)
from core.social.delivery import coerce_platform_message_id, deliver_lines
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
    return await deliver_lines(
        lines, scope=scope, trace_id=trace, turn_id=turn, send_one=adapter.send
    )


class TestDeliverLines:
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
        # 总开关关闭（scope=None）：不写任何行
        assert _rows(social_db, "SELECT COUNT(*) FROM social_deliveries")[0][0] == 0

    async def test_receipts_are_idempotent_on_replay(self, social_db):
        """补偿重放同 turn/片段不允许产生第二行事实。"""
        adapter = FakeAdapter()
        await _run(["一句"], adapter, turn="same")
        adapter2 = FakeAdapter()
        await _run(["一句"], adapter2, turn="same")
        rows = _rows(social_db, "SELECT COUNT(*) FROM social_deliveries")
        assert rows[0][0] == 1
        # 幂等重放绝不再次调用网络 send——第一次调用有真实回执，第二次只是补账
        assert adapter2.sent == ["一句"]


class TestCoercePlatformMessageId:
    def test_onebot_dict(self):
        assert coerce_platform_message_id({"message_id": 12345}) == "12345"

    def test_plain_int(self):
        assert coerce_platform_message_id(42) == "42"

    def test_none_and_garbage(self):
        assert coerce_platform_message_id(None) is None
        assert coerce_platform_message_id("ok") is None
        assert coerce_platform_message_id(True) is None


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
