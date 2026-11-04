# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Mneme 一次性求证持久生命周期（2026-11-03 计划 §6.4，S2-01）。

职责边界：Mneme 持有 verification attempts 与 rejection tombstones；Aoede
通过 :class:`MnemeVerificationStore` 操作，不直接读写候选表，也不拥有
晋升/证据合同。与旧 ``_check_reply_later`` 内存退避的关系：用户级
consecutive_no_reply 与自然度 skip 是社交退避，不是候选拒绝记录；
tombstone 不因新消息/reset_no_reply/重启被清除。

状态机（计划 §6.4）：RESERVED → SENDING → PENDING_VERIFICATION →
CONFIRMED / DENIED / UNANSWERED / UNCLEAR；另有 CANCELLED（确定未发）与
DELIVERY_UNKNOWN（发送结果未知，保守占用、不重投）。

事务纪律：单进程内用 ``BEGIN IMMEDIATE``；active attempt 的部分唯一索引
保证同一 claim 同时最多一个在途求证；候选 CAS（NEW/OBSERVING → REJECTED）
与终态/tombstone 写入在同一事务完成。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from nonebot import logger

# 默认确认窗口（计划 §12：原确认窗口 300 秒为首版实验初值）。
DEFAULT_VERIFICATION_WINDOW_SECONDS = 300.0

ATTEMPT_STATES = (
    "RESERVED",
    "SENDING",
    "PENDING_VERIFICATION",
    "CONFIRMED",
    "DENIED",
    "UNANSWERED",
    "UNCLEAR",
    "CANCELLED",
    "DELIVERY_UNKNOWN",
)
ACTIVE_STATES = ("RESERVED", "SENDING", "PENDING_VERIFICATION")
TERMINAL_STATES = ("CONFIRMED", "DENIED", "UNANSWERED", "UNCLEAR", "CANCELLED")

VERIFICATION_ATTEMPTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memory_verification_attempts (
    attempt_id TEXT PRIMARY KEY,
    opportunity_id TEXT NOT NULL DEFAULT '',
    candidate_id TEXT NOT NULL,
    candidate_content_digest TEXT NOT NULL DEFAULT '',
    owner_type TEXT NOT NULL DEFAULT '',
    owner_key TEXT NOT NULL DEFAULT '',
    subject_key TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
    fact_key TEXT NOT NULL DEFAULT '',
    evidence_digest TEXT NOT NULL DEFAULT '',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    source_row_ids TEXT NOT NULL DEFAULT '[]',
    source_digests TEXT NOT NULL DEFAULT '[]',
    bot_ref TEXT NOT NULL DEFAULT '',
    connection_id TEXT NOT NULL DEFAULT '',
    conversation_key TEXT NOT NULL DEFAULT '',
    question_message_ids TEXT NOT NULL DEFAULT '[]',
    state TEXT NOT NULL DEFAULT 'RESERVED',
    result_reason TEXT NOT NULL DEFAULT '',
    reply_message_id TEXT NOT NULL DEFAULT '',
    reply_digest TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    sent_at TEXT,
    deadline TEXT,
    lease_owner TEXT NOT NULL DEFAULT '',
    lease_expiry TEXT,
    settlement_operation_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
)
"""

# 同一 claim（owner/audience/fact/subject）同时最多一个在途 attempt；
# 终态行不占用该约束（历史可追溯）。
VERIFICATION_ATTEMPTS_ACTIVE_UNIQUE_INDEX_DDL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_verification_attempts_active_claim
ON memory_verification_attempts (owner_key, audience, fact_key, subject_key)
WHERE state IN ('RESERVED', 'SENDING', 'PENDING_VERIFICATION', 'DELIVERY_UNKNOWN')
"""

VERIFICATION_ATTEMPTS_OVERDUE_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_memory_verification_attempts_overdue
ON memory_verification_attempts (state, deadline)
"""

REJECTION_TOMBSTONES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memory_rejection_tombstones (
    tombstone_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL DEFAULT '',
    owner_type TEXT NOT NULL DEFAULT '',
    owner_key TEXT NOT NULL DEFAULT '',
    subject_key TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '',
    fact_key TEXT NOT NULL DEFAULT '',
    evidence_digest TEXT NOT NULL DEFAULT '',
    source_row_ids TEXT NOT NULL DEFAULT '[]',
    source_digests TEXT NOT NULL DEFAULT '[]',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""

REJECTION_TOMBSTONES_CLAIM_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_memory_rejection_tombstones_claim
ON memory_rejection_tombstones (owner_key, audience, fact_key, subject_key)
"""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest_json(value: object) -> str:
    """稳定摘要：来源集合/原文一致性核对用，不含原始聊天文本。"""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AttemptRecord:
    """attempt 行的不可变视图（公开日志不携带问题/回复原文）。"""

    attempt_id: str
    candidate_id: str
    owner_key: str
    audience: str
    fact_key: str
    subject_key: str
    conversation_key: str
    state: str
    question_message_ids: tuple[str, ...]
    deadline: str | None


