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

    def test_running_trace_with_live_process_stays_running(self, client: TestClient,
                                                            auth_header, flow_home):
        """O01 正确合同：running + 活进程（同化身）→ 保持 running，不误判中断。"""
        _seed_trace("rt-open", close=False)
        item = client.get("/api/v1/trace/messages",
                          headers=auth_header).json()["data"]["items"][0]
        assert item["status"] == "running"

    def test_running_trace_with_dead_incarnation_interrupted(
            self, client: TestClient, auth_header, flow_home):
        """O01：旧化身 + 心跳过期 → interrupted（进程已死的残留）。"""
        import sqlite3

        _seed_trace("rt-dead", close=False)
        conn = sqlite3.connect(flow_home)
        conn.execute(
            "UPDATE message_traces SET process_instance_id='dead0001', "
            "last_heartbeat_utc='2020-01-01T00:00:00.000' WHERE trace_id='rt-dead'")
        conn.commit()
        conn.close()
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


class TestFlowMessageContext:
    def test_input_output_from_memory_db(self, client: TestClient,
                                         auth_header, flow_home,
                                         isolated_home, monkeypatch):
        """输入按 (group, msg_id) 精确命中；输出 = 窗口内 BOT_SELF 行。"""
        import sqlite3 as s3

        import config.settings as settings

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)
        _seed_trace("rc-1")
        # 输出匹配用轨迹时间窗：按已种轨迹的 started 秒播种，保证落在窗内
        import sqlite3 as s3b

        tdb = s3b.connect(flow_home)
        started = tdb.execute(
            "SELECT started_utc FROM message_traces WHERE trace_id='rc-1'"
        ).fetchone()[0].replace("T", " ")[:19]
        tdb.close()
        mem = s3.connect(db)
        mem.execute(
            "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "group_id TEXT, user_id TEXT, content TEXT, source_kind TEXT, "
            "msg_id INTEGER, timestamp DATETIME)"
        )
        mem.executemany(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, timestamp) VALUES (?,?,?,?,?,?)",
            [
                ("123", "u1", "你好呀", "AT_MENTION", 7, started),
                ("123", "bot", "你也好", "BOT_SELF", 0, started),
                ("123", "bot", "在听", "BOT_SELF", 0, started),
            ],
        )
        mem.commit()
        mem.close()
        data = client.get("/api/v1/trace/messages/rc-1/context",
                          headers=auth_header).json()["data"]
        assert data["input"]["content"] == "你好呀"
        assert data["input"]["msg_id"] == 7
        assert data["output"]["lines"] == ["你也好", "在听"]
        # 输出来自时间窗 fallback（该轨迹无回执档案）：来源必须显式说明
        assert any("BOT_SELF" in n for n in data["notes"])

    def test_output_prefers_acknowledged_receipts(self, client: TestClient,
                                                  auth_header, flow_home,
                                                  isolated_home, monkeypatch):
        """O02 正确合同：有回执档案时输出按业务 ID 关联，不看 root 分类。

        qq_passive root 也可能有已送达回复；回执优先于时间窗猜测。
        """
        import sqlite3

        import config.settings as settings
        from core.observability import message_flow as mf

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)

        root = mf.begin_trace(root_kind="qq_passive", platform="qq",
                              scope="qq:55", source_message_key="qq:b:55:3",
                              trace_id="rc-rec")
        mf.end_trace(root, outcome="delivered")
        mf.flush()
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT, "
            "source_kind TEXT, msg_id INTEGER, timestamp DATETIME)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS social_deliveries (delivery_id TEXT "
            "PRIMARY KEY, turn_id TEXT, part_index INTEGER, trace_id TEXT, "
            "epoch INTEGER, platform TEXT, bot_id TEXT, group_id TEXT, "
            "status TEXT, platform_message_id TEXT, acknowledged_at_utc TEXT, "
            "text TEXT, text_hash TEXT, created_at_utc TEXT, updated_at_utc TEXT)")
        conn.executemany(
            "INSERT INTO social_deliveries (delivery_id, turn_id, part_index, "
            "trace_id, status, text, platform_message_id) VALUES (?,?,?,?,?,?,?)",
            [("d1", "t", 0, "rc-rec", "acknowledged", "回执第一段", "9001"),
             ("d2", "t", 1, "rc-rec", "acknowledged", "回执第二段", "9002"),
             ("d3", "t", 2, "rc-rec", "failed", "", None)])
        # 时间窗内另一条 BOT_SELF 干扰行：不该出现在输出里
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, timestamp) VALUES ('55','bot','窗口噪声','BOT_SELF',0,'2020-01-01 00:00:00')")
        conn.commit()
        conn.close()
        data = client.get("/api/v1/trace/messages/rc-rec/context",
                          headers=auth_header).json()["data"]
        assert data["output"]["lines"] == ["回执第一段", "回执第二段"]
        assert any("发送失败" in n for n in data["notes"])

    def test_passive_trace_notes_no_reply(self, client: TestClient,
                                          auth_header, flow_home):
        _seed_trace("rc-2")
        # rc-2 的来源键 qq:bot:123:7 没有对应输入行：input 为空且不报错
        data = client.get("/api/v1/trace/messages/rc-2/context",
                          headers=auth_header).json()["data"]
        assert data["input"] is None
        assert data["output"]["lines"] == []
        assert data["notes"]

    def test_context_404(self, client: TestClient, auth_header, flow_home):
        resp = client.get("/api/v1/trace/messages/nope/context",
                          headers=auth_header)
        assert resp.status_code == 404


