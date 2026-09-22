# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""会话浏览与决策轨迹 API 测试。

服务层在**调用时**读 ``settings.DB_PATH``，夹具据此把记忆库指到临时文件，
用最小 DDL 播种（列与服务的 SELECT 对齐即可，不必复刻完整 schema）。
库缺失时的降级形状（空列表而非 500）单独钉死。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config.settings as settings

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


@pytest.fixture
def seeded_db(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """播种一份最小记忆库：消息 / checkpoint / 记忆 / 两条轨迹 / 参与决策。"""
    db = isolated_home / "memory" / "agent_memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "DB_PATH", db)
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id TEXT, user_id TEXT, content TEXT,
            source_kind TEXT DEFAULT 'PASSIVE', msg_id INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE consolidation_state (
            group_id TEXT PRIMARY KEY, last_processed_id INTEGER,
            skip_streak INTEGER, updated_at DATETIME
        );
        CREATE TABLE memories (
            id TEXT PRIMARY KEY, type TEXT, content TEXT, user_id TEXT
        );
        CREATE TABLE memory_traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            group_id TEXT, group_shared_space TEXT, user_id TEXT,
            message TEXT, mode TEXT, trigger TEXT,
            candidate_ids TEXT, filtered_ids TEXT, final_ids TEXT,
            rejected_ids TEXT, behavior_ids TEXT, score_map TEXT,
            prompt_snapshot TEXT, output TEXT, debug INTEGER DEFAULT 0
        );
        CREATE TABLE participation_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts DATETIME DEFAULT CURRENT_TIMESTAMP,
            group_id TEXT, topic_id INTEGER,
            relevance REAL, opportunity REAL, social_opportunity REAL,
            topic_involvement REAL, silence_bonus REAL,
            recent_speech_penalty REAL, velocity_penalty REAL,
            repetition_penalty REAL, expired_penalty REAL,
            final_score REAL, mode TEXT, decision TEXT,
            reason_flags TEXT, snapshot TEXT
        );
        """
    )
    for content, kind in [
        ("早", "PASSIVE"), ("在吗", "AT_MENTION"), ("在的", "BOT_SELF")
    ]:
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content, source_kind) "
            "VALUES ('123', 'u1', ?, ?)",
            (content, kind),
        )
    conn.execute(
        "INSERT INTO consolidation_state (group_id, last_processed_id, skip_streak, updated_at) "
        "VALUES ('123', 3, 1, '2026-09-22 12:00:00')"
    )
    conn.execute(
        "INSERT INTO memories (id, type, content, user_id) "
        "VALUES ('mem-1', 'FACT', '用户叫小明', 'u1')"
    )
    conn.execute(
        """INSERT INTO memory_traces (
            group_id, group_shared_space, user_id, message, mode, trigger,
            candidate_ids, final_ids, rejected_ids, score_map,
            prompt_snapshot, output
        ) VALUES (
            '123', 'space-a', 'u1', '在吗', 'NORMAL', 'reply',
            '["mem-1", "mem-gone"]', '["mem-1"]', '["mem-gone"]',
            '{"mem-1": 0.87}', 'PROMPT...', '在的'
        )"""
    )
    conn.execute(
        """INSERT INTO participation_log (
            group_id, topic_id, relevance, final_score, mode, decision,
            reason_flags, snapshot
        ) VALUES ('123', 9, 0.4, -12.5, 'observe', 'IGNORE',
            '["SILENCE", "TOO_QUIET"]', '{"recent_messages": 3}')"""
    )
    conn.commit()
    conn.close()
    return db


def test_conversations_missing_db_degrades(
    client: TestClient, auth_header: dict, isolated_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    # 不能依赖「会话库不存在」：全套件运行时其它测试会先建出会话库——
    # 显式指向一个不存在的路径来验证降级（全量运行实测踩过顺序问题）。
    monkeypatch.setattr(settings, "DB_PATH", isolated_home / "no" / "such.db")
    resp = client.get("/api/v1/conversations/groups", headers=auth_header)
    assert resp.status_code == 200
    assert resp.json()["data"]["groups"] == []


def test_conversation_groups_and_pagination(
    client: TestClient, auth_header: dict, seeded_db: Path
):
    resp = client.get("/api/v1/conversations/groups", headers=auth_header)
    groups = resp.json()["data"]["groups"]
    assert len(groups) == 1
    assert groups[0]["group_id"] == "123"
    assert groups[0]["messages"] == 3

    resp = client.get(
        "/api/v1/conversations",
        params={"group_id": "123", "page": 1, "page_size": 2},
        headers=auth_header,
    )
    data = resp.json()["data"]
    assert data["total"] == 3
    assert [i["content"] for i in data["items"]] == ["在的", "在吗"]  # id 倒序
    assert data["items"][0]["source_kind"] == "BOT_SELF"


def test_conversation_context_checkpoint(client: TestClient, auth_header: dict, seeded_db):
    resp = client.get(
        "/api/v1/conversations/context",
        params={"group_id": "123"},
        headers=auth_header,
    )
    checkpoint = resp.json()["data"]["consolidation"]
    assert checkpoint["last_processed_id"] == 3
    assert checkpoint["skip_streak"] == 1


def test_trace_list_and_detail(
    client: TestClient, auth_header: dict, seeded_db: Path
):
    resp = client.get(
        "/api/v1/trace/memory", params={"group_id": "123"}, headers=auth_header
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["counts"] == {
        "candidates": 2, "filtered": 0, "final": 1, "rejected": 1, "behavior": 0,
    }
    # 列表不带 prompt/output 大字段
    assert "prompt_snapshot" not in item

    resp = client.get("/api/v1/trace/memory/1", headers=auth_header)
    detail = resp.json()["data"]
    assert detail["output"] == "在的"
    # 记忆正文还原 + 分数注入；库中不存在的 id 标 missing 而不是消失
    final = detail["memories"]["final"]
    assert final[0]["content"] == "用户叫小明"
    assert final[0]["score"] == 0.87
    assert detail["memories"]["rejected"][0]["missing"] is True
    assert detail["prompt_snapshot"] == "PROMPT..."


def test_trace_detail_404(client: TestClient, auth_header: dict, seeded_db):
    resp = client.get("/api/v1/trace/memory/999", headers=auth_header)
    assert resp.status_code == 404
    assert resp.json()["status"] == "error"


def test_participation_stream(client: TestClient, auth_header: dict, seeded_db):
    resp = client.get(
        "/api/v1/trace/participation", params={"group_id": "123"}, headers=auth_header
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["decision"] == "IGNORE"
    assert item["reason_flags"] == ["SILENCE", "TOO_QUIET"]
    assert item["snapshot"] == {"recent_messages": 3}
    assert item["final_score"] == pytest.approx(-12.5)


def test_trace_requires_auth(client: TestClient, seeded_db):
    for path in (
        "/api/v1/trace/memory",
        "/api/v1/trace/memory/1",
        "/api/v1/trace/participation",
        "/api/v1/conversations",
        "/api/v1/conversations/context",
    ):
        assert client.get(path, params={"group_id": "123"}).status_code == 401, path
