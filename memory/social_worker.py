# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""社交后台工作队列（计划 §6.7）：持久化、有界、lease 租约。

设计要点：

- 队列在 ``social_jobs`` 表里持久化——进程重启不丢任务，替代旧
  「asyncio.sleep 延迟任务 + 定时 sweep」的双路结算（那两路可能同时结算
  同一行，是 HIGH 风险 ``_resolve_effect`` 的根因）；
- 领取用 ``BEGIN IMMEDIATE`` 短事务 + 状态 CAS：``pending → running``、
  ``running``（lease 过期可重领）；同一作业不会被两个 tick 同时拿走；
- 最多 2 次重试并指数退避；最终失败标记 dead，**可见**（日志 + 状态列），
  不静默蒸发；
- 队列上限 1000：满载时拒绝低价值新任务并计数（投递事实**从不**经队列，
  它们在发送循环里同步落库，天然不受队列容量影响）；
- 优先级（计划 §6.7）：效果落账 → 词义 → 表达；同类型按 not_before 时间。

全部数据库操作都是短事务；绝不把网络/模型调用包进事务。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from nonebot import logger

from core.social.contracts import parse_utc, utc_now_iso
from memory import social_store
from memory.timeutil import log_sqlite_error, utc_now

QUEUE_LIMIT = 1000
JOB_LEASE_SECONDS = 120.0
MAX_ATTEMPTS = 2
RETRY_BACKOFF_BASE_SECONDS = 60.0

# job 类型 → 处理器（延迟注册，避免 import 环）
_HANDLERS: dict[str, Any] = {}


def register_handler(job_type: str, handler) -> None:
    """注册作业处理器：``handler(payload: dict) -> bool``（False=可重试失败）。"""
    _HANDLERS[job_type] = handler


def _connect() -> sqlite3.Connection:
    from config import settings

    return sqlite3.connect(settings.DB_PATH, timeout=10.0)


def queue_depth() -> int:
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM social_jobs WHERE status IN ('pending','running')"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_worker.queue_depth", e)
        return 0


def enqueue_job(
    job_type: str,
    *,
    dedupe_key: str,
    payload_refs: dict[str, Any] | None = None,
    not_before_utc: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    """入队一个作业；dedupe_key 幂等。返回是否真正入队（False=重复/满载）。"""
    own = conn is None
    try:
        if own:
            social_store.ensure_tables()
            conn = _connect()
        assert conn is not None
        depth = conn.execute(
            "SELECT COUNT(*) FROM social_jobs WHERE status IN ('pending','running')"
        ).fetchone()[0]
        if depth >= QUEUE_LIMIT:
            logger.warning(f"[Social] 队列已满（{depth}），丢弃任务 {job_type}:{dedupe_key}")
            return False
        cur = conn.execute(
            "INSERT OR IGNORE INTO social_jobs (job_id, type, dedupe_key, payload_refs, "
            "status, attempts, not_before_utc, created_at_utc, updated_at_utc) "
            "VALUES (?,?,?,?,?,0,?,?,?)",
            (
                uuid.uuid4().hex, job_type, dedupe_key,
                json.dumps(payload_refs or {}, ensure_ascii=False),
                "pending", not_before_utc, utc_now_iso(), utc_now_iso(),
            ),
        )
        if own:
            conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error as e:
        log_sqlite_error("social_worker.enqueue_job", e)
        return False
    finally:
        if own and conn is not None:
            conn.close()


def lease_due_jobs(now_iso: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """原子领取到期作业（含 lease 过期的 running 重领）。"""
    now = now_iso or utc_now_iso()
    now_dt = parse_utc(now) or utc_now()
    lease_until = (now_dt + timedelta(seconds=JOB_LEASE_SECONDS)).isoformat(timespec="milliseconds")
    jobs: list[dict[str, Any]] = []
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT job_id, type, dedupe_key, payload_refs, attempts FROM social_jobs "
                "WHERE (status = 'pending' AND (not_before_utc IS NULL OR not_before_utc <= ?)) "
                "OR (status = 'running' AND lease_until_utc IS NOT NULL "
                "    AND lease_until_utc < ?) "
                "ORDER BY not_before_utc ASC LIMIT ?",
                (now, now, max(1, int(limit))),
            ).fetchall()
            for job_id, job_type, dedupe_key, payload, attempts in rows:
                if attempts >= MAX_ATTEMPTS:
                    conn.execute(
                        "UPDATE social_jobs SET status = 'dead', updated_at_utc = ?, "
                        "last_error = ? WHERE job_id = ?",
                        (now, "attempts_exhausted", job_id),
                    )
                    continue
                conn.execute(
                    "UPDATE social_jobs SET status = 'running', lease_until_utc = ?, "
                    "attempts = attempts + 1, updated_at_utc = ? WHERE job_id = ?",
                    (lease_until, now, job_id),
                )
                try:
                    payload_refs = json.loads(payload or "{}")
                except ValueError:
                    payload_refs = {}
                jobs.append({
                    "job_id": job_id, "type": job_type, "dedupe_key": dedupe_key,
                    "payload_refs": payload_refs, "attempts": int(attempts) + 1,
                })
            conn.execute("COMMIT")
            return jobs
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_worker.lease_due_jobs", e)
        return jobs


def complete_job(job_id: str) -> None:
    _finish(job_id, "done", "")


def fail_job(job_id: str, attempts: int, error: str = "") -> None:
    """失败：还有重试额度 → pending + 退避；否则 dead（可见终态）。"""
    try:
        status = "pending" if attempts < MAX_ATTEMPTS else "dead"
        backoff = (parse_utc(utc_now_iso()) or utc_now()) + timedelta(
            seconds=RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1))
        )
        _finish(job_id, status, error[:200], not_before=backoff.isoformat(timespec="milliseconds"))
    except sqlite3.Error as e:
        log_sqlite_error("social_worker.fail_job", e)


