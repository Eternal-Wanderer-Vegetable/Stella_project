from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

import memory.pre_processors as pre
from core.context import ChatContext
from core.transport.message_event import (
    MessageEventV1,
    MessagePartV1,
    MessageRelationV1,
)
from memory.capture_gate import (
    CAPTURE_RESULT_DENIED,
    CAPTURE_RESULT_OK,
    CaptureDecision,
)
from memory.message_store import effective_history
from memory.pre_processors import record_message, resolve_reply_target

CONNECTION = "matrix:main"
CONVERSATION = "matrix:main:room:room-1:thread:thread-8"


def _ctx(*, message: str, message_id: str, user_id: str = "user:alpha") -> ChatContext:
    return ChatContext(
        user_id=user_id,
        group_id=901,
        msg_id=0,
        message=message,
        source_kind="PASSIVE",
        conversation_kind="thread",
        conversation_key=CONVERSATION,
        bot_id="bot-1",
        peer_id="room-1",
        storage_session_id=901,
        connection_id=CONNECTION,
        platform_message_id=message_id,
    )


def _event(
    message_id: str,
    kind: str = "create",
    *,
    revision: str | None = None,
    text: str = "",
    relations: tuple[MessageRelationV1, ...] = (),
) -> MessageEventV1:
    return MessageEventV1(
        platform_message_id=message_id,
        occurred_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        components=(() if kind == "delete" else (MessagePartV1("text", text=text),)),
        relations=relations,
        event_kind=kind,
        platform_revision_id=revision,
    )


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_create_edit_delete_are_atomic_and_project_latest_live_body(tmp_path, monkeypatch):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    allowed = CaptureDecision(True, "ready", "", 1)

    create_ctx = _ctx(message="原文", message_id="opaque/id:1")
    create_event = _event(
        "opaque/id:1",
        text="原文",
        relations=(
            MessageRelationV1(
                "reply",
                target_message_id="missing-target",
                target_connection_id="matrix:main",
                target_conversation_key=CONVERSATION,
            ),
        ),
    )
    asyncio.run(record_message(create_ctx, capture=allowed, message_event=create_event))
    assert create_ctx.capture_result == CAPTURE_RESULT_OK
    assert create_ctx.recorded_row_id > 0
    initial_context = asyncio.run(pre.build_context(_ctx(message="", message_id="")))
    assert "原文" in initial_context.short_term

    conn = _connect(db_path)
    try:
        part = conn.execute(
            "SELECT kind, safe_payload_json FROM transport_message_parts"
        ).fetchone()
        assert part["kind"] == "text"
        assert json.loads(part["safe_payload_json"]) == {
            "text": "原文",
            "subject_key": None,
            "display_name": None,
            "mime_type": None,
            "size_bytes": None,
            "attachment_ref": None,
        }
        relation = conn.execute(
            "SELECT target_message_id, resolution_status "
            "FROM transport_message_relations"
        ).fetchone()
        assert tuple(relation) == ("missing-target", "unresolved")
    finally:
        conn.close()

    edit_ctx = _ctx(message="修订版", message_id="opaque/id:1")
    asyncio.run(
        record_message(
            edit_ctx,
            capture=allowed,
            message_event=_event(
                "opaque/id:1", "edit", revision="rev-B", text="修订版"
            ),
        )
    )
    assert edit_ctx.recorded_row_id > create_ctx.recorded_row_id

    conn = _connect(db_path)
    try:
        live = effective_history(
            conn, connection_id=CONNECTION, conversation_key=CONVERSATION
        )
        assert len(live) == 1
        assert live[0]["content"] == "修订版"
        tail, _ = pre._fetch_recent_tail(conn.cursor(), 901, 12)
        assert "修订版" in tail
        assert "原文" not in tail
        conn.execute(
            "CREATE TABLE memory_evidence ("
            "id TEXT PRIMARY KEY, owner_key TEXT, source_conversation_key TEXT, "
            "source_row_id INTEGER, verification_status TEXT)"
        )
        from memory.schema import create_memory_scope_versions_table

        create_memory_scope_versions_table(conn)
        conn.execute(
            "INSERT INTO memory_evidence VALUES (?, ?, ?, ?, ?)",
            (
                "ev-create",
                "space:transport:test",
                CONVERSATION,
                create_ctx.recorded_row_id,
                "accepted",
            ),
        )
        conn.execute(
            "INSERT INTO memory_evidence VALUES (?, ?, ?, ?, ?)",
            (
                "ev-edit",
                "space:transport:test",
                CONVERSATION,
                edit_ctx.recorded_row_id,
                "accepted",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    delete_ctx = _ctx(message="", message_id="opaque/id:1")
    asyncio.run(
        record_message(
            delete_ctx,
            capture=allowed,
            message_event=_event("opaque/id:1", "delete"),
        )
    )
    assert delete_ctx.capture_result == CAPTURE_RESULT_OK
    assert delete_ctx.recorded_row_id == 0  # a tombstone has no body snapshot
    refreshed_context = asyncio.run(pre.build_context(_ctx(message="", message_id="")))
    assert "原文" not in refreshed_context.short_term
    assert "修订版" not in refreshed_context.short_term

    conn = _connect(db_path)
    try:
        assert effective_history(
            conn, connection_id=CONNECTION, conversation_key=CONVERSATION
        ) == []
        tail, _ = pre._fetch_recent_tail(conn.cursor(), 901, 12)
        assert "原文" not in tail and "修订版" not in tail
        states = conn.execute(
            "SELECT verification_status FROM memory_evidence ORDER BY id"
        ).fetchall()
        assert [row[0] for row in states] == [
            "source_unavailable",
            "source_unavailable",
        ]
        version = conn.execute(
            "SELECT version FROM memory_scope_versions WHERE scope_key=?",
            ("space:transport:test",),
        ).fetchone()
        assert version[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0] == 2
        assert conn.execute(
            "SELECT COUNT(*) FROM transport_message_events WHERE event_kind='delete'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
    assert resolve_reply_target(
        "opaque/id:1",
        901,
        connection_id=CONNECTION,
        conversation_key=CONVERSATION,
    ) == ""


def test_reconnect_create_is_idempotent_and_opaque_reply_is_session_exact(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    allowed = CaptureDecision(True, "ready", "", 1)

    first = _ctx(message="author A", message_id="same/id")
    asyncio.run(
        record_message(
            first, capture=allowed, message_event=_event("same/id", text="author A")
        )
    )
    replay = _ctx(message="must not duplicate", message_id="same/id")
    asyncio.run(
        record_message(
            replay,
            capture=allowed,
            message_event=_event("same/id", text="must not duplicate"),
        )
    )
    assert replay.recorded_row_id == first.recorded_row_id

    conn = _connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM group_messages").fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM transport_message_events"
        ).fetchone()[0] == 1
    finally:
        conn.close()

    assert resolve_reply_target(
        "same/id", 901, connection_id=CONNECTION, conversation_key=CONVERSATION
    ) == "user:alpha"
    assert resolve_reply_target(
        "same/id", 901, connection_id="matrix:other", conversation_key=CONVERSATION
    ) == ""
    assert resolve_reply_target(
        "same/id", 902, connection_id=CONNECTION,
        conversation_key="matrix:main:room:room-2",
    ) == ""

    outgoing = _ctx(message="bot reply", message_id="bot/id", user_id="bot:1")
    outgoing.source_kind = "BOT_SELF"
    asyncio.run(
        record_message(
            outgoing,
            capture=allowed,
            message_event=_event("bot/id", text="bot reply"),
        )
    )
    assert resolve_reply_target(
        "bot/id", 901, connection_id=CONNECTION, conversation_key=CONVERSATION
    ) == "bot:1"


def test_capture_denial_with_transport_event_writes_nothing(tmp_path, monkeypatch):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    denied = CaptureDecision(False, "unavailable", "not_ready", 2)
    ctx = _ctx(message="must not persist", message_id="denied")
    out = asyncio.run(
        record_message(
            ctx, capture=denied, message_event=_event("denied", text="must not persist")
        )
    )
    assert out.recorded_row_id == 0
    assert out.capture_result == CAPTURE_RESULT_DENIED
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0] == 0
    finally:
        conn.close()


def test_context_and_event_message_ids_must_match(tmp_path, monkeypatch):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    ctx = _ctx(message="mismatch", message_id="context/id")
    out = asyncio.run(
        record_message(
            ctx,
            capture=CaptureDecision(True, "ready", "", 1),
            message_event=_event("event/id", text="mismatch"),
        )
    )
    assert out.recorded_row_id == 0
    assert out.capture_result == pre.CAPTURE_RESULT_STORAGE_FAILED


def test_unversioned_edits_are_not_deduplicated_by_body_or_time(tmp_path, monkeypatch):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    allowed = CaptureDecision(True, "ready", "", 1)
    for text in ("same body", "same body"):
        ctx = _ctx(message=text, message_id="opaque-edit")
        asyncio.run(
            record_message(
                ctx,
                capture=allowed,
                message_event=_event("opaque-edit", "edit", text=text),
            )
        )

    conn = _connect(db_path)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM transport_message_events WHERE event_kind='edit'"
        ).fetchone()[0] == 2
        live = effective_history(
            conn, connection_id=CONNECTION, conversation_key=CONVERSATION
        )
        assert len(live) == 1 and live[0]["content"] == "same body"
    finally:
        conn.close()


def test_integer_reply_fallback_requires_explicit_legacy_qq(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    asyncio.run(
        record_message(
            ChatContext(
                user_id="qq-user",
                group_id=901,
                msg_id=42,
                message="legacy source",
                conversation_key="qq:bot:group:901",
                conversation_kind="group",
                bot_id="bot",
                storage_session_id=901,
            )
        )
    )
    assert resolve_reply_target(
        "42", 901, bot_id="bot", conversation_key="qq:bot:group:901"
    ) == ""
    assert resolve_reply_target(
        "42", 901, bot_id="bot", conversation_key="qq:bot:group:901", legacy_qq=True
    ) == "qq-user"


def test_commit_failure_rolls_back_body_and_all_transport_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "transport-memory.db"
    monkeypatch.setattr(pre, "DB_PATH", db_path)
    connect = pre.connect_sqlite

    class FailingCommit:
        def __init__(self):
            self.connection = connect(pre.StorageDomain.MEMORY, db_path)

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    monkeypatch.setattr(pre, "connect_sqlite", lambda *_args: FailingCommit())
    ctx = _ctx(message="atomic", message_id="commit-fail")
    out = asyncio.run(
        record_message(
            ctx,
            capture=CaptureDecision(True, "ready", "", 1),
            message_event=_event("commit-fail", text="atomic"),
        )
    )
    assert out.recorded_row_id == 0
    assert out.capture_result == pre.CAPTURE_RESULT_STORAGE_FAILED

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "group_messages" not in tables
        assert "transport_message_events" not in tables
        assert "transport_message_parts" not in tables
        assert "transport_message_relations" not in tables
    finally:
        conn.close()


def test_schema_22_dry_run_and_upgrade_preserve_legacy_rows(tmp_path):
    from memory import schema
    from memory.migrations import MigrationContext

    db_path = tmp_path / "schema-22.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE schema_meta ("
        "k TEXT PRIMARY KEY, version INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
        "INSERT INTO schema_meta (k, version) VALUES ('version', 22);"
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY, group_id TEXT, content TEXT);"
        "INSERT INTO group_messages VALUES (1, '77', 'untouched legacy body');"
    )
    conn.close()
    migration_ctx = MigrationContext(resolver=lambda group_id: str(group_id))

    preview = schema.migrate_to_latest(db_path, ctx=migration_ctx, dry_run=True)
    assert preview.ok
    assert preview.from_version == 22 and preview.to_version == 23
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT version FROM schema_meta WHERE k='version'").fetchone() == (22,)
        assert conn.execute("SELECT content FROM group_messages WHERE id=1").fetchone() == (
            "untouched legacy body",
        )
    finally:
        conn.close()

    migrated = schema.migrate_to_latest(db_path, ctx=migration_ctx)
    assert migrated.ok, migrated.to_markdown()
    assert [step.version for step in migrated.steps] == [23]
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT version FROM schema_meta WHERE k='version'").fetchone() == (23,)
        assert conn.execute("SELECT content FROM group_messages WHERE id=1").fetchone() == (
            "untouched legacy body",
        )
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "transport_message_events",
            "transport_message_parts",
            "transport_message_relations",
        }.issubset(tables)
    finally:
        conn.close()

    rerun = schema.migrate_to_latest(db_path, ctx=migration_ctx)
    assert rerun.ok and rerun.steps == []