class TestPrivateChatIoIdentity:
    """R1（修复计划 M0/M2 探针固化）：私聊输入输出按注册表存储键精确命中。

    私聊真实存储 ID 是注册表负整数；scope 展示键绝不能当 group_id 查询，
    更不能把负 storage ID 展示成群号。输出可来自会话中立回执
    （learning_eligible=0，不参与群学习）。
    """

    def test_private_input_via_storage_session_id(self, client, auth_header,
                                                  flow_home, isolated_home,
                                                  monkeypatch):
        import sqlite3

        import config.settings as settings
        from core.observability import message_flow as mf

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)

        root = mf.begin_trace(
            root_kind="qq_private", platform="qq",
            scope="qq:10001:private:20001",
            conversation_key="qq:10001:private:20001",
            bot_id="10001", conversation_kind="private", peer_id="20001",
            storage_session_id=-11, source_message_id="7",
            source_message_key="qq:10001:private:20001:msg:7",
            trace_id="rc-priv")
        mf.end_trace(root, outcome="delivered")
        mf.flush()
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT, "
            "source_kind TEXT, msg_id INTEGER, timestamp DATETIME, "
            "bot_id TEXT DEFAULT '', conversation_key TEXT DEFAULT '')")
        # 私聊行真实存储键 = 注册表负整数；msg_id 唯一性只在本会话内成立
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, timestamp, bot_id, conversation_key) "
            "VALUES ('-11','20001','私聊在吗',"
            "'PRIVATE_DIRECT',7,'2026-10-04 12:00:00','10001',"
            "'qq:10001:private:20001')")
        # 干扰行：另一 Bot 同 msg_id（不同 storage 键）绝不能串线
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, timestamp, bot_id, conversation_key) "
            "VALUES ('-99','20002','别的会话',"
            "'PRIVATE_DIRECT',7,'2026-10-04 12:00:00','10002',"
            "'qq:10002:private:20002')")
        conn.commit()
        conn.close()
        data = client.get("/api/v1/trace/messages/rc-priv/context",
                          headers=auth_header).json()["data"]
        assert data["input"] is not None, "私聊输入必须可查（R1 缺口）"
        assert data["input"]["content"] == "私聊在吗"
        assert data["input"]["identity_state"] == "exact"

    def test_private_output_from_neutral_receipts(self, client, auth_header,
                                                  flow_home, isolated_home,
                                                  monkeypatch):
        """会话中立回执（scope=None + 明确 ref）可查且不进群学习口径。"""
        import sqlite3

        import config.settings as settings
        from core.observability import message_flow as mf

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)
        root = mf.begin_trace(
            root_kind="qq_private", platform="qq",
            scope="qq:10001:private:20001",
            conversation_key="qq:10001:private:20001",
            bot_id="10001", conversation_kind="private", peer_id="20001",
            storage_session_id=-11, source_message_id="8",
            trace_id="rc-priv-out")
        mf.end_trace(root, outcome="delivered")
        mf.flush()
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS social_deliveries (delivery_id TEXT "
            "PRIMARY KEY, turn_id TEXT, part_index INTEGER, trace_id TEXT, "
            "epoch INTEGER, platform TEXT, bot_id TEXT, group_id TEXT, "
            "status TEXT, platform_message_id TEXT, acknowledged_at_utc TEXT, "
            "text TEXT, text_hash TEXT, created_at_utc TEXT, updated_at_utc TEXT)")
        conn.executemany(
            "INSERT INTO social_deliveries (delivery_id, turn_id, part_index, "
            "trace_id, platform, bot_id, group_id, status, text) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [("dp1", "tp", 0, "rc-priv-out", "qq", "10001", "",
              "acknowledged", "私聊回复第一段"),
             ("dp2", "tp", 1, "rc-priv-out", "qq", "10001", "",
              "failed", "私聊回复第二段")])
        conn.commit()
        conn.close()
        data = client.get("/api/v1/trace/messages/rc-priv-out/context",
                          headers=auth_header).json()["data"]
        assert data["output"]["lines"] == ["私聊回复第一段"]
        assert any("发送失败" in n for n in data["notes"])
        # 逐段投递事实（验收报告 M6）：原 part_index + status 保留
        segs = data["output"]["segments"]
        assert [s["part_index"] for s in segs] == [0, 1]
        assert segs[0]["status"] == "acknowledged"
        assert segs[1]["status"] == "failed" 


