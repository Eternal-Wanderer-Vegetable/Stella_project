# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Versioned transport message events keep opaque IDs and safe relations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.transport.message_event import (
    MessageEventV1,
    MessagePartV1,
    MessageRelationV1,
)


def test_event_preserves_opaque_ids_component_order_and_normalizes_time_to_utc():
    local_time = datetime(2026, 10, 25, 20, tzinfo=timezone(timedelta(hours=8)))
    event = MessageEventV1(
        platform_message_id="007:雪",
        occurred_at=local_time,
        components=(MessagePartV1("text", text="hello"), MessagePartV1("image", attachment_ref="attachment:abc")),
        relations=(MessageRelationV1("reply", target_message_id="message/001"),),
    )

    assert event.platform_message_id == "007:雪"
    assert event.occurred_at == datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    assert [part.kind for part in event.components] == ["text", "image"]
    assert event.relations[0].target_message_id == "message/001"


def test_event_rejects_naive_times_raw_attachment_urls_and_delete_bodies():
    with pytest.raises(ValueError, match="timezone-aware"):
        MessageEventV1("opaque", datetime(2026, 10, 25))
    with pytest.raises(ValueError, match="controlled attachment"):
        MessagePartV1("file", attachment_ref="https://host/signed?token=secret")
    with pytest.raises(ValueError, match="must not retain"):
        MessageEventV1(
            "opaque",
            datetime(2026, 10, 25, tzinfo=timezone.utc),
            components=(MessagePartV1("text", text="body"),),
            event_kind="delete",
        )


def test_relations_preserve_unresolved_targets_without_cross_conversation_assumptions():
    relation = MessageRelationV1(
        "reply",
        target_message_id="reply:前导零007",
        target_connection_id="connection:two",
        target_conversation_key="opaque/scene",
    )
    assert relation.resolved is False
    with pytest.raises(ValueError, match="opaque target message ID"):
        MessageRelationV1("quote")
