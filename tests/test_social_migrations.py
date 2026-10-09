# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""社交旁表组件迁移（memory/social_schema.py）的行为测试。

覆盖计划 §8.1 迁移矩阵的核心行：原版四表 / 空库 / 重复迁移 / 失败中断 →
正确恢复且旧记录守恒；legacy 无来源 → 不猜 scope；重复执行不增量复制。
测试一律使用临时库，禁止连接生产库。
"""

from __future__ import annotations

import sqlite3

import pytest

from memory.social_schema import (
    SOCIAL_SCHEMA_VERSION,
    ensure_social_schema,
    social_schema_version,
)


def _make_legacy_db(path, *, with_legacy: bool = True) -> None:
    """构造一个带旧表达系统四表的库（与 memory/expression_store.py 同构）。"""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE expression_examples (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT NOT NULL,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'phrase',
            source TEXT NOT NULL DEFAULT 'AT_MENTION',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE jargon_glossary (
            term TEXT NOT NULL,
            group_shared_space TEXT NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'candidate',
            first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (term, group_shared_space)
        );
        CREATE TABLE reply_effects (
            id TEXT PRIMARY KEY,
            group_shared_space TEXT NOT NULL,
            group_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            trigger TEXT NOT NULL DEFAULT 'reply',
            reply_excerpt TEXT NOT NULL DEFAULT '',
            asked_at_mono REAL NOT NULL,
            asked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL DEFAULT '',
            resolved_at DATETIME
        );
        """
    )
    if with_legacy:
        conn.execute(
            "INSERT INTO expression_examples (id, group_shared_space, user_id, text, kind) "
            "VALUES ('e1', '123456', '100', '这也太离谱了吧', 'phrase')"
        )
        conn.execute(
            "INSERT INTO expression_examples (id, group_shared_space, user_id, text, kind) "
            "VALUES ('e2', '123456', '200', '这也太离谱了吧', 'phrase')"
        )
        conn.execute(
            "INSERT INTO expression_examples (id, group_shared_space, user_id, text, kind) "
            "VALUES ('e3', 'shared_space', '300', '好耶', 'phrase')"
        )
        conn.execute(
            "INSERT INTO jargon_glossary (term, group_shared_space, hit_count, status) "
            "VALUES ('yyds', '123456', 7, 'candidate')"
        )
        conn.execute(
            "INSERT INTO reply_effects (id, group_shared_space, group_id, user_id, "
            "trigger, reply_excerpt, asked_at_mono, resolved, outcome) "
            "VALUES ('r1', '123456', '123456', '100', 'reply', '回复片段', 12.5, 1, 'responded')"
        )
        conn.execute(
            "INSERT INTO reply_effects (id, group_shared_space, group_id, user_id, "
            "trigger, reply_excerpt, asked_at_mono, resolved) "
            "VALUES ('r2', '123456', '123456', '0', 'proactive', '', 99.0, 0)"
        )
    conn.commit()
    conn.close()


@pytest.fixture()
def spaced(tmp_path, monkeypatch):
    """把空间 123456 唯一映射到真实群 123456（迁移 scope 判定的前提）。"""
    import config.spaces as spaces

    spaces_dir = tmp_path / "spaces"
    spaces_dir.mkdir(exist_ok=True)
    (spaces_dir / "123456.toml").write_text("qq_groups = [123456]\n", encoding="utf-8")
    monkeypatch.setattr(spaces, "SPACES_DIR", spaces_dir)
    monkeypatch.setattr(spaces, "_AUTO_FILE", tmp_path / ".space_assignments.json")
    spaces.reload()
    yield
    spaces.reload()


def _count(db, sql: str) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute(sql).fetchone()[0])
    finally:
        conn.close()


class TestFreshDatabase:
    def test_empty_db_gets_all_tables_and_version(self, tmp_path):
        db = tmp_path / "fresh.db"
        stats = ensure_social_schema(db, backup=False)
        assert stats == {}
        assert social_schema_version(db) == SOCIAL_SCHEMA_VERSION
        conn = sqlite3.connect(db)
        try:
            names = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        for table in (
            "social_schema_meta", "social_events", "social_deliveries", "social_effects",
            "social_delivery_plans",
            "social_effect_evidence", "social_assets", "social_asset_evidence",
            "social_asset_usage", "social_aggregate_events", "social_jobs",
            "social_migration_map",
        ):
            assert table in names, table

    def test_re_run_is_noop(self, tmp_path):
        db = tmp_path / "fresh.db"
        ensure_social_schema(db, backup=False)
        assert ensure_social_schema(db, backup=False) == {}
        assert social_schema_version(db) == SOCIAL_SCHEMA_VERSION


