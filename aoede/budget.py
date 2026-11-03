# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Aoede 持久主动预算（2026-11-03 计划 §6.5，S2-03）。

唯一普通用户数值 ``PROACTIVE_FREQUENCY``（默认 1.0 次/小时，范围 0–6，
支持小数）驱动一个**每精确会话**的持久 token bucket：

- 容量 1；补充速率 R/3600 token/秒；一次逻辑主动发言扣 1。
- 新桶初始 0——重启/建状态不送免费机会。
- 持久化 tokens、last_refill（UTC 墙钟）、 outstanding reservations；
  进程内等待用单调钟，墙钟回退不补额度（elapsed 按 0），前跳最多补到
  容量 1；R 调整不清历史债务、不送免费 token。
- 同一会话的 context-only / context+memory / verification ASK / 主动
  睡眠播报共用一个桶；被动回复与用户预约任务（scheduled gate/配额）
  不经过本桶。
- 原子 reserve 先于生成/发送；ACK commit 一次；确定 FAILED 且无任何已
  发片段 release；UNKNOWN 或部分成功保守消耗。
- store 不可用 → fail closed（拒绝，不仿照旧 get_state 的「全零可发」）。

表 DDL 由同一升级协调器（mneme.schema v24）在同一 DB 创建；Aoede 只经
本模块访问。
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from nonebot import logger

AOEDE_PROACTIVE_BUDGET_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS aoede_proactive_budget (
    scope_key TEXT PRIMARY KEY,
    tokens REAL NOT NULL DEFAULT 0.0,
    last_refill_utc TEXT NOT NULL,
    config_frequency REAL NOT NULL DEFAULT 1.0,
    updated_at_utc TEXT NOT NULL
)
"""

AOEDE_BUDGET_RESERVATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS aoede_budget_reservations (
    operation_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'CONTRIBUTE',
    state TEXT NOT NULL DEFAULT 'RESERVED',
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
)
"""

RESERVATION_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_aoede_budget_reservations_scope
ON aoede_budget_reservations (scope_key, state)
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError):
        return None


@dataclass(frozen=True)
class BudgetDecision:
    """reserve 的结果；store 不可用时 fail closed（granted=False, unknown=True）。"""

    granted: bool
    unknown: bool = False
    reason: str = ""


def budget_scope_key(bot_ref, group_id: int) -> str:
    """连接 + Bot + 精确会话 目标的预算桶键（计划 §6.5 scope 规则）。"""
    return (
        f"{getattr(bot_ref, 'connection_id', '')}|"
        f"{getattr(bot_ref, 'self_id', '')}|group:{int(group_id)}"
    )


