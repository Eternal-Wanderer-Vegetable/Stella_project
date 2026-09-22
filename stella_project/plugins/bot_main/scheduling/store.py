# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度库的事务性存取层（TaskStore）。

只做存取与并发原语，不做权限与业务判定——那些在 :mod:`.service` 与
:mod:`.runtime`。四个并发正确性支柱（计划 §9）全部落在这一层：

1. **幂等插入**：``(task_id, revision, scheduled_for_utc)`` 与幂等键两个唯一索引
   + ``INSERT OR IGNORE``，停机补跑 / 并发 worker / 人工重放都不会产生重复运行；
2. **修订门闩**：认领时 ``tasks.revision = runs.task_revision`` 才可认领，排队中
   的过期运行被就地扫成 ``skipped``——编辑/暂停/取消对排队工作是 fences；
3. **租约**：认领即持有带期限的租约，过期后 :meth:`recover_expired_leases` 把
   claimed/running/ready 还回队列、把 ``sending`` 判为 ``delivery_unknown``
   （平台调用可能已发生，重发有刷屏风险，只能人工重试）；
4. **配额**：认领事务内递增 ``(group_id, day)`` 配额行，超额运行被扫成
   ``skipped(quota_exceeded)``，不会先扣后跑。

事务模式：写路径一律 ``BEGIN IMMEDIATE``（SQLite 串行写；避免延迟事务升级时的
SQLITE_BUSY），读路径随用随开。每次操作短连接，与 memory/ 各模块同款。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from nonebot import logger

from .migrations import connect, default_db_path, migrate
from .models import (
    ACTIVE_RUN_STATES,
    AuditEntry,
    NotificationMode,
    Run,
    RunState,
    Task,
    TaskMode,
    TaskStatus,
    day_key,
    iso_utc,
    lease_deadline,
    parse_iso_utc,
    utc_now,
)

_ACTIVE_STATES_SQL = "('" + "', '".join(s.value for s in ACTIVE_RUN_STATES) + "')"

# 「正在执行」的状态（占用群串行名额）。queued 只是在排队——若把它也算进
# 群忙判定，同群两条排队运行会互相视对方为忙，谁也认领不到（死锁）。
_EXECUTING_STATES_SQL = "('claimed', 'running', 'ready', 'sending')"

# 认领扫描一次最多处理的候选数。防个别任务的运行被反复跳过时无限循环；
# 正常情况下队头很快会被认领或清扫。
_CLAIM_CANDIDATE_LIMIT = 64


class SchedulingStoreError(RuntimeError):
    """存取层错误基类。"""


class TaskNotFoundError(SchedulingStoreError):
    """任务不存在（含已物理缺失）。"""


class StaleRevisionError(SchedulingStoreError):
    """乐观锁冲突：任务已被并发修改。调用方应重读后重试或放弃。"""


class GroupTaskLimitError(SchedulingStoreError):
    """该群的非取消任务数已达上限。"""


def _new_id() -> str:
    return uuid.uuid4().hex


def _task_from_row(row: sqlite3.Row) -> Task:
    try:
        policy = json.loads(row["policy_json"] or "{}")
    except (ValueError, TypeError):
        policy = {}
    if not isinstance(policy, dict):
        policy = {}
    return Task(
        task_id=row["task_id"],
        instance_id=row["instance_id"] or "",
        bot_id=row["bot_id"],
        group_id=int(row["group_id"]),
        owner_id=int(row["owner_id"]),
        mode=TaskMode(row["mode"]),
        objective=row["objective"],
        cron_expr=row["cron_expr"],
        timezone=row["timezone"],
        revision=int(row["revision"]),
        status=TaskStatus(row["status"]),
        policy=policy,
        next_run_utc=parse_iso_utc(row["next_run_utc"]),
        last_run_utc=parse_iso_utc(row["last_run_utc"]),
        max_model_rounds=int(row["max_model_rounds"]),
        max_tool_calls=int(row["max_tool_calls"]),
        run_timeout_seconds=float(row["run_timeout_seconds"]),
        output_max_chars=int(row["output_max_chars"]),
        notification_mode=NotificationMode(row["notification_mode"]),
        created_at=parse_iso_utc(row["created_at"]),
        updated_at=parse_iso_utc(row["updated_at"]),
    )


