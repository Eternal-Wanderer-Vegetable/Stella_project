# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度库（``STELLA_HOME/scheduling/tasks.db``）的 schema 版本迁移。

刻意用**独立的 SQLite 文件**而不是挂在记忆库（``memory/agent_memory.db``）上：
调度任务的失败模式（worker 卡死、配额打满、任务爆炸式增长）与记忆库完全不同，
隔离后互不拖累，也免去记忆库 schema 版本与本子系统的版本耦合（计划 §3）。

版本策略与 ``memory/schema.py`` 同款：``meta`` 表记录 ``schema_version``，逐级
幂等迁移；新库从 0 直接建到最新版。**迁移失败抛** :class:`MigrationError`，
调用方（runtime 接线）必须因此保持 worker 停用——半套 schema 上跑调度比不跑
更危险（幂等键失灵会重复投递）。v1 全是 CREATE IF NOT EXISTS，天然可重放。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nonebot import logger

# 当前 schema 版本。每 +1 必须新增一个 _apply_vN 并配一个旧库回归测试
# （与 memory/schema.py 的「本版不做数据迁移禁令」同一纪律；本库暂无历史数据
# 要搬，v1 是纯建表）。
SCHEMA_VERSION = 1

_META_TABLE = "meta"


class MigrationError(RuntimeError):
    """迁移失败。runtime 捕获后必须停用 worker，不得带病运行。"""


def default_db_path() -> Path:
    """调度库的默认落点：``STELLA_HOME/scheduling/tasks.db``。

    延迟导入 config：本模块会在 nonebot 未启动的测试环境被 import，而 config
    的导入成本高且带 .env 副作用，没必要在模块加载时付。
    """
    from config import STELLA_HOME

    return Path(STELLA_HOME) / "scheduling" / "tasks.db"


def connect(db_path: Path | str) -> sqlite3.Connection:
    """打开调度库连接。每次操作短连接（与 memory/proactive_state.py 同款），
    WAL 模式提升并发读；``timeout`` 给写入方留排队余量。"""
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _apply_v1(conn: sqlite3.Connection) -> None:
    """v1：任务 / 运行 / 每日配额 / worker 租约 / 审计 五张表与全部索引。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL DEFAULT '',
            bot_id TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('reminder', 'agent')),
            objective TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            timezone TEXT NOT NULL,
            policy_json TEXT NOT NULL DEFAULT '{}',
            revision INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'paused', 'cancelled')),
            next_run_utc TEXT,
            last_run_utc TEXT,
            max_model_rounds INTEGER NOT NULL DEFAULT 4,
            max_tool_calls INTEGER NOT NULL DEFAULT 8,
            run_timeout_seconds REAL NOT NULL DEFAULT 300.0,
            output_max_chars INTEGER NOT NULL DEFAULT 1200,
            notification_mode TEXT NOT NULL DEFAULT 'on_content'
                CHECK (notification_mode IN ('always', 'on_content')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tasks_group ON tasks(group_id, status)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            task_revision INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            idempotency_key TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ('queued', 'claimed', 'running', 'ready', 'sending',
                                 'sent', 'silent', 'failed', 'skipped', 'cancelled',
                                 'delivery_unknown')),
            scheduled_for_utc TEXT,
            request_id TEXT NOT NULL DEFAULT '',
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_expires_utc TEXT,
            model_rounds INTEGER NOT NULL DEFAULT 0,
            tool_calls INTEGER NOT NULL DEFAULT 0,
            result_text TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            delivery_receipt TEXT NOT NULL DEFAULT '',
            delivery_error TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL DEFAULT '',
            queued_at_utc TEXT NOT NULL,
            claimed_at_utc TEXT,
            finished_at_utc TEXT
        )
        """
    )
    # 幂等键唯一：Cron 触发 = task:revision:scheduled_for；人工 = task:revision:manual:request_id。
    # INSERT OR IGNORE 靠它挡住重复入队（停机补跑、并发 worker、重放）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_idem ON runs(idempotency_key)"
    )
    # 计划 §6.1 的出现唯一键；同时充当「同一修订同一触发时刻只跑一次」的硬约束。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_occurrence "
        "ON runs(task_id, task_revision, scheduled_for_utc) "
        "WHERE scheduled_for_utc IS NOT NULL"
    )
    # 每任务至多一个活跃运行（部分唯一索引；SQLite 3.8+ 支持 partial index）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_runs_active_per_task "
        "ON runs(task_id) "
        "WHERE state IN ('queued', 'claimed', 'running', 'ready', 'sending')"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_runs_claim ON runs(state, scheduled_for_utc)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_runs_task ON runs(task_id, queued_at_utc)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quotas (
            group_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            runs_used INTEGER NOT NULL DEFAULT 0,
            messages_used INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (group_id, day)
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_lease (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            worker_id TEXT NOT NULL,
            expires_at_utc TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            task_id TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_audit_group ON audit_log(group_id, created_at)")


_MIGRATIONS = {1: _apply_v1}


def migrate(db_path: Path | str) -> None:
    """把库迁移到 :data:`SCHEMA_VERSION`；已就绪则空操作（幂等，可每次启动调用）。

    任何一步失败都回滚当前迁移并抛 :class:`MigrationError`——**不删除、不改写
    已有数据**，库保持在旧版本，worker 由调用方停用。
    """
    db_path = Path(db_path)
    if db_path.parent and not db_path.parent.exists():
        # 刻意只建调度库自己的目录；STELLA_HOME 由 deploy init 负责
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {_META_TABLE} "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            f"SELECT value FROM {_META_TABLE} WHERE key = 'schema_version'"
        ).fetchone()
        version = int(row[0]) if row else 0

        if version > SCHEMA_VERSION:
            raise MigrationError(
                f"调度库 schema 版本 {version} 高于本程序支持的 {SCHEMA_VERSION}——"
                "这是降级部署，拒绝运行以免误读新字段"
            )

        if version == SCHEMA_VERSION:
            conn.close()
            return

        for target in range(version + 1, SCHEMA_VERSION + 1):
            apply_fn = _MIGRATIONS.get(target)
            if apply_fn is None:
                raise MigrationError(f"缺少 v{target} 迁移实现（库版本 {version}）")
            try:
                with conn:
                    apply_fn(conn)
                    conn.execute(
                        f"INSERT INTO {_META_TABLE} (key, value) VALUES ('schema_version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(target),),
                    )
            except sqlite3.Error as e:
                raise MigrationError(f"调度库迁移到 v{target} 失败: {e}") from e
            logger.info(f"[Scheduling] 调度库 schema 已迁移到 v{target}")
        conn.close()
    except Exception:
        with_name = getattr(conn, "close", None)
        if callable(with_name):
            with_name()
        raise


__all__ = ["SCHEMA_VERSION", "MigrationError", "connect", "default_db_path", "migrate"]