class MnemeVerificationStore:
    """verification attempts / tombstones 的唯一持久入口。"""

    def __init__(self, db_path: str):
        self._db_path = str(db_path)

    # ── 建表（schema24 经 mneme.schema._migrate 调用；此处供独立初始化） ──
    def ensure_tables(self, conn: sqlite3.Connection) -> None:
        conn.execute(VERIFICATION_ATTEMPTS_TABLE_DDL)
        conn.execute(VERIFICATION_ATTEMPTS_ACTIVE_UNIQUE_INDEX_DDL)
        conn.execute(VERIFICATION_ATTEMPTS_OVERDUE_INDEX_DDL)
        conn.execute(REJECTION_TOMBSTONES_TABLE_DDL)
        conn.execute(REJECTION_TOMBSTONES_CLAIM_INDEX_DDL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    # ── 预留（必须在发送前落盘：修复「发出后才建记录」的崩溃窗口） ──
    def open_attempt(
        self,
        *,
        candidate_id: str,
        candidate_content_digest: str,
        owner_type: str,
        owner_key: str,
        subject_key: str,
        audience: str,
        fact_key: str,
        evidence_digest: str,
        evidence_ids: list[str],
        source_row_ids: list[int],
        source_digests: list[str],
        bot_ref: str,
        connection_id: str,
        conversation_key: str,
        opportunity_id: str = "",
        lease_owner: str = "",
    ) -> bool:
        """创建 RESERVED attempt；claim 已有在途求证/UNKNOWN 占用时返回 False。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self.ensure_tables(conn)
                conn.execute(
                    "INSERT INTO memory_verification_attempts ("
                    " attempt_id, opportunity_id, candidate_id, candidate_content_digest,"
                    " owner_type, owner_key, subject_key, audience, fact_key,"
                    " evidence_digest, evidence_ids, source_row_ids, source_digests,"
                    " bot_ref, connection_id, conversation_key, question_message_ids,"
                    " state, created_at, lease_owner, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'RESERVED', ?, ?, ?)",
                    (
                        uuid.uuid4().hex,
                        opportunity_id,
                        str(candidate_id),
                        candidate_content_digest,
                        owner_type,
                        owner_key,
                        subject_key,
                        audience,
                        fact_key,
                        evidence_digest,
                        json.dumps(evidence_ids),
                        json.dumps(source_row_ids),
                        json.dumps(source_digests),
                        bot_ref,
                        connection_id,
                        conversation_key,
                        "[]",
                        utc_now_iso(),
                        lease_owner,
                        utc_now_iso(),
                    ),
                )
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                # 唯一 active claim 冲突：同一旧证据已在求证中（含
                # DELIVERY_UNKNOWN 保守占用——崩溃后不重投同一证据）
                conn.rollback()
                return False
            except BaseException:
                conn.rollback()
                raise
        finally:
            conn.close()

    # ── 发送结算（ACK / 失败 / UNKNOWN） ──
    def mark_sent(
        self,
        candidate_id: str,
        question_message_ids: list[str],
        *,
        verification_window_seconds: float = DEFAULT_VERIFICATION_WINDOW_SECONDS,
    ) -> bool:
        """RESERVED/SENDING → PENDING_VERIFICATION：记录全部物理片段与 deadline。

        只允许从 RESERVED/SENDING 推进（先 mark_sending 再 ACK 也合法）；
        deadline = ACK 时刻 + 窗口。
        """
        if not question_message_ids:
            return False
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE memory_verification_attempts SET"
                " state='PENDING_VERIFICATION', question_message_ids=?,"
                " sent_at=?, deadline=?, updated_at=?"
                " WHERE candidate_id=? AND state IN ('RESERVED','SENDING')",
                (
                    json.dumps([str(m) for m in question_message_ids]),
                    utc_now_iso(),
                    _iso_after(verification_window_seconds),
                    utc_now_iso(),
                    str(candidate_id),
                ),
            )
            conn.commit()
            return cur.rowcount > 0
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_cancelled(self, candidate_id: str, reason: str) -> bool:
        """确定未发送 → CANCELLED（不产生 tombstone：没有证据被拒绝）。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE memory_verification_attempts SET state='CANCELLED',"
                " result_reason=?, updated_at=?"
                " WHERE candidate_id=? AND state IN ('RESERVED','SENDING')",
                (reason, utc_now_iso(), str(candidate_id)),
            )
            conn.commit()
            return cur.rowcount > 0
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_delivery_unknown(self, candidate_id: str, reason: str) -> bool:
        """发送结果未知 → DELIVERY_UNKNOWN：保守占用、不重投、不冒充未回应。"""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE memory_verification_attempts SET state='DELIVERY_UNKNOWN',"
                " result_reason=?, updated_at=?"
                " WHERE candidate_id=? AND state IN ('RESERVED','SENDING')",
                (reason, utc_now_iso(), str(candidate_id)),
            )
            conn.commit()
            return cur.rowcount > 0
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── 回应裁决（保守绑定：明确回复问题片段才可结算） ──
    def settle_reply(
        self,
        *,
        conversation_key: str,
        subject_key: str,
        reply_message_id: str,
        reply_to_message_id: str | None,
        text: str,
    ) -> str | None:
        """尝试用一条入站消息裁决在途求证；返回结算动词或 None。

        可绑定：同一会话、正确主体、且**显式回复**问题片段之一。
        他人代答、无关 @、纯 @ 到 Bot（无回复链）都不能确认——无法关联
        则继续等待到 deadline（由 resolve_expired 结算 UNANSWERED）。
        肯定 → CONFIRMED（只记录确认关系；不自动晋升，见计划 §6.4）；
        明确否认 → DENIED；回避/含糊 → UNCLEAR（终结，不追问第二次）。
        """
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT attempt_id, candidate_id, question_message_ids, state FROM"
                " memory_verification_attempts"
                " WHERE conversation_key=? AND subject_key=?"
                " AND state='PENDING_VERIFICATION'"
                " ORDER BY created_at DESC LIMIT 1",
                (conversation_key, subject_key),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None
            question_ids = set(json.loads(row["question_message_ids"] or "[]"))
            if not reply_to_message_id or str(reply_to_message_id) not in question_ids:
                # 无可靠绑定：等待原 deadline，不提前裁决
                conn.rollback()
                return None
            verdict = _classify_reply_text(text or "")
            cur = conn.execute(
                "UPDATE memory_verification_attempts SET state=?,"
                " reply_message_id=?, reply_digest=?, result_reason=?, updated_at=?"
                " WHERE attempt_id=? AND state='PENDING_VERIFICATION'",
                (
                    verdict,
                    str(reply_message_id),
                    digest_json({"text": text or ""}),
                    f"reply_binding:{verdict.lower()}",
                    utc_now_iso(),
                    row["attempt_id"],
                ),
            )
            applied = cur.rowcount > 0
            if applied and verdict in ("DENIED", "UNCLEAR"):
                self._write_tombstone_locked(conn, row["attempt_id"])
                self._cas_reject_candidate_locked(conn, row["candidate_id"])
            conn.commit()
            return verdict if applied else None
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── 到期与恢复 ──
    def resolve_expired(self, now: datetime | None = None) -> list[str]:
        """到期 PENDING → UNANSWERED + tombstone + 候选 CAS 拒绝。

        晚到回应不复活旧 attempt（结算按可信入站时间与持久顺序；
        deadline 判定用持久 UTC 时间戳，不用 monotonic）。
        返回结算的 attempt_id 列表。
        """
        now_iso = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT attempt_id, candidate_id FROM memory_verification_attempts"
                " WHERE state='PENDING_VERIFICATION' AND deadline IS NOT NULL"
                " AND deadline <= ?",
                (now_iso,),
            ).fetchall()
            settled: list[str] = []
            for row in rows:
                cur = conn.execute(
                    "UPDATE memory_verification_attempts SET state='UNANSWERED',"
                    " result_reason='deadline_expired', updated_at=?"
                    " WHERE attempt_id=? AND state='PENDING_VERIFICATION'",
                    (utc_now_iso(), row["attempt_id"]),
                )
                if cur.rowcount > 0:
                    self._write_tombstone_locked(conn, row["attempt_id"])
                    self._cas_reject_candidate_locked(conn, row["candidate_id"])
                    settled.append(row["attempt_id"])
            conn.commit()
            return settled
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def recover_on_startup(self) -> dict[str, int]:
        """启动扫描：到期 PENDING 幂等到期；SENDING/UNKNOWN 不自动重投。

        SENDING 是「预留后、ACK 前崩溃」的窗口——按计划保守标记为
        DELIVERY_UNKNOWN（占用机会、不伪装成用户沉默/拒绝、不重发）。
        """
        recovered = {"expired": 0, "unknown": 0}
        recovered["expired"] = len(self.resolve_expired())
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "UPDATE memory_verification_attempts SET state='DELIVERY_UNKNOWN',"
                " result_reason='startup_recovery_sending', updated_at=?"
                " WHERE state='SENDING'",
                (utc_now_iso(),),
            )
            recovered["unknown"] = cur.rowcount
            conn.commit()
            return recovered
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── tombstone 查询（写侧 consolidator / 晋升侧共用） ──
    def claim_rejected(self, *, owner_key: str, audience: str, fact_key: str,
                       subject_key: str) -> sqlite3.Row | None:
        """该 claim 是否存在拒绝 tombstone（终态拒绝记录，不因重启/新消息消失）。"""
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT * FROM memory_rejection_tombstones"
                " WHERE owner_key=? AND audience=? AND fact_key=? AND subject_key=?"
                " ORDER BY created_at DESC LIMIT 1",
                (owner_key, audience, fact_key, subject_key),
            ).fetchone()
        finally:
            conn.close()

    def resurrection_blocked(
        self, *, owner_key: str, audience: str, fact_key: str, subject_key: str,
        source_row_ids: list[int], source_digests: list[str],
    ) -> str | None:
        """旧证据子集重放检测：返回拦截原因；合法新证据返回 None。

        规则（计划 §6.4）：同 claim 的 tombstone 存在，且本次来源集合是
        tombstone 来源集合的**子集**（或逐字相同）→ 拦截。全新来源
        （新 UUID/新提取时间/转述不构成新证据，但新 row id 是）→ 放行，
        允许新 candidate generation。
        """
        tomb = self.claim_rejected(
            owner_key=owner_key, audience=audience, fact_key=fact_key,
            subject_key=subject_key,
        )
        if tomb is None:
            return None
        tomb_rows = set(json.loads(tomb["source_row_ids"] or "[]"))
        tomb_digests = set(json.loads(tomb["source_digests"] or "[]"))
        new_rows = {str(r) for r in source_row_ids}
        new_digests = set(source_digests or [])
        if not new_rows and not new_digests:
            return "tombstone:no_sources"
        rows_subset = bool(new_rows) and new_rows.issubset(tomb_rows)
        digests_subset = bool(new_digests) and new_digests.issubset(tomb_digests)
        if rows_subset or digests_subset:
            return "tombstone:old_source_replay"
        return None

    # ── 事务内私有助手（调用方已持 BEGIN IMMEDIATE） ──
    def _write_tombstone_locked(self, conn: sqlite3.Connection, attempt_id: str) -> None:
        row = conn.execute(
            "SELECT * FROM memory_verification_attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if row is None:
            return
        conn.execute(
            "INSERT OR IGNORE INTO memory_rejection_tombstones ("
            " tombstone_id, attempt_id, owner_type, owner_key, subject_key, audience,"
            " fact_key, evidence_digest, source_row_ids, source_digests, reason, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                uuid.uuid4().hex,
                attempt_id,
                row["owner_type"],
                row["owner_key"],
                row["subject_key"],
                row["audience"],
                row["fact_key"],
                row["evidence_digest"],
                row["source_row_ids"],
                row["source_digests"],
                row["result_reason"] or "rejected",
                utc_now_iso(),
            ),
        )

    def _cas_reject_candidate_locked(self, conn: sqlite3.Connection, candidate_id: str) -> None:
        """条件更新：只有仍是 NEW/OBSERVING 的候选被拒绝；并发晋升提交后
        不覆盖（REJECTED 不抢已 CONFIRMED/晋升的行），重复结算幂等。"""
        conn.execute(
            "UPDATE memory_candidates SET status='REJECTED', updated_at=CURRENT_TIMESTAMP"
            " WHERE id=? AND status IN ('NEW','OBSERVING')",
            (str(candidate_id),),
        )


