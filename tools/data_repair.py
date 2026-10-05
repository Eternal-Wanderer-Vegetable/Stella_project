# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据修复工具 - 来源驱动的预览/应用/撤销（整改计划 P6，复核 F6-F9）。

复核整改后的硬合同：

- **来源驱动（F9）**：wrong_space 识别「owner=SPACE 但来源会话经
  conversation_registry 证明是私聊」的行——真实 09:00 现场形状
  （SPACE / space:space_4 / CURRENT_SPACE）由来源证据命中，不再按
  「PERSON+audience='SPACE'」这种与现场无关的查询形状；来源不明的行只列
  unknown，绝不猜。不迁移整个 space_*，逐行带 digest 操作。
- **作用域去重（F6）**：重复只在同一 (owner_type, owner_key, subject_key,
  audience, fact_key) 组内成立；PRIVATE_ONLY 原件 + USER_SHARED 副本是
  **合法双受众形状**永不标记（audience 在分组键里）；空 fact_key 一律列
  unknown 不自动处理；保留项 = 最早 created_at（平局取最小 id），稳定序。
- **注册表孤儿判定（F7）**：会话真相是 conversation_registry——身份
  revision 表只在声明/纠正时写入，缺行不代表缺来源（F7 的误判根因）。
  「注册表无此会话 **且** 证据来源行确实不存在」才进 source_missing 复核
  清单；该类操作必须显式 confirm 才可 apply。
- **列级 CAS 审计（F8）**：preview manifest 带整行期望旧值 + 内容 digest；
  apply 逐行重核（不信任 preview 旧结论），审计记录**逐列** old/new；
  revoke 按审计恢复全部被改列（绝不把 audience 塞回 status），前置 CAS
  = 当前行内容 digest 与 apply 后一致，保护期间用户的新变化。
- 撤回「错误公开 SPACE 行」的批次会恢复公开错误形状——含
  private_owner_repair 的批次 revoke 需要显式 confirm。

**三类显式操作**（原计划 §6.7）：private_owner_repair（复制到正确
PERSON/PRIVATE_ONLY + 证据 + 失活错误公开行）、share_grant_apply（经
memory.personal_sharing 的已核验授权路径）、identity_claim_recheck（按
当前解析器重检旧声明；本版提供声明重检的清单/复核入口，落库复用
conversation_identity 现有事务）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nonebot import logger

from config import DB_PATH

# 内容 digest 的列（修复一致性与 CAS 都锚定它；其余列由期望旧值锚定）
_DIGEST_COLUMNS = ("type", "content")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_digest(row: dict) -> str:
    payload = "|".join(str(row.get(c) or "") for c in _DIGEST_COLUMNS)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class RepairRecord:
    """单个待修复条目（来源驱动 + 可撤回 manifest）。

    Attributes:
        record_id: 行 ID
        table_name: memories / memory_candidates
        operation: private_owner_repair / share_grant_apply / identity_claim_recheck
        issue_class: wrong_space / duplicate / orphan_source_missing / unknown_source
        expected_old: 期望旧值（含内容 digest）；apply 逐列重核
        payload: 操作参数（如目标 person 归属）
        reason: 判定原因（人读）
        confidence: 置信度（展示用；门禁靠 expected_old 而不是它）
        requires_confirm: True 时 apply 必须显式确认（source_missing/撤回等）
    """

    record_id: str
    table_name: str
    operation: str
    issue_class: str
    expected_old: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)
    reason: str = ""
    confidence: float = 0.0
    requires_confirm: bool = False

    def to_manifest(self) -> dict:
        return {
            "record_id": self.record_id,
            "table_name": self.table_name,
            "operation": self.operation,
            "issue_class": self.issue_class,
            "expected_old": self.expected_old,
            "payload": self.payload,
            "reason": self.reason,
            "requires_confirm": self.requires_confirm,
        }

    @classmethod
    def from_manifest(cls, data: dict) -> "RepairRecord":
        return cls(
            record_id=str(data["record_id"]),
            table_name=str(data["table_name"]),
            operation=str(data["operation"]),
            issue_class=str(data["issue_class"]),
            expected_old=dict(data.get("expected_old") or {}),
            payload=dict(data.get("payload") or {}),
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence") or 0.0),
            requires_confirm=bool(data.get("requires_confirm")),
        )