class ProactiveBudgetStore:
    """持久 token bucket + 预留台账（BEGIN IMMEDIATE 原子操作）。"""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)

    def ensure_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(AOEDE_PROACTIVE_BUDGET_TABLE_DDL)
        conn.execute(AOEDE_BUDGET_RESERVATIONS_TABLE_DDL)
        conn.execute(RESERVATION_INDEX_DDL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def reserve(
        self,
        scope_key: str,
        operation_id: str,
        *,
        frequency_per_hour: float,
        kind: str = "CONTRIBUTE",
    ) -> BudgetDecision:
        """原子预留 1 个 token；不足或 store 不可用时拒绝（fail closed）。"""
        if not math.isfinite(frequency_per_hour) or frequency_per_hour < 0:
            return BudgetDecision(granted=False, reason="invalid_frequency")
        if frequency_per_hour == 0:
            # R=0 是绝对关闭（计划 §6.5）：即使桶里还有存量 token 也不放行
            return BudgetDecision(granted=False, reason="proactive_disabled_r0")
        now = datetime.now(timezone.utc)
        try:
            conn = self._connect()
        except sqlite3.Error as e:
            logger.warning(f"⛔ [Aoede] 预算 store 不可用，fail closed: {e}")
            return BudgetDecision(granted=False, unknown=True,
                                  reason="store_unavailable")
        try:
            conn.execute("BEGIN IMMEDIATE")
            self.ensure_tables(conn)
            try:
                row = conn.execute(
                    "SELECT tokens, last_refill_utc FROM aoede_proactive_budget"
                    " WHERE scope_key=?",
                    (scope_key,),
                ).fetchone()
                if row is None:
                    tokens, last_refill = 0.0, now
                else:
                    tokens = float(row["tokens"])
                    last = _parse_utc(row["last_refill_utc"]) or now
                    # 墙钟回退不补额度（elapsed 按 0）；前跳最多补到容量 1
                    elapsed = max(0.0, (now - last).total_seconds())
                    tokens = min(1.0, tokens + elapsed * frequency_per_hour / 3600.0)
                    last_refill = now
                if tokens < 1.0:
                    conn.execute(
                        "INSERT INTO aoede_proactive_budget (scope_key, tokens,"
                        " last_refill_utc, config_frequency, updated_at_utc)"
                        " VALUES (?,?,?,?,?)"
                        " ON CONFLICT(scope_key) DO UPDATE SET tokens=excluded.tokens,"
                        " last_refill_utc=excluded.last_refill_utc,"
                        " config_frequency=excluded.config_frequency,"
                        " updated_at_utc=excluded.updated_at_utc",
                        (scope_key, tokens, last_refill.isoformat(timespec="seconds"),
                         frequency_per_hour, utc_now_iso()),
                    )
                    conn.commit()
                    return BudgetDecision(granted=False, reason="budget_empty")
                tokens -= 1.0
                conn.execute(
                    "INSERT INTO aoede_proactive_budget (scope_key, tokens,"
                    " last_refill_utc, config_frequency, updated_at_utc)"
                    " VALUES (?,?,?,?,?)"
                    " ON CONFLICT(scope_key) DO UPDATE SET tokens=excluded.tokens,"
                    " last_refill_utc=excluded.last_refill_utc,"
                    " config_frequency=excluded.config_frequency,"
                    " updated_at_utc=excluded.updated_at_utc",
                    (scope_key, tokens, last_refill.isoformat(timespec="seconds"),
                     frequency_per_hour, utc_now_iso()),
                )
                conn.execute(
                    "INSERT INTO aoede_budget_reservations (operation_id, scope_key,"
                    " kind, state, created_at_utc, updated_at_utc)"
                    " VALUES (?,?,?,?,?,?)",
                    (operation_id, scope_key, kind, "RESERVED",
                     utc_now_iso(), utc_now_iso()),
                )
                conn.commit()
                return BudgetDecision(granted=True)
            except BaseException:
                conn.rollback()
                raise
        except sqlite3.Error as e:
            # fail closed：拿不到桶状态绝不放行（不仿照旧 get_state 全零默认）
            logger.warning(f"⛔ [Aoede] 预算 store 不可用，fail closed: {e}")
            return BudgetDecision(granted=False, unknown=True,
                                  reason="store_unavailable")
        finally:
            conn.close()

    def _settle(self, operation_id: str, state: str) -> bool:
        """RESERVED → COMMITTED/RELEASED；幂等（终态不再变更）。"""
        try:
            conn = self._connect()
        except sqlite3.Error:
            return False
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE aoede_budget_reservations SET state=?, updated_at_utc=?"
                " WHERE operation_id=? AND state='RESERVED'",
                (state, utc_now_iso(), operation_id),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error:
            # 结算失败时保守方向：commit 失败不影响已扣 token；release 失败
            # 意味着 token 已被保守消耗——符合「UNKNOWN 不自动退款」。
            return False
        finally:
            conn.close()

    def commit(self, operation_id: str) -> bool:
        """ACK 后一次性确认（消费该 token）。"""
        return self._settle(operation_id, "COMMITTED")

    def release(self, operation_id: str) -> bool:
        """确定 FAILED 且无任何已发片段 → 退还 token（不超过容量 1）。"""
        try:
            conn = self._connect()
        except sqlite3.Error:
            return False
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT scope_key FROM aoede_budget_reservations"
                " WHERE operation_id=? AND state='RESERVED'",
                (operation_id,),
            ).fetchone()
            if row is None:
                conn.commit()
                return False
            conn.execute(
                "UPDATE aoede_budget_reservations SET state='RELEASED',"
                " updated_at_utc=? WHERE operation_id=?",
                (utc_now_iso(), operation_id),
            )
            current = conn.execute(
                "SELECT tokens FROM aoede_proactive_budget WHERE scope_key=?",
                (row["scope_key"],),
            ).fetchone()
            if current is not None:
                conn.execute(
                    "UPDATE aoede_proactive_budget SET tokens=?, updated_at_utc=?"
                    " WHERE scope_key=?",
                    (min(1.0, float(current["tokens"]) + 1.0), utc_now_iso(),
                     row["scope_key"]),
                )
            conn.commit()
            return True
        except sqlite3.Error:
            return False
        finally:
            conn.close()

    def resolve_unknown(self, operation_id: str) -> bool:
        """UNKNOWN / 部分成功：保守消耗（保持 RESERVED→COMMITTED）。"""
        return self._settle(operation_id, "COMMITTED")

    def current_tokens(self, scope_key: str) -> float | None:
        """只读查看（诊断/测试用）；store 不可用返回 None（不仿造默认值）。"""
        try:
            conn = self._connect()
        except sqlite3.Error:
            return None
        try:
            row = conn.execute(
                "SELECT tokens FROM aoede_proactive_budget WHERE scope_key=?",
                (scope_key,),
            ).fetchone()
            return None if row is None else float(row["tokens"])
        except sqlite3.Error:
            return None
        finally:
            conn.close()


_reservation_seq = 0


def new_operation_id() -> str:
    """进程内唯一的预算操作 id（reserve 幂等键）。"""
    global _reservation_seq
    _reservation_seq += 1
    return f"aoede-budget-{uuid.uuid4().hex[:12]}-{_reservation_seq}"


__all__ = [
    "AOEDE_BUDGET_RESERVATIONS_TABLE_DDL",
    "AOEDE_PROACTIVE_BUDGET_TABLE_DDL",
    "BudgetDecision",
    "ProactiveBudgetStore",
    "budget_scope_key",
    "new_operation_id",
    "utc_now_iso",
]