_store_singleton: "MnemeVerificationStore | None" = None
_store_singleton_db: str = ""
_startup_recovery_done: bool = False


def get_verification_store(db_path: str) -> MnemeVerificationStore:
    """进程级单例访问器；首次访问执行一次启动恢复扫描（幂等）。

    惰性触发（不挂 startup 钩子）：pytest 游荡 lifespan 不会误触发恢复；
    运行时首个 tick/入站结算即完成扫描。SENDING→DELIVERY_UNKNOWN 与
    过期 PENDING→UNANSWERED 各只跑一次。
    """
    global _store_singleton, _store_singleton_db, _startup_recovery_done
    key = str(db_path)
    if _store_singleton is None or _store_singleton_db != key:
        _store_singleton = MnemeVerificationStore(key)
        _store_singleton_db = key
        _startup_recovery_done = False
    if not _startup_recovery_done:
        _startup_recovery_done = True
        try:
            recovered = _store_singleton.recover_on_startup()
            if recovered.get("unknown") or recovered.get("expired"):
                logger.info(
                    f"🔁 [主动@] 启动求证恢复：{recovered.get('expired', 0)} 条到期、"
                    f"{recovered.get('unknown', 0)} 条 SENDING→UNKNOWN"
                )
        except Exception as e:  # 恢复失败不阻塞主流程；下个 tick 的 resolve_expired 兜底
            logger.warning(f"⚠️ [主动@] 启动求证恢复异常（跳过）: {e}")
    return _store_singleton


