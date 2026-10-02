# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""消息流程 API 测试（计划 §6.6）：messages/detail/events/spec + SSE。

夹具用真实 message_flow 写入临时诊断库（与 turn_trace 同库），验证
envelope/鉴权/增量游标/中断标注；SSE 用 TestClient 流式读取到 trace_end。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.observability import message_flow, turn_trace

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


@pytest.fixture
def flow_home(isolated_home: Path):
    """诊断库指到临时目录；用后还原 configure。"""
    db = isolated_home / "turn_trace.db"
    turn_trace.configure(db)
    yield db
    message_flow.flush()
    turn_trace.configure(None)


def _seed_trace(trace_id: str = "rt-1", *, close: bool = True) -> None:
    root = message_flow.begin_trace(
        root_kind="qq_chat", platform="qq", scope="qq:123",
        source_message_key="qq:bot:123:7", trace_id=trace_id)
    with message_flow.span(root, "chat.group_lock"):
        pass
    message_flow.decision(root, "chat.daily_budget", status="blocked",
                          reason_code="pause_all")
    if close:
        message_flow.end_trace(root, outcome="budget_blocked")
    message_flow.flush()


class TestFlowMessagesApi:
    def test_requires_auth(self, client: TestClient, flow_home):
        resp = client.get("/api/v1/trace/messages")
        assert resp.status_code == 401

    def test_list_and_detail(self, client: TestClient, auth_header, flow_home):
        _seed_trace("rt-1")
        resp = client.get("/api/v1/trace/messages",
                          headers=auth_header,
                          params={"root_kind": "qq_chat"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        item = data["items"][0]
        assert item["trace_id"] == "rt-1"
        assert item["outcome"] == "budget_blocked"
        assert item["complete"] is True

        detail = client.get("/api/v1/trace/messages/rt-1",
                            headers=auth_header).json()["data"]
        assert detail["scope"] == "qq:123"
        node_ids = {s["node_id"] for s in detail["spans"]}
        span_ids = {s["span_id"] for s in detail["spans"]}
        assert "chat.group_lock" in node_ids and "root" in span_ids
        assert detail["event_count"] >= 4
        assert detail["high_watermark"] > 0

    def test_detail_404(self, client: TestClient, auth_header, flow_home):
        resp = client.get("/api/v1/trace/messages/nope", headers=auth_header)
        assert resp.status_code == 404

    def test_running_trace_reported_interrupted(self, client: TestClient,
                                                auth_header, flow_home):
        _seed_trace("rt-open", close=False)
        item = client.get("/api/v1/trace/messages",
                          headers=auth_header).json()["data"]["items"][0]
        assert item["status"] == "interrupted"

    def test_events_incremental_cursor(self, client: TestClient,
                                       auth_header, flow_home):
        _seed_trace("rt-2")
        first = client.get("/api/v1/trace/messages/rt-2/events",
                           headers=auth_header,
                           params={"after": 0}).json()["data"]["items"]
        assert first, "有事件"
        mid = first[len(first) // 2]["row_id"]
        rest = client.get("/api/v1/trace/messages/rt-2/events",
                          headers=auth_header,
                          params={"after": mid}).json()["data"]["items"]
        assert all(ev["row_id"] > mid for ev in rest)
        ids = [ev["event_id"] for ev in first]
        assert len(ids) == len(set(ids))

    def test_spec_missing_is_404(self, client: TestClient, auth_header,
                                 flow_home):
        resp = client.get("/api/v1/trace/flow/specs/1999.01.01",
                          headers=auth_header)
        assert resp.status_code == 404


class TestFlowStream:
    def test_stream_emits_events_then_trace_end(self, client: TestClient,
                                                auth_header, flow_home):
        _seed_trace("rt-sse")
        with client.stream(
            "GET", "/api/v1/trace/messages/rt-sse/stream",
            headers=auth_header, params={"after": 0},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(chunk for chunk in resp.iter_text())
        assert "trace_end" in body
        assert "chat.daily_budget" in body
        # 帧带自增 id（Last-Event-ID 补漏锚点）
        assert "id: " in body

    def test_stream_from_cursor_skips_earlier(self, client: TestClient,
                                              auth_header, flow_home):
        _seed_trace("rt-sse2")
        events = client.get("/api/v1/trace/messages/rt-sse2/events",
                            headers=auth_header).json()["data"]["items"]
        cursor = events[len(events) // 2]["row_id"]
        with client.stream(
            "GET", "/api/v1/trace/messages/rt-sse2/stream",
            headers=auth_header, params={"after": cursor},
        ) as resp:
            body = "".join(chunk for chunk in resp.iter_text())
        for ev in events:
            if ev["row_id"] <= cursor:
                assert ev["event_id"] not in body
