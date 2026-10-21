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
from core.transport.models import BotRef, SceneRef
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


class TestTransportRegistry:
    def test_v2_registration_preserves_opaque_identity_and_legacy_alias(self, conn, tmp_path):
        bot = BotRef("connection:one", "adapter", "platform", "bot:007")
        scene = SceneRef("thread", "频道/雪", ("server:1", "channel/2"), "thread:9")
        alias = "qq:10000:group:263402786"

        registered = registry.register_conversation_v2(
            conn, bot, scene, legacy_aliases=(alias,)
        )

        assert registered.scene == scene
        assert registered.bot == bot
        assert registered.storage_session_id < -1
        assert registered.memory_space == f"transport:{registered.canonical_key}"
        assert registry.lookup_conversation_v2(conn, bot, scene) == registered
        assert registry.lookup_conversation_v2_by_alias(
            conn, alias, bot=bot, scene=scene
        ) == registered

        # A fresh connection models process restart and must resolve persisted aliases.
        reopened = sqlite3.connect(tmp_path / "agent_memory.db")
        try:
            assert registry.lookup_conversation_v2_by_alias(reopened, alias) == registered
            assert registry.lookup_conversation_v2(reopened, bot, scene) == registered
        finally:
            reopened.close()

    def test_alias_collision_across_bots_fails_closed_without_context(self, conn):
        scene = SceneRef("channel", "same-opaque-id", ("server",))
        bots = [
            BotRef("connection-a", "adapter", "platform", "same-bot-id"),
            BotRef("connection-b", "adapter", "platform", "same-bot-id"),
        ]
        refs = [
            registry.register_conversation_v2(
                conn, bot, scene, legacy_aliases=("runtime:shared-alias",)
            )
            for bot in bots
        ]

        assert refs[0].storage_session_id != refs[1].storage_session_id
        assert refs[0].memory_space != refs[1].memory_space
        assert registry.lookup_conversation_v2_by_alias(conn, "runtime:shared-alias") is None
        assert registry.lookup_conversation_v2_by_alias(
            conn,
            "runtime:shared-alias",
            bot=bots[0],
            scene=scene,
        ) == refs[0]
        assert registry.lookup_conversation_v2_by_alias(
            conn,
            "runtime:shared-alias",
            bot=bots[1],
            scene=scene,
        ) == refs[1]

    def test_legacy_enumeration_does_not_coerce_v2_rows(self, conn):
        bot = BotRef("connection-a", "adapter", "platform", "bot-id")
        scene = SceneRef("group", "not-an-integer")
        registered = registry.register_conversation_v2(conn, bot, scene)

        assert registry.all_registered(conn) == []
        assert registry.all_registered_v2(conn) == [registered]
        assert registry.lookup(conn, registered.canonical_key) is None
        assert registry.lookup_by_storage_session_id(
            conn, registered.storage_session_id
        ) is None

    @pytest.mark.parametrize("register_v2_first", [False, True])
    def test_legacy_and_v2_allocators_share_negative_id_sequence(
        self, conn, register_v2_first
    ):
        bot = BotRef("connection-a", "adapter", "platform", "bot-id")
        scene = SceneRef("channel", "opaque-id")

        if register_v2_first:
            transport_ref = registry.register_conversation_v2(conn, bot, scene)
            legacy_ref = registry.get_or_register_private(conn, "10000", 20001)
        else:
            legacy_ref = registry.get_or_register_private(conn, "10000", 20001)
            transport_ref = registry.register_conversation_v2(conn, bot, scene)

        assert transport_ref.storage_session_id != legacy_ref.storage_session_id
        assert min(transport_ref.storage_session_id, legacy_ref.storage_session_id) < -1

    def test_v2_registration_is_idempotent_and_adds_new_aliases(self, conn):
        bot = BotRef("connection-a", "adapter", "platform", "bot-id")
        scene = SceneRef("private", "opaque-user-id")
        first = registry.register_conversation_v2(
            conn, bot, scene, legacy_aliases=("old-runtime-key",)
        )
        second = registry.register_conversation_v2(
            conn,
            bot,
            scene,
            legacy_aliases=("old-runtime-key", "new-runtime-key"),
        )

        assert second.storage_session_id == first.storage_session_id
        assert second.legacy_aliases == ("new-runtime-key", "old-runtime-key")
        assert registry.lookup_conversation_v2_by_alias(
            conn, "new-runtime-key", bot=bot, scene=scene
        ) == second

    def test_concurrent_v2_registrations_allocate_distinct_storage_ids(self, conn, tmp_path):
        db_path = str(tmp_path / "agent_memory.db")
        barrier = threading.Barrier(6)
        results = []
        errors = []

        def worker(index: int) -> None:
            local = sqlite3.connect(db_path, timeout=5)
            try:
                local.execute("PRAGMA busy_timeout = 5000")
                bot = BotRef(f"connection-{index}", "adapter", "platform", "bot-id")
                scene = SceneRef("channel", f"opaque:{index}/雪")
                barrier.wait(timeout=5)
                results.append(registry.register_conversation_v2(local, bot, scene))
            except Exception as exc:  # pragma: no cover - failures are surfaced below
                errors.append(exc)
            finally:
                local.close()

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not errors, errors
        assert all(not thread.is_alive() for thread in threads)
        assert len(results) == 6
        assert len({ref.storage_session_id for ref in results}) == 6
        assert all(ref.storage_session_id < -1 for ref in results)