def _run_from_row(row: sqlite3.Row) -> Run:
    return Run(
        run_id=row["run_id"],
        task_id=row["task_id"],
        task_revision=int(row["task_revision"]),
        group_id=int(row["group_id"]),
        idempotency_key=row["idempotency_key"],
        state=RunState(row["state"]),
        scheduled_for_utc=parse_iso_utc(row["scheduled_for_utc"]),
        request_id=row["request_id"] or "",
        lease_owner=row["lease_owner"] or "",
        lease_expires_utc=parse_iso_utc(row["lease_expires_utc"]),
        model_rounds=int(row["model_rounds"]),
        tool_calls=int(row["tool_calls"]),
        result_text=row["result_text"] or "",
        error=row["error"] or "",
        delivery_receipt=row["delivery_receipt"] or "",
        delivery_error=row["delivery_error"] or "",
        fingerprint=row["fingerprint"] or "",
        queued_at_utc=parse_iso_utc(row["queued_at_utc"]),
        claimed_at_utc=parse_iso_utc(row["claimed_at_utc"]),
        finished_at_utc=parse_iso_utc(row["finished_at_utc"]),
    )


class TaskStore:
    """调度库的门面。每个进程一个实例即可（连接短开短关，线程安全）。"""

    def __init__(self, db_path: Path | str | None = None, *, auto_migrate: bool = True) -> None:
        self.db_path = Path(db_path) if db_path is not None else default_db_path()
        if auto_migrate:
            migrate(self.db_path)

    # ── 连接 ─────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        return connect(self.db_path)

    # ── 任务生命周期 ─────────────────────────────────────
    def create_task(
        self,
        *,
        task_id: str | None = None,
        instance_id: str = "",
        bot_id: str,
        group_id: int,
        owner_id: int,
        mode: TaskMode,
        objective: str,
        cron_expr: str,
        timezone: str,
        policy: dict | None = None,
        max_model_rounds: int = 4,
        max_tool_calls: int = 8,
        run_timeout_seconds: float = 300.0,
        output_max_chars: int = 1200,
        notification_mode: NotificationMode = NotificationMode.ON_CONTENT,
        max_tasks_per_group: int = 0,
        now: datetime | None = None,
    ) -> Task:
        """写入一条新任务（revision=1, status=active）。

        ``max_tasks_per_group`` > 0 时在同一事务里检查该群非取消任务数上限，
        超限抛 :class:`GroupTaskLimitError`——计数与插入同事务，并发创建不会
        越过上限。
        """
        now = now or utc_now()
        task_id = task_id or _new_id()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if max_tasks_per_group > 0:
                row = conn.execute(
                    "SELECT COUNT(*) FROM tasks WHERE group_id = ? AND status != 'cancelled'",
                    (group_id,),
                ).fetchone()
                if row and int(row[0]) >= max_tasks_per_group:
                    conn.rollback()
                    raise GroupTaskLimitError(
                        f"群 {group_id} 的任务数已达上限 {max_tasks_per_group}"
                    )
            conn.execute(
                "INSERT INTO tasks (task_id, instance_id, bot_id, group_id, owner_id, mode, "
                "objective, cron_expr, timezone, policy_json, revision, status, "
                "max_model_rounds, max_tool_calls, run_timeout_seconds, output_max_chars, "
                "notification_mode, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    instance_id,
                    str(bot_id),
                    group_id,
                    owner_id,
                    mode.value,
                    objective,
                    cron_expr,
                    timezone,
                    json.dumps(policy or {}, ensure_ascii=False),
                    max_model_rounds,
                    max_tool_calls,
                    run_timeout_seconds,
                    output_max_chars,
                    notification_mode.value,
                    iso_utc(now),
                    iso_utc(now),
                ),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> Task | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            return _task_from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_tasks(
        self,
        group_id: int,
        *,
        owner_id: int | None = None,
        include_cancelled: bool = False,
    ) -> list[Task]:
        """列出某群的（可选按属主过滤的）任务，创建时间升序。"""
        sql = "SELECT * FROM tasks WHERE group_id = ?"
        params: list[object] = [group_id]
        if owner_id is not None:
            sql += " AND owner_id = ?"
            params.append(owner_id)
        if not include_cancelled:
            sql += " AND status != 'cancelled'"
        sql += " ORDER BY created_at ASC"
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [_task_from_row(row) for row in rows]
        finally:
            conn.close()

    # 可被 edit_task 修改的字段白名单（列名 → 是否需要额外处理）。
    _EDITABLE_COLUMNS = (
        "objective",
        "cron_expr",
        "timezone",
        "max_model_rounds",
        "max_tool_calls",
        "run_timeout_seconds",
        "output_max_chars",
        "notification_mode",
    )

    def edit_task(
        self,
        task_id: str,
        expected_revision: int,
        *,
        updates: dict | None = None,
        policy: dict | None = None,
        now: datetime | None = None,
    ) -> Task:
        """按乐观锁编辑任务：``expected_revision`` 不匹配即抛 :class:`StaleRevisionError`。

        编辑本身不 bump 出新运行；下一次触发的 ``task_revision`` 自然取到新值，
        旧修订的排队运行会在认领扫描里被作废（修订门闩）。
        """
        now = now or utc_now()
        updates = dict(updates or {})
        unknown = set(updates) - set(self._EDITABLE_COLUMNS)
        if unknown:
            raise ValueError(f"不可编辑的字段: {sorted(unknown)}")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            if int(row["revision"]) != expected_revision:
                conn.rollback()
                raise StaleRevisionError(
                    f"任务 {task_id} 修订已变化（期望 {expected_revision}，"
                    f"实际 {row['revision']}）"
                )
            sets = ["revision = revision + 1", "updated_at = ?"]
            params: list[object] = [iso_utc(now)]
            for column in self._EDITABLE_COLUMNS:
                if column in updates:
                    sets.append(f"{column} = ?")
                    params.append(updates[column])
            if policy is not None:
                sets.append("policy_json = ?")
                params.append(json.dumps(policy, ensure_ascii=False))
            params.append(task_id)
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", params
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_task(task_id)  # type: ignore[return-value]

    def set_status(
        self,
        task_id: str,
        expected_revision: int,
        status: TaskStatus,
        *,
        now: datetime | None = None,
    ) -> Task:
        """pause / resume / cancel（同样走修订门闩；每次状态变更 revision +1）。

        取消是终态：同事务把该任务**排队中**的运行一并置 ``cancelled``；
        已认领/在途的运行交给运行时在生成前与发送前的检查点自行放弃
        （计划 §6.2：pause 亦复用同一重查点）。
        """
        now = now or utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT revision, status FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                conn.rollback()
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            if int(row["revision"]) != expected_revision:
                conn.rollback()
                raise StaleRevisionError(
                    f"任务 {task_id} 修订已变化（期望 {expected_revision}，"
                    f"实际 {row['revision']}）"
                )
            conn.execute(
                "UPDATE tasks SET status = ?, revision = revision + 1, updated_at = ? "
                "WHERE task_id = ?",
                (status.value, iso_utc(now), task_id),
            )
            if status is TaskStatus.CANCELLED:
                conn.execute(
                    "UPDATE runs SET state = 'cancelled', error = 'task_cancelled', "
                    "finished_at_utc = ? WHERE task_id = ? AND state = 'queued'",
                    (iso_utc(now), task_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return self.get_task(task_id)  # type: ignore[return-value]

    def record_task_fired(
        self,
        task_id: str,
        *,
        last_run_utc: datetime | None = None,
        next_run_utc: datetime | None = None,
        clear_next_run: bool = False,
    ) -> None:
        """刷新 next/last 触发时刻缓存（展示用，不参与正确性；不 bump revision）。

        只更新传入的字段；``clear_next_run`` 用于任务取消/暂停时清掉预览。
        """
        sets: list[str] = []
        params: list[object] = []
        if last_run_utc is not None:
            sets.append("last_run_utc = ?")
            params.append(iso_utc(last_run_utc))
        if clear_next_run:
            sets.append("next_run_utc = NULL")
        elif next_run_utc is not None:
            sets.append("next_run_utc = ?")
            params.append(iso_utc(next_run_utc))
        if not sets:
            return
        params.append(task_id)
        conn = self._connect()
        try:
            conn.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", params
            )
            conn.commit()
        finally:
            conn.close()

    # ── 运行（runs） ─────────────────────────────────────
    def insert_run(
        self,
        task_id: str,
        *,
        scheduled_for: datetime | None = None,
        request_id: str = "",
        now: datetime | None = None,
    ) -> str | None:
        """入队一次运行；幂等键已存在（重复触发/任务已有活跃运行）返回 None。

        Cron 触发传 ``scheduled_for``（该次触发的语义时刻）；人工 run-now 传
        ``request_id``（调用方生成的请求标识，重放同一 request_id 不会重复入队）。
        """
        if scheduled_for is None and not request_id:
            raise ValueError("insert_run 需要 scheduled_for（Cron）或 request_id（人工）")
        now = now or utc_now()
        run_id = _new_id()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT task_id, revision, group_id, status FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise TaskNotFoundError(f"任务 {task_id} 不存在")
            if row["status"] == TaskStatus.CANCELLED.value:
                conn.commit()
                return None
            revision = int(row["revision"])
            if scheduled_for is not None:
                idem = f"{task_id}:{revision}:{iso_utc(scheduled_for)}"
            else:
                idem = f"{task_id}:{revision}:manual:{request_id}"
            cursor = conn.execute(
                "INSERT OR IGNORE INTO runs (run_id, task_id, task_revision, group_id, "
                "idempotency_key, state, scheduled_for_utc, request_id, queued_at_utc) "
                "VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (
                    run_id,
                    task_id,
                    revision,
                    int(row["group_id"]),
                    idem,
                    iso_utc(scheduled_for) if scheduled_for is not None else None,
                    request_id,
                    iso_utc(now),
                ),
            )
            inserted = cursor.rowcount == 1
            conn.commit()
        except sqlite3.IntegrityError:
            # 与 INSERT OR IGNORE 同义（唯一索引兜底路径），不是错误
            conn.rollback()
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return run_id if inserted else None

    def get_run(self, run_id: str) -> Run | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return _run_from_row(row) if row is not None else None
        finally:
            conn.close()

    def list_runs(self, task_id: str, *, limit: int = 20) -> list[Run]:
        """某任务的运行历史（新→旧）。"""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM runs WHERE task_id = ? "
                "ORDER BY COALESCE(scheduled_for_utc, queued_at_utc) DESC, run_id DESC "
                "LIMIT ?",
                (task_id, max(int(limit), 1)),
            ).fetchall()
            return [_run_from_row(row) for row in rows]
        finally:
            conn.close()

    def count_group_active_runs(self, group_id: int) -> int:
        """该群当前处于活跃状态的运行数（运行时并发上限的查询侧）。"""
        conn = self._connect()
        try:
            row = conn.execute(
                f"SELECT COUNT(*) FROM runs WHERE group_id = ? AND state IN {_ACTIVE_STATES_SQL}",
                (group_id,),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def claim_next_run(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
        lease_seconds: float = 600.0,
        daily_group_run_cap: int = 0,
    ) -> Run | None:
        """认领一条到期运行（事务性；这是 worker 的主入口）。

        判定顺序（同一事务内）：

        1. **清扫**：任务已取消/暂停或修订过期的排队运行 → ``skipped``
           （原因写进 ``error``，历史可查，队列不再积压）；
        2. 依次考察到期候选（``scheduled_for`` 升序）：
           - 该群已有其它活跃运行 → 直接返回 None（等下一轮，不跳过不消费）；
           - 每日配额已满（``daily_group_run_cap`` > 0 时）→ 该运行置
             ``skipped(quota_exceeded)``，继续看下一个候选；
           - 否则置 ``claimed``、写租约、配额 +1，返回该运行。
        """
        now = now or utc_now()
        now_iso = iso_utc(now)
        lease_exp_iso = iso_utc(lease_deadline(now, lease_seconds))
        day = day_key(now)
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # 1. 清扫不可能再跑的队头运行
            conn.execute(
                "UPDATE runs SET state = 'skipped', "
                "error = CASE "
                "  WHEN (SELECT status FROM tasks WHERE task_id = runs.task_id) "
                "       = 'cancelled' THEN 'task_cancelled' "
                "  WHEN (SELECT status FROM tasks WHERE task_id = runs.task_id) "
                "       = 'paused' THEN 'task_paused' "
                "  ELSE 'revision_stale' END, "
                "finished_at_utc = ? "
                "WHERE state = 'queued' AND EXISTS ("
                "  SELECT 1 FROM tasks t WHERE t.task_id = runs.task_id "
                "  AND (t.status != 'active' OR t.revision != runs.task_revision))",
                (now_iso,),
            )
            candidates = conn.execute(
                "SELECT r.run_id FROM runs r JOIN tasks t ON t.task_id = r.task_id "
                "WHERE r.state = 'queued' "
                "AND (r.scheduled_for_utc IS NULL OR r.scheduled_for_utc <= ?) "
                "AND t.status = 'active' AND t.revision = r.task_revision "
                "ORDER BY COALESCE(r.scheduled_for_utc, r.queued_at_utc) ASC, "
                "r.queued_at_utc ASC LIMIT ?",
                (now_iso, _CLAIM_CANDIDATE_LIMIT),
            ).fetchall()
            for candidate in candidates:
                candidate_id = candidate["run_id"]
                group_row = conn.execute(
                    "SELECT group_id FROM runs WHERE run_id = ?", (candidate_id,)
                ).fetchone()
                if group_row is None:
                    continue
                group_id = int(group_row["group_id"])
                # 2a. 群内串行：已有**执行中**的其它运行时本轮不认领（保留在队列）。
                #     只看 executing 状态、排除候选自身——queued 相互不算忙。
                busy = conn.execute(
                    f"SELECT 1 FROM runs WHERE group_id = ? AND run_id != ? "
                    f"AND state IN {_EXECUTING_STATES_SQL} LIMIT 1",
                    (group_id, candidate_id),
                ).fetchone()
                if busy is not None:
                    conn.commit()
                    return None
                # 2b. 每日配额：满则该运行跳过（终态），继续下一个候选
                quota_row = conn.execute(
                    "SELECT runs_used FROM quotas WHERE group_id = ? AND day = ?",
                    (group_id, day),
                ).fetchone()
                runs_used = int(quota_row["runs_used"]) if quota_row else 0
                if daily_group_run_cap > 0 and runs_used >= daily_group_run_cap:
                    conn.execute(
                        "UPDATE runs SET state = 'skipped', error = 'quota_exceeded', "
                        "finished_at_utc = ? WHERE run_id = ? AND state = 'queued'",
                        (now_iso, candidate_id),
                    )
                    continue
                # 2c. 认领 + 配额递增（同一事务，配额不会先扣后跑）
                claimed = conn.execute(
                    "UPDATE runs SET state = 'claimed', lease_owner = ?, "
                    "lease_expires_utc = ?, claimed_at_utc = ? "
                    "WHERE run_id = ? AND state = 'queued'",
                    (worker_id, lease_exp_iso, now_iso, candidate_id),
                )
                if claimed.rowcount != 1:
                    continue
                conn.execute(
                    "INSERT INTO quotas (group_id, day, runs_used, messages_used) "
                    "VALUES (?, ?, 1, 0) "
                    "ON CONFLICT(group_id, day) DO UPDATE SET runs_used = runs_used + 1",
                    (group_id, day),
                )
                conn.commit()
                return self.get_run(candidate_id)
            conn.commit()
            return None
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_lease(
        self, run_id: str, worker_id: str, *, seconds: float, now: datetime | None = None
    ) -> bool:
        """续租；租约已易主/运行已不再可租时返回 False（调用方应立即停止工作）。"""
        now = now or utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE runs SET lease_expires_utc = ? "
                "WHERE run_id = ? AND lease_owner = ? AND state IN ('claimed', 'running')",
                (iso_utc(lease_deadline(now, seconds)), run_id, worker_id),
            )
            conn.commit()
            return cursor.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def transition_run(
        self,
        run_id: str,
        worker_id: str,
        *,
        from_states: tuple[RunState, ...],
        to_state: RunState,
        result_text: str | None = None,
        error: str | None = None,
        delivery_receipt: str | None = None,
        delivery_error: str | None = None,
        fingerprint: str | None = None,
        model_rounds: int | None = None,
        tool_calls: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """通用 CAS 状态迁移（投递状态机的底层原语，见 :mod:`.delivery`）。

        只有当前租约持有者能把运行从 ``from_states`` 迁到 ``to_state``；竞争失败
        返回 False——调用方必须立即放弃后续动作（尤其不得再向平台发送）。
        终态迁移同时写 ``finished_at_utc``。
        """
        now = now or utc_now()
        from_sql = "(" + ", ".join(f"'{s.value}'" for s in from_states) + ")"
        sets = ["state = ?"]
        params: list[object] = [to_state.value]
        if result_text is not None:
            sets.append("result_text = ?")
            params.append(result_text)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if delivery_receipt is not None:
            sets.append("delivery_receipt = ?")
            params.append(delivery_receipt)
        if delivery_error is not None:
            sets.append("delivery_error = ?")
            params.append(delivery_error)
        if fingerprint is not None:
            sets.append("fingerprint = ?")
            params.append(fingerprint)
        if model_rounds is not None:
            sets.append("model_rounds = ?")
            params.append(model_rounds)
        if tool_calls is not None:
            sets.append("tool_calls = ?")
            params.append(tool_calls)
        if to_state not in ACTIVE_RUN_STATES:
            sets.append("finished_at_utc = ?")
            params.append(iso_utc(now))
        params.extend([run_id, worker_id])
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"UPDATE runs SET {', '.join(sets)} "
                f"WHERE run_id = ? AND lease_owner = ? AND state IN {from_sql}",
                params,
            )
            conn.commit()
            return cursor.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_running(self, run_id: str, worker_id: str) -> bool:
        return self.transition_run(
            run_id, worker_id, from_states=(RunState.CLAIMED,), to_state=RunState.RUNNING
        )

    def recover_expired_leases(self, *, now: datetime | None = None) -> dict[str, int]:
        """租约恢复（worker 重启 / 接管过期租约时调用）。

        - ``claimed`` / ``running`` / ``ready`` 过期 → 回队列（``ready`` 的产物
          保留在 result_text，但重跑会重新生成——有界预算保证重跑代价可控）；
        - ``sending`` 过期 → ``delivery_unknown``：QQ 调用可能已发出，进程却在
          回执落库前死了。**绝不自动重投**，只等人工 run-now。
        """
        now = now or utc_now()
        now_iso = iso_utc(now)
        counts = {"requeued": 0, "delivery_unknown": 0}
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                f"UPDATE runs SET state = 'queued', lease_owner = '', lease_expires_utc = NULL "
                f"WHERE state IN ('{RunState.CLAIMED.value}', '{RunState.RUNNING.value}', "
                f"'{RunState.READY.value}') AND lease_expires_utc IS NOT NULL "
                "AND lease_expires_utc <= ?",
                (now_iso,),
            )
            counts["requeued"] = cursor.rowcount
            cursor = conn.execute(
                f"UPDATE runs SET state = '{RunState.DELIVERY_UNKNOWN.value}', "
                "lease_owner = '', lease_expires_utc = NULL, "
                "delivery_error = COALESCE(NULLIF(delivery_error, ''), "
                "'worker_died_after_send_call'), finished_at_utc = ? "
                f"WHERE state = '{RunState.SENDING.value}' AND lease_expires_utc IS NOT NULL "
                "AND lease_expires_utc <= ?",
                (now_iso, now_iso),
            )
            counts["delivery_unknown"] = cursor.rowcount
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if counts["requeued"] or counts["delivery_unknown"]:
            logger.warning(
                f"⚠️ [Scheduling] 租约恢复：{counts['requeued']} 条重回队列，"
                f"{counts['delivery_unknown']} 条判为投递未知（需人工处理）"
            )
        return counts

    # ── 配额查询 ─────────────────────────────────────────
    def quota_usage(self, group_id: int, *, now: datetime | None = None) -> dict[str, int]:
        now = now or utc_now()
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT runs_used, messages_used FROM quotas WHERE group_id = ? AND day = ?",
                (group_id, day_key(now)),
            ).fetchone()
            if row is None:
                return {"runs_used": 0, "messages_used": 0}
            return {"runs_used": int(row["runs_used"]), "messages_used": int(row["messages_used"])}
        finally:
            conn.close()

    def record_delivered_message(self, group_id: int, *, count: int = 1, now: datetime | None = None) -> None:
        """投递侧消息计数（observability；不拦截，拦截在认领时按 runs 口径）。"""
        now = now or utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO quotas (group_id, day, runs_used, messages_used) "
                "VALUES (?, ?, 0, ?) "
                "ON CONFLICT(group_id, day) DO UPDATE SET messages_used = messages_used + ?",
                (group_id, day_key(now), count, count),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── worker 单租约（一库一活跃 worker；多 worker 部署 v1 不支持） ──
    def acquire_worker_lease(
        self, worker_id: str, *, ttl_seconds: float, now: datetime | None = None
    ) -> bool:
        """尝试成为该库唯一的活跃 worker。已被活着的其它 worker 持有时返回 False。"""
        now = now or utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT worker_id, expires_at_utc FROM worker_lease WHERE id = 1"
            ).fetchone()
            expires_iso = iso_utc(lease_deadline(now, ttl_seconds))
            if row is None:
                conn.execute(
                    "INSERT INTO worker_lease (id, worker_id, expires_at_utc) VALUES (1, ?, ?)",
                    (worker_id, expires_iso),
                )
                conn.commit()
                return True
            held_expired = parse_iso_utc(row["expires_at_utc"]) is not None and (
                parse_iso_utc(row["expires_at_utc"]) <= now  # type: ignore[operator]
            )
            if row["worker_id"] == worker_id or held_expired:
                conn.execute(
                    "UPDATE worker_lease SET worker_id = ?, expires_at_utc = ? WHERE id = 1",
                    (worker_id, expires_iso),
                )
                conn.commit()
                return True
            conn.commit()
            return False
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_worker_lease(
        self, worker_id: str, *, ttl_seconds: float, now: datetime | None = None
    ) -> bool:
        now = now or utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE worker_lease SET expires_at_utc = ? "
                "WHERE id = 1 AND worker_id = ? AND expires_at_utc > ?",
                (iso_utc(lease_deadline(now, ttl_seconds)), worker_id, iso_utc(now)),
            )
            conn.commit()
            return cursor.rowcount == 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def release_worker_lease(self, worker_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM worker_lease WHERE id = 1 AND worker_id = ?", (worker_id,)
            )
            conn.commit()
        finally:
            conn.close()

    # ── 审计 ─────────────────────────────────────────────
    def record_audit(
        self,
        action: str,
        *,
        actor_id: int,
        group_id: int,
        task_id: str = "",
        detail: str = "",
        now: datetime | None = None,
    ) -> None:
        """记录一次受控变更。审计写入失败只告警不阻断业务（与 memory/ 同哲学）。"""
        now = now or utc_now()
        try:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO audit_log (created_at, actor_id, group_id, task_id, action, detail) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (iso_utc(now), actor_id, group_id, task_id, action, detail),
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.warning(f"⚠️ [Scheduling] 审计写入失败: {e}")

    def list_audit(
        self, group_id: int | None = None, *, limit: int = 50
    ) -> list[AuditEntry]:
        sql = "SELECT * FROM audit_log"
        params: list[object] = []
        if group_id is not None:
            sql += " WHERE group_id = ?"
            params.append(group_id)
        sql += " ORDER BY audit_id DESC LIMIT ?"
        params.append(max(int(limit), 1))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [
                AuditEntry(
                    audit_id=int(row["audit_id"]),
                    created_at_utc=parse_iso_utc(row["created_at"]),
                    actor_id=int(row["actor_id"]),
                    group_id=int(row["group_id"]),
                    task_id=row["task_id"] or "",
                    action=row["action"] or "",
                    detail=row["detail"] or "",
                )
                for row in rows
            ]
        finally:
            conn.close()


__all__ = [
    "GroupTaskLimitError",
    "Run",
    "SchedulingStoreError",
    "StaleRevisionError",
    "Task",
    "TaskNotFoundError",
    "TaskStore",
]