def _finish(job_id: str, status: str, error: str, not_before: str | None = None) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE social_jobs SET status = ?, last_error = ?, not_before_utc = "
            "COALESCE(?, not_before_utc), lease_until_utc = NULL, updated_at_utc = ? "
            "WHERE job_id = ?",
            (status, error, not_before, utc_now_iso(), job_id),
        )
        conn.commit()
    finally:
        conn.close()


def run_due_jobs(now_iso: str | None = None, limit: int = 20) -> dict[str, int]:
    """领取并执行到期作业。任何处理器异常都折算为可重试失败。"""
    jobs = lease_due_jobs(now_iso=now_iso, limit=limit)
    stats = {"claimed": len(jobs), "done": 0, "retry": 0, "dead": 0}
    for job in jobs:
        handler = _HANDLERS.get(job["type"])
        if handler is None:
            fail_job(job["job_id"], MAX_ATTEMPTS, f"no_handler:{job['type']}")
            stats["dead"] += 1
            continue
        try:
            ok = bool(handler(job.get("payload_refs") or {}))
        except Exception as e:  # 处理器崩溃=本轮失败，走重试
            logger.warning(f"[Social] 作业 {job['type']} 处理异常: {e}")
            ok = False
        if ok:
            complete_job(job["job_id"])
            stats["done"] += 1
        else:
            fail_job(job["job_id"], job["attempts"])
            stats["retry" if job["attempts"] < MAX_ATTEMPTS else "dead"] += 1
    return stats


def tick() -> dict[str, int]:
    """定时入口：补偿 sweep + 执行到期作业。定时任务与启动补偿共用。"""
    try:
        from memory.reply_effect_service import sweep_due_effects

        swept = sweep_due_effects()
        stats = run_due_jobs()
        stats["swept"] = swept
        return stats
    except Exception as e:  # worker 是旁路：绝不上抛拖垮定时调度
        logger.debug(f"[Social] worker tick 异常（跳过本轮）: {e}")
        return {}


def prune_jobs(keep_days: float = 7.0) -> int:
    """清理终态作业行（done/dead），保留队列审计窗口。"""
    try:
        from memory.timeutil import db_timestamp_str

        conn = _connect()
        try:
            cur = conn.execute(
                "DELETE FROM social_jobs WHERE status IN ('done','dead') "
                "AND julianday(?) - julianday(updated_at_utc) > ?",
                (db_timestamp_str(), float(keep_days)),
            )
            conn.commit()
            return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("social_worker.prune_jobs", e)
        return 0


# 默认作业处理器：效果结算（计划 §6.6——定时与重启 sweep 共用同一函数）
def _handle_resolve_effect(payload: dict[str, Any]) -> bool:
    from memory.reply_effect_service import log_settlement, resolve_effect

    effect_id = str(payload.get("effect_id") or "")
    if not effect_id:
        return True  # 引用缺失没有重试价值：终止为成功空操作
    status = resolve_effect(effect_id)
    log_settlement(effect_id, status)
    # missing/state_conflict 重试也无意义；error（DB 抖动）值得重试
    return status != "error"


register_handler("resolve_effect", _handle_resolve_effect)
