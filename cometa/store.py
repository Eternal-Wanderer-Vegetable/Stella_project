# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 任务库的事务性存取层（CometaStore，方案 §6.3）。

只做存取与并发原语，不做权限与业务判定——那些在 :mod:`.service` 与
:mod:`.policy`。并发正确性支柱：

1. **受理幂等**：``(instance_id, origin_scope, idempotency_key)`` 部分唯一索引；
   同 key 同内容回原任务，同 key 不同内容抛 :class:`IdempotencyConflictError`
   （**绝不能覆盖任务**，方案 §6.3 事务边界 1）；
2. **租约围栏**：attempt 持带期限租约，写入方必须携带 owner+epoch 对上才放行；
   过期只允许接管数据库控制权，不能证明旧 Agent 停了外部副作用（§6.8）；
3. **状态 CAS**：任务状态迁移全部条件更新（from_states + revision），
   终态不可被迟到的 progress 覆盖（§6.2）；
4. **通知同事务**：事件追加与通知 upsert 同事务（§6.3 事务边界 3）；
   final 出现后取消过时 progress；final / input_required 不可被覆盖。

事务模式：写路径一律 ``BEGIN IMMEDIATE`` 短事务（SQLite 串行写）；数据库繁忙
抛 :class:`StoreBusyError`，由服务层译成「提交状态待确认」——客户端继续用原
幂等键查询，**禁止换 key 重提**（§6.3）。

刻意不 import nonebot：独立 worker 进程（``python -m cometa.worker``）与本包共用。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from .migrations import connect, default_db_path, migrate
from .models import (
    ACTIVE_TASK_STATES,
    ArtifactAvailability,
    ControlKind,
    ControlState,
    EventKind,
    InputRequestState,
    NotificationKind,
    NotificationState,
    Origin,
    Outcome,
    TaskSpec,
    TaskState,
    VerificationStatus,
    iso_utc,
    lease_deadline,
    new_id,
    parse_iso_utc,
    utc_now,
)

_LOGGER = logging.getLogger("cometa.store")

_T = TypeVar("_T")

# 配额与工作区互斥检查计入的状态（占用真实资源）。
_BUSY_STATES_SQL = "('" + "', '".join(s.value for s in ACTIVE_TASK_STATES) + "')"


# ============================================================
# 错误
# ============================================================


class CometaStoreError(RuntimeError):
    """存取层错误基类。"""


class TaskNotFoundError(CometaStoreError):
    """任务不存在。"""


class IdempotencyConflictError(CometaStoreError):
    """同幂等键、不同任务内容（方案 §6.3：不能覆盖任务）。"""


class QuotaExceededError(CometaStoreError):
    """配额已满（受理事务内原子判定，方案 §6.3）。"""


class StaleLeaseError(CometaStoreError):
    """租约/代际校验失败：调用方已失去写权（CAS 落败）。"""


class StoreBusyError(CometaStoreError):
    """SQLite 繁忙。受理方应返回「提交状态待确认」，客户端沿用原幂等键。"""


class InputRequestStateError(CometaStoreError):
    """答复与请求状态不匹配（已答复/已过期/内容冲突）。"""


# ============================================================
# 行记录
# ============================================================


@dataclass(slots=True)
class TaskRecord:
    """tasks 行的内存形态。origin/spec 以 JSON 存库，读出时反序列化。"""

    task_id: str
    instance_id: str
    origin_platform: str
    origin_scope: str
    origin: Origin
    spec: TaskSpec
    config_snapshot: dict
    idempotency_key: str
    content_hash: str
    requester_id: str
    group_id: str
    backend_id: str
    profile: str
    workspace_id: str
    workspace_key: str
    state: TaskState
    revision: int
    current_attempt: str
    attempt_no: int
    phase: str
    last_activity_at: datetime | None
    heartbeat_at: datetime | None
    deadline_at: datetime | None
    waiting_request_id: str
    result_id: str
    delivery_state: str
    retry_of: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class AttemptRecord:
    attempt_id: str
    task_id: str
    attempt_no: int
    backend_id: str
    backend_version: str
    session_id: str
    turn_id: str
    launch_phase: str
    lease_owner: str
    lease_epoch: int
    lease_until: datetime | None
    usage: dict
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class EventRecord:
    task_id: str
    sequence: int
    attempt_id: str
    kind: EventKind
    payload: dict
    backend_event_id: str
    occurred_at: datetime


@dataclass(slots=True)
class ResultRecord:
    result_id: str
    task_id: str
    attempt_id: str
    outcome: Outcome
    summary: str
    final_text_ref: str
    evidence: list[dict]
    verification_status: VerificationStatus
    limitations: list[str]
    error: str
    usage: dict
    manifest_ref: str
    created_at: datetime


@dataclass(slots=True)
class ArtifactRecord:
    artifact_id: str
    task_id: str
    result_id: str
    relative_storage_key: str
    sha256: str
    size: int
    mime: str
    display_name: str
    availability: ArtifactAvailability
    created_at: datetime


@dataclass(slots=True)
class InputRequestRecord:
    request_id: str
    task_id: str
    attempt_id: str
    connection_generation: int
    backend_request_id: str
    kind: str  # input | approval
    question: str
    schema: dict
    options: list
    state: InputRequestState
    revision: int
    expires_at: datetime | None
    answer: str
    answered_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class ControlRecord:
    control_id: str
    task_id: str
    kind: ControlKind
    request_id: str
    payload: dict
    state: ControlState
    idempotency_key: str
    actor: str
    result_note: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class NotificationRecord:
    notification_id: str
    task_id: str
    kind: NotificationKind
    sequence: int
    dedupe_key: str
    target: dict
    payload: dict
    state: NotificationState
    receipt: str
    error: str
    send_attempts: int
    next_attempt_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class NotificationSpec:
    """随事件同事务 upsert 的通知（方案 §6.3 事务边界 3）。

    ``merge``=True 的通知（progress）允许被同 key 后续事件覆盖合并；
    final / input_required / ack 一律不可覆盖。
    """

    kind: NotificationKind
    dedupe_key: str
    payload: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    merge: bool = False


def origin_scope_of(origin: Origin) -> str:
    """受理幂等的会话范围键：同会话同 key 才判重，跨会话天然隔离。"""
    return f"{origin.platform}:{origin.conversation_id}"


