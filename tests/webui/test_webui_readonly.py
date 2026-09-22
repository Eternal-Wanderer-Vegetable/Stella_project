# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""M1 只读面板 API 测试：usage / providers 运行态 / platform 链路 / plugins。

原则：服务层取数失败必须降级（空形状 + unavailable 标记）而不是 500；
所有端点要求已登录；usage 的日账查询以临时库验证（monkeypatch
usage_store.DB_PATH——_connect 在调用时读模块全局，正是可替换缝）。
"""

from __future__ import annotations

import sqlite3
import sys
import types

from fastapi.testclient import TestClient

from core.llm import usage_store

USER = {"username": "admin", "password": "correct horse battery"}


def _auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


def test_readonly_endpoints_require_auth(client: TestClient):
    for path in (
        "/api/v1/usage/today",
        "/api/v1/usage/daily",
        "/api/v1/providers/runtime",
        "/api/v1/platform/link",
        "/api/v1/plugins",
    ):
        assert client.get(path).status_code == 401, path


def test_usage_today_shape(client: TestClient):
    headers = _auth_header(client)
    resp = client.get("/api/v1/usage/today", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    # usage_snapshot 的脱敏契约字段 + webui 附加的降级段
    assert "accounting" in data
    assert "totals" in data
    assert "fallback_states" in data


def test_query_daily_reads_temp_db(isolated_home, monkeypatch):
    """query_daily：临时库插两行 → 只读返回；空库/坏路径 → 空列表降级。"""
    from core.llm import usage_store
    from memory.schema import create_llm_usage_daily_table

    db = isolated_home / "usage-test.db"
    monkeypatch.setattr(usage_store, "DB_PATH", db)
    conn = sqlite3.connect(db)
    create_llm_usage_daily_table(conn)
    conn.execute(
        "INSERT INTO llm_usage_daily (date, role, slot, model, kind, calls, "
        "prompt_tokens, completion_tokens) VALUES (?, 'CHAT', 'ONLINE_CHAT', 'gpt', '-', 3, 100, 50)",
        (usage_store._date_key(),),
    )
    conn.commit()
    conn.close()

    rows = usage_store.query_daily(days=7)
    assert len(rows) == 1
    assert rows[0]["role"] == "CHAT"
    assert rows[0]["prompt_tokens"] == 100

    # 坏路径降级为空列表，不抛异常
    monkeypatch.setattr(usage_store, "DB_PATH", isolated_home / "no" / "such.db")
    assert usage_store.query_daily(days=7) == []


def test_usage_daily_aggregation(client: TestClient, monkeypatch):
    """服务层聚合：序列按日期补零、排行按 token 降序。"""

    today_key = usage_store._date_key()
    rows = [
        {"date": today_key, "role": "CHAT", "slot": "ONLINE_CHAT", "model": "m1",
         "kind": "-", "calls": 2, "failures": 0, "truncated": 0,
         "prompt_tokens": 100, "completion_tokens": 50, "cached_tokens": 10,
         "estimated_prompt_tokens": 0, "estimated_cached_tokens": 0},
        {"date": today_key, "role": "CONSOLIDATION", "slot": "EXTRA", "model": "m2",
         "kind": "-", "calls": 1, "failures": 1, "truncated": 0,
         "prompt_tokens": 20, "completion_tokens": 5, "cached_tokens": 0,
         "estimated_prompt_tokens": 0, "estimated_cached_tokens": 0},
    ]
    monkeypatch.setattr(usage_store, "query_daily", lambda days: rows)
    headers = _auth_header(client)
    resp = client.get("/api/v1/usage/daily?days=7", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["series"]) == 7  # 补零到完整 7 天
    assert data["series"][-1]["date"] == today_key
    assert data["series"][-1]["calls"] == 3
    # by_role 按 prompt+completion 降序：CHAT(150) > CONSOLIDATION(25)
    assert data["by_role"][0]["name"] == "CHAT"
    assert data["by_role"][0]["total_tokens"] == 150


def test_providers_runtime_shape(client: TestClient):
    headers = _auth_header(client)
    resp = client.get("/api/v1/providers/runtime", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "scheduler" in data
    assert "fallback_states" in data


def test_platform_link_degrades_to_unavailable(client: TestClient, monkeypatch):
    """link_monitor 取不到（非 nonebot 环境）→ 降级形状而非 500。"""
    monkeypatch.setitem(sys.modules, "extensions.link_monitor", None)  # 强制 import 失败
    headers = _auth_header(client)
    resp = client.get("/api/v1/platform/link", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["unavailable"] is True
    assert data["connected"] is False


def test_platform_link_passthrough(client: TestClient, monkeypatch):
    """link_monitor 可导入时原样透传（None 值契约由前端可空渲染承接）。"""
    fake = types.ModuleType("extensions.link_monitor")
    fake.link_status = lambda: {
        "enabled": True, "connected": True, "bot_self_id": "123",
        "connected_seconds": 42.0, "last_event_seconds_ago": None,
    }
    monkeypatch.setitem(sys.modules, "extensions", types.ModuleType("extensions"))
    monkeypatch.setitem(sys.modules, "extensions.link_monitor", fake)
    headers = _auth_header(client)
    resp = client.get("/api/v1/platform/link", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["connected"] is True
    assert data["last_event_seconds_ago"] is None  # None 契约原样透传


def test_plugins_inventory_shape(client: TestClient):
    headers = _auth_header(client)
    resp = client.get("/api/v1/plugins", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    # 测试环境注册表为空，但三段结构必须完整
    assert data["plugins"] == []
    assert data["failed"] == {}
    assert "capabilities" in data
