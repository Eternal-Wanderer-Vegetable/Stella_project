# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 任务库（``STELLA_HOME/cometa/tasks.db``）的 schema 迁移。

独立 SQLite 文件（方案 §6.3）：cometa 的失败模式（worker 卡死、任务堆积、
协议演化）与记忆库/调度库完全不同，隔离后互不拖累。同一数据根的多实例
共库，用 ``instance_id`` 划分所有权。

版本策略与 scheduling/migrations.py 同款：``meta`` 表记录 ``schema_version``，
逐级幂等迁移；新库从 0 直接建到最新版。迁移失败抛 :class:`MigrationError`，
调用方必须停用 cometa——半套 schema 上跑任务比不跑更危险（幂等键失灵会
重复委派外部 Agent 改代码）。v1 全是 CREATE IF NOT EXISTS，天然可重放。
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

# 刻意不用 nonebot logger：独立 worker 进程不导入 NoneBot。
_LOGGER = logging.getLogger("cometa.migrations")

SCHEMA_VERSION = 1

_META_TABLE = "meta"

# tasks.state 的合法值（与 cometa.models.TaskState 一一对应；CHECK 在库层兜底）。
_TASK_STATES = (
    "queued",
    "starting",
    "running",
    "waiting_input",
    "waiting_approval",
    "cancelling",
    "cancelled",
    "succeeded",
    "partial",
    "failed",
    "timed_out",
    "recovering",
    "recovery_required",
)

_TASK_STATES_SQL = ", ".join(f"'{s}'" for s in _TASK_STATES)


class MigrationError(RuntimeError):
    """迁移失败。调用方必须停用 cometa，不得带病运行。"""


def default_db_path() -> Path:
    """任务库默认落点：``STELLA_HOME/cometa/tasks.db``。

    延迟解析 STELLA_HOME：worker 进程与测试环境不依赖 Bot 的 config 包。
    """
    from .config import _resolve_stella_home

    return _resolve_stella_home(dict(os.environ)) / "cometa" / "tasks.db"