def _loads_json(raw: str | None, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


# ============================================================
# Store
# ============================================================


class CometaStore:
    """cometa 库的门面。每个进程一个实例（短连接，线程安全靠 SQLite 串行写）。"""

    def __init__(self, db_path: Path | str | None = None, *, auto_migrate: bool = True):
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        if auto_migrate:
            migrate(self.db_path)

    # ── 连接与事务 ───────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    def _tx(self, fn: Callable[[sqlite3.Connection], _T]) -> _T:
        """BEGIN IMMEDIATE 短事务。繁忙译成 StoreBusyError（不重试——受理
        接口的预算决策在上层，方案 §6.3「返回明确忙碌状态」）。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = fn(conn)
            conn.commit()
            return result
        except sqlite3.OperationalError as e:
            conn.rollback()
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                raise StoreBusyError(f"cometa 数据库繁忙: {e}") from e
            raise
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _read(self, fn: Callable[[sqlite3.Connection], _T]) -> _T:
        conn = self._connect()
        try:
            return fn(conn)
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                raise StoreBusyError(f"cometa 数据库繁忙: {e}") from e
            raise
        finally:
            conn.close()

    # ── 行反序列化 ───────────────────────────────────────
    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            instance_id=row["instance_id"],
            origin_platform=row["origin_platform"],
            origin_scope=row["origin_scope"],
            origin=Origin.from_dict(_loads_json(row["origin_json"], {})),
            spec=TaskSpec.from_dict(_loads_json(row["spec_json"], {})),
            config_snapshot=_loads_json(row["config_snapshot"], {}),
            idempotency_key=row["idempotency_key"] or "",
            content_hash=row["content_hash"] or "",
            requester_id=row["requester_id"],
            group_id=row["group_id"] or "",
            backend_id=row["backend_id"] or "",
            profile=row["profile"] or "",
            workspace_id=row["workspace_id"] or "",
            workspace_key=row["workspace_key"] or "",
            state=TaskState(row["state"]),
            revision=int(row["revision"]),
            current_attempt=row["current_attempt"] or "",
            attempt_no=int(row["attempt_no"]),
            phase=row["phase"] or "",
            last_activity_at=parse_iso_utc(row["last_activity_utc"]),
            heartbeat_at=parse_iso_utc(row["heartbeat_utc"]),
            deadline_at=parse_iso_utc(row["deadline_utc"]),
            waiting_request_id=row["waiting_request_id"] or "",
            result_id=row["result_id"] or "",
            delivery_state=row["delivery_state"] or "",
            retry_of=row["retry_of"] or "",
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
            updated_at=parse_iso_utc(row["updated_utc"]) or utc_now(),
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> AttemptRecord:
        return AttemptRecord(
            attempt_id=row["attempt_id"],
            task_id=row["task_id"],
            attempt_no=int(row["attempt_no"]),
            backend_id=row["backend_id"] or "",
            backend_version=row["backend_version"] or "",
            session_id=row["session_id"] or "",
            turn_id=row["turn_id"] or "",
            launch_phase=row["launch_phase"] or "claimed",
            lease_owner=row["lease_owner"] or "",
            lease_epoch=int(row["lease_epoch"]),
            lease_until=parse_iso_utc(row["lease_until_utc"]),
            usage=_loads_json(row["usage_json"], {}),
            started_at=parse_iso_utc(row["started_utc"]),
            finished_at=parse_iso_utc(row["finished_utc"]),
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            task_id=row["task_id"],
            sequence=int(row["sequence"]),
            attempt_id=row["attempt_id"] or "",
            kind=EventKind(row["kind"]),
            payload=_loads_json(row["payload_json"], {}),
            backend_event_id=row["backend_event_id"] or "",
            occurred_at=parse_iso_utc(row["occurred_utc"]) or utc_now(),
        )

    @staticmethod
    def _result_from_row(row: sqlite3.Row) -> ResultRecord:
        return ResultRecord(
            result_id=row["result_id"],
            task_id=row["task_id"],
            attempt_id=row["attempt_id"] or "",
            outcome=Outcome(row["outcome"]),
            summary=row["summary"] or "",
            final_text_ref=row["final_text_ref"] or "",
            evidence=_loads_json(row["evidence_json"], []),
            verification_status=VerificationStatus(row["verification_status"]),
            limitations=_loads_json(row["limitations_json"], []),
            error=row["error"] or "",
            usage=_loads_json(row["usage_json"], {}),
            manifest_ref=row["manifest_ref"] or "",
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
        )

    @staticmethod
    def _artifact_from_row(row: sqlite3.Row) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=row["artifact_id"],
            task_id=row["task_id"],
            result_id=row["result_id"] or "",
            relative_storage_key=row["relative_storage_key"],
            sha256=row["sha256"] or "",
            size=int(row["size"]),
            mime=row["mime"] or "",
            display_name=row["display_name"] or "",
            availability=ArtifactAvailability(row["availability"]),
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
        )

    @staticmethod
    def _input_from_row(row: sqlite3.Row) -> InputRequestRecord:
        return InputRequestRecord(
            request_id=row["request_id"],
            task_id=row["task_id"],
            attempt_id=row["attempt_id"] or "",
            connection_generation=int(row["connection_generation"]),
            backend_request_id=row["backend_request_id"] or "",
            kind=row["kind"],
            question=row["question"] or "",
            schema=_loads_json(row["schema_json"], {}),
            options=_loads_json(row["options_json"], []),
            state=InputRequestState(row["state"]),
            revision=int(row["revision"]),
            expires_at=parse_iso_utc(row["expires_utc"]),
            answer=row["answer"] or "",
            answered_at=parse_iso_utc(row["answered_utc"]),
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
        )

    @staticmethod
    def _control_from_row(row: sqlite3.Row) -> ControlRecord:
        return ControlRecord(
            control_id=row["control_id"],
            task_id=row["task_id"],
            kind=ControlKind(row["kind"]),
            request_id=row["request_id"] or "",
            payload=_loads_json(row["payload_json"], {}),
            state=ControlState(row["state"]),
            idempotency_key=row["idempotency_key"] or "",
            actor=row["actor"] or "",
            result_note=row["result_note"] or "",
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
            updated_at=parse_iso_utc(row["updated_utc"]) or utc_now(),
        )

    @staticmethod
    def _notification_from_row(row: sqlite3.Row) -> NotificationRecord:
        return NotificationRecord(
            notification_id=row["notification_id"],
            task_id=row["task_id"],
            kind=NotificationKind(row["kind"]),
            sequence=int(row["sequence"]),
            dedupe_key=row["dedupe_key"] or "",
            target=_loads_json(row["target_json"], {}),
            payload=_loads_json(row["payload_json"], {}),
            state=NotificationState(row["state"]),
            receipt=row["receipt"] or "",
            error=row["error"] or "",
            send_attempts=int(row["send_attempts"]),
            next_attempt_at=parse_iso_utc(row["next_attempt_utc"]),
            created_at=parse_iso_utc(row["created_utc"]) or utc_now(),
            updated_at=parse_iso_utc(row["updated_utc"]) or utc_now(),
        )

    # ── 事件序列 ─────────────────────────────────────────
    @staticmethod
    def _next_sequence(conn: sqlite3.Connection, task_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row[0]) + 1

    @staticmethod
    def _insert_event(
        conn: sqlite3.Connection,
        *,
        task_id: str,
        attempt_id: str,
        kind: EventKind,
        payload: dict,
        occurred_at: datetime,
        backend_event_id: str = "",
    ) -> int | None:
        """追加事件。原生事件 ID 冲突 = 重放，跳过（返回 None）。"""
        sequence = CometaStore._next_sequence(conn, task_id)
        try:
            conn.execute(
                "INSERT INTO events (task_id, sequence, attempt_id, kind, payload_json,"
                " backend_event_id, occurred_utc) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    sequence,
                    attempt_id,
                    kind.value,
                    json.dumps(payload or {}, ensure_ascii=False),
                    backend_event_id,
                    iso_utc(occurred_at),
                ),
            )
        except sqlite3.IntegrityError:
            return None
        return sequence

    # ── 通知 upsert（同事务调用） ────────────────────────
    @staticmethod
    def _upsert_notification(
        conn: sqlite3.Connection,
        *,
        task_id: str,
        spec: NotificationSpec,
        sequence: int,
        now: datetime,
    ) -> str:
        """按幂等策略 upsert 通知（方案 §6.11）：

        - merge（progress）：已发送/未知/过期行重新武装为 pending——旧 progress
          合并语义的落点；sending 中的行不碰（pump 正拿着）；
        - 不可合并（ack/final/input）：pending 行更新 payload；已进入投递流程的行
          **绝不重置**（不重复发送）。
        """
        existing = conn.execute(
            "SELECT * FROM notifications WHERE task_id = ? AND dedupe_key = ?",
            (task_id, spec.dedupe_key),
        ).fetchone()
        if existing is not None:
            state = NotificationState(existing["state"])
            if spec.merge and state is NotificationState.SENDING:
                return existing["notification_id"]  # pump 正在投递，不合并
            if spec.merge or state is NotificationState.PENDING:
                conn.execute(
                    "UPDATE notifications SET payload_json = ?, sequence = ?, "
                    "state = 'pending', error = '', next_attempt_utc = NULL, "
                    "updated_utc = ? WHERE notification_id = ?",
                    (
                        json.dumps(spec.payload, ensure_ascii=False),
                        sequence,
                        iso_utc(now),
                        existing["notification_id"],
                    ),
                )
                return existing["notification_id"]
            return existing["notification_id"]  # 已发送/未知：不重复
        notification_id = new_id()
        conn.execute(
            "INSERT INTO notifications (notification_id, task_id, kind, sequence,"
            " dedupe_key, target_json, payload_json, state, created_utc, updated_utc)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                notification_id,
                task_id,
                spec.kind.value,
                sequence,
                spec.dedupe_key,
                json.dumps(spec.target or {}, ensure_ascii=False),
                json.dumps(spec.payload or {}, ensure_ascii=False),
                iso_utc(now),
                iso_utc(now),
            ),
        )
        return notification_id

    @staticmethod
    def _target_from_task_row(conn: sqlite3.Connection, task_id: str) -> dict:
        """从任务行的 origin_json 派生通知投递目标。

        所有随事件同事务创建的通知（ack/final/input）必须带 target——
        否则泵按默认 qq + 空 group 发送，必然失败（2026-09-30 人工清单实测：
        final 全部 delivery_unknown，err=RuntimeError）。"""
        row = conn.execute(
            "SELECT origin_json FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return {}
        origin = Origin.from_dict(_loads_json(row["origin_json"], {}))
        return {
            "platform": origin.platform,
            "bot_id": origin.bot_id,
            "conversation_id": origin.conversation_id,
            "requester_id": origin.requester_id,
            "reply_to_message_id": origin.reply_to_message_id,
            "group_id": origin.conversation_id if origin.platform == "qq" else "",
        }

    @staticmethod
    def _supersede_progress(conn: sqlite3.Connection, task_id: str, now: datetime) -> None:
        conn.execute(
            "UPDATE notifications SET state = 'superseded', updated_utc = ? "
            "WHERE task_id = ? AND kind = 'progress' AND state = 'pending'",
            (iso_utc(now), task_id),
        )

    # ============================================================
    # 受理（事务边界 1，方案 §6.3）
    # ============================================================

    def submit_task(
        self,
        *,
        origin: Origin,
        spec: TaskSpec,
        idempotency_key: str,
        requester_id: str,
        group_id: str,
        backend_id: str,
        profile: str,
        workspace_id: str,
        workspace_key: str,
        deadline_at: datetime,
        config_snapshot: dict,
        task_id: str | None = None,
        retry_of: str = "",
        now: datetime | None = None,
    ) -> tuple[str, bool]:
        """受理任务：tasks + accepted 事件 + ack notification 同事务。

        返回 ``(task_id, created)``：同 key 同内容返回**原任务**（created=False）；
        同 key 不同内容抛 :class:`IdempotencyConflictError`；配额满抛
        :class:`QuotaExceededError`——配额检查与插入同事务，并发提交不会越限。
        """
        now = now or utc_now()
        origin_json = json.dumps(origin.to_dict(), ensure_ascii=False)
        spec_json = json.dumps(spec.to_dict(), ensure_ascii=False)
        content_hash = spec.content_fingerprint()
        snapshot_json = json.dumps(config_snapshot or {}, ensure_ascii=False)

        def _do(conn: sqlite3.Connection) -> tuple[str, bool]:
            if idempotency_key:
                row = conn.execute(
                    "SELECT task_id, content_hash FROM tasks"
                    " WHERE instance_id = ? AND origin_scope = ? AND idempotency_key = ?",
                    (origin.instance_id, origin_scope_of(origin), idempotency_key),
                ).fetchone()
                if row is not None:
                    if str(row["content_hash"] or "") != content_hash:
                        raise IdempotencyConflictError(
                            "同幂等键对应不同任务内容，拒绝覆盖（方案 §6.3）"
                        )
                    return str(row["task_id"]), False

            # 配额（同事务原子判定）
            active = _BUSY_STATES_SQL
            per_user = conn.execute(
                f"SELECT COUNT(*) FROM tasks WHERE instance_id = ? AND requester_id = ?"
                f" AND state IN {active}",
                (origin.instance_id, requester_id),
            ).fetchone()
            limits = (config_snapshot or {}).get("limits", {})
            per_user_max = int(limits.get("per_user_active", 1))
            if per_user and int(per_user[0]) >= per_user_max:
                raise QuotaExceededError(
                    f"该用户已有 {int(per_user[0])} 个进行中任务（上限 {per_user_max}）"
                )
            if group_id:
                per_group = conn.execute(
                    f"SELECT COUNT(*) FROM tasks WHERE instance_id = ? AND group_id = ?"
                    f" AND state IN {active}",
                    (origin.instance_id, group_id),
                ).fetchone()
                per_group_max = int(limits.get("per_group_active", 2))
                if per_group and int(per_group[0]) >= per_group_max:
                    raise QuotaExceededError(
                        f"该会话已有 {int(per_group[0])} 个进行中任务（上限 {per_group_max}）"
                    )

            tid = task_id or new_id()
            conn.execute(
                "INSERT INTO tasks (task_id, instance_id, origin_platform, origin_scope,"
                " origin_json, spec_json, config_snapshot, idempotency_key, content_hash,"
                " requester_id, group_id, backend_id, profile, workspace_id, workspace_key,"
                " state, revision, deadline_utc, retry_of, created_utc, updated_utc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 1, ?, ?, ?, ?)",
                (
                    tid,
                    origin.instance_id,
                    origin.platform,
                    origin_scope_of(origin),
                    origin_json,
                    spec_json,
                    snapshot_json,
                    idempotency_key,
                    content_hash,
                    requester_id,
                    group_id,
                    backend_id,
                    profile,
                    workspace_id,
                    workspace_key,
                    iso_utc(deadline_at),
                    retry_of,
                    iso_utc(now),
                    iso_utc(now),
                ),
            )
            ack_payload = {
                "state": "queued",
                "objective": spec.objective,
                "backend_id": backend_id,
            }
            ack_target = {
                "platform": origin.platform,
                "bot_id": origin.bot_id,
                "conversation_id": origin.conversation_id,
                "requester_id": origin.requester_id,
                "reply_to_message_id": origin.reply_to_message_id,
                "group_id": group_id,
            }
            self._insert_event(
                conn,
                task_id=tid,
                attempt_id="",
                kind=EventKind.ACCEPTED,
                payload=ack_payload,
                occurred_at=now,
            )
            self._upsert_notification(
                conn,
                task_id=tid,
                spec=NotificationSpec(
                    kind=NotificationKind.ACK,
                    dedupe_key=f"ack:{tid}",
                    payload=ack_payload,
                    target=ack_target,
                ),
                sequence=1,
                now=now,
            )
            return tid, True

        return self._tx(_do)

    # ============================================================
    # 认领（事务边界 2，方案 §6.3）
    # ============================================================

    def claim_next_task(
        self,
        *,
        instance_id: str,
        worker_id: str,
        backend_ids: set[str],
        lease_seconds: float,
        now: datetime | None = None,
    ) -> tuple[TaskRecord, AttemptRecord] | None:
        """认领一个可运行任务：条件更新 + 新 attempt + 租约 + started 事件 +
        工作区锁**同事务**。调用 Agent 前必须完成这次提交（方案 §6.3）。

        ``backend_ids`` 是本 worker 可用的后端集合：指定后端不在其中时跳过
        （多 worker 分工；单 worker 全量场景传全部启用后端）。
        """
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> tuple[TaskRecord, AttemptRecord] | None:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE instance_id = ? AND state = 'queued'"
                " ORDER BY created_utc ASC LIMIT 64",
                (instance_id,),
            ).fetchall()
            for row in rows:
                task = self._task_from_row(row)
                if task.backend_id and task.backend_id not in backend_ids:
                    continue
                if task.deadline_at is not None and task.deadline_at <= now:
                    continue  # 已到期：交给超时清扫，不认领
                if task.workspace_key:
                    lock = conn.execute(
                        "SELECT task_id FROM workspace_leases WHERE workspace_key = ?"
                        " AND lease_until_utc > ?",
                        (task.workspace_key, iso_utc(now)),
                    ).fetchone()
                    if lock is not None and str(lock["task_id"]) != task.task_id:
                        continue  # 同一工作区已有写任务（方案 §6.9）
                attempt_no = task.attempt_no + 1
                attempt_id = new_id()
                lease_until = lease_deadline(now, lease_seconds)
                conn.execute(
                    "INSERT INTO attempts (attempt_id, task_id, attempt_no, backend_id,"
                    " launch_phase, lease_owner, lease_epoch, lease_until_utc, created_utc)"
                    " VALUES (?, ?, ?, ?, 'claimed', ?, 1, ?, ?)",
                    (
                        attempt_id,
                        task.task_id,
                        attempt_no,
                        task.backend_id,
                        worker_id,
                        iso_utc(lease_until),
                        iso_utc(now),
                    ),
                )
                conn.execute(
                    "UPDATE tasks SET state = 'starting', current_attempt = ?,"
                    " attempt_no = ?, revision = revision + 1, phase = 'claimed',"
                    " heartbeat_utc = ?, updated_utc = ? WHERE task_id = ?",
                    (attempt_id, attempt_no, iso_utc(now), iso_utc(now), task.task_id),
                )
                if task.workspace_key:
                    conn.execute(
                        "INSERT INTO workspace_leases (workspace_key, task_id, attempt_id,"
                        " epoch, lease_until_utc, acquired_utc) VALUES (?, ?, ?, 1, ?, ?)"
                        " ON CONFLICT(workspace_key) DO UPDATE SET"
                        " task_id = excluded.task_id, attempt_id = excluded.attempt_id,"
                        " epoch = epoch + 1, lease_until_utc = excluded.lease_until_utc",
                        (
                            task.workspace_key,
                            task.task_id,
                            attempt_id,
                            iso_utc(lease_until),
                            iso_utc(now),
                        ),
                    )
                sequence = self._insert_event(
                    conn,
                    task_id=task.task_id,
                    attempt_id=attempt_id,
                    kind=EventKind.STARTED,
                    payload={"attempt_no": attempt_no, "backend_id": task.backend_id},
                    occurred_at=now,
                )
                conn.execute(
                    "UPDATE tasks SET last_activity_utc = ? WHERE task_id = ?",
                    (iso_utc(now), task.task_id),
                )
                updated = conn.execute(
                    "SELECT * FROM tasks WHERE task_id = ?", (task.task_id,)
                ).fetchone()
                attempt_row = conn.execute(
                    "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
                ).fetchone()
                _ = sequence  # started 事件不需要通知（§6.11：开始类最短合并间隔由 pump 管）
                return self._task_from_row(updated), self._attempt_from_row(attempt_row)
            return None

        return self._tx(_do)

    # ============================================================
    # attempt 生命周期（租约围栏）
    # ============================================================

    def get_attempt(self, attempt_id: str) -> AttemptRecord | None:
        def _do(conn: sqlite3.Connection) -> AttemptRecord | None:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            return self._attempt_from_row(row) if row is not None else None

        return self._read(_do)

    def get_task(self, task_id: str) -> TaskRecord | None:
        def _do(conn: sqlite3.Connection) -> TaskRecord | None:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return self._task_from_row(row) if row is not None else None

        return self._read(_do)

    def get_attempt_for(self, attempt_id: str, owner: str, epoch: int) -> AttemptRecord:
        """读取 attempt 并校验租约归属；不匹配抛 :class:`StaleLeaseError`。"""
        attempt = self.get_attempt(attempt_id)
        if attempt is None:
            raise TaskNotFoundError(f"attempt {attempt_id} 不存在")
        if attempt.lease_owner != owner or attempt.lease_epoch != epoch:
            raise StaleLeaseError(
                f"attempt {attempt_id} 租约已变更"
                f"（owner={attempt.lease_owner!r}/epoch={attempt.lease_epoch}）"
            )
        return attempt

    def update_launch_phase(
        self,
        attempt_id: str,
        owner: str,
        epoch: int,
        phase: str,
        *,
        session_id: str | None = None,
        turn_id: str | None = None,
        backend_version: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """推进 launch_phase（方案 §6.8 启动协议）。CAS：租约不匹配返回 False。"""
        now = now or utc_now()
        sets = ["launch_phase = ?"]
        params: list[object] = [phase]
        if session_id is not None:
            sets.append("session_id = ?")
            params.append(session_id)
        if turn_id is not None:
            sets.append("turn_id = ?")
            params.append(turn_id)
        if backend_version is not None:
            sets.append("backend_version = ?")
            params.append(backend_version)
        params.extend([attempt_id, owner, epoch])

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                f"UPDATE attempts SET {', '.join(sets)} WHERE attempt_id = ?"
                " AND lease_owner = ? AND lease_epoch = ?",
                params,
            )
            if cur.rowcount != 1:
                return False
            conn.execute(
                "UPDATE tasks SET phase = ?, heartbeat_utc = ?, updated_utc = ?"
                " WHERE task_id = (SELECT task_id FROM attempts WHERE attempt_id = ?)",
                (phase, iso_utc(now), iso_utc(now), attempt_id),
            )
            return True

        return self._tx(_do)

    def renew_lease(
        self, attempt_id: str, owner: str, *, lease_seconds: float, now: datetime | None = None
    ) -> bool:
        """续租（worker 每 lease_renew_seconds 一次）。CAS 失败 = 租约已丢。"""
        now = now or utc_now()
        lease_until = lease_deadline(now, lease_seconds)

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE attempts SET lease_until_utc = ? WHERE attempt_id = ?"
                " AND lease_owner = ? AND lease_until_utc > ?",
                (iso_utc(lease_until), attempt_id, owner, iso_utc(now)),
            )
            if cur.rowcount != 1:
                return False
            conn.execute(
                "UPDATE tasks SET heartbeat_utc = ? WHERE current_attempt = ?",
                (iso_utc(now), attempt_id),
            )
            return True

        return self._tx(_do)

    def take_over_expired_attempt(
        self, attempt_id: str, new_owner: str, *, lease_seconds: float, now: datetime | None = None
    ) -> AttemptRecord | None:
        """接管过期租约：**只允许接管数据库控制权**（方案 §6.8——租约过期
        不能证明旧 Agent 停止了外部副作用，外部核对是 executor 的职责）。"""
        now = now or utc_now()
        lease_until = lease_deadline(now, lease_seconds)

        def _do(conn: sqlite3.Connection) -> AttemptRecord | None:
            cur = conn.execute(
                "UPDATE attempts SET lease_owner = ?, lease_epoch = lease_epoch + 1,"
                " lease_until_utc = ? WHERE attempt_id = ? AND lease_until_utc <= ?",
                (new_owner, iso_utc(lease_until), attempt_id, iso_utc(now)),
            )
            if cur.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            return self._attempt_from_row(row)

        return self._tx(_do)

    def transition_task(
        self,
        task_id: str,
        *,
        attempt_id: str,
        owner: str,
        epoch: int,
        from_states: tuple[TaskState, ...],
        to_state: TaskState,
        phase: str | None = None,
        waiting_request_id: str | None = None,
        clear_waiting: bool = False,
        now: datetime | None = None,
    ) -> bool:
        """任务状态 CAS（租约围栏 + from_states + current_attempt 三重校验）。

        终态不可被迟到事件覆盖的保证就在这里：调用方给的 to_state 与
        from_states 都由 executor 显式枚举，终态从不出现在 from_states。
        """
        now = now or utc_now()
        from_sql = "('" + "', '".join(s.value for s in from_states) + "')"
        sets = ["state = ?", "revision = revision + 1", "heartbeat_utc = ?", "updated_utc = ?"]
        params: list[object] = [to_state.value, iso_utc(now), iso_utc(now)]
        if phase is not None:
            sets.append("phase = ?")
            params.append(phase)
        if waiting_request_id is not None:
            sets.append("waiting_request_id = ?")
            params.append(waiting_request_id)
        if clear_waiting:
            sets.append("waiting_request_id = ''")
        # WHERE 顺序：task_id、current_attempt、两个租约子查询各需 attempt_id+值
        params.extend([task_id, attempt_id, attempt_id, owner, attempt_id, epoch])

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?"
                f" AND current_attempt = ? AND state IN {from_sql}"
                " AND (SELECT lease_owner FROM attempts WHERE attempt_id = ?) = ?"
                " AND (SELECT lease_epoch FROM attempts WHERE attempt_id = ?) = ?",
                params,
            )
            return cur.rowcount == 1

        return self._tx(_do)

    def append_event(
        self,
        task_id: str,
        *,
        attempt_id: str = "",
        owner: str = "",
        epoch: int = 0,
        kind: EventKind,
        payload: dict,
        backend_event_id: str = "",
        occurred_at: datetime | None = None,
        notification: NotificationSpec | None = None,
        update_activity: bool = True,
        now: datetime | None = None,
    ) -> int | None:
        """追加归一事件；带租约围栏（owner+epoch 不匹配返回 None）。

        事件与通知同事务（方案 §6.3 事务边界 3）；原生事件 ID 冲突（重放）
        返回 -1，调用方按「已见过」处理。终态后的迟到 progress 一律拒绝：
        任务已终态时只接受 completed/failed/cancelled 类收尾事件。
        """
        now = now or utc_now()
        occurred_at = occurred_at or now

        def _do(conn: sqlite3.Connection) -> int | None:
            task = conn.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            state = TaskState(task["state"])
            is_terminal = state in TERMINAL_STATES_SET
            if is_terminal and kind in (
                EventKind.PROGRESS,
                EventKind.STARTED,
                EventKind.INPUT_REQUIRED,
                EventKind.APPROVAL_REQUIRED,
            ):
                return None  # 终态不可被迟到事件覆盖（方案 §6.2）
            if attempt_id and (owner or epoch):
                attempt = conn.execute(
                    "SELECT lease_owner, lease_epoch FROM attempts WHERE attempt_id = ?",
                    (attempt_id,),
                ).fetchone()
                if attempt is None:
                    raise TaskNotFoundError(f"attempt {attempt_id} 不存在")
                if str(attempt["lease_owner"]) != owner or int(attempt["lease_epoch"]) != epoch:
                    return None  # 租约已丢
            sequence = self._insert_event(
                conn,
                task_id=task_id,
                attempt_id=attempt_id,
                kind=kind,
                payload=payload,
                occurred_at=occurred_at,
                backend_event_id=backend_event_id,
            )
            if sequence is None:
                return -1
            if update_activity:
                conn.execute(
                    "UPDATE tasks SET last_activity_utc = ? WHERE task_id = ?",
                    (iso_utc(occurred_at), task_id),
                )
            if notification is not None:
                self._upsert_notification(
                    conn,
                    task_id=task_id,
                    spec=notification,
                    sequence=sequence,
                    now=now,
                )
                if notification.kind is NotificationKind.FINAL:
                    self._supersede_progress(conn, task_id, now)
            return sequence

        return self._tx(_do)

    # ============================================================
    # 输入与审批（方案 §6.10）
    # ============================================================

    def register_input_request(
        self,
        task_id: str,
        *,
        attempt_id: str,
        owner: str,
        epoch: int,
        backend_request_id: str,
        kind: str,
        question: str,
        schema: dict,
        options: list,
        expires_at: datetime,
        connection_generation: int = 0,
        now: datetime | None = None,
    ) -> str | None:
        """登记输入/审批请求并转入等待态（critical：立即提交+通知）。"""
        now = now or utc_now()
        request_id = new_id()
        waiting_state = (
            TaskState.WAITING_APPROVAL if kind == "approval" else TaskState.WAITING_INPUT
        )
        event_kind = (
            EventKind.APPROVAL_REQUIRED if kind == "approval" else EventKind.INPUT_REQUIRED
        )

        def _do(conn: sqlite3.Connection) -> str | None:
            attempt = conn.execute(
                "SELECT lease_owner, lease_epoch, task_id FROM attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or str(attempt["task_id"]) != task_id:
                return None
            if str(attempt["lease_owner"]) != owner or int(attempt["lease_epoch"]) != epoch:
                return None
            conn.execute(
                "INSERT INTO input_requests (request_id, task_id, attempt_id,"
                " connection_generation, backend_request_id, kind, question, schema_json,"
                " options_json, state, expires_utc, created_utc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    request_id,
                    task_id,
                    attempt_id,
                    connection_generation,
                    backend_request_id,
                    kind,
                    question,
                    json.dumps(schema or {}, ensure_ascii=False),
                    json.dumps(options or [], ensure_ascii=False),
                    iso_utc(expires_at),
                    iso_utc(now),
                ),
            )
            payload = {"request_id": request_id, "question": question, "kind": kind}
            sequence = self._insert_event(
                conn,
                task_id=task_id,
                attempt_id=attempt_id,
                kind=event_kind,
                payload=payload,
                occurred_at=now,
            )
            if sequence is None:
                return None
            self._upsert_notification(
                conn,
                task_id=task_id,
                spec=NotificationSpec(
                    kind=NotificationKind.INPUT_REQUIRED,
                    dedupe_key=f"input:{task_id}:{request_id}",
                    payload=payload,
                    target=self._target_from_task_row(conn, task_id),
                ),
                sequence=sequence,
                now=now,
            )
            conn.execute(
                "UPDATE tasks SET state = ?, waiting_request_id = ?, updated_utc = ?"
                " WHERE task_id = ? AND current_attempt = ? AND state IN"
                " ('running', 'starting', 'waiting_input', 'waiting_approval')",
                (waiting_state.value, request_id, iso_utc(now), task_id, attempt_id),
            )
            return request_id

        return self._tx(_do)

    def get_input_request(self, request_id: str) -> InputRequestRecord | None:
        def _do(conn: sqlite3.Connection) -> InputRequestRecord | None:
            row = conn.execute(
                "SELECT * FROM input_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            return self._input_from_row(row) if row is not None else None

        return self._read(_do)

    def respond_input(
        self,
        request_id: str,
        answer: str,
        *,
        actor: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> ControlReceiptLike:
        """答复输入请求（方案 §6.10）：revision 校验 + 状态 CAS + 控制命令同事务。

        - 重复答复相同内容 → 返回原结果（幂等）；
        - 重复答复不同内容 → :class:`InputRequestStateError`；
        - 已过期/已取消 → 同样拒绝（用户沉默不等于批准）。
        """
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> ControlReceiptLike:
            row = conn.execute(
                "SELECT * FROM input_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"输入请求 {request_id} 不存在")
            record = self._input_from_row(row)
            if record.state is InputRequestState.ANSWERED:
                if record.answer == answer:
                    return ("answered_before", record.task_id, record.answer)
                raise InputRequestStateError(
                    "该请求已用不同内容答复过，不能覆盖（方案 §6.10）"
                )
            if record.state is not InputRequestState.PENDING:
                raise InputRequestStateError(
                    f"请求状态为 {record.state.value}，不能答复"
                )
            if int(row["revision"]) != expected_revision:
                raise InputRequestStateError(
                    f"revision 已变化（期望 {expected_revision}，"
                    f"实际 {int(row['revision'])}），请刷新后重试"
                )
            if record.expires_at is not None and record.expires_at <= now:
                conn.execute(
                    "UPDATE input_requests SET state = 'expired', revision = revision + 1"
                    " WHERE request_id = ?",
                    (request_id,),
                )
                raise InputRequestStateError("请求已过期，不能答复")
            conn.execute(
                "UPDATE input_requests SET state = 'answered', answer = ?,"
                " answered_utc = ?, revision = revision + 1 WHERE request_id = ?",
                (answer, iso_utc(now), request_id),
            )
            control_id = new_id()
            conn.execute(
                "INSERT INTO controls (control_id, task_id, kind, request_id,"
                " payload_json, state, idempotency_key, actor, created_utc, updated_utc)"
                " VALUES (?, ?, 'respond', ?, ?, 'pending', ?, ?, ?, ?)",
                (
                    control_id,
                    record.task_id,
                    request_id,
                    json.dumps({"answer": answer}, ensure_ascii=False),
                    f"respond:{request_id}",
                    actor,
                    iso_utc(now),
                    iso_utc(now),
                ),
            )
            return ("queued", record.task_id, "")

        return self._tx(_do)

    def expire_stale_inputs(self, now: datetime | None = None) -> list[str]:
        """到期的 pending 请求置 expired；其任务转 cancelling（等待中断）。

        返回被中断的 task_id 列表。用户沉默不等于批准（方案 §6.10）。
        """
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute(
                "SELECT request_id, task_id FROM input_requests"
                " WHERE state = 'pending' AND expires_utc IS NOT NULL AND expires_utc <= ?",
                (iso_utc(now),),
            ).fetchall()
            interrupted: list[str] = []
            for row in rows:
                request_id = str(row["request_id"])
                task_id = str(row["task_id"])
                conn.execute(
                    "UPDATE input_requests SET state = 'expired', revision = revision + 1"
                    " WHERE request_id = ? AND state = 'pending'",
                    (request_id,),
                )
                conn.execute(
                    "UPDATE tasks SET state = 'cancelling', revision = revision + 1,"
                    " updated_utc = ? WHERE task_id = ? AND state IN"
                    " ('waiting_input', 'waiting_approval')",
                    (iso_utc(now), task_id),
                )
                cur = conn.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ? AND state = 'cancelling'",
                    (task_id,),
                )
                if cur.fetchone() is not None:
                    interrupted.append(task_id)
                    self._insert_event(
                        conn,
                        task_id=task_id,
                        attempt_id="",
                        kind=EventKind.CANCEL_REQUESTED,
                        payload={"reason": "input_expired", "request_id": request_id},
                        occurred_at=now,
                    )
            return interrupted

        return self._tx(_do)

    # ============================================================
    # 控制命令（取消/答复的投递通道）
    # ============================================================

    def request_cancel(
        self,
        task_id: str,
        *,
        actor: str,
        idempotency_key: str = "",
        now: datetime | None = None,
    ) -> ControlReceiptLike:
        """请求取消（方案 §6.8）：持久控制命令；queued 直接终态，
        在途任务转 cancelling，由 worker 确认停止后落 cancelled。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> ControlReceiptLike:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            task = self._task_from_row(row)
            if task.state in TERMINAL_STATES_SET:
                return ("already_terminal", task.task_id, task.state.value)
            # 幂等：同 key 已有 cancel 控制 → 返回既有命令
            if idempotency_key:
                existing = conn.execute(
                    "SELECT control_id, state FROM controls WHERE task_id = ?"
                    " AND kind = 'cancel' AND idempotency_key = ?",
                    (task_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    return (
                        "already_requested",
                        task.task_id,
                        str(existing["control_id"]),
                    )
            control_id = new_id()
            conn.execute(
                "INSERT INTO controls (control_id, task_id, kind, state,"
                " idempotency_key, actor, created_utc, updated_utc)"
                " VALUES (?, ?, 'cancel', 'pending', ?, ?, ?, ?)",
                (control_id, task_id, idempotency_key, actor, iso_utc(now), iso_utc(now)),
            )
            if task.state is TaskState.QUEUED:
                # 未启动：直接终态，不需要 worker 参与
                conn.execute(
                    "UPDATE tasks SET state = 'cancelled', revision = revision + 1,"
                    " updated_utc = ? WHERE task_id = ? AND state = 'queued'",
                    (iso_utc(now), task_id),
                )
                self._insert_event(
                    conn,
                    task_id=task_id,
                    attempt_id="",
                    kind=EventKind.CANCEL_REQUESTED,
                    payload={"actor": actor, "immediate": True},
                    occurred_at=now,
                )
                self._insert_event(
                    conn,
                    task_id=task_id,
                    attempt_id="",
                    kind=EventKind.CANCELLED,
                    payload={"actor": actor, "reason": "queued_cancel"},
                    occurred_at=now,
                )
                final_payload = {"state": "cancelled", "summary": "任务在开始前被取消。"}
                self._upsert_notification(
                    conn,
                    task_id=task_id,
                    spec=NotificationSpec(
                        kind=NotificationKind.FINAL,
                        dedupe_key=f"final:{task_id}",
                        payload=final_payload,
                        target=self._target_from_task_row(conn, task_id),
                    ),
                    sequence=self._next_sequence(conn, task_id) - 1,
                    now=now,
                )
                self._supersede_progress(conn, task_id, now)
                conn.execute(
                    "UPDATE controls SET state = 'consumed', result_note = 'queued_cancel',"
                    " updated_utc = ? WHERE control_id = ?",
                    (iso_utc(now), control_id),
                )
                return ("cancelled_immediately", task_id, control_id)
            # 在途：转 cancelling，worker 消费控制命令后确认
            conn.execute(
                "UPDATE tasks SET state = 'cancelling', revision = revision + 1,"
                " updated_utc = ? WHERE task_id = ? AND state IN"
                " ('starting', 'running', 'waiting_input', 'waiting_approval', 'recovering')",
                (iso_utc(now), task_id),
            )
            self._insert_event(
                conn,
                task_id=task_id,
                attempt_id=task.current_attempt,
                kind=EventKind.CANCEL_REQUESTED,
                payload={"actor": actor},
                occurred_at=now,
            )
            return ("cancelling", task_id, control_id)

        return self._tx(_do)

    def pending_controls_for_task(
        self, task_id: str, *, owner: str, epoch: int, attempt_id: str
    ) -> list[ControlRecord]:
        """worker 消费待处理控制命令（CAS pending → delivered，租约围栏）。"""
        now = utc_now()

        def _do(conn: sqlite3.Connection) -> list[ControlRecord]:
            attempt = conn.execute(
                "SELECT lease_owner, lease_epoch FROM attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or str(attempt["lease_owner"]) != owner or int(
                attempt["lease_epoch"]
            ) != epoch:
                return []
            rows = conn.execute(
                "SELECT * FROM controls WHERE task_id = ? AND state = 'pending'"
                " ORDER BY created_utc ASC",
                (task_id,),
            ).fetchall()
            records = [self._control_from_row(r) for r in rows]
            for record in records:
                conn.execute(
                    "UPDATE controls SET state = 'delivered', updated_utc = ?"
                    " WHERE control_id = ? AND state = 'pending'",
                    (iso_utc(now), record.control_id),
                )
            return records

        return self._tx(_do)

    def finish_control(self, control_id: str, *, note: str = "", now: datetime | None = None):
        """worker 处理完控制命令后的收尾标记。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE controls SET state = 'consumed', result_note = ?, updated_utc = ?"
                " WHERE control_id = ?",
                (note, iso_utc(now), control_id),
            )

        self._tx(_do)

    # ============================================================
    # 完成（事务边界 4，方案 §6.3）
    # ============================================================

    def finish_task(
        self,
        task_id: str,
        *,
        attempt_id: str,
        owner: str,
        epoch: int,
        outcome: Outcome,
        state: TaskState,
        summary: str,
        final_text_ref: str = "",
        evidence: list[dict] | None = None,
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
        limitations: list[str] | None = None,
        error: str = "",
        usage: dict | None = None,
        manifest_ref: str = "",
        artifacts: list[dict] | None = None,
        final_notification: NotificationSpec | None = None,
        now: datetime | None = None,
    ) -> str:
        """落终态：结果 + 产物 + 终态事件 + final notification 同事务。

        返回 result_id。租约/状态不匹配抛 :class:`StaleLeaseError`——
        「Agent 完成但 cometa 未写结果」的重交路径先 take_over 再调用。
        """
        now = now or utc_now()
        result_id = new_id()

        def _do(conn: sqlite3.Connection) -> str:
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
            if attempt is None:
                raise TaskNotFoundError(f"attempt {attempt_id} 不存在")
            if str(attempt["lease_owner"]) != owner or int(attempt["lease_epoch"]) != epoch:
                raise StaleLeaseError("租约已变更，不能提交终态")
            task = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            if str(task["current_attempt"] or "") != attempt_id:
                raise StaleLeaseError("当前 attempt 已易主，不能提交终态")
            if TaskState(task["state"]) in TERMINAL_STATES_SET:
                raise StaleLeaseError(
                    f"任务已是终态 {task['state']}，不能重复提交终态"
                )

            conn.execute(
                "INSERT INTO results (result_id, task_id, attempt_id, outcome, summary,"
                " final_text_ref, evidence_json, verification_status, limitations_json,"
                " error, usage_json, manifest_ref, created_utc)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result_id,
                    task_id,
                    attempt_id,
                    outcome.value,
                    summary,
                    final_text_ref,
                    json.dumps(evidence or [], ensure_ascii=False),
                    verification_status.value,
                    json.dumps(limitations or [], ensure_ascii=False),
                    error,
                    json.dumps(usage or {}, ensure_ascii=False),
                    manifest_ref,
                    iso_utc(now),
                ),
            )
            for artifact in artifacts or []:
                artifact_id = artifact.get("artifact_id") or new_id()
                conn.execute(
                    "INSERT INTO artifacts (artifact_id, task_id, result_id,"
                    " relative_storage_key, sha256, size, mime, display_name,"
                    " availability, created_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        artifact_id,
                        task_id,
                        result_id,
                        artifact.get("relative_storage_key", ""),
                        artifact.get("sha256", ""),
                        int(artifact.get("size", 0)),
                        artifact.get("mime", ""),
                        artifact.get("display_name", ""),
                        artifact.get("availability", ArtifactAvailability.AVAILABLE.value),
                        iso_utc(now),
                    ),
                )
            terminal_kind = {
                Outcome.SUCCEEDED: EventKind.COMPLETED,
                Outcome.PARTIAL: EventKind.COMPLETED,
                Outcome.FAILED: EventKind.FAILED,
                Outcome.CANCELLED: EventKind.CANCELLED,
            }[outcome]
            payload = {"outcome": outcome.value, "summary": summary, "result_id": result_id}
            if error:
                payload["error"] = error
            sequence = self._insert_event(
                conn,
                task_id=task_id,
                attempt_id=attempt_id,
                kind=terminal_kind,
                payload=payload,
                occurred_at=now,
            )
            final_spec = final_notification or NotificationSpec(
                kind=NotificationKind.FINAL,
                dedupe_key=f"final:{task_id}",
                payload={
                    "state": state.value,
                    "outcome": outcome.value,
                    "summary": summary,
                    "result_id": result_id,
                },
                target=self._target_from_task_row(conn, task_id),
            )
            if sequence is not None:
                self._upsert_notification(
                    conn, task_id=task_id, spec=final_spec, sequence=sequence, now=now
                )
                self._supersede_progress(conn, task_id, now)
            conn.execute(
                "UPDATE tasks SET state = ?, result_id = ?, delivery_state = 'pending',"
                " waiting_request_id = '', revision = revision + 1, heartbeat_utc = ?,"
                " updated_utc = ? WHERE task_id = ?",
                (state.value, result_id, iso_utc(now), iso_utc(now), task_id),
            )
            conn.execute(
                "UPDATE attempts SET finished_utc = ?, usage_json = ? WHERE attempt_id = ?",
                (iso_utc(now), json.dumps(usage or {}, ensure_ascii=False), attempt_id),
            )
            # 释放工作区锁（确认本 attempt 已停止才能释放——终态提交即已确认）
            conn.execute(
                "DELETE FROM workspace_leases WHERE workspace_key ="
                " (SELECT workspace_key FROM tasks WHERE task_id = ?)"
                " AND task_id = ? AND attempt_id = ?",
                (task_id, task_id, attempt_id),
            )
            # 未消费的控制命令就地作废（终态裁决完成）
            conn.execute(
                "UPDATE controls SET state = 'consumed',"
                " result_note = 'task_terminal', updated_utc = ?"
                " WHERE task_id = ? AND state IN ('pending', 'delivered')",
                (iso_utc(now), task_id),
            )
            return result_id

        return self._tx(_do)

    # ============================================================
    # 恢复（方案 §6.8 恢复矩阵）
    # ============================================================

    def tasks_needing_recovery(self, instance_id: str, *, now: datetime) -> list[TaskRecord]:
        """启动/巡检时找出「租约已过期但任务未终态」的记录。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> list[TaskRecord]:
            rows = conn.execute(
                "SELECT t.* FROM tasks t JOIN attempts a ON a.attempt_id = t.current_attempt"
                " WHERE t.instance_id = ? AND t.state IN"
                " ('starting', 'running', 'waiting_input', 'waiting_approval',"
                "  'cancelling', 'recovering')"
                " AND (a.lease_until_utc IS NULL OR a.lease_until_utc <= ?)",
                (instance_id, iso_utc(now)),
            ).fetchall()
            return [self._task_from_row(r) for r in rows]

        return self._read(_do)

    def begin_recovery(self, task_id: str, *, now: datetime | None = None) -> bool:
        """running/waiting → recovering（接管前先标记，防并发重复处理）。"""

        def _do(conn: sqlite3.Connection) -> bool:
            now2 = now or utc_now()
            cur = conn.execute(
                "UPDATE tasks SET state = 'recovering', revision = revision + 1,"
                " updated_utc = ? WHERE task_id = ? AND state IN"
                " ('starting', 'running', 'waiting_input', 'waiting_approval', 'cancelling')",
                (iso_utc(now2), task_id),
            )
            return cur.rowcount == 1

        return self._tx(_do)

    def requeue_task(self, task_id: str, *, reason: str, now: datetime | None = None) -> bool:
        """starting 且确定未发出的任务回队（恢复矩阵第 2 行：清理空会话后重备）。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE tasks SET state = 'queued', current_attempt = '', phase = '',"
                " revision = revision + 1, updated_utc = ? WHERE task_id = ?"
                " AND state = 'recovering'",
                (iso_utc(now), task_id),
            )
            if cur.rowcount != 1:
                return False
            self._insert_event(
                conn,
                task_id=task_id,
                attempt_id="",
                kind=EventKind.PROGRESS,
                payload={"event": "requeued", "reason": reason},
                occurred_at=now,
            )
            return True

        return self._tx(_do)

    def mark_recovery_required(self, task_id: str, *, reason: str, now: datetime | None = None):
        """recovery_required：系统无法确认执行状态，等管理员处理（**不是可重跑**）。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE tasks SET state = 'recovery_required', revision = revision + 1,"
                " updated_utc = ? WHERE task_id = ? AND state IN"
                " ('recovering', 'starting', 'running', 'waiting_input',"
                "  'waiting_approval', 'cancelling')",
                (iso_utc(now), task_id),
            )
            self._insert_event(
                conn,
                task_id=task_id,
                attempt_id="",
                kind=EventKind.RECOVERY_REQUIRED,
                payload={"reason": reason},
                occurred_at=now,
            )

        self._tx(_do)

    # ============================================================
    # 超时与到期（方案 §6.2：预算到期 → cancelling → timed_out）
    # ============================================================

    def enforce_deadlines(self, now: datetime | None = None) -> list[str]:
        """把到达墙钟期限的未完成任务收束（方案 §6.2：预算到期 → cancelling →
        timed_out）。queued 直接终态（从未启动，无需确认停止）；
        在途任务转 cancelling 并注入系统取消命令，由 worker 确认后落 timed_out。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> list[str]:
            handled: list[str] = []
            # queued：从未启动，直接取消
            queued_rows = conn.execute(
                "SELECT task_id FROM tasks WHERE deadline_utc IS NOT NULL"
                " AND deadline_utc <= ? AND state = 'queued'",
                (iso_utc(now),),
            ).fetchall()
            for row in queued_rows:
                task_id = str(row["task_id"])
                cur = conn.execute(
                    "UPDATE tasks SET state = 'cancelled', revision = revision + 1,"
                    " updated_utc = ? WHERE task_id = ? AND state = 'queued'"
                    " AND deadline_utc <= ?",
                    (iso_utc(now), task_id, iso_utc(now)),
                )
                if cur.rowcount != 1:
                    continue
                self._insert_event(
                    conn,
                    task_id=task_id,
                    attempt_id="",
                    kind=EventKind.CANCELLED,
                    payload={"reason": "deadline_exceeded", "immediate": True},
                    occurred_at=now,
                )
                self._upsert_notification(
                    conn,
                    task_id=task_id,
                    spec=NotificationSpec(
                        kind=NotificationKind.FINAL,
                        dedupe_key=f"final:{task_id}",
                        payload={
                            "state": "timed_out_queued",
                            "summary": "任务在排队期间到达期限，未启动即取消。",
                        },
                        target=self._target_from_task_row(conn, task_id),
                    ),
                    sequence=self._next_sequence(conn, task_id) - 1,
                    now=now,
                )
                self._supersede_progress(conn, task_id, now)
                handled.append(task_id)

            # 在途：转 cancelling + 系统取消命令（worker 确认停止后落 timed_out）
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE deadline_utc IS NOT NULL AND deadline_utc <= ?"
                " AND state IN ('starting', 'running', 'waiting_input', 'waiting_approval')",
                (iso_utc(now),),
            ).fetchall()
            expired: list[str] = []
            for row in rows:
                task_id = str(row["task_id"])
                cur = conn.execute(
                    "UPDATE tasks SET state = 'cancelling', revision = revision + 1,"
                    " updated_utc = ? WHERE task_id = ? AND deadline_utc <= ?"
                    " AND state IN ('starting', 'running', 'waiting_input',"
                    " 'waiting_approval')",
                    (iso_utc(now), task_id, iso_utc(now)),
                )
                if cur.rowcount == 1:
                    existing = conn.execute(
                        "SELECT 1 FROM controls WHERE task_id = ? AND kind = 'cancel'"
                        " AND state IN ('pending', 'delivered')",
                        (task_id,),
                    ).fetchone()
                    if existing is None:
                        conn.execute(
                            "INSERT INTO controls (control_id, task_id, kind, state,"
                            " idempotency_key, actor, created_utc, updated_utc)"
                            " VALUES (?, ?, 'cancel', 'pending', ?, 'system', ?, ?)",
                            (
                                new_id(),
                                task_id,
                                f"deadline:{task_id}",
                                iso_utc(now),
                                iso_utc(now),
                            ),
                        )
                    self._insert_event(
                        conn,
                        task_id=task_id,
                        attempt_id="",
                        kind=EventKind.CANCEL_REQUESTED,
                        payload={"reason": "deadline_exceeded"},
                        occurred_at=now,
                    )
                    expired.append(task_id)
            return handled + expired

        return self._tx(_do)

    def has_deadline_control(self, task_id: str) -> bool:
        """该任务的取消命令里是否含到期注入（idempotency_key=deadline:…）。

        executor 用它区分「用户取消」与「超时取消」，后者落
        ``timed_out`` 终态（方案 §6.2：到期 → cancelling → timed_out）。
        """

        def _do(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT 1 FROM controls WHERE task_id = ? AND kind = 'cancel'"
                " AND idempotency_key LIKE 'deadline:%' LIMIT 1",
                (task_id,),
            ).fetchone()
            return row is not None

        return self._read(_do)

    # ============================================================
    # 通知投递（事务边界 5，方案 §6.3）
    # ============================================================

    def due_notifications(
        self, *, limit: int = 16, now: datetime | None = None
    ) -> list[NotificationRecord]:
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> list[NotificationRecord]:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE state = 'pending'"
                " AND (next_attempt_utc IS NULL OR next_attempt_utc <= ?)"
                " ORDER BY created_utc ASC LIMIT ?",
                (iso_utc(now), limit),
            ).fetchall()
            return [self._notification_from_row(r) for r in rows]

        return self._read(_do)

    def claim_notification(
        self, notification_id: str, *, now: datetime | None = None
    ) -> NotificationRecord | None:
        """CAS pending → sending。入口 ack 与后台 pump 用同一原子操作竞争，
        只有一个发送者（方案 §6.5）。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> NotificationRecord | None:
            cur = conn.execute(
                "UPDATE notifications SET state = 'sending', send_attempts = send_attempts + 1,"
                " updated_utc = ? WHERE notification_id = ? AND state = 'pending'",
                (iso_utc(now), notification_id),
            )
            if cur.rowcount != 1:
                return None
            row = conn.execute(
                "SELECT * FROM notifications WHERE notification_id = ?", (notification_id,)
            ).fetchone()
            return self._notification_from_row(row)

        return self._tx(_do)

    def mark_notification(
        self,
        notification_id: str,
        *,
        state: NotificationState,
        receipt: str = "",
        error: str = "",
        next_attempt_at: datetime | None = None,
        now: datetime | None = None,
    ) -> bool:
        """记录投递结果。``pending`` + next_attempt_at = 发送前失败的退避重试；
        ``delivery_unknown`` 是终态：不自动重发（方案 §6.5/§6.11）。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "UPDATE notifications SET state = ?, receipt = ?, error = ?,"
                " next_attempt_utc = ?, updated_utc = ? WHERE notification_id = ?"
                " AND state = 'sending'",
                (
                    state.value,
                    receipt,
                    error,
                    iso_utc(next_attempt_at) if next_attempt_at is not None else None,
                    iso_utc(now),
                    notification_id,
                ),
            )
            if cur.rowcount != 1:
                return False
            if state in (
                NotificationState.SENT,
                NotificationState.SERVER_EMITTED,
                NotificationState.DELIVERY_UNKNOWN,
            ):
                # delivery_state 只跟 final 通知走（§6.2：任务终态与投递状态分开）
                conn.execute(
                    "UPDATE tasks SET delivery_state = ? WHERE task_id = ("
                    " SELECT task_id FROM notifications WHERE notification_id = ?)"
                    " AND result_id != '' AND (SELECT kind FROM notifications"
                    " WHERE notification_id = ?) = 'final'",
                    (state.value, notification_id, notification_id),
                )
            return True

        return self._tx(_do)

    def notification_of_dedupe(
        self, task_id: str, dedupe_key: str
    ) -> NotificationRecord | None:
        def _do(conn: sqlite3.Connection) -> NotificationRecord | None:
            row = conn.execute(
                "SELECT * FROM notifications WHERE task_id = ? AND dedupe_key = ?",
                (task_id, dedupe_key),
            ).fetchone()
            return self._notification_from_row(row) if row is not None else None

        return self._read(_do)

    # ============================================================
    # worker 租约
    # ============================================================

    def register_worker(
        self,
        instance_id: str,
        worker_id: str,
        process_identity: str,
        *,
        lease_seconds: float,
        now: datetime | None = None,
    ) -> int:
        """登记/续约 worker。同 instance 已有**未过期**的其他 worker → 抛错
        （双 worker 不重复启动的数据库侧保证）；过期则接管（epoch+1）。"""
        now = now or utc_now()
        lease_until = lease_deadline(now, lease_seconds)

        def _do(conn: sqlite3.Connection) -> int:
            row = conn.execute(
                "SELECT * FROM worker_leases WHERE instance_id = ?", (instance_id,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO worker_leases (instance_id, worker_id, process_identity,"
                    " epoch, lease_until_utc, updated_utc) VALUES (?, ?, ?, 1, ?, ?)",
                    (instance_id, worker_id, process_identity, iso_utc(lease_until), iso_utc(now)),
                )
                return 1
            existing_worker = str(row["worker_id"])
            existing_until = parse_iso_utc(row["lease_until_utc"])
            if existing_worker == worker_id:
                conn.execute(
                    "UPDATE worker_leases SET process_identity = ?, lease_until_utc = ?,"
                    " updated_utc = ? WHERE instance_id = ?",
                    (process_identity, iso_utc(lease_until), iso_utc(now), instance_id),
                )
                return int(row["epoch"])
            if existing_until is not None and existing_until > now:
                raise StoreBusyError(
                    f"实例 {instance_id} 已有存活 worker {existing_worker!r}（至 "
                    f"{existing_until.isoformat()}），不允许第二个 worker 认领"
                )
            conn.execute(
                "UPDATE worker_leases SET worker_id = ?, process_identity = ?,"
                " epoch = epoch + 1, lease_until_utc = ?, updated_utc = ?"
                " WHERE instance_id = ?",
                (worker_id, process_identity, iso_utc(lease_until), iso_utc(now), instance_id),
            )
            return int(row["epoch"]) + 1

        return self._tx(_do)

    def release_worker(self, instance_id: str, worker_id: str, *, now: datetime | None = None):
        """受控关闭：释放 worker 租约（下个 worker 无需等过期）。"""
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM worker_leases WHERE instance_id = ? AND worker_id = ?",
                (instance_id, worker_id),
            )

        self._tx(_do)

    # ============================================================
    # 工作区锁（跨实例共享同一数据根时也互斥，方案 §6.9）
    # ============================================================

    def workspace_lock_holder(self, workspace_key: str, *, now: datetime | None = None):
        now = now or utc_now()

        def _do(conn: sqlite3.Connection):
            row = conn.execute(
                "SELECT * FROM workspace_leases WHERE workspace_key = ? AND lease_until_utc > ?",
                (workspace_key, iso_utc(now)),
            ).fetchone()
            if row is None:
                return None
            return {
                "task_id": str(row["task_id"]),
                "attempt_id": str(row["attempt_id"]),
                "epoch": int(row["epoch"]),
                "lease_until": parse_iso_utc(row["lease_until_utc"]),
            }

        return self._read(_do)

    def release_workspace_lock(self, workspace_key: str, *, task_id: str, attempt_id: str):
        def _do(conn: sqlite3.Connection) -> bool:
            cur = conn.execute(
                "DELETE FROM workspace_leases WHERE workspace_key = ? AND task_id = ?"
                " AND attempt_id = ?",
                (workspace_key, task_id, attempt_id),
            )
            return cur.rowcount == 1

        return self._tx(_do)

    # ============================================================
    # 查询
    # ============================================================

    def snapshot(self, task_id: str) -> TaskRecord | None:
        return self.get_task(task_id)

    def list_tasks(
        self,
        instance_id: str,
        *,
        requester_id: str | None = None,
        state: TaskState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRecord]:
        def _do(conn: sqlite3.Connection) -> list[TaskRecord]:
            sql = "SELECT * FROM tasks WHERE instance_id = ?"
            params: list[object] = [instance_id]
            if requester_id is not None:
                sql += " AND requester_id = ?"
                params.append(requester_id)
            if state is not None:
                sql += " AND state = ?"
                params.append(state.value)
            sql += " ORDER BY created_utc DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            return [self._task_from_row(r) for r in conn.execute(sql, params).fetchall()]

        return self._read(_do)

    def events_page(
        self, task_id: str, *, after_sequence: int = 0, limit: int = 200
    ) -> list[EventRecord]:
        def _do(conn: sqlite3.Connection) -> list[EventRecord]:
            rows = conn.execute(
                "SELECT * FROM events WHERE task_id = ? AND sequence > ?"
                " ORDER BY sequence ASC LIMIT ?",
                (task_id, after_sequence, limit),
            ).fetchall()
            return [self._event_from_row(r) for r in rows]

        return self._read(_do)

    def latest_event(self, task_id: str) -> EventRecord | None:
        def _do(conn: sqlite3.Connection) -> EventRecord | None:
            row = conn.execute(
                "SELECT * FROM events WHERE task_id = ? ORDER BY sequence DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            return self._event_from_row(row) if row is not None else None

        return self._read(_do)

    def get_result(self, task_id: str) -> ResultRecord | None:
        def _do(conn: sqlite3.Connection) -> ResultRecord | None:
            task = conn.execute(
                "SELECT result_id FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if task is None or not str(task["result_id"]):
                return None
            row = conn.execute(
                "SELECT * FROM results WHERE result_id = ?", (str(task["result_id"]),)
            ).fetchone()
            return self._result_from_row(row) if row is not None else None

        return self._read(_do)

    def list_artifacts(self, task_id: str) -> list[ArtifactRecord]:
        def _do(conn: sqlite3.Connection) -> list[ArtifactRecord]:
            rows = conn.execute(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_utc ASC",
                (task_id,),
            ).fetchall()
            return [self._artifact_from_row(r) for r in rows]

        return self._read(_do)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        def _do(conn: sqlite3.Connection) -> ArtifactRecord | None:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            return self._artifact_from_row(row) if row is not None else None

        return self._read(_do)

    def events_for_retention(self, *, before: datetime, limit: int = 500) -> list[str]:
        """retention 清扫：返回可清理的终态 task_id（产物/工作区保留由调用方核对）。"""
        before_iso = iso_utc(before)

        def _do(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute(
                "SELECT task_id FROM tasks WHERE state IN"
                " ('cancelled', 'succeeded', 'partial', 'failed', 'timed_out')"
                " AND updated_utc < ? LIMIT ?",
                (before_iso, limit),
            ).fetchall()
            return [str(r["task_id"]) for r in rows]

        return self._read(_do)

    # ============================================================
    # 审计（方案 §6.3：不保存密钥或完整提示词）
    # ============================================================

    def audit(
        self,
        *,
        actor: str,
        action: str,
        task_id: str = "",
        request_id: str = "",
        attempt_id: str = "",
        detail: str = "",
        now: datetime | None = None,
    ) -> None:
        now = now or utc_now()

        def _do(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO audit (created_utc, actor, action, task_id, request_id,"
                " attempt_id, detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    iso_utc(now),
                    actor,
                    action,
                    task_id,
                    request_id,
                    attempt_id,
                    detail[:500],
                ),
            )

        self._tx(_do)


# 终态集合（store 内部判断用；与 models.TERMINAL_TASK_STATES 等价）
TERMINAL_STATES_SET = frozenset(
    {
        TaskState.CANCELLED,
        TaskState.SUCCEEDED,
        TaskState.PARTIAL,
        TaskState.FAILED,
        TaskState.TIMED_OUT,
        TaskState.RECOVERY_REQUIRED,
    }
)

# respond_input / request_cancel 的轻量回执（task_id, 状态说明, 附加信息）。
ControlReceiptLike = tuple[str, str, str]

__all__ = [
    "ArtifactRecord",
    "AttemptRecord",
    "CometaStore",
    "CometaStoreError",
    "ControlRecord",
    "EventRecord",
    "IdempotencyConflictError",
    "InputRequestRecord",
    "InputRequestStateError",
    "NotificationRecord",
    "NotificationSpec",
    "QuotaExceededError",
    "ResultRecord",
    "StaleLeaseError",
    "StoreBusyError",
    "TaskNotFoundError",
    "TaskRecord",
    "origin_scope_of",
]