class TestLegacyImport:
    def test_legacy_rows_imported_idempotently(self, tmp_path, spaced):
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        stats = ensure_social_schema(db, backup=False)
        # 3 条表达样本 → 3 证据 + 2 资产（同 space 同文聚合）；1 黑话；2 旧效果
        assert stats["assets"] == 3
        assert stats["effects"] == 2
        assert _count(db, "SELECT COUNT(*) FROM social_asset_evidence") == 3
        assert _count(db, "SELECT COUNT(*) FROM social_events WHERE source_kind='LEGACY'") == 3

        # 重复执行不增量复制
        stats2 = ensure_social_schema(db, backup=False)
        assert stats2 == {}
        assert _count(db, "SELECT COUNT(*) FROM social_assets") == 3
        assert _count(db, "SELECT COUNT(*) FROM social_effects") == 2
        assert _count(db, "SELECT COUNT(*) FROM social_asset_evidence") == 3

    def test_real_group_scope_only_when_reliably_resolvable(self, tmp_path, spaced):
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        ensure_social_schema(db, backup=False)
        conn = sqlite3.connect(db)
        try:
            # 空间 123456 唯一对应真实群 → 赋 qq scope（bot_id 未知留空）
            scoped = conn.execute(
                "SELECT COUNT(*) FROM social_assets WHERE kind='expression' "
                "AND platform='qq' AND group_id='123456'"
            ).fetchone()[0]
            # shared_space 解析不出唯一群 → legacy_unscoped（group_id=''），
            # 且 legacy_scope 保留原名供人工核对
            unscoped = conn.execute(
                "SELECT COUNT(*) FROM social_assets WHERE group_id='' "
                "AND legacy_scope='shared_space'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert scoped == 1
        assert unscoped == 1

    def test_numeric_space_falls_back_to_group_number(self, tmp_path):
        """数字空间名按项目约定即群号（config.spaces.qq_groups_of 的历史回退）：
        即使没有空间 TOML，也视为可靠映射；非数字空间名一律不猜。"""
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        ensure_social_schema(db, backup=False)
        conn = sqlite3.connect(db)
        try:
            scoped = conn.execute(
                "SELECT COUNT(*) FROM social_assets WHERE platform='qq' AND group_id='123456'"
            ).fetchone()[0]
            unscoped = conn.execute(
                "SELECT COUNT(*) FROM social_assets WHERE group_id=''"
            ).fetchone()[0]
        finally:
            conn.close()
        assert scoped == 2  # 表达资产 1 + 黑话 1
        assert unscoped == 1  # shared_space 的「好耶」

    def test_legacy_effects_are_unverifiable_and_not_assessable(self, tmp_path, spaced):
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        ensure_social_schema(db, backup=False)
        conn = sqlite3.connect(db)
        try:
            rows = conn.execute(
                "SELECT status, assessable, target_user_id FROM social_effects "
                "ORDER BY effect_id"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 2
        for status, assessable, _target in rows:
            assert status == "legacy_unverifiable"
            assert assessable == 0
        # user_id=0（主动群聊旧路径）不猜目标：target 为 NULL
        targets = {r[2] for r in rows}
        assert None in targets

    def test_non_numeric_space_stays_unscoped_without_mapping(self, tmp_path):
        """非数字空间名在没有任何映射时不得猜群：shared_space 的资产全部隔离。"""
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        ensure_social_schema(db, backup=False)
        conn = sqlite3.connect(db)
        try:
            unscoped = conn.execute(
                "SELECT COUNT(*) FROM social_assets WHERE group_id='' "
                "AND legacy_scope='shared_space'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert unscoped == 1


class TestFailureSemantics:
    def test_failed_import_rolls_back_whole_upgrade(self, tmp_path, monkeypatch):
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        import memory.social_schema as schema_mod

        def boom(conn, now):
            raise RuntimeError("injected failure")

        monkeypatch.setattr(schema_mod, "_import_jargon", boom)
        with pytest.raises(RuntimeError):
            ensure_social_schema(db, backup=False)
        # 版本未提升；新表也不应残留（单事务回滚）
        assert social_schema_version(db) == 0
        conn = sqlite3.connect(db)
        try:
            names = {
                r[0]
                for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert "social_effects" not in names
        assert "social_schema_meta" not in names

    def test_backup_created_on_upgrade(self, tmp_path, spaced):
        db = tmp_path / "legacy.db"
        _make_legacy_db(db)
        ensure_social_schema(db)  # backup 默认开
        backups = list(tmp_path.glob("legacy.db.pre-social-*.bak"))
        assert len(backups) == 1
        # 备份可打开且含旧数据
        assert _count(backups[0], "SELECT COUNT(*) FROM expression_examples") == 3


class TestSchemaV2:
    """social schema v1→v3 增量迁移与最终投递摘要持久化。

    - v1 库直接打开即补列（conversation/kind/peer/storage/learning_eligible）；
    - 旧行以可信 QQ 群字段回填 eligibility（platform='qq' 且 group_id 非空）；
      缺 Bot/中立行不捏造 canonical key，保持 0；v3 digest 列幂等补齐；
    - 重复执行幂等；单事务失败回滚保持 v1。
    """

    def _make_v1_db(self, path) -> None:
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE social_deliveries (
                delivery_id TEXT PRIMARY KEY,
                turn_id TEXT NOT NULL,
                part_index INTEGER NOT NULL,
                trace_id TEXT NOT NULL DEFAULT '',
                epoch INTEGER NOT NULL DEFAULT 0,
                platform TEXT NOT NULL DEFAULT '',
                bot_id TEXT NOT NULL DEFAULT '',
                group_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                platform_message_id TEXT,
                acknowledged_at_utc TEXT,
                text TEXT NOT NULL DEFAULT '',
                text_hash TEXT NOT NULL DEFAULT '',
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                UNIQUE (turn_id, part_index)
            );
            CREATE TABLE social_schema_meta (
                component TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO social_schema_meta (component, version) VALUES ('social', 1);
            INSERT INTO social_deliveries (delivery_id, turn_id, part_index, platform,
                bot_id, group_id, status, text, created_at_utc, updated_at_utc)
                VALUES ('g1', 't1', 0, 'qq', '10001', '123',
                        'acknowledged', '群回复', '2026-09-01T00:00:00.000',
                        '2026-09-01T00:00:00.000');
            INSERT INTO social_deliveries (delivery_id, turn_id, part_index, platform,
                bot_id, group_id, status, text, created_at_utc, updated_at_utc)
                VALUES ('n1', 't2', 0, '', '', '',
                        'acknowledged', '无身份旧行', '2026-09-01T00:00:00.000',
                        '2026-09-01T00:00:00.000');
            """
        )
        conn.commit()
        conn.close()

    def test_v1_database_migrates_to_v2_with_eligibility_backfill(self, tmp_path):
        db = tmp_path / "social-v1.db"
        self._make_v1_db(db)
        ensure_social_schema(db, backup=False)
        assert social_schema_version(db) == SOCIAL_SCHEMA_VERSION
        conn = sqlite3.connect(db)
        try:
            rows = dict(conn.execute(
                "SELECT delivery_id, learning_eligible FROM social_deliveries"
            ).fetchall())
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(social_deliveries)")}
        finally:
            conn.close()
        assert rows == {"g1": 1, "n1": 0}, "可信 QQ 群行=1，无身份行保持 0"
        for col in ("conversation_key", "conversation_kind", "peer_id",
                    "storage_session_id", "learning_eligible", "delivery_plan_id",
                    "delivery_plan_digest", "decision_digest"):
            assert col in cols, col
        conn = sqlite3.connect(db)
        try:
            assert conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='social_delivery_plans'"
            ).fetchone() == ("social_delivery_plans",)
        finally:
            conn.close()

    def test_re_run_after_v2_is_noop(self, tmp_path):
        db = tmp_path / "social-v1.db"
        self._make_v1_db(db)
        ensure_social_schema(db, backup=False)
        assert ensure_social_schema(db, backup=False) == {}
        assert social_schema_version(db) == SOCIAL_SCHEMA_VERSION

    def test_empty_database_directly_v2(self, tmp_path):
        db = tmp_path / "fresh.db"
        ensure_social_schema(db, backup=False)
        conn = sqlite3.connect(db)
        try:
            cols = {r[1] for r in conn.execute(
                "PRAGMA table_info(social_deliveries)")}
            plan_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='social_delivery_plans'"
            ).fetchone()
            empty_plan_count = conn.execute(
                "SELECT COUNT(*) FROM social_delivery_plans"
            ).fetchone()[0]
        finally:
            conn.close()
        assert "learning_eligible" in cols
        assert {"delivery_plan_id", "delivery_plan_digest", "decision_digest"} <= cols
        assert plan_table == ("social_delivery_plans",)
        assert empty_plan_count == 0
