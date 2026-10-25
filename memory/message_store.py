# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Append-only persistence and effective projection for transport message events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from core.transport.message_event import MessageEventV1

TRANSPORT_MESSAGE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS transport_message_events (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    conversation_key TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    event_kind TEXT NOT NULL CHECK (event_kind IN ('create', 'edit', 'delete')),
    platform_message_id TEXT NOT NULL,
    platform_revision_id TEXT,
    local_event_id TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    legacy_row_id INTEGER,
    availability TEXT NOT NULL DEFAULT 'available'
        CHECK (availability IN ('available', 'deleted')),
    payload_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE (
        connection_id, conversation_key, direction, event_kind,
        platform_message_id, dedupe_key
    )
)
"""

TRANSPORT_MESSAGE_PARTS_DDL = """
CREATE TABLE IF NOT EXISTS transport_message_parts (
    event_id TEXT NOT NULL,
    part_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    safe_payload_json TEXT NOT NULL,
    PRIMARY KEY (event_id, part_index),
    FOREIGN KEY (event_id) REFERENCES transport_message_events(event_id)
        ON DELETE CASCADE
)
"""

TRANSPORT_MESSAGE_RELATIONS_DDL = """
CREATE TABLE IF NOT EXISTS transport_message_relations (
    relation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    relation_index INTEGER NOT NULL,
    relation_kind TEXT NOT NULL,
    target_connection_id TEXT,
    target_conversation_key TEXT,
    target_message_id TEXT,
    subject_key TEXT,
    resolution_status TEXT NOT NULL CHECK (resolution_status IN ('resolved', 'unresolved')),
    UNIQUE (event_id, relation_index),
    FOREIGN KEY (event_id) REFERENCES transport_message_events(event_id)
        ON DELETE CASCADE
)
"""

TRANSPORT_MESSAGE_EVENT_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_transport_message_lookup "
    "ON transport_message_events "
    "(connection_id, conversation_key, direction, platform_message_id, event_seq)",
    "CREATE INDEX IF NOT EXISTS idx_transport_message_legacy_row "
    "ON transport_message_events (legacy_row_id) WHERE legacy_row_id IS NOT NULL",
)


def create_message_store_tables(conn: sqlite3.Connection) -> None:
    """Create the additive transport message tables and indexes idempotently."""
    conn.execute(TRANSPORT_MESSAGE_EVENTS_DDL)
    conn.execute(TRANSPORT_MESSAGE_PARTS_DDL)
    conn.execute(TRANSPORT_MESSAGE_RELATIONS_DDL)
    for ddl in TRANSPORT_MESSAGE_EVENT_INDEXES:
        conn.execute(ddl)


def _safe_part_payload(part) -> str:
    # The DTO intentionally has no SDK object, raw URL, or arbitrary payload field.
    payload = {
        "text": part.text,
        "subject_key": part.subject_key,
        "display_name": part.display_name,
        "mime_type": part.mime_type,
        "size_bytes": part.size_bytes,
        "attachment_ref": part.attachment_ref,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class ExistingMessageEvent:
    event_id: str
    legacy_row_id: int | None


def event_dedupe_key(event: MessageEventV1) -> str:
    """Build an exact transport identity; unversioned edits remain distinct."""
    if event.event_kind == "edit":
        if event.platform_revision_id:
            return f"revision:{event.platform_revision_id}"
        # Adapters without revision IDs cannot promise edit deduplication.
        return f"local:{uuid.uuid4().hex}"
    if event.event_kind == "delete" and event.platform_revision_id:
        return f"revision:{event.platform_revision_id}"
    # A create and an unversioned delete are idempotent by the trusted message ID.
    return "stable-message"


def find_existing_event(
    conn: sqlite3.Connection,
    *,
    connection_id: str,
    conversation_key: str,
    direction: str,
    event: MessageEventV1,
    dedupe_key: str,
) -> ExistingMessageEvent | None:
    row = conn.execute(
        "SELECT event_id, legacy_row_id FROM transport_message_events "
        "WHERE connection_id = ? AND conversation_key = ? AND direction = ? "
        "AND event_kind = ? AND platform_message_id = ? AND dedupe_key = ?",
        (
            connection_id,
            conversation_key,
            direction,
            event.event_kind,
            event.platform_message_id,
            dedupe_key,
        ),
    ).fetchone()
    if row is None:
        return None
    return ExistingMessageEvent(
        str(row[0]), int(row[1]) if row[1] is not None else None
    )


def append_message_event(
    conn: sqlite3.Connection,
    *,
    connection_id: str,
    conversation_key: str,
    direction: str,
    event: MessageEventV1,
    legacy_row_id: int | None,
    dedupe_key: str,
) -> str:
    """Append event metadata and safe component/relation rows in the caller's transaction."""
    event_id = uuid.uuid4().hex
    local_event_id = uuid.uuid4().hex
    availability = "deleted" if event.event_kind == "delete" else "available"
    conn.execute(
        "INSERT INTO transport_message_events ("
        "event_id, conversation_key, connection_id, direction, event_kind, "
        "platform_message_id, platform_revision_id, local_event_id, dedupe_key, "
        "occurred_at, legacy_row_id, availability, payload_version"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            conversation_key,
            connection_id,
            direction,
            event.event_kind,
            event.platform_message_id,
            event.platform_revision_id,
            local_event_id,
            dedupe_key,
            event.occurred_at.isoformat(),
            legacy_row_id,
            availability,
            event.version,
        ),
    )
    if event.event_kind != "delete":
        conn.executemany(
            "INSERT INTO transport_message_parts "
            "(event_id, part_index, kind, safe_payload_json) VALUES (?, ?, ?, ?)",
            [
                (event_id, index, part.kind, _safe_part_payload(part))
                for index, part in enumerate(event.components)
            ],
        )
    conn.executemany(
        "INSERT INTO transport_message_relations ("
        "relation_id, event_id, relation_index, relation_kind, target_connection_id, "
        "target_conversation_key, target_message_id, subject_key, resolution_status"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                uuid.uuid4().hex,
                event_id,
                index,
                relation.kind,
                relation.target_connection_id,
                relation.target_conversation_key,
                relation.target_message_id,
                relation.subject_key,
                "resolved" if relation.resolved else "unresolved",
            )
            for index, relation in enumerate(event.relations)
        ],
    )
    return event_id