def connect(db_path: Path | str) -> sqlite3.Connection:
    """打开任务库连接。短连接 + WAL + busy_timeout（与 scheduling 同款）。

    ``busy_timeout``（10s）必须**小于**受理接口预算（COMETA_SUBMIT_TIMEOUT_SECONDS
    默认 2s 的上游是调用方）；数据库仍繁忙时写路径抛 :class:`sqlite3.
    OperationalError`，服务层译成「忙碌/待确认」而不是重试到天荒地老。
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _apply_v1(conn: sqlite3.Connection) -> None:
    """v1：任务 / attempt / 事件 / 结果 / 产物 / 输入 / 控制 / 通知 /
    worker 租约 / 工作区租约 / 审计 十一张表与全部索引（方案 §6.3）。"""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            instance_id TEXT NOT NULL,
            origin_platform TEXT NOT NULL,
            origin_scope TEXT NOT NULL,
            origin_json TEXT NOT NULL,
            spec_json TEXT NOT NULL,
            config_snapshot TEXT NOT NULL DEFAULT '{{}}',
            idempotency_key TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL DEFAULT '',
            requester_id TEXT NOT NULL,
            group_id TEXT NOT NULL DEFAULT '',
            backend_id TEXT NOT NULL DEFAULT '',
            profile TEXT NOT NULL DEFAULT '',
            workspace_id TEXT NOT NULL DEFAULT '',
            workspace_key TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL DEFAULT 'queued'
                CHECK (state IN ({_TASK_STATES_SQL})),
            revision INTEGER NOT NULL DEFAULT 1,
            current_attempt TEXT NOT NULL DEFAULT '',
            attempt_no INTEGER NOT NULL DEFAULT 0,
            phase TEXT NOT NULL DEFAULT '',
            last_activity_utc TEXT,
            heartbeat_utc TEXT,
            deadline_utc TEXT,
            waiting_request_id TEXT NOT NULL DEFAULT '',
            result_id TEXT NOT NULL DEFAULT '',
            delivery_state TEXT NOT NULL DEFAULT '',
            retry_of TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """
    )
    # 受理幂等（方案 §6.3）：相同 (instance, 会话, key) 只有一个任务；
    # 同 key 不同内容由 store 读出 content_hash 后判冲突（不能靠唯一索引区分）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_tasks_idem ON tasks"
        "(instance_id, origin_scope, idempotency_key) WHERE idempotency_key != ''"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_state ON tasks"
        "(instance_id, state, created_utc)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_requester ON tasks"
        "(instance_id, requester_id, state)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS attempts (
            attempt_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_no INTEGER NOT NULL,
            backend_id TEXT NOT NULL DEFAULT '',
            backend_version TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            turn_id TEXT NOT NULL DEFAULT '',
            launch_phase TEXT NOT NULL DEFAULT 'claimed',
            lease_owner TEXT NOT NULL DEFAULT '',
            lease_epoch INTEGER NOT NULL DEFAULT 1,
            lease_until_utc TEXT,
            usage_json TEXT NOT NULL DEFAULT '{}',
            started_utc TEXT,
            finished_utc TEXT,
            created_utc TEXT NOT NULL,
            UNIQUE (task_id, attempt_no)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_attempts_lease ON attempts(lease_until_utc)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_attempts_task ON attempts(task_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            task_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            attempt_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            backend_event_id TEXT NOT NULL DEFAULT '',
            occurred_utc TEXT NOT NULL,
            PRIMARY KEY (task_id, sequence)
        )
        """
    )
    # 原生事件唯一键（可空）：后端自带事件 ID 时防重放（方案 §6.3）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_events_native ON events"
        "(attempt_id, backend_event_id) WHERE backend_event_id != ''"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS results (
            result_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL DEFAULT '',
            outcome TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            final_text_ref TEXT NOT NULL DEFAULT '',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            limitations_json TEXT NOT NULL DEFAULT '[]',
            error TEXT NOT NULL DEFAULT '',
            usage_json TEXT NOT NULL DEFAULT '{}',
            manifest_ref TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_results_task ON results(task_id, created_utc)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            result_id TEXT NOT NULL DEFAULT '',
            relative_storage_key TEXT NOT NULL,
            sha256 TEXT NOT NULL DEFAULT '',
            size INTEGER NOT NULL DEFAULT 0,
            mime TEXT NOT NULL DEFAULT '',
            display_name TEXT NOT NULL DEFAULT '',
            availability TEXT NOT NULL DEFAULT 'available',
            created_utc TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_artifacts_task ON artifacts(task_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS input_requests (
            request_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL DEFAULT '',
            connection_generation INTEGER NOT NULL DEFAULT 0,
            backend_request_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'input',
            question TEXT NOT NULL DEFAULT '',
            schema_json TEXT NOT NULL DEFAULT '{}',
            options_json TEXT NOT NULL DEFAULT '[]',
            state TEXT NOT NULL DEFAULT 'pending',
            revision INTEGER NOT NULL DEFAULT 1,
            expires_utc TEXT,
            answer TEXT NOT NULL DEFAULT '',
            answered_utc TEXT,
            created_utc TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_inputs_task ON input_requests(task_id, state)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS controls (
            control_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            request_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'pending',
            idempotency_key TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            result_note TEXT NOT NULL DEFAULT '',
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """
    )
    # 取消/答复幂等（方案 §6.10：同一请求重复答复，相同内容返回原结果）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_controls_idem ON controls"
        "(task_id, idempotency_key) WHERE idempotency_key != ''"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_controls_state ON controls(state, created_utc)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            sequence INTEGER NOT NULL DEFAULT 0,
            dedupe_key TEXT NOT NULL DEFAULT '',
            target_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'pending',
            receipt TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            send_attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_utc TEXT,
            created_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """
    )
    # 同任务 dedupe_key 唯一：ack 只有一条；final 覆盖过时 progress（§6.11）。
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_notifications_dedupe ON notifications"
        "(task_id, dedupe_key) WHERE dedupe_key != ''"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_state ON notifications"
        "(state, next_attempt_utc)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_task ON notifications"
        "(task_id, created_utc)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_leases (
            instance_id TEXT PRIMARY KEY,
            worker_id TEXT NOT NULL,
            process_identity TEXT NOT NULL DEFAULT '',
            epoch INTEGER NOT NULL DEFAULT 1,
            lease_until_utc TEXT NOT NULL,
            updated_utc TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_leases (
            workspace_key TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL DEFAULT '',
            epoch INTEGER NOT NULL DEFAULT 1,
            lease_until_utc TEXT NOT NULL,
            acquired_utc TEXT NOT NULL
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_utc TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            task_id TEXT NOT NULL DEFAULT '',
            request_id TEXT NOT NULL DEFAULT '',
            attempt_id TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT ''
        )
        """
    )


_MIGRATIONS = {1: _apply_v1}


def migrate(db_path: Path | str) -> None:
    """把库迁移到 :data:`SCHEMA_VERSION`；已就绪则空操作（幂等，可每次启动调用）。

    任何一步失败都回滚当前迁移并抛 :class:`MigrationError`——**不删除、不改写
    已有数据**，库保持在旧版本，cometa 由调用方停用。
    """
    db_path = Path(db_path)
    if db_path.parent and not db_path.parent.exists():
        # 刻意只建 cometa 库自己的目录；STELLA_HOME 由 deploy init 负责
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
                f"cometa 库 schema 版本 {version} 高于本程序支持的 {SCHEMA_VERSION}——"
                "这是降级部署，拒绝运行以免误读新字段（方案 §9）"
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
                raise MigrationError(f"cometa 库迁移到 v{target} 失败: {e}") from e
            _LOGGER.info("cometa schema migrated to v%s", target)
        conn.close()
    except Exception:
        with_name = getattr(conn, "close", None)
        if callable(with_name):
            with_name()
        raise


__all__ = ["SCHEMA_VERSION", "MigrationError", "connect", "default_db_path", "migrate"]
