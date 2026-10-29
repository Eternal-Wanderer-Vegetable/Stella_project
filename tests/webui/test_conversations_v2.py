# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Authenticated, exact-identity scene and effective-history API checks."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config.settings as settings
from core.transport.keys import conversation_key_v2
from core.transport.models import BotRef, SceneRef

USER = {"username": "admin", "password": "correct horse battery"}
CONNECTION_A = "11111111-1111-4111-8111-111111111111"
CONNECTION_B = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def auth_header(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/setup", json=USER)
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['token']}"}


@pytest.fixture
def v2_db(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    db = isolated_home / "memory" / "agent_memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DB_PATH", db)
    key_a = conversation_key_v2(
        BotRef(CONNECTION_A, "adapter.example", "community", "bot:α"),
        SceneRef("channel", "room:007", ("server:1",)),
    )
    key_b = conversation_key_v2(
        BotRef(CONNECTION_B, "adapter.example", "community", "bot:β"),
        SceneRef("channel", "room:007", ("server:1",)),
    )
    key_thread = conversation_key_v2(
        BotRef(CONNECTION_A, "adapter.example", "community", "bot:α"),
        SceneRef("thread", "thread:9", ("server:1", "room:007"), "thread:9"),
    )
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE conversation_registry_v2 (
            conversation_key TEXT PRIMARY KEY,
            storage_session_id INTEGER NOT NULL UNIQUE,
            memory_space TEXT NOT NULL,
            created_at TEXT
        );
        CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY, group_id TEXT, timestamp TEXT, user_id TEXT,
            content TEXT, source_kind TEXT, msg_id INTEGER, platform_message_id TEXT,
            connection_id TEXT, conversation_key TEXT
        );
        CREATE TABLE transport_message_events (
            event_seq INTEGER PRIMARY KEY, connection_id TEXT, conversation_key TEXT,
            direction TEXT, platform_message_id TEXT, event_kind TEXT, legacy_row_id INTEGER
        );
        """
    )
    for index, (key, space) in enumerate(
        ((key_a, "space-a"), (key_b, "space-b"), (key_thread, "space-a")), start=1
    ):
        conn.execute(
            "INSERT INTO conversation_registry_v2 VALUES (?, ?, ?, '2026-10-25T00:00:00Z')",
            (key, -index, space),
        )
    conn.executemany(
        "INSERT INTO group_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, "-2", "2026-10-25T00:00:01Z", "u1", "old revision", "PASSIVE", None,
             "msg:007", CONNECTION_A, key_a),
            (2, "-2", "2026-10-25T00:00:02Z", "u1", "edited revision", "PASSIVE", None,
             "msg:007", CONNECTION_A, key_a),
            (3, "-2", "2026-10-25T00:00:03Z", "u1", "deleted body", "PASSIVE", None,
             "msg:delete", CONNECTION_A, key_a),
            (4, "-3", "2026-10-25T00:00:04Z", "u2", "other bot body", "PASSIVE", None,
             "msg:007", CONNECTION_B, key_b),
            (5, "-4", "2026-10-25T00:00:05Z", "u3", "other thread body", "PASSIVE", None,
             "msg:007", CONNECTION_A, key_thread),
            (6, "-2", "2026-10-25T00:00:06Z", "u1", "later message", "PASSIVE", None,
             "msg:later", CONNECTION_A, key_a),
        ],
    )
    conn.executemany(
        "INSERT INTO transport_message_events VALUES (?, ?, ?, 'inbound', ?, ?, ?)",
        [
            (1, CONNECTION_A, key_a, "msg:007", "create", 1),
            (2, CONNECTION_A, key_a, "msg:007", "edit", 2),
            (3, CONNECTION_A, key_a, "msg:delete", "delete", None),
        ],
    )
    conn.commit()
    conn.close()
    return {"path": str(db), "key_a": key_a, "key_b": key_b, "key_thread": key_thread}


def test_v2_scenes_keep_bot_and_thread_identity(
    client: TestClient, auth_header: dict[str, str], v2_db: dict[str, str]
) -> None:
    response = client.get("/api/v1/conversations/scenes", headers=auth_header)
    assert response.status_code == 200
    scenes = response.json()["data"]["scenes"]
    assert len(scenes) == 3
    assert {scene["conversation_key"] for scene in scenes} == {
        v2_db["key_a"], v2_db["key_b"], v2_db["key_thread"]
    }
    room_scenes = [scene for scene in scenes if scene["scene_id"] == "room:007"]
    assert {scene["connection_id"] for scene in room_scenes} == {CONNECTION_A, CONNECTION_B}
    assert next(scene for scene in scenes if scene["kind"] == "thread")["thread_id"] == "thread:9"
    assert next(scene for scene in room_scenes if scene["connection_id"] == CONNECTION_A)["messages"] == 2

    filtered = client.get(
        "/api/v1/conversations/scenes",
        params={"connection_id": CONNECTION_B, "kind": "channel"},
        headers=auth_header,
    )
    assert [scene["conversation_key"] for scene in filtered.json()["data"]["scenes"]] == [
        v2_db["key_b"]
    ]


def test_v2_history_uses_exact_identity_and_effective_projection(
    client: TestClient, auth_header: dict[str, str], v2_db: dict[str, str]
) -> None:
    response = client.get(
        "/api/v1/conversations/messages",
        params={"conversation_key": v2_db["key_a"], "page_size": 1},
        headers=auth_header,
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 2
    assert [item["content"] for item in data["items"]] == ["later message"]
    assert data["next_cursor"] == 6

    # New appends after the first request do not move the cursor window.
    conn = sqlite3.connect(v2_db["path"])
    conn.execute(
        "INSERT INTO group_messages VALUES (7, '-2', '2026-10-25T00:00:07Z', 'u1', "
        "'new append', 'PASSIVE', NULL, 'msg:new', ?, ?)",
        (CONNECTION_A, v2_db["key_a"]),
    )
    conn.commit()
    conn.close()
    next_page = client.get(
        "/api/v1/conversations/messages",
        params={
            "conversation_key": v2_db["key_a"],
            "page_size": 1,
            "cursor": data["next_cursor"],
            "snapshot_id": data["snapshot_id"],
        },
        headers=auth_header,
    ).json()["data"]
    assert [item["content"] for item in next_page["items"]] == ["edited revision"]
    assert next_page["next_cursor"] is None

    other_bot = client.get(
        "/api/v1/conversations/messages",
        params={"conversation_key": v2_db["key_b"]},
        headers=auth_header,
    )
    assert [item["content"] for item in other_bot.json()["data"]["items"]] == [
        "other bot body"
    ]


def test_v2_history_rejects_unknown_and_malformed_identity(
    client: TestClient, auth_header: dict[str, str], v2_db: dict[str, str]
) -> None:
    unregistered = conversation_key_v2(
        BotRef(CONNECTION_A, "adapter.example", "community", "bot:α"),
        SceneRef("channel", "not-registered"),
    )
    missing = client.get(
        "/api/v1/conversations/messages",
        params={"conversation_key": unregistered},
        headers=auth_header,
    )
    assert missing.status_code == 404
    malformed = client.get(
        "/api/v1/conversations/messages",
        params={"conversation_key": "c2.not-canonical"},
        headers=auth_header,
    )
    assert malformed.status_code == 400
    invalid_cursor = client.get(
        "/api/v1/conversations/messages",
        params={"conversation_key": v2_db["key_a"], "cursor": 6},
        headers=auth_header,
    )
    assert invalid_cursor.status_code == 400
    assert invalid_cursor.json()["data"]["code"] == "history_cursor_invalid"


def test_v2_scene_routes_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/conversations/scenes").status_code == 401
    assert client.get(
        "/api/v1/conversations/messages", params={"conversation_key": "c2.x"}
    ).status_code == 401