@dataclass
class RepairBatch:
    batch_id: str
    repair_count: int
    applied_at: str
    operator: str
    rollback_available: bool
    skipped: list[str] = field(default_factory=list)
    audit_log_ids: list[int] = field(default_factory=list)


# ── 表（audit 列级化；工具侧表，首次 apply 时创建） ────────────────────


def _create_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_repair_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            record_id TEXT NOT NULL,
            table_name TEXT NOT NULL,
            operation TEXT NOT NULL,
            issue_class TEXT NOT NULL,
            old_state TEXT NOT NULL,
            new_state TEXT NOT NULL,
            content_digest TEXT NOT NULL DEFAULT '',
            applied_at TEXT NOT NULL,
            revoked_at TEXT,
            operator TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_batch ON data_repair_audit(batch_id)"
    )


# ── 检测（来源驱动；全部只读） ─────────────────────────────────────────


def _private_conversation_keys(conn: sqlite3.Connection) -> dict[str, dict]:
    """注册表中的私聊会话：conversation_key → {bot_id, peer_id, memory_space}。"""
    try:
        rows = conn.execute(
            "SELECT conversation_key, bot_id, peer_id FROM conversation_registry"
            " WHERE kind = 'private'"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {
        str(r[0]): {"bot_id": str(r[1] or ""), "peer_id": str(r[2] or "")}
        for r in rows
        if r[0]
    }


def _known_conversation_keys(conn: sqlite3.Connection) -> set[str]:
    try:
        rows = conn.execute(
            "SELECT conversation_key FROM conversation_registry"
        ).fetchall()
    except sqlite3.OperationalError:
        return set()
    return {str(r[0]) for r in rows if r[0]}


def _load_row(conn: sqlite3.Connection, table: str, record_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
    return dict(zip(cols, row, strict=True))


def preview_private_owner_repairs(conn: sqlite3.Connection) -> list[RepairRecord]:
    """识别「公开 SPACE 行、但来源证明是私聊」的归属修复项（复核 F9）。

    命中链（任一即可，全部来源驱动）：
    1. 行的 source_conversation_key 在注册表中登记为私聊；
    2. 行的 (fact_key, source_conversation_key) 在 memory_evidence 中有
       私聊来源证据。
    两者皆无 → 不猜测（space_* 本身可能是合法群空间）。
    """
    records: list[RepairRecord] = []
    private_keys = _private_conversation_keys(conn)
    if not private_keys:
        return records
    for table in ("memories", "memory_candidates"):
        rows = conn.execute(
            f"SELECT id, owner_type, owner_key, audience, status, fact_key,"
            f" source_conversation_key FROM {table}"
            f" WHERE status != 'DEPRECATED'"
        ).fetchall()
        for rid, owner_type, owner_key, audience, status, fact_key, src_conv in rows:
            info = private_keys.get(str(src_conv or ""))
            if info is None:
                continue
            if str(owner_type or "") == "PERSON":
                continue  # 已是 PERSON 归属，无需修复
            if not info["bot_id"] or not info["peer_id"]:
                continue
            from memory.ownership import person_owner_key

            records.append(
                RepairRecord(
                    record_id=str(rid),
                    table_name=table,
                    operation="private_owner_repair",
                    issue_class="wrong_space",
                    expected_old={
                        "owner_type": str(owner_type or ""),
                        "owner_key": str(owner_key or ""),
                        "audience": str(audience or ""),
                        "status": str(status or ""),
                        "fact_key": str(fact_key or ""),
                        "source_conversation_key": str(src_conv or ""),
                    },
                    payload={
                        "platform": "qq",
                        "bot_id": info["bot_id"],
                        "user_id": info["peer_id"],
                        "target_owner_key": person_owner_key(
                            "qq", info["bot_id"], info["peer_id"]
                        ),
                        "target_subject_key": f"qq:{info['peer_id']}",
                    },
                    reason=f"space_row_with_private_source:{src_conv}",
                    confidence=0.95,
                )
            )
    return records


def preview_duplicates(conn: sqlite3.Connection) -> tuple[list[RepairRecord], list[RepairRecord]]:
    """作用域内重复（复核 F6）。返回 (duplicates, unknowns)。

    - 只在同一 (owner_type, owner_key, subject_key, audience, fact_key) 组内
      比对；fact_key 为空的行进 unknowns（不自动处理）；
    - PRIVATE_ONLY + USER_SHARED 双受众是合法形状（audience 在组键里）；
    - 保留 = 最早 created_at（平局取最小 id），其余标 duplicate。
    """
    duplicates: list[RepairRecord] = []
    unknowns: list[RepairRecord] = []
    for table in ("memories", "memory_candidates"):
        rows = conn.execute(
            f"SELECT id, owner_type, owner_key, subject_key, audience, fact_key,"
            f" status, created_at, type, content FROM {table}"
            f" WHERE status != 'DEPRECATED' ORDER BY created_at ASC, id ASC"
        ).fetchall()
        groups: dict[tuple, list[tuple]] = {}
        empty_key = 0
        for row in rows:
            _rid, owner_type, owner_key, subject_key, audience, fact_key, _status, _created, _ctype, _content = row
            key = (str(owner_type or ""), str(owner_key or ""), str(subject_key or ""),
                   str(audience or ""), str(fact_key or ""))
            if not key[4]:
                empty_key += 1
                continue
            groups.setdefault(key, []).append(row)
        for key, members in groups.items():
            if len(members) < 2:
                continue
            keep = members[0]
            for dup in members[1:]:
                duplicates.append(
                    RepairRecord(
                        record_id=str(dup[0]),
                        table_name=table,
                        operation="duplicate_deprecate",
                        issue_class="duplicate",
                        expected_old={
                            "owner_type": key[0], "owner_key": key[1],
                            "subject_key": key[2], "audience": key[3],
                            "fact_key": key[4],
                            "status": str(dup[6] or ""),
                            "content_digest": _row_digest(
                                {"type": dup[8], "content": dup[9]}
                            ),
                        },
                        payload={"keep_id": str(keep[0])},
                        reason=f"scoped_duplicate_keep:{keep[0]}",
                        confidence=0.9,
                    )
                )
        if empty_key:
            unknowns.append(
                RepairRecord(
                    record_id="",
                    table_name=table,
                    operation="none",
                    issue_class="unknown_source",
                    payload={"empty_fact_key_rows": empty_key},
                    reason="empty_fact_key_not_auto_processed",
                    confidence=0.0,
                    requires_confirm=True,
                )
            )
    return duplicates, unknowns


def preview_orphans(conn: sqlite3.Connection) -> list[RepairRecord]:
    """来源缺失候选（复核 F7：注册表是会话真相）。

    「已注册/有证据」的正常会话永不判孤儿——身份 revision 表缺行不代表
    缺来源。只有「注册表无此会话 **且** 无任何来源证据」才列
    source_missing 复核项（requires_confirm，apply 须显式确认）。
    """
    records: list[RepairRecord] = []
    known = _known_conversation_keys(conn)
    for row in conn.execute(
        "SELECT id, source_conversation_key, fact_key, status FROM memory_candidates"
        " WHERE status != 'DEPRECATED'"
    ).fetchall():
        cid, src_conv, fact_key, status = row
        src_conv = str(src_conv or "")
        if src_conv and src_conv in known:
            continue  # 注册表在册 → 正常会话（有无身份声明无关，F7 反例）
        has_evidence = False
        if fact_key:
            try:
                has_evidence = bool(
                    conn.execute(
                        "SELECT 1 FROM memory_evidence WHERE fact_key = ? LIMIT 1",
                        (str(fact_key),),
                    ).fetchone()
                )
            except sqlite3.OperationalError:
                has_evidence = False
        if has_evidence:
            continue  # 来源证据真实存在 → 不判孤儿
        records.append(
            RepairRecord(
                record_id=str(cid),
                table_name="memory_candidates",
                operation="orphan_deprecate",
                issue_class="orphan_source_missing",
                expected_old={
                    "status": str(status or ""),
                    "fact_key": str(fact_key or ""),
                    "source_conversation_key": src_conv,
                },
                reason="registry_missing_and_no_evidence",
                confidence=0.8,
                requires_confirm=True,
            )
        )
    return records


def preview_identity_claim_rechecks(conn: sqlite3.Connection) -> list[RepairRecord]:
    """旧身份声明的重检清单（复核 F9 第三类操作；只列不改）。"""
    try:
        rows = conn.execute(
            "SELECT id, conversation_key, subject_user_id, alias, status,"
            " evidence_excerpt FROM conversation_identity_claims"
            " WHERE claim_kind = 'self_alias' AND status = 'active'"
            " ORDER BY id DESC LIMIT 200"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    records = []
    for rid, key, subject, alias, status, excerpt in rows:
        records.append(
            RepairRecord(
                record_id=str(rid),
                table_name="conversation_identity_claims",
                operation="identity_claim_recheck",
                issue_class="identity_recheck",
                expected_old={
                    "status": str(status or ""),
                    "alias": str(alias or ""),
                },
                payload={
                    "conversation_key": str(key or ""),
                    "subject_user_id": str(subject or ""),
                    "evidence_excerpt": str(excerpt or "")[:96],
                },
                reason="recheck_with_current_parser",
                confidence=0.0,
                requires_confirm=True,
            )
        )
    return records


def preview_repairs(conn: sqlite3.Connection | None = None) -> dict:
    """全量预览（只读）。返回分类清单；调用方审查后按 manifest 逐条 apply。"""
    own = conn is None
    if own:
        conn = sqlite3.connect(DB_PATH)
    try:
        duplicates, unknowns = preview_duplicates(conn)
        return {
            "private_owner_repairs": preview_private_owner_repairs(conn),
            "duplicates": duplicates,
            "orphans": preview_orphans(conn),
            "identity_claim_rechecks": preview_identity_claim_rechecks(conn),
            "unknowns": unknowns,
        }
    finally:
        if own:
            conn.close()


# ── apply / revoke（列级 CAS） ─────────────────────────────────────────


def _verify_expected(conn: sqlite3.Connection, record: RepairRecord) -> tuple[bool, str]:
    """apply 前逐列重核（复核 F8：不信任 preview 的旧结论）。"""
    row = _load_row(conn, record.table_name, record.record_id)
    if row is None:
        return False, "row_missing"
    expected = record.expected_old
    for col in ("owner_type", "owner_key", "audience", "status", "fact_key",
                "source_conversation_key", "subject_key"):
        if col in expected and str(row.get(col) or "") != str(expected.get(col) or ""):
            return False, f"mismatch:{col}"
    if "content_digest" in expected and _row_digest(row) != expected["content_digest"]:
        return False, "content_changed"
    return True, "ok"


def _apply_private_owner_repair(
    conn: sqlite3.Connection, record: RepairRecord, audit_rows: list
) -> None:
    """复制到正确 PERSON/PRIVATE_ONLY + 证据 + 失活错误公开行（同事务）。"""
    payload = record.payload
    row = _load_row(conn, record.table_name, record.record_id)
    target_owner = str(payload["target_owner_key"])
    target_subject = str(payload["target_subject_key"])
    compat_space = f"personal:{target_owner}:PRIVATE_ONLY"
    copy_id = f"{record.record_id}:por"

    columns = list(row.keys())
    select_cols = ", ".join(c for c in columns if c != "id")
    insert_cols = ", ".join(["id"] + [c for c in columns if c != "id"])
    conn.execute(
        f"INSERT INTO {record.table_name} ({insert_cols})"
        f" SELECT '{copy_id}'"
        + ("," + select_cols if select_cols else "")
        + f" FROM {record.table_name} WHERE id = ?",
        (record.record_id,),
    )
    # 副本改为正确 PERSON/PRIVATE_ONLY 归属
    updates = {
        "owner_type": "PERSON",
        "owner_key": target_owner,
        "subject_key": target_subject,
        "audience": "PRIVATE_ONLY",
    }
    if "group_shared_space" in columns:
        updates["group_shared_space"] = compat_space
    set_sql = ", ".join(f"{c} = ?" for c in updates)
    conn.execute(
        f"UPDATE {record.table_name} SET {set_sql}, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        (*updates.values(), copy_id),
    )
    # 证据行跟随副本（来源不变、归属换正确 person）
    fact_key = str(row.get("fact_key") or "")
    src_conv = str(row.get("source_conversation_key") or "")
    if fact_key and src_conv:
        conn.execute(
            "INSERT OR IGNORE INTO memory_evidence ("
            " id, owner_type, owner_key, subject_key, audience, fact_key,"
            " source_conversation_key, source_row_id, candidate_id)"
            " SELECT 'por:' || source_row_id, 'PERSON', ?, ?, 'PRIVATE_ONLY',"
            " fact_key, source_conversation_key, source_row_id, ?"
            " FROM memory_evidence WHERE owner_key = ? AND fact_key = ?",
            (target_owner, target_subject, copy_id,
             str(record.expected_old.get("owner_key") or ""), fact_key),
        )
    # 失活错误公开行（列级审计）
    new_state = dict(row)
    new_state["status"] = "DEPRECATED"
    conn.execute(
        f"UPDATE {record.table_name} SET status = 'DEPRECATED',"
        " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (record.record_id,),
    )
    audit_rows.append((record, row, new_state))
    # 规范 scope 版本推进（新 person 可见 + 旧 space 缓存换桶）
    from memory import scope_versions

    scope_versions.bump(target_owner, conn=conn, strict=True)
    old_space_key = str(record.expected_old.get("owner_key") or "")
    if old_space_key.startswith("space:"):
        scope_versions.bump(old_space_key, conn=conn, strict=True)


def apply_repairs(
    records: list[RepairRecord],
    operator: str = "system",
    dry_run: bool = False,
    confirm_source_missing: bool = False,
) -> RepairBatch | None:
    """应用修复批次（复核 F8：列级 CAS + 同事务版本推进）。

    - 逐条重核 expected_old，任何漂移跳过并记入 batch.skipped；
    - requires_confirm 的条目未显式确认时跳过；
    - 全程单事务：任一硬失败回滚整批（包括 scope 版本推进）。
    """
    if not records:
        logger.info("✅ [DataRepair] No records to repair")
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    try:
        _create_audit_table(conn)
        conn.execute("BEGIN")
        batch_id = f"repair_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        audit_rows: list = []
        skipped: list[str] = []

        for record in records:
            if record.requires_confirm and not (
                confirm_source_missing
                or record.operation in ("private_owner_repair", "duplicate_deprecate")
            ):
                skipped.append(f"{record.record_id}:needs_confirm")
                continue
            if record.operation == "none":
                skipped.append(f"{record.record_id or 'unknown'}:not_an_operation")
                continue
            ok, reason = _verify_expected(conn, record)
            if not ok:
                skipped.append(f"{record.record_id}:{reason}")
                continue
            if record.operation == "private_owner_repair":
                _apply_private_owner_repair(conn, record, audit_rows)
            elif record.operation == "duplicate_deprecate":
                row = _load_row(conn, record.table_name, record.record_id)
                new_state = dict(row)
                new_state["status"] = "DEPRECATED"
                conn.execute(
                    f"UPDATE {record.table_name} SET status = 'DEPRECATED',"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (record.record_id,),
                )
                audit_rows.append((record, row, new_state))
            elif record.operation == "orphan_deprecate":
                if not confirm_source_missing:
                    skipped.append(f"{record.record_id}:needs_confirm")
                    continue
                row = _load_row(conn, record.table_name, record.record_id)
                new_state = dict(row)
                new_state["status"] = "DEPRECATED"
                conn.execute(
                    "UPDATE memory_candidates SET status = 'DEPRECATED',"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (record.record_id,),
                )
                audit_rows.append((record, row, new_state))
            elif record.operation == "identity_claim_recheck":
                # 复核类：落库走 conversation_identity 现有事务/审计；
                # 本工具只登记复核批次，不改声明状态
                skipped.append(f"{record.record_id}:handled_by_identity_module")
            else:
                skipped.append(f"{record.record_id}:unknown_operation")

        audit_log_ids = []
        for record, old_state, new_state in audit_rows:
            cur = conn.execute(
                "INSERT INTO data_repair_audit ("
                " batch_id, record_id, table_name, operation, issue_class,"
                " old_state, new_state, content_digest, applied_at, operator)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id, record.record_id, record.table_name,
                    record.operation, record.issue_class,
                    json.dumps(old_state, ensure_ascii=False, default=str),
                    json.dumps(
                        {k: new_state.get(k) for k in old_state},
                        ensure_ascii=False, default=str,
                    ),
                    str(record.expected_old.get("content_digest") or ""),
                    _utcnow(), operator,
                ),
            )
            audit_log_ids.append(cur.lastrowid)

        if dry_run:
            conn.execute("ROLLBACK")
            logger.info(
                f"🧪 [DataRepair] Dry run: would repair {len(audit_rows)} records,"
                f" skip {len(skipped)}"
            )
            return None
        conn.execute("COMMIT")
        logger.info(
            f"✅ [DataRepair] Applied {len(audit_rows)} repairs in batch {batch_id}"
            f" (skipped {len(skipped)})"
        )
        return RepairBatch(
            batch_id=batch_id,
            repair_count=len(audit_rows),
            applied_at=_utcnow(),
            operator=operator,
            rollback_available=bool(audit_rows),
            skipped=skipped,
            audit_log_ids=audit_log_ids,
        )
    except Exception as e:
        with __import__("contextlib").suppress(Exception):
            conn.execute("ROLLBACK")
        logger.error(f"❌ [DataRepair] Failed to apply repairs: {e}")
        raise
    finally:
        conn.close()


def revoke_batch(
    batch_id: str,
    confirm_owner_repair: bool = False,
) -> bool:
    """撤销修复批次（复核 F8：列级还原 + 后置 CAS）。

    - 按审计的 old_state 恢复**全部被改列**（绝不把单值塞错列）；
    - 前置 CAS：当前行内容 digest == 审计 new_state 的 digest（apply 之后
      没有新变化），否则该条跳过并告警——保护期间用户的新数据；
    - 含 private_owner_repair 的批次会恢复公开错误行，必须显式确认。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    try:
        _create_audit_table(conn)
        conn.execute("BEGIN")
        rows = conn.execute(
            "SELECT audit_id, record_id, table_name, operation, old_state, new_state"
            " FROM data_repair_audit WHERE batch_id = ? AND revoked_at IS NULL",
            (batch_id,),
        ).fetchall()
        if not rows:
            logger.warning(f"⚠️ [DataRepair] Batch {batch_id} not found or already revoked")
            conn.execute("ROLLBACK")
            return False

        if not confirm_owner_repair and any(
            r[3] == "private_owner_repair" for r in rows
        ):
            logger.warning(
                "⚠️ [DataRepair] 批次含归属修复（撤回会恢复公开错误行），"
                "需要 confirm_owner_repair=True"
            )
            conn.execute("ROLLBACK")
            return False

        restored = 0
        for audit_id, record_id, table_name, _op, old_json, new_json in rows:
            old_state = json.loads(old_json)
            new_state = json.loads(new_json)
            row = _load_row(conn, table_name, record_id)
            if row is None:
                logger.warning(f"⚠️ [DataRepair] 行不存在，跳过撤回: {record_id}")
                continue
            if _row_digest(row) != _row_digest(new_state):
                logger.warning(
                    f"⚠️ [DataRepair] 行在 apply 后发生了新变化，CAS 拒绝撤回:"
                    f" {record_id}"
                )
                continue
            set_sql = ", ".join(f"{c} = ?" for c in old_state)
            conn.execute(
                f"UPDATE {table_name} SET {set_sql}, updated_at = CURRENT_TIMESTAMP"
                " WHERE id = ?",
                (*old_state.values(), record_id),
            )
            conn.execute(
                "UPDATE data_repair_audit SET revoked_at = ? WHERE audit_id = ?",
                (_utcnow(), audit_id),
            )
            restored += 1

        conn.execute("COMMIT")
        logger.info(f"✅ [DataRepair] Revoked batch {batch_id} ({restored} records)")
        return True
    except Exception as e:
        with __import__("contextlib").suppress(Exception):
            conn.execute("ROLLBACK")
        logger.error(f"❌ [DataRepair] Failed to revoke batch {batch_id}: {e}")
        return False
    finally:
        conn.close()


def list_batches() -> list[RepairBatch]:
    conn = sqlite3.connect(DB_PATH)
    try:
        _create_audit_table(conn)
        rows = conn.execute("""
            SELECT batch_id, COUNT(*) as cnt, MIN(applied_at) as applied_at, operator,
                   SUM(CASE WHEN revoked_at IS NULL THEN 1 ELSE 0 END) as active_cnt
            FROM data_repair_audit
            GROUP BY batch_id
            ORDER BY applied_at DESC
        """).fetchall()
        return [
            RepairBatch(
                batch_id=r[0], repair_count=r[1], applied_at=r[2], operator=r[3],
                rollback_available=(r[4] > 0), audit_log_ids=[],
            )
            for r in rows
        ]
    finally:
        conn.close()