def reset_verification_store_for_tests() -> None:
    """清空单例与恢复标记（测试隔离用）。"""
    global _store_singleton, _store_singleton_db, _startup_recovery_done
    _store_singleton = None
    _store_singleton_db = ""
    _startup_recovery_done = False


def _iso_after(seconds: float) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="seconds"
    )


# 保守裁决词表：只认显式肯定/否认；含糊、转移话题 → UNCLEAR。
_AFFIRMATIVE_EXACT = {
    "是", "对", "嗯", "嗯嗯", "是的", "对哦", "对的", "没错", "还在", "是的呢",
    "yes", "yeah", "yep", "correct", "true", "still", "still am", "still do",
}
_NEGATION_MARKERS = (
    "不是", "没了", "不玩", "不用了", "换了吧", "早就", "没有", "不", "没",
    "no", "not", "nope", "don't", "dont", "sold", "stopped", "never",
)
_EVASIVE_MARKERS = ("怎么说呢", "不好说", "忘了", "不告诉你", "再说吧", "maybe", "not sure")


def _classify_reply_text(text: str) -> str:
    """保守三分类：DENIED 只认显式否定；UNCLEAR 只认显式回避；其余肯定。

    「嗯」单独出现只有绑定明确（reply-to 问题片段）才算确认——绑定检查
    在 settle_reply 中先行完成，这里只做文本分类。
    """
    stripped = (text or "").strip().lower()
    if not stripped:
        return "UNCLEAR"
    if any(marker in stripped for marker in _EVASIVE_MARKERS):
        return "UNCLEAR"
    if any(marker in stripped for marker in _NEGATION_MARKERS):
        # 「不是吧（惊讶）」类不是否认——保守起见交 UNCLEAR 由人工/后续证据裁决？
        # 不：计划要求「有明确关联但回避/含糊则 UNCLEAR，终结且不追问第二次」；
        # 显式否定词命中即 DENIED（误杀由合法新证据通道兜底）。
        return "DENIED"
    if stripped in _AFFIRMATIVE_EXACT or stripped.replace(" ", "") in _AFFIRMATIVE_EXACT:
        return "CONFIRMED"
    # 长句默认含糊（不把多余的话强行当确认）
    if len(stripped) <= 6:
        return "CONFIRMED"
    return "UNCLEAR"


__all__ = [
    "ATTEMPT_STATES",
    "DEFAULT_VERIFICATION_WINDOW_SECONDS",
    "REJECTION_TOMBSTONES_CLAIM_INDEX_DDL",
    "REJECTION_TOMBSTONES_TABLE_DDL",
    "TERMINAL_STATES",
    "VERIFICATION_ATTEMPTS_ACTIVE_UNIQUE_INDEX_DDL",
    "VERIFICATION_ATTEMPTS_OVERDUE_INDEX_DDL",
    "VERIFICATION_ATTEMPTS_TABLE_DDL",
    "AttemptRecord",
    "MnemeVerificationStore",
    "digest_json",
    "get_verification_store",
    "reset_verification_store_for_tests",
    "utc_now_iso",
]