def test_schema_23_migration_failure_rolls_back_version_and_ddl(tmp_path, monkeypatch):
    from memory import message_store, schema
    from memory.migrations import MigrationContext

    db_path = tmp_path / "schema-22-failure.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE schema_meta ("
        "k TEXT PRIMARY KEY, version INTEGER, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
        "INSERT INTO schema_meta (k, version) VALUES ('version', 22);"
        "CREATE TABLE group_messages (id INTEGER PRIMARY KEY, group_id TEXT, content TEXT);"
        "INSERT INTO group_messages VALUES (1, '77', 'preserve on failure');"
    )
    conn.close()

    create_tables = message_store.create_message_store_tables

    def fail_after_first_table(connection):
        create_tables(connection)
        raise sqlite3.OperationalError("injected v23 migration failure")

    monkeypatch.setattr(message_store, "create_message_store_tables", fail_after_first_table)
    monkeypatch.setattr(schema, "backup_database", lambda _path: None)
    monkeypatch.setattr(schema, "backup_before_migration", lambda _path, _version: None)
    report = schema.migrate_to_latest(
        db_path,
        ctx=MigrationContext(resolver=lambda group_id: str(group_id)),
    )
    assert not report.ok
    assert "injected v23 migration failure" in report.error

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT version FROM schema_meta WHERE k='version'").fetchone() == (22,)
        assert conn.execute("SELECT content FROM group_messages WHERE id=1").fetchone() == (
            "preserve on failure",
        )
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "transport_message_events" not in tables
        assert "transport_message_parts" not in tables
        assert "transport_message_relations" not in tables
    finally:
        conn.close()