class TestCommandReplyVisible:
    def test_command_reply_merged_into_output(self, client: TestClient,
                                              auth_header, flow_home):
        """命令回复（command.reply 检查点）合并进输出行。"""
        from core.observability import message_flow as mf

        root = mf.begin_trace(root_kind="qq_command", platform="qq",
                              scope="qq:9", source_message_key="qq:b:9:1",
                              trace_id="rc-cmd")
        mf.checkpoint(root, "command.reply", summary="已进入安静模式")
        mf.end_trace(root, outcome="command_sent")
        mf.flush()
        data = client.get("/api/v1/trace/messages/rc-cmd/context",
                          headers=auth_header).json()["data"]
        assert data["input"] is None
        assert data["output"]["lines"] == ["已进入安静模式"]


class TestExactInputCrossBot:
    """验收报告 H2：同 storage（群号）+ 同 msg_id、不同 Bot——exact 输入
    绝不能返回另一台 Bot 的正文。"""

    def _seed_private_trace(self, trace_id, conv_key, bot_id):
        from core.observability import message_flow as mf

        root = mf.begin_trace(
            root_kind="qq_private", platform="qq",
            scope=f"qq:{bot_id}:private:20001",
            conversation_key=conv_key, bot_id=bot_id,
            conversation_kind="private", peer_id="20001",
            storage_session_id=-11, source_message_id="7",
            trace_id=trace_id)
        mf.end_trace(root, outcome="delivered")
        mf.flush()

    def test_same_storage_same_msg_other_bot_never_returned(
            self, client, auth_header, flow_home, isolated_home, monkeypatch):
        import sqlite3

        import config.settings as settings
        from core.observability import message_flow as mf

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)
        self._seed_private_trace("h2-a", "qq:10001:private:20001", "10001")
        # 两台 Bot 的同 storage 语义在群里才共享；这里用群 kind 直接种
        # 身份列构造反例：同群号同 msg_id，两台 Bot 各有一行
        root = mf.begin_trace(
            root_kind="qq_chat", platform="qq", scope="qq:555",
            conversation_key="qq:10001:group:555", bot_id="10001",
            conversation_kind="group", peer_id="555",
            storage_session_id=555, source_message_id="7",
            trace_id="h2-group-a")
        mf.end_trace(root, outcome="delivered")
        mf.flush()
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT, "
            "source_kind TEXT, msg_id INTEGER, timestamp DATETIME, "
            "bot_id TEXT DEFAULT '', conversation_key TEXT DEFAULT '')")
        conn.executemany(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, bot_id, conversation_key) "
            "VALUES (?,?,?,?,?,?,?)",
            [("555", "u1", "甲 Bot 会话的正文", "AT_MENTION", 7,
              "10001", "qq:10001:group:555"),
             ("555", "u2", "乙 Bot 会话的正文", "AT_MENTION", 7,
              "10002", "qq:10002:group:555")])
        conn.commit()
        conn.close()
        data = client.get("/api/v1/trace/messages/h2-group-a/context",
                          headers=auth_header).json()["data"]
        assert data["input"] is not None
        assert data["input"]["content"] == "甲 Bot 会话的正文"
        assert data["input"]["identity_state"] == "exact"

        # 反向：trace 属于乙 Bot → 必须取乙的行，不串到甲
        root_b = mf.begin_trace(
            root_kind="qq_chat", platform="qq", scope="qq:555",
            conversation_key="qq:10002:group:555", bot_id="10002",
            conversation_kind="group", peer_id="555",
            storage_session_id=555, source_message_id="7",
            trace_id="h2-group-b")
        mf.end_trace(root_b, outcome="delivered")
        mf.flush()
        data_b = client.get("/api/v1/trace/messages/h2-group-b/context",
                            headers=auth_header).json()["data"]
        assert data_b["input"]["content"] == "乙 Bot 会话的正文"

    def test_identity_mismatch_returns_no_input_not_other_bot(
            self, client, auth_header, flow_home, isolated_home, monkeypatch):
        """候选行身份都不匹配当前 Bot → 不返回（绝不冒充 exact）。"""
        import sqlite3

        import config.settings as settings

        db = isolated_home / "memory" / "agent_memory.db"
        db.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, "DB_PATH", db)
        self._seed_private_trace("h2-c", "qq:20002:private:20001", "20002")
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS group_messages (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, group_id TEXT, user_id TEXT, content TEXT, "
            "source_kind TEXT, msg_id INTEGER, timestamp DATETIME, "
            "bot_id TEXT DEFAULT '', conversation_key TEXT DEFAULT '')")
        conn.execute(
            "INSERT INTO group_messages (group_id, user_id, content, "
            "source_kind, msg_id, bot_id, conversation_key) "
            "VALUES ('-11','u','别的 Bot 的行','PRIVATE_DIRECT',7,"
            "'10001','qq:10001:private:20001')")
        conn.commit()
        conn.close()
        data = client.get("/api/v1/trace/messages/h2-c/context",
                          headers=auth_header).json()["data"]
        assert data["input"] is None
        assert any("无当前 Bot 身份" in n for n in data["notes"])