def mark_source_unavailable(
    conn: sqlite3.Connection,
    *,
    conversation_key: str,
    connection_id: str,
    direction: str,
    platform_message_id: str,
) -> int:
    """Mark deleted-source evidence unavailable and invalidate its owner caches."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_evidence'"
    ).fetchone()
    if exists is None:
        return 0
    evidence_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(memory_evidence)").fetchall()
    }
    owner_keys: list[str] = []
    if "owner_key" in evidence_columns:
        owner_keys = [
            str(row[0])
            for row in conn.execute(
                "SELECT DISTINCT owner_key FROM memory_evidence "
                "WHERE source_conversation_key = ? "
                "AND source_row_id IN (SELECT legacy_row_id "
                "FROM transport_message_events WHERE connection_id = ? "
                "AND conversation_key = ? AND direction = ? "
                "AND platform_message_id = ? AND legacy_row_id IS NOT NULL)",
                (
                    conversation_key,
                    connection_id,
                    conversation_key,
                    direction,
                    platform_message_id,
                ),
            ).fetchall()
            if row[0]
        ]
    cursor = conn.execute(
        "UPDATE memory_evidence SET verification_status = 'source_unavailable' "
        "WHERE source_conversation_key = ? "
        "AND source_row_id IN (SELECT legacy_row_id FROM transport_message_events "
        "WHERE connection_id = ? AND conversation_key = ? AND direction = ? "
        "AND platform_message_id = ? AND legacy_row_id IS NOT NULL)",
        (
            conversation_key,
            connection_id,
            conversation_key,
            direction,
            platform_message_id,
        ),
    )
    changed = int(cursor.rowcount)
    if changed and owner_keys:
        from memory.scope_versions import bump

        for owner_key in owner_keys:
            bump(owner_key, conn=conn, strict=True)
    return changed


def effective_history(
    conn: sqlite3.Connection,
    *,
    connection_id: str,
    conversation_key: str,
) -> list[sqlite3.Row | tuple]:
    """Return latest live source rows plus legacy rows with no transport event.

    Latest is defined by local append order, never by comparing opaque revision IDs or
    wall-clock timestamps. The identity key always includes connection and conversation.
    """
    row_cursor = conn.execute(
        "SELECT * FROM group_messages WHERE connection_id = ? "
        "AND conversation_key = ? ORDER BY id",
        (connection_id, conversation_key),
    )
    column_names = [column[0] for column in row_cursor.description or ()]
    rows = row_cursor.fetchall()
    events = conn.execute(
        "SELECT event_seq, direction, platform_message_id, event_kind, legacy_row_id "
        "FROM transport_message_events WHERE connection_id = ? "
        "AND conversation_key = ? ORDER BY event_seq",
        (connection_id, conversation_key),
    ).fetchall()
    latest: dict[tuple[str, str], tuple[str, int | None]] = {}
    for _seq, direction, message_id, event_kind, row_id in events:
        latest[(str(direction), str(message_id))] = (
            str(event_kind), int(row_id) if row_id is not None else None
        )
    selected = []
    for row in rows:
        values = dict(row) if isinstance(row, sqlite3.Row) else dict(zip(column_names, row, strict=False))
        source_kind = values.get("source_kind") or "PASSIVE"
        message_id = values.get("platform_message_id") or ""
        direction = "outbound" if source_kind == "BOT_SELF" else "inbound"
        state = latest.get((direction, str(message_id))) if message_id else None
        if state is None:
            selected.append(row)
            continue
        kind, source_row = state
        if kind != "delete" and source_row is not None and int(values["id"]) == source_row:
            selected.append(row)
    return selected


def effective_history_filter(cursor: sqlite3.Cursor) -> str:
    """Return a SQL predicate hiding superseded/deleted rows in legacy tail queries."""
    tables = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='transport_message_events'"
    ).fetchone()
    if tables is None:
        return ""
    columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(group_messages)").fetchall()
    }
    required = {"connection_id", "conversation_key", "platform_message_id", "source_kind"}
    if not required.issubset(columns):
        return ""
    return """
      AND NOT EXISTS (
          SELECT 1 FROM transport_message_events AS latest
          WHERE latest.connection_id = group_messages.connection_id
            AND latest.conversation_key = group_messages.conversation_key
            AND latest.direction = CASE
                WHEN group_messages.source_kind = 'BOT_SELF' THEN 'outbound'
                ELSE 'inbound'
            END
            AND latest.platform_message_id = group_messages.platform_message_id
            AND latest.event_seq = (
                SELECT MAX(newer.event_seq) FROM transport_message_events AS newer
                WHERE newer.connection_id = latest.connection_id
                  AND newer.conversation_key = latest.conversation_key
                  AND newer.direction = latest.direction
                  AND newer.platform_message_id = latest.platform_message_id
            )
            AND (latest.event_kind = 'delete' OR latest.legacy_row_id IS NOT group_messages.id)
      )
    """


__all__ = [
    "ExistingMessageEvent",
    "append_message_event",
    "create_message_store_tables",
    "effective_history",
    "effective_history_filter",
    "event_dedupe_key",
    "find_existing_event",
    "mark_source_unavailable",
]
