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


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_digest(row: dict) -> str:
    # Repairs are row-level CAS operations. Hash every persisted column so a
    # status/owner/source change during the review window cannot pass merely
    # because type/content stayed the same.
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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


_LINEAGE_ENTITY_TABLES = {
    "memory_candidate": "memory_candidates",
    "memory": "memories",
    "atomic_fact": "atomic_facts",
    "profile_fact": "personal_profile_facts",
    "shared_copy": "memories",
    "proactive_hypothesis": "proactive_hypotheses",
}


def _dict_rows(conn: sqlite3.Connection, table: str, where: str, params: tuple) -> list[dict]:
    cur = conn.execute(f"SELECT * FROM {table} WHERE {where}", params)
    names = [item[0] for item in cur.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def _lineage_snapshot(
    conn: sqlite3.Connection, owner_key: str, audience: str, fact_key: str
) -> dict:
    """Capture exact evidence, claim links, derived rows and epochs for one claim."""
    evidence = _dict_rows(
        conn,
        "memory_evidence",
        "owner_key = ? AND audience = ? AND fact_key = ?",
        (owner_key, audience, fact_key),
    )
    links = _dict_rows(
        conn,
        "memory_claim_links",
        "owner_key = ? AND audience = ? AND claim_key = ?",
        (owner_key, audience, fact_key),
    )
    entities: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for link in links:
        table = _LINEAGE_ENTITY_TABLES.get(str(link.get("entity_type") or ""))
        entity_id = str(link.get("entity_id") or "")
        if not table or not entity_id or (table, entity_id) in seen:
            continue
        seen.add((table, entity_id))
        try:
            rows = _dict_rows(conn, table, "id = ?", (entity_id,))
        except sqlite3.OperationalError:
            rows = []
        entities.append({"table": table, "id": entity_id, "row": rows[0] if rows else None})
    scope_keys = {owner_key, "global"}
    for entity in entities:
        row = entity.get("row") or {}
        group_space = str(row.get("group_shared_space") or "")
        if group_space:
            scope_keys.add(f"space:{group_space}")
    scope_versions = {
        str(key): int(version)
        for key, version in conn.execute(
            "SELECT scope_key, version FROM memory_scope_versions "
            "WHERE scope_key IN (" + ",".join("?" for _ in scope_keys) + ")",
            tuple(sorted(scope_keys)),
        ).fetchall()
    }
    for key in scope_keys:
        scope_versions.setdefault(key, 0)
    return {
        "owner_key": owner_key,
        "audience": audience,
        "fact_key": fact_key,
        "evidence": sorted(evidence, key=lambda row: str(row.get("id") or "")),
        "links": sorted(links, key=lambda row: str(row.get("id") or "")),
        "entities": sorted(entities, key=lambda row: (row["table"], row["id"])),
        "scope_versions": dict(sorted(scope_versions.items())),
    }


def _lineage_digest(snapshot: dict) -> str:
    value = {key: snapshot[key] for key in ("owner_key", "audience", "fact_key", "evidence", "links", "entities")}
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def preview_claim_invalidation(
    conn: sqlite3.Connection,
    *,
    evidence_id: str,
    invalidation_kind: str,
    superseded_by_evidence_id: str = "",
    reason: str = "reviewed_claim_correction",
) -> RepairRecord:
    """Build a read-only, exact claim/source invalidation manifest entry.

    The caller must identify the correction evidence; this function never infers a
    target claim from similar text or from the recording author alone.
    """
    if invalidation_kind not in {"source", "claim"}:
        raise ValueError("invalidation_kind must be 'source' or 'claim'")
    row = conn.execute(
        "SELECT owner_key, audience, fact_key, fact_subject_key, verification_status "
        "FROM memory_evidence WHERE id = ?",
        (evidence_id,),
    ).fetchone()
    if row is None:
        raise ValueError("source evidence does not exist")
    owner_key, audience, fact_key, subject_key, status = map(str, row)
    if not owner_key or not audience or not fact_key:
        raise ValueError("source evidence has incomplete claim scope")
    if status != "accepted":
        raise ValueError("only currently accepted source evidence can be invalidated")
    correction_digest = ""
    if invalidation_kind == "claim":
        correction_row = _load_row(conn, "memory_evidence", superseded_by_evidence_id)
        correction = conn.execute(
            "SELECT owner_key, audience, fact_subject_key, fact_key, verification_status "
            "FROM memory_evidence WHERE id = ?",
            (superseded_by_evidence_id,),
        ).fetchone()
        if correction is None:
            raise ValueError("claim invalidation requires existing correction evidence")
        if (
            str(correction[0]) != owner_key
            or str(correction[1]) != audience
            or str(correction[2]) != subject_key
            or str(correction[3]) == fact_key
            or str(correction[4]) != "accepted"
        ):
            raise ValueError("correction evidence owner/subject/status does not match")
        correction_digest = _row_digest(correction_row or {})
    snapshot = _lineage_snapshot(conn, owner_key, audience, fact_key)
    if invalidation_kind == "source" and not any(
        str(item.get("id")) == evidence_id for item in snapshot["evidence"]
    ):
        raise ValueError("source evidence is outside the claim snapshot")
    return RepairRecord(
        record_id=f"{owner_key}|{audience}|{fact_key}",
        table_name="memory_evidence",
        operation="claim_invalidate",
        issue_class=f"{invalidation_kind}_invalidation",
        expected_old={
            "lineage_digest": _lineage_digest(snapshot),
            "correction_digest": correction_digest,
        },
        payload={
            "owner_key": owner_key,
            "audience": audience,
            "fact_key": fact_key,
            "fact_subject_key": subject_key,
            "evidence_id": evidence_id,
            "invalidation_kind": invalidation_kind,
            "superseded_by_evidence_id": superseded_by_evidence_id,
            "evidence_status": status,
        },
        reason=reason,
        requires_confirm=True,
    )


def _bump_scope_keys(conn: sqlite3.Connection, keys) -> None:
    from memory import scope_versions

    for key in sorted({str(item) for item in keys if item}):
        scope_versions.bump(key, conn=conn, strict=True)


def _repair_scope_keys(*rows: dict, extra=()) -> set[str]:
    keys = {"global", *(str(item) for item in extra if item)}
    for row in rows:
        if not row:
            continue
        owner = str(row.get("owner_key") or "")
        group_space = str(row.get("group_shared_space") or "")
        owner_type = str(row.get("owner_type") or "").upper()
        if owner:
            keys.add(owner)
        elif group_space and owner_type == "SPACE":
            keys.add(f"space:{group_space}")
        if group_space and owner_type == "SPACE":
            keys.add(f"space:{group_space}")
    return keys


def _invalidate_claim(conn: sqlite3.Connection, record: RepairRecord, before: dict) -> dict:
    payload = record.payload
    kind = str(payload["invalidation_kind"])
    evidence_id = str(payload["evidence_id"])
    correction_id = str(payload.get("superseded_by_evidence_id") or "")
    target_ids = (
        {evidence_id}
        if kind == "source"
        else {str(row["id"]) for row in before["evidence"]}
    )
    if kind == "claim" and correction_id not in {str(row["id"]) for row in before["evidence"]}:
        # Correction evidence normally asserts the new claim and therefore has a
        # different fact_key; it must not be folded into the old claim snapshot.
        correction = conn.execute(
            "SELECT owner_key, audience, fact_subject_key, fact_key, verification_status "
            "FROM memory_evidence WHERE id = ?",
            (correction_id,),
        ).fetchone()
        if (
            correction is None
            or str(correction[0]) != payload["owner_key"]
            or str(correction[1]) != payload["audience"]
            or str(correction[2]) != payload["fact_subject_key"]
            or str(correction[3]) == payload["fact_key"]
            or str(correction[4]) != "accepted"
        ):
            raise RuntimeError("claim correction evidence changed after preview")
    for item in before["evidence"]:
        if str(item.get("id")) not in target_ids:
            continue
        try:
            provenance = json.loads(item.get("provenance_json") or "{}")
        except (TypeError, ValueError):
            provenance = {}
        provenance.update(
            {
                "verification_status": "superseded",
                "invalidation_kind": kind,
                "superseded_by_evidence_id": correction_id,
            }
        )
        conn.execute(
            "UPDATE memory_evidence SET verification_status = 'superseded', "
            "provenance_json = ? WHERE id = ? AND verification_status = ?",
            (
                json.dumps(provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                item["id"], item["verification_status"],
            ),
        )
    for link in before["links"]:
        entity_type = str(link.get("entity_type") or "")
        link_evidence_id = str(link.get("evidence_id") or "")
        should_invalidate = (
            kind == "claim"
            or (entity_type != "claim_state" and link_evidence_id in target_ids)
        )
        if not should_invalidate:
            continue
        state = "superseded" if entity_type == "claim_state" and kind == "claim" else "invalidated"
        conn.execute(
            "UPDATE memory_claim_links SET status = ?, invalidation_kind = ?, "
            "invalidated_by_evidence_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (state, kind, correction_id or evidence_id, link["id"]),
        )

    for entity in before["entities"]:
        table, entity_id, row = entity["table"], entity["id"], entity.get("row")
        if not row or "status" not in row:
            continue
        entity_types = {
            str(link.get("entity_type") or "")
            for link in before["links"]
            if str(link.get("entity_id") or "") == str(entity_id)
            and _LINEAGE_ENTITY_TABLES.get(str(link.get("entity_type") or "")) == table
        }
        if not entity_types:
            continue
        if kind == "source":
            placeholders = ",".join("?" for _ in entity_types)
            remains = conn.execute(
                "SELECT 1 FROM memory_claim_links l JOIN memory_evidence e ON e.id = l.evidence_id "
                "WHERE l.owner_key = ? AND l.audience = ? AND l.claim_key = ? "
                f"AND l.entity_type IN ({placeholders}) AND l.entity_id = ? "
                "AND l.status = 'active' AND e.verification_status = 'accepted' LIMIT 1",
                (payload["owner_key"], payload["audience"], payload["fact_key"],
                 *sorted(entity_types), entity_id),
            ).fetchone()
            if remains:
                continue
        status = "REJECTED" if table == "memory_candidates" else (
            "superseded" if table == "personal_profile_facts" else "DEPRECATED"
        )
        conn.execute(
            f"UPDATE {table} SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, entity_id),
        )
    scope_keys = _repair_scope_keys(
        *(entity.get("row") or {} for entity in before["entities"]),
        extra=(payload["owner_key"], "global"),
    )
    _bump_scope_keys(conn, scope_keys)
    return _lineage_snapshot(
        conn, payload["owner_key"], payload["audience"], payload["fact_key"]
    )


def _restore_lineage_snapshot(conn: sqlite3.Connection, snapshot: dict) -> None:
    restore_groups = [
        ("memory_evidence", snapshot["evidence"]),
        ("memory_claim_links", snapshot["links"]),
    ]
    for table, rows in restore_groups:
        for row in rows:
            current = _load_row(conn, table, str(row["id"]))
            if current is None:
                raise RuntimeError(f"claim lineage row disappeared during revoke: {table}:{row['id']}")
            assignments = ", ".join(f"{column} = ?" for column in row if column != "id")
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*(row[column] for column in row if column != "id"), row["id"]),
            )
    for item in snapshot["entities"]:
        row = item.get("row")
        if not row:
            continue
        table = item["table"]
        current = _load_row(conn, table, str(item["id"]))
        if current is None:
            raise RuntimeError(f"claim projection row disappeared during revoke: {table}:{item['id']}")
        assignments = ", ".join(f"{column} = ?" for column in row if column != "id")
        conn.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?",
            (*(row[column] for column in row if column != "id"), row["id"]),
        )


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

    if _load_row(conn, record.table_name, copy_id) is not None:
        raise RuntimeError(f"private repair copy already exists: {copy_id}")

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
            " source_conversation_key, source_row_id, candidate_id, fact_subject_key)"
            " SELECT ? || ':' || source_row_id, 'PERSON', ?, ?, 'PRIVATE_ONLY',"
            " fact_key, source_conversation_key, source_row_id, ?, ?"
            " FROM memory_evidence WHERE owner_key = ? AND fact_key = ?",
            (f"por:{copy_id}", target_owner, target_subject, copy_id, target_subject,
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
    copied_row = _load_row(conn, record.table_name, copy_id)
    created_rows = [{"table": record.table_name, "id": copy_id, "row": copied_row}]
    if fact_key and src_conv:
        evidence_rows = _dict_rows(
            conn, "memory_evidence", "candidate_id = ?", (copy_id,)
        )
        created_rows.extend(
            {"table": "memory_evidence", "id": str(item["id"]), "row": item}
            for item in evidence_rows
        )
    new_state = _load_row(conn, record.table_name, record.record_id) or new_state
    scope_keys = _repair_scope_keys(row, copied_row)
    new_state["__scope_keys"] = sorted(scope_keys)
    new_state["__created_rows"] = created_rows
    _bump_scope_keys(conn, scope_keys)
    audit_rows.append((record, row, new_state))


def apply_repairs(
    records: list[RepairRecord],
    operator: str = "system",
    dry_run: bool = False,
    confirm_source_missing: bool = False,
    confirm_claim_invalidation: bool = False,
) -> RepairBatch | None:
    """应用一批经过审核的修复，所有 CAS 和副作用共用一个事务。

    Manifest 漂移、确认缺失或任一 lineage 成员变化都会拒绝整批；不会
    部分应用兄弟修复。dry-run 执行同样的预检和写入，再整体回滚。
    """
    if not records:
        logger.info("✅ [DataRepair] No records to repair")
        return None

    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    try:
        _create_audit_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        batch_id = f"repair_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        audit_rows: list = []
        skipped: list[str] = []
        prepared: list[tuple[RepairRecord, dict | None]] = []

        for record in records:
            if record.operation == "none":
                skipped.append(f"{record.record_id or 'unknown'}:not_an_operation")
                continue
            if record.operation == "identity_claim_recheck":
                # 声明重检仍由 conversation_identity 的事务 API 执行。
                skipped.append(f"{record.record_id}:handled_by_identity_module")
                continue
            if record.operation not in {
                "private_owner_repair", "duplicate_deprecate", "orphan_deprecate",
                "claim_invalidate",
            }:
                raise RuntimeError(f"unknown repair operation: {record.operation}")
            confirmed = (
                record.operation in ("private_owner_repair", "duplicate_deprecate")
                or (record.operation == "orphan_deprecate" and confirm_source_missing)
                or (record.operation == "claim_invalidate" and confirm_claim_invalidation)
            )
            if record.requires_confirm and not confirmed:
                raise RuntimeError(f"{record.record_id}: explicit confirmation required")
            if record.operation == "claim_invalidate":
                snapshot = _lineage_snapshot(
                    conn, str(record.payload["owner_key"]),
                    str(record.payload["audience"]), str(record.payload["fact_key"]),
                )
                if _lineage_digest(snapshot) != str(
                    record.expected_old.get("lineage_digest") or ""
                ):
                    raise RuntimeError(f"{record.record_id}: claim lineage CAS conflict")
                correction_id = str(record.payload.get("superseded_by_evidence_id") or "")
                if correction_id:
                    correction_row = _load_row(conn, "memory_evidence", correction_id)
                    if correction_row is None or _row_digest(correction_row) != str(
                        record.expected_old.get("correction_digest") or ""
                    ):
                        raise RuntimeError(f"{record.record_id}: correction evidence CAS conflict")
                prepared.append((record, snapshot))
                continue
            ok, reason = _verify_expected(conn, record)
            if not ok:
                raise RuntimeError(f"{record.record_id}: manifest CAS conflict ({reason})")
            prepared.append((record, _load_row(conn, record.table_name, record.record_id)))

        for record, before in prepared:
            if record.operation == "claim_invalidate":
                assert before is not None
                after = _invalidate_claim(conn, record, before)
                before_scope_keys = _repair_scope_keys(
                    *(entity.get("row") or {} for entity in before["entities"]),
                    extra=(record.payload["owner_key"], "global"),
                )
                after_scope_keys = _repair_scope_keys(
                    *(entity.get("row") or {} for entity in after["entities"]),
                    extra=(record.payload["owner_key"], "global"),
                )
                audit_rows.append((
                    record,
                    {"__lineage__": True, "snapshot": before},
                    {
                        "__lineage__": True,
                        "digest": _lineage_digest(after),
                        "scope_keys": sorted(before_scope_keys | after_scope_keys),
                    },
                ))
                continue
            assert before is not None
            if record.operation == "private_owner_repair":
                _apply_private_owner_repair(conn, record, audit_rows)
            elif record.operation == "duplicate_deprecate":
                row = before
                conn.execute(
                    f"UPDATE {record.table_name} SET status = 'DEPRECATED',"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (record.record_id,),
                )
                new_state = _load_row(conn, record.table_name, record.record_id) or {}
                scope_keys = _repair_scope_keys(row, new_state)
                new_state["__scope_keys"] = sorted(scope_keys)
                _bump_scope_keys(conn, scope_keys)
                audit_rows.append((record, row, new_state))
            elif record.operation == "orphan_deprecate":
                row = before
                conn.execute(
                    "UPDATE memory_candidates SET status = 'DEPRECATED',"
                    " updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (record.record_id,),
                )
                new_state = _load_row(conn, "memory_candidates", record.record_id) or {}
                scope_keys = _repair_scope_keys(row, new_state)
                new_state["__scope_keys"] = sorted(scope_keys)
                _bump_scope_keys(conn, scope_keys)
                audit_rows.append((record, row, new_state))

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
                    json.dumps(new_state, ensure_ascii=False, default=str),
                    str(record.expected_old.get(
                        "content_digest", record.expected_old.get("lineage_digest", "")
                    )),
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
    """原子撤销一批修复；任一行或副作用漂移即回滚整个撤销批次。"""
    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None
    try:
        _create_audit_table(conn)
        conn.execute("BEGIN IMMEDIATE")
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

        # Preflight the entire batch before restoring any sibling. Audit rows
        # from older versions have no metadata and remain supported.
        prepared = []
        for audit_id, record_id, table_name, operation, old_json, new_json in rows:
            old_state = json.loads(old_json)
            new_state = json.loads(new_json)
            if new_state.get("__lineage__"):
                before = old_state.get("snapshot") or {}
                current = _lineage_snapshot(
                    conn, str(before["owner_key"]),
                    str(before["audience"]), str(before["fact_key"]),
                )
                if _lineage_digest(current) != str(new_state.get("digest") or ""):
                    raise RuntimeError(
                        f"claim lineage changed after apply; refusing partial revoke: {record_id}"
                    )
                prepared.append((audit_id, record_id, table_name, operation,
                                 old_state, new_state, current))
                continue
            row = _load_row(conn, table_name, record_id)
            if row is None:
                raise RuntimeError(f"repair row disappeared; refusing partial revoke: {record_id}")
            applied_row = {key: value for key, value in new_state.items() if not key.startswith("__")}
            expected_applied = {key: applied_row.get(key) for key in old_state}
            if _row_digest(row) != _row_digest(expected_applied):
                raise RuntimeError(
                    f"repair row changed after apply; refusing partial revoke: {record_id}"
                )
            created_rows = new_state.get("__created_rows") or []
            for item in created_rows:
                created = _load_row(conn, str(item["table"]), str(item["id"]))
                if created is None or _row_digest(created) != _row_digest(item["row"]):
                    raise RuntimeError(
                        f"repair side effect changed after apply; refusing partial revoke: "
                        f"{item['table']}:{item['id']}"
                    )
            prepared.append((audit_id, record_id, table_name, operation,
                             old_state, new_state, row))

        restored = 0
        for audit_id, record_id, table_name, _operation, old_state, new_state, current in reversed(prepared):
            if new_state.get("__lineage__"):
                before = old_state["snapshot"]
                restore_keys = _repair_scope_keys(
                    *(entity.get("row") or {} for entity in before["entities"]),
                    *(entity.get("row") or {} for entity in current["entities"]),
                    extra=(before["owner_key"], "global"),
                )
                _restore_lineage_snapshot(conn, before)
                _bump_scope_keys(conn, restore_keys)
            else:
                created_rows = new_state.get("__created_rows") or []
                # Delete child evidence before copied projections.
                for item in sorted(created_rows, key=lambda value: value["table"] != "memory_evidence"):
                    conn.execute(
                        f"DELETE FROM {item['table']} WHERE id = ?",
                        (item["id"],),
                    )
                assignments = [key for key in old_state if key != "id"]
                set_sql = ", ".join(f"{column} = ?" for column in assignments)
                suffix = "" if "updated_at" in old_state else ", updated_at = CURRENT_TIMESTAMP"
                conn.execute(
                    f"UPDATE {table_name} SET {set_sql}{suffix} WHERE id = ?",
                    (*(old_state[column] for column in assignments), record_id),
                )
                restored_row = _load_row(conn, table_name, record_id) or {}
                scope_keys = set(new_state.get("__scope_keys") or ())
                scope_keys.update(_repair_scope_keys(current, restored_row))
                _bump_scope_keys(conn, scope_keys)
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