class TestMessagesKeysetPagination:
    """验收报告 H3：降序 keyset 方向、offset 兼容与稳定 total。"""

    def _seed_five(self, flow_home):
        from core.observability import message_flow as mf

        for i in range(1, 6):
            root = mf.begin_trace(root_kind="webchat", trace_id=f"kt-{i}")
            mf.end_trace(root, outcome="done")
        mf.flush()

    def test_cursor_pages_older_records(self, client, auth_header, flow_home):
        self._seed_five(flow_home)
        page1 = client.get("/api/v1/trace/messages", headers=auth_header,
                           params={"limit": 2}).json()["data"]
        ids1 = [i["trace_id"] for i in page1["items"]]
        assert ids1 == ["kt-5", "kt-4"]
        assert page1["total"] == 5 and page1["next_cursor"]
        page2 = client.get("/api/v1/trace/messages", headers=auth_header,
                           params={"limit": 2,
                                   "cursor": page1["next_cursor"]}).json()["data"]
        assert [i["trace_id"] for i in page2["items"]] == ["kt-3", "kt-2"]
        assert page2["total"] == 5, "total 不含游标，分页期间稳定"
        page3 = client.get("/api/v1/trace/messages", headers=auth_header,
                           params={"limit": 2,
                                   "cursor": page2["next_cursor"]}).json()["data"]
        assert [i["trace_id"] for i in page3["items"]] == ["kt-1"]
        assert page3["next_cursor"] in (None, ""), "取尽后无游标"

    def test_offset_still_works(self, client, auth_header, flow_home):
        self._seed_five(flow_home)
        data = client.get("/api/v1/trace/messages", headers=auth_header,
                          params={"limit": 2, "offset": 2}).json()["data"]
        assert [i["trace_id"] for i in data["items"]] == ["kt-3", "kt-2"]

    def test_concurrent_insert_does_not_duplicate_between_pages(
            self, client, auth_header, flow_home):
        """翻页间隙新插入的（更新一侧）轨迹不进入后续页、不产生重复。"""
        from core.observability import message_flow as mf

        self._seed_five(flow_home)
        page1 = client.get("/api/v1/trace/messages", headers=auth_header,
                           params={"limit": 2}).json()["data"]
        root = mf.begin_trace(root_kind="webchat", trace_id="kt-new")
        mf.end_trace(root, outcome="done")
        mf.flush()
        page2 = client.get("/api/v1/trace/messages", headers=auth_header,
                           params={"limit": 2,
                                   "cursor": page1["next_cursor"]}).json()["data"]
        ids = [i["trace_id"] for i in page2["items"]]
        assert "kt-new" not in ids, "keyset 严格小于：新行不回灌旧页"
        assert len(ids) == len(set(ids))
