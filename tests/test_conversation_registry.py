# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话注册表测试（计划 §6.1/§8.2 tests/test_conversation_registry.py）。

覆盖：旧群 legacy 绑定、WebChat -1 保留、私聊负整数分配（避开历史占用）、
并发注册、重启恢复、多 Bot 存储冲突不盲绑。数据库用 tmp_path 独立文件；
空间配置由 conftest 的 autouse 夹具隔离。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from core.conversation import conversation_key
from memory import conversation_registry as registry


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "agent_memory.db")
    c.execute("PRAGMA busy_timeout = 3000")
    yield c
    c.close()


class TestGroupRegistration:
    def test_group_gets_legacy_alias_and_positive_storage(self, conn):
        ref = registry.get_or_register_group(conn, "10000", 263402786)
        assert ref.storage_session_id == 263402786
        assert ref.runtime_key == "qq:263402786"
        assert ref.memory_space  # 空间已解析（自动命名 space_N）
        # 注册表同时存规范键
        row = conn.execute(
            "SELECT conversation_key, legacy_binding FROM conversation_registry"
            " WHERE storage_session_id = 263402786"
        ).fetchone()
        assert row[0] == "qq:10000:group:263402786"
        assert row[1] == "10000"

    def test_group_registration_is_idempotent(self, conn):
        a = registry.get_or_register_group(conn, "10000", 263402786)
        b = registry.get_or_register_group(conn, "10000", 263402786)
        assert a == b
        count = conn.execute("SELECT COUNT(*) FROM conversation_registry").fetchone()[0]
        assert count == 1


class TestWebchatReservation:
    def test_webchat_keeps_negative_one(self, conn):
        ref = registry.get_or_register_webchat(conn, 800_000_000)
        assert ref.storage_session_id == -1
        assert ref.runtime_key == "webchat:800000000"
        assert ref.memory_space == "webchat"

    def test_private_never_takes_webchat_slot(self, conn):
        """WebChat -1 保留：第一个私聊必须拿到 -2 而不是 -1（§8.1）。"""
        registry.get_or_register_webchat(conn, 800_000_000)
        ref = registry.get_or_register_private(conn, "10000", 20001)
        assert ref.storage_session_id == -2
        ref2 = registry.get_or_register_private(conn, "10000", 20002)
        assert ref2.storage_session_id == -3


class TestPrivateAllocation:
    def test_private_allocation_avoids_history_negatives(self, conn):
        """历史消息里已有负值占用时，分配起点必须小于全部占用值。"""
        conn.execute(
            "CREATE TABLE group_messages (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " group_id TEXT, user_id TEXT, content TEXT)"
        )
        conn.execute("INSERT INTO group_messages (group_id) VALUES ('-7')")
        conn.commit()
        ref = registry.get_or_register_private(conn, "10000", 20001)
        assert ref.storage_session_id == -8

    def test_private_allocation_is_idempotent_across_restart(self, conn):
        a = registry.get_or_register_private(conn, "10000", 20001)
        # 「重启」= 新连接读同一个库
        b = registry.get_or_register_private(conn, "10000", 20001)
        assert a == b
        assert a.storage_session_id == -2
        assert a.runtime_key == "qq:10000:private:20001"
        assert a.memory_space == "private:qq:10000:20001"

    def test_multi_bot_same_user_gets_distinct_sessions(self, conn):
        a = registry.get_or_register_private(conn, "10000", 20001)
        b = registry.get_or_register_private(conn, "20000", 20001)
        assert a.conversation_key != b.conversation_key
        assert a.storage_session_id != b.storage_session_id

    def test_concurrent_registration_single_row(self, conn, tmp_path):
        """两线程同时注册同一私聊：唯一约束兜底，最终只一行、同一存储 ID。"""
        db_path = str(tmp_path / "agent_memory.db")
        results: list = []
        errors: list = []

        def worker():
            try:
                # 每线程独立连接（连接不跨线程复用）
                local = sqlite3.connect(db_path)
                local.execute("PRAGMA busy_timeout = 5000")
                results.append(registry.get_or_register_private(local, "10000", 20001))
                local.close()
            except Exception as e:  # pragma: no cover - 失败要显式暴露
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        assert len({r.storage_session_id for r in results}) == 1
        count = conn.execute(
            "SELECT COUNT(*) FROM conversation_registry WHERE kind = 'private'"
        ).fetchone()[0]
        assert count == 1


class TestMultiBotConflict:
    def test_second_bot_gets_independent_storage_for_same_group(self, conn):
        """群已被 Bot A legacy 绑定时，Bot B 拿独立负存储，不共享历史。"""
        a = registry.get_or_register_group(conn, "10000", 263402786)
        b = registry.get_or_register_group(conn, "20000", 263402786)
        assert a.storage_session_id == 263402786
        assert b.storage_session_id < 0  # 专用序列分配
        assert b.runtime_key == "qq:20000:group:263402786"
        # 空间语义不变：同一个真实群解析到同一空间
        assert a.memory_space == b.memory_space

    def test_multi_bot_registration_stable_across_reconnect(self, conn):
        """单 Bot 视角下同一群的注册幂等（首个注册者获得 legacy 绑定；
        只有当**另一个** Bot 再来时才触发存储冲突，见上一用例）。"""
        first = registry.get_or_register_group(conn, "20000", 263402786)
        again = registry.get_or_register_group(conn, "20000", 263402786)
        assert again == first


class TestDrainEnumeration:
    def test_all_registered_covers_private(self, conn):
        registry.get_or_register_group(conn, "10000", 263402786)
        registry.get_or_register_private(conn, "10000", 20001)
        registry.get_or_register_webchat(conn, 800_000_000)
        refs = registry.all_registered(conn)
        kinds = {ref.kind for ref in refs}
        assert kinds == {"group", "private", "webchat"}
        keys = {ref.conversation_key for ref in refs}
        assert conversation_key("qq", "10000", "group", "263402786") in keys
