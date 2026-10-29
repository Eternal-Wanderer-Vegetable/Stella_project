# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Connection registry identity remains stable and rejects ambiguous bot slots."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from core.transport.connection_registry import (
    ConfiguredConnectionRegistry,
    ConnectionConflictError,
)


@dataclass(frozen=True)
class Identity:
    connection_id: str
    adapter: str
    platform_scope: str
    self_id: str


def test_registry_is_idempotent_and_opaque_ids_survive_reordering():
    registry = ConfiguredConnectionRegistry()
    a = Identity("connection-a", "telegram", "telegram", "007:雪")
    b = Identity("connection-b", "discord", "discord", "007:雪")

    assert registry.bind_bot(a) == registry.bind_bot(a)
    registry.bind_bot(b)
    assert registry.by_connection_id("connection-a").self_id == "007:雪"
    assert registry.by_bot_slot("telegram", "007:雪").connection_id == "connection-a"
    assert [item.connection_id for item in registry.connections()] == [
        "connection-a",
        "connection-b",
    ]


def test_registry_rejects_a_second_connection_for_the_same_adapter_slot():
    registry = ConfiguredConnectionRegistry()
    registry.bind_bot(Identity("connection-a", "telegram", "telegram", "007"))
    with pytest.raises(ConnectionConflictError, match="slot"):
        registry.bind_bot(Identity("connection-b", "telegram", "other-scope", "007"))


def test_registry_rejects_rebinding_a_connection_id_to_another_identity():
    registry = ConfiguredConnectionRegistry()
    registry.bind_bot(Identity("connection-a", "telegram", "telegram", "007"))
    with pytest.raises(ConnectionConflictError, match="connection_id"):
        registry.bind_bot(Identity("connection-a", "telegram", "telegram", "008"))


def test_unbind_releases_slot_without_changing_other_connections():
    registry = ConfiguredConnectionRegistry()
    registry.bind_bot(Identity("connection-a", "telegram", "telegram", "007"))
    assert registry.unbind("connection-a") is True
    assert registry.unbind("connection-a") is False
    assert registry.by_bot_slot("telegram", "007") is None
    registry.bind_bot(Identity("connection-b", "telegram", "telegram", "007"))
    assert registry.by_connection_id("connection-b") is not None
