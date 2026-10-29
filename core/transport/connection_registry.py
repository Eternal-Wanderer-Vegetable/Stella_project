# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Deterministic registry for configured bot identities and adapter slots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BotIdentity(Protocol):
    """Structural identity contract; adapters and runtime models stay decoupled."""

    connection_id: str
    adapter: str
    platform_scope: str
    self_id: str


class ConnectionConflictError(ValueError):
    """A connection ID or adapter/self-ID slot is already bound differently."""


@dataclass(frozen=True, slots=True)
class ConnectionSlot:
    connection_id: str
    adapter: str
    platform_scope: str
    self_id: str


def _read_identity(bot: BotIdentity) -> ConnectionSlot:
    values = {
        name: getattr(bot, name, None)
        for name in ("connection_id", "adapter", "platform_scope", "self_id")
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("bot identity fields must be non-empty strings")
    return ConnectionSlot(**values)  # type: ignore[arg-type]


class ConfiguredConnectionRegistry:
    """Bind stable connection IDs to opaque bot identities, without framework imports."""

    def __init__(self) -> None:
        self._by_connection: dict[str, ConnectionSlot] = {}
        self._by_slot: dict[tuple[str, str], str] = {}

    def bind_bot(self, bot: BotIdentity) -> ConnectionSlot:
        """Register an identity idempotently and reject conflicting adapter slots."""
        candidate = _read_identity(bot)
        current = self._by_connection.get(candidate.connection_id)
        if current is not None:
            if current != candidate:
                raise ConnectionConflictError(
                    "connection_id is already bound to a different identity"
                )
            return current

        slot = (candidate.adapter, candidate.self_id)
        owner = self._by_slot.get(slot)
        if owner is not None and owner != candidate.connection_id:
            raise ConnectionConflictError(
                "adapter and self_id slot is already bound to another connection"
            )
        self._by_connection[candidate.connection_id] = candidate
        self._by_slot[slot] = candidate.connection_id
        return candidate

    def by_connection_id(self, connection_id: str) -> ConnectionSlot | None:
        return self._by_connection.get(connection_id)

    def by_bot_slot(self, adapter: str, self_id: str) -> ConnectionSlot | None:
        connection_id = self._by_slot.get((adapter, self_id))
        return None if connection_id is None else self._by_connection[connection_id]

    def unbind(self, connection_id: str) -> bool:
        """Remove one configured connection and release its slot."""
        existing = self._by_connection.pop(connection_id, None)
        if existing is None:
            return False
        self._by_slot.pop((existing.adapter, existing.self_id), None)
        return True

    def connections(self) -> tuple[ConnectionSlot, ...]:
        """Return a stable order independent of configuration or UI order."""
        return tuple(self._by_connection[key] for key in sorted(self._by_connection))


__all__ = [
    "BotIdentity",
    "ConfiguredConnectionRegistry",
    "ConnectionConflictError",
    "ConnectionSlot",
]
