# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""个人记忆并发与恢复测试（计划 §8.1/§8.2 tests/test_personal_memory_concurrency.py）。

覆盖：不同会话并发写同一用户的共享事实（证据唯一约束兜底、无丢失更新）、
证据重放幂等、持久缓存版本随提交推进。连接独立（SQLite 串行写 + 短事务）。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from core.conversation import qq_private_ref


@pytest.fixture()
def writer_env(tmp_path, monkeypatch):
    db = tmp_path / "agent_memory.db"
    db.touch()
    monkeypatch.setattr("memory.consolidator.DB_PATH", db)
    monkeypatch.setattr("memory.memory_manager.DB_PATH", db)
    import config

    monkeypatch.setattr(config, "PERSONAL_MEMORY_WRITE_ENABLED", True)
    import config.settings as settings

    monkeypatch.setattr(settings, "PERSONAL_MEMORY_WRITE_ENABLED", True)
    # 本组测试测的是「证据去重的并发写」，不是迁移竞态：单线程预先把 schema
    # 建到当前版本。否则两条工作线程会各自懒加载迁移——v16 起「全新库首写」
    # 才是真实迁移工作，线程间抢锁会让其中一方失败后被 suppress 吞掉、
    # 随即写库撞 no such table（CI linux 3.12 回归）。迁移并发本身由
    # tests/test_migrations.py 的并发序列化回归覆盖。
    from memory.schema import ensure_v2_schema

    assert ensure_v2_schema(db)
    return db


def _write(db_path, ref, content, source_row_id):
    """独立连接跑一次写入（模拟并发会话各自的整合事务）。"""
    conn = sqlite3.connect(db_path)
    try:
        from memory.consolidator import MemoryConsolidator as C

        c = C.__new__(C)
        counts = c._write_memory_candidates(
            ref.memory_space,
            [{
                "user_id": ref.peer_id,
                "type": "PREFERENCE",
                "content": content,
                "confidence": 0.8,
                "importance": 0.6,
                "source_message_ids": [source_row_id],
            }],
            sender_ids=[ref.peer_id],
            at_senders=[ref.peer_id],
            origin_group_id=ref.storage_session_id,
            conversation=ref,
            source_rows=[(source_row_id, ref.peer_id, content, "PRIVATE_DIRECT")],
        )
        conn.commit()
        return counts
    finally:
        conn.close()


class TestConcurrentEvidence:
    def test_two_conversations_same_fact_distinct_rows(self, writer_env):
        """两个私聊会话各自的整合写同一事实：候选不重复、证据各一行。

        候选表没有 (owner,audience,fact) 唯一约束（强化路径依赖同 space 相似
        合并），并发窗口下 SQLite 串行写保证 second writer 走 INSERT——这产生
        两行候选是**当前契约**；晋升路径的同 owner 相似合并会把它们收敛为
        一条记忆（见 test_promotion_merges_same_owner）。证据表唯一约束才是
        硬闸：同会话同消息行永远只有一条证据。
        """
        db = writer_env
        a = qq_private_ref("10000", 20001, storage_session_id=-2)
        b = qq_private_ref("10000", 20001, storage_session_id=-3)  # 同用户另一会话
        counts_a = _write(db, a, "希望被称呼为队长", 11)
        counts_b = _write(db, b, "希望被称呼为队长", 99)
        # B 的候选与 A 同 owner 同受众同空间（personal namespace 只由
        # owner+audience 决定）→ 走强化分支累积证据，而非重复立行
        assert counts_a["written"] == 1
        assert counts_b["reinforced"] == 1
        conn = sqlite3.connect(db)
        try:
            evidence = conn.execute(
                "SELECT COUNT(DISTINCT source_row_id), COUNT(*) FROM memory_evidence"
            ).fetchone()
        finally:
            conn.close()
        # 同一事实、两个会话的真实新证据：distinct source rows = 2
        assert evidence == (2, 2)

    def test_replay_same_row_no_double_evidence(self, writer_env):
        a = qq_private_ref("10000", 20001, storage_session_id=-2)
        assert _write(writer_env, a, "希望被称呼为队长", 11)["written"] == 1
        replay = _write(writer_env, a, "希望被称呼为队长", 11)
        assert replay["written"] == 0 and replay["skipped"] == 1
        conn = sqlite3.connect(writer_env)
        try:
            n = conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
        finally:
            conn.close()
        assert n == 1

    def test_concurrent_replay_bounded_by_unique_constraint(self, writer_env):
        """两线程同消息重放并发写：唯一约束兜底，证据仍只一行。"""
        db = writer_env
        ref = qq_private_ref("10000", 20001, storage_session_id=-2)
        results: list = []
        errors: list = []

        def worker():
            try:
                results.append(_write(db, ref, "希望被称呼为队长", 11))
            except Exception as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, errors
        conn = sqlite3.connect(db)
        try:
            n = conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]
        finally:
            conn.close()
        assert n == 1


class TestPromotionMergesSameOwner:
    def test_promotion_merges_same_owner(self, writer_env):
        """同 owner+audience 的相似候选晋升后收敛为一条记忆（计划 §6.5）。"""
        from memory.memory_manager import MemoryManager

        db = writer_env
        a = qq_private_ref("10000", 20001, storage_session_id=-2)
        _write(db, a, "希望被称呼为队长", 11)
        _write(db, a, "希望被称呼为队长", 99)  # 新消息行 → 强化同一候选
        manager = MemoryManager()
        manager.process_new_candidates()
        conn = sqlite3.connect(db)
        try:
            memories = conn.execute(
                "SELECT COUNT(*), MAX(owner_type), MAX(audience) FROM memories"
            ).fetchone()
            candidates_left = conn.execute(
                "SELECT COUNT(*) FROM memory_candidates WHERE status = 'CONFIRMED'"
            ).fetchone()[0]
        finally:
            conn.close()
        # 同归属相似合并：只立一条个人记忆，受众保持 PRIVATE_ONLY
        assert memories[0] == 1
        assert memories[1] == "PERSON"
        assert memories[2] == "PRIVATE_ONLY"
        assert candidates_left == 1
