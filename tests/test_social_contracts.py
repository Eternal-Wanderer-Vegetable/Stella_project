# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""社交契约（core/social/contracts.py）的行为测试：计划 §6.1。"""

from __future__ import annotations

import pytest

from core.social.contracts import (
    AGGREGATE_COMPLETE,
    AGGREGATE_FAILED,
    AGGREGATE_PARTIAL,
    AGGREGATE_UNKNOWN,
    DELIVERY_ACKNOWLEDGED,
    DELIVERY_FAILED,
    DELIVERY_UNKNOWN,
    ConversationScope,
    DeliveryReceipt,
    MessageEvidence,
    aggregate_delivery_status,
    content_hash,
    delivered_texts,
    parse_utc,
    utc_now_iso,
)


class TestConversationScope:
    def test_qq_scope_key_contains_all_three_axes(self):
        scope = ConversationScope.for_qq(123, bot_id=456)
        assert scope.key == "qq:456:123"

    def test_same_group_different_bot_is_different_scope(self):
        a = ConversationScope.for_qq(123, bot_id=1)
        b = ConversationScope.for_qq(123, bot_id=2)
        assert a.key != b.key

    def test_empty_group_or_platform_rejected(self):
        with pytest.raises(ValueError):
            ConversationScope(platform="qq", bot_id="", group_id="")
        with pytest.raises(ValueError):
            ConversationScope(platform="", bot_id="", group_id="123")


class TestMessageEvidence:
    def test_defaults_are_stable_and_complete(self):
        scope = ConversationScope.for_qq(1)
        ev = MessageEvidence(scope=scope, user_id="u1", text_excerpt="hello 世界")
        ev2 = MessageEvidence(scope=scope, user_id="u1", text_excerpt="hello 世界")
        # event_id 恒为独立 UUID：无平台 ID 的事件绝不共享唯一键
        assert ev.event_id and ev2.event_id and ev.event_id != ev2.event_id
        assert ev.content_hash == content_hash("hello 世界")
        assert parse_utc(ev.received_at_utc) is not None

    def test_explicit_event_id_is_preserved(self):
        ev = MessageEvidence(scope=ConversationScope.for_qq(1), event_id="fixed")
        assert ev.event_id == "fixed"

    def test_text_excerpt_is_capped(self):
        ev = MessageEvidence(scope=ConversationScope.for_qq(1), text_excerpt="x" * 500)
        assert len(ev.text_excerpt) == 200


class TestDeliveryAggregate:
    def test_all_acknowledged_is_complete(self):
        assert aggregate_delivery_status([DELIVERY_ACKNOWLEDGED] * 3) == AGGREGATE_COMPLETE

    def test_mixed_ack_and_failed_is_partial(self):
        assert (
            aggregate_delivery_status([DELIVERY_ACKNOWLEDGED, DELIVERY_FAILED])
            == AGGREGATE_PARTIAL
        )

    def test_mixed_ack_and_unknown_is_partial(self):
        assert (
            aggregate_delivery_status([DELIVERY_ACKNOWLEDGED, DELIVERY_UNKNOWN])
            == AGGREGATE_PARTIAL
        )

    def test_all_failed_is_failed(self):
        assert aggregate_delivery_status([DELIVERY_FAILED] * 2) == AGGREGATE_FAILED

    def test_all_unknown_is_unknown_never_failed_success(self):
        # unknown 不是失败也不许伪装成功
        assert aggregate_delivery_status([DELIVERY_UNKNOWN, DELIVERY_UNKNOWN]) == AGGREGATE_UNKNOWN

    def test_empty_is_failed(self):
        assert aggregate_delivery_status([]) == AGGREGATE_FAILED


class TestDeliveredTexts:
    def test_only_acknowledged_segments_in_order(self):
        scope = ConversationScope.for_qq(1)
        r0 = DeliveryReceipt(trace_id="t", turn_id="n", part_index=0, status=DELIVERY_ACKNOWLEDGED,
                             text="第一句", scope=scope)
        r1 = DeliveryReceipt(trace_id="t", turn_id="n", part_index=1, status=DELIVERY_FAILED,
                             text="没发出去", scope=scope)
        r2 = DeliveryReceipt(trace_id="t", turn_id="n", part_index=2, status=DELIVERY_ACKNOWLEDGED,
                             text="第三句", scope=scope)
        assert delivered_texts([r2, r0, r1]) == ["第一句", "第三句"]

    def test_receipt_text_hash_defaults(self):
        r = DeliveryReceipt(trace_id="t", turn_id="n", part_index=0, text="abc")
        assert r.text_hash == content_hash("abc")
        assert not r.delivered

    def test_utc_now_iso_parse_roundtrip(self):
        assert parse_utc(utc_now_iso()) is not None
