# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""历史个人记忆回填 CLI（计划 §6.9）：preview / apply / revoke。

定位：schema15 迁移只把存量标 SPACE，**不自动共享任何旧记忆**；跨空间个人
认知的修复必须走一次**审查后**的回填。本工具是唯一入口：

- **preview**：按 manifest 逐条判定 ``copy / skip / conflict`` 与原因，不改库；
- **apply**：以**复制**语义建立 PERSON + USER_SHARED 副本（原 SPACE 行原样
  保留），写批次审计，推进持久缓存版本；同 ``memory_id + owner +
  policy_version`` 重复 apply 幂等跳过；
- **revoke**：按批次删除副本并恢复版本，原始 SPACE 数据不受影响。

manifest（JSON）：显式 Bot 绑定 + 逐条 (memory_id, user_id,
source_conversation_key, source_row_id) 与类型白名单。服务端逐条核验：
记忆存在且仍为 SPACE、主体合法、会话在注册表且归属本 Bot、来源消息行真实
存在于该会话、类型在白名单内——任何一项不过即 ``skip``（落原因），
**绝不**因「看起来像」而迁移。

```powershell
python -m tools.backfill_personal_memory preview --manifest m.json
python -m tools.backfill_personal_memory apply    --manifest m.json --batch-id b1
python -m tools.backfill_personal_memory revoke   --batch-id b1
```
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from config import DB_PATH
from memory.ownership import (
    AUDIENCE_USER_SHARED,
    OWNER_TYPE_PERSON,
    POLICY_VERSION,
    person_compat_space,
)

# CLI 自管的审计表（ops 工具边界，不进核心 schema 版本）
_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS personal_memory_backfill_audit (
    batch_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    copied_memory_id TEXT NOT NULL,
    owner_key TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    manifest_fingerprint TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    PRIMARY KEY (memory_id, owner_key, policy_version)
)
"""

# 默认可共享类型白名单（计划 §6.5 第一版：稳定称呼/偏好/技术偏好；
# 群关系/行为约束/私密事实不在白名单，manifest 可收紧不可放宽出本集合）
_ALLOWED_TYPES = frozenset({"PREFERENCE", "RELATION", "FACT"})
_DEFAULT_TYPES = ["PREFERENCE", "RELATION"]


@dataclass
class EntryVerdict:
    """单条 manifest 条目的判定。"""

    memory_id: str
    action: str  # copy / skip / conflict
    reason: str = ""
    user_id: str = ""
    source_conversation_key: str = ""
    source_row_id: int = 0
    copied_memory_id: str = ""


@dataclass
class BackfillReport:
    batch_id: str
    entries: list[EntryVerdict] = field(default_factory=list)

    def summary(self) -> str:
        copied = sum(1 for e in self.entries if e.action == "copy")
        skipped = sum(1 for e in self.entries if e.action == "skip")
        conflicts = sum(1 for e in self.entries if e.action == "conflict")
        return (
            f"batch={self.batch_id} copy={copied} skip={skipped} conflict={conflicts}"
        )


def _connect(db_path: Path, *, create_audit: bool = False) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if create_audit:
        # 审计表只在写路径（apply/revoke）创建——preview 必须**零写入**
        # （§8.1：preview 不改原库，建表也算改）。
        conn.execute(_AUDIT_DDL)
    return conn


def _manifest_fingerprint(manifest: dict) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _verdict_entry(conn: sqlite3.Connection, manifest: dict, entry: dict) -> EntryVerdict:
    """单条服务端核验（计划 §6.9：不明来源不迁）。"""
    memory_id = str(entry.get("memory_id", "") or "")
    user_id = str(entry.get("user_id", "") or "").strip()
    sck = str(entry.get("source_conversation_key", "") or "").strip()
    try:
        source_row_id = int(entry.get("source_row_id", 0) or 0)
    except (TypeError, ValueError):
        source_row_id = 0
    verdict = EntryVerdict(memory_id=memory_id, action="skip",
                           user_id=user_id, source_conversation_key=sck,
                           source_row_id=source_row_id)

    if not memory_id or not user_id or not sck or not source_row_id:
        verdict.reason = "missing_field(memory_id/user_id/source_conversation_key/source_row_id)"
        return verdict
    if not user_id.isdigit() or int(user_id) <= 0:
        verdict.reason = f"invalid_subject({user_id!r})"
        return verdict
    bot_id = str(manifest.get("bot_id", "") or "")
    if not bot_id or not sck.startswith(f"qq:{bot_id}:"):
        verdict.reason = "conversation_key_not_bound_to_manifest_bot"
        return verdict

    # 记忆必须存在、active、仍是 SPACE（已迁移/PERSON 行 → conflict）
    row = conn.execute(
        "SELECT status, owner_type, user_id, type, content FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if row is None:
        verdict.reason = "memory_not_found"
        return verdict
    if (row["status"] or "") != "active":
        verdict.reason = f"memory_status({row['status']})"
        return verdict
    existing_owner = conn.execute(
        "SELECT owner_type FROM memories WHERE id = ? AND owner_type = 'PERSON'",
        (memory_id,),
    ).fetchone()
    if existing_owner is not None:
        verdict.action = "conflict"
        verdict.reason = "memory_already_person"
        return verdict
    if not (row["content"] or "").strip():
        verdict.reason = "empty_content"
        return verdict

    types = [str(t).upper() for t in manifest.get("types", _DEFAULT_TYPES)]
    if any(t not in _ALLOWED_TYPES for t in types):
        verdict.reason = f"manifest_type_outside_whitelist({types})"
        return verdict
    if (row["type"] or "").upper() not in types:
        verdict.reason = f"type_not_shareable({row['type']})"
        return verdict

    # 会话必须在注册表、是群会话、归属 manifest 声明的 Bot
    conv = conn.execute(
        "SELECT kind, bot_id, storage_session_id FROM conversation_registry"
        " WHERE conversation_key = ?",
        (sck,),
    ).fetchone()
    if conv is None:
        verdict.reason = "conversation_not_registered"
        return verdict
    if conv["kind"] != "group" or str(conv["bot_id"]) != bot_id:
        verdict.reason = "conversation_kind_or_bot_mismatch"
        return verdict

    # 来源消息行必须真实存在于该会话（存储键一致），且 sender == subject
    msg = conn.execute(
        "SELECT user_id, source_kind FROM group_messages WHERE id = ? AND group_id = ?",
        (source_row_id, str(conv["storage_session_id"])),
    ).fetchone()
    if msg is None:
        verdict.reason = "source_row_not_in_conversation"
        return verdict
    if str(msg["user_id"]) != user_id:
        verdict.reason = "source_row_sender_mismatch"
        return verdict
    if str(msg["source_kind"]) == "BOT_SELF":
        verdict.reason = "source_row_is_bot_self"
        return verdict

    verdict.action = "copy"
    return verdict


def preview(manifest: dict, *, db_path: Path = DB_PATH) -> BackfillReport:
    """只判定不落库（preview 不改原库，§8.1）。"""
    report = BackfillReport(batch_id=str(manifest.get("batch_id", "") or "preview"))
    conn = _connect(db_path)
    try:
        for entry in manifest.get("entries", []):
            report.entries.append(_verdict_entry(conn, manifest, entry))
    finally:
        conn.close()
    return report


def _copy_one(conn: sqlite3.Connection, manifest: dict, verdict: EntryVerdict) -> str:
    """复制 SPACE 行为 PERSON + USER_SHARED 副本；返回副本 id。"""
    src = conn.execute(
        "SELECT id, group_shared_space, user_id, type, content, content_raw,"
        " importance, confidence, confirmation_count, usage_tags, visibility,"
        " source_kind, origin_group_id, fact_key, last_confirmed_at"
        " FROM memories WHERE id = ?",
        (verdict.memory_id,),
    ).fetchone()
    bot_id = str(manifest["bot_id"])
    owner = f"person:qq:{bot_id}:{verdict.user_id}"
    subject = f"qq:{verdict.user_id}"
    new_id = uuid.uuid4().hex
    fact_key = verdict.memory_id  # 回填副本的 fact 锚定原记忆 id（防重复回填）
    conn.execute(
        "INSERT INTO memories ("
        "id, group_shared_space, user_id, type, content, content_raw, importance,"
        " confidence, status, confirmation_count, last_confirmed_at, last_accessed_at,"
        " usage_tags, visibility, behavior_rule, source_kind, origin_group_id,"
        " owner_type, owner_key, subject_key, audience, source_conversation_key,"
        " fact_key, policy_version)"
        " VALUES (?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            new_id,
            person_compat_space(owner, AUDIENCE_USER_SHARED),
            str(src["user_id"]),
            str(src["type"]),
            str(src["content"]),
            str(src["content_raw"] or src["content"]),
            float(src["importance"] or 0.0),
            float(src["confidence"] or 0.0),
            int(src["confirmation_count"] or 1),
            src["last_confirmed_at"],
            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            str(src["usage_tags"] or "[]"),
            # 共享副本不得比原行更开放（§6.5：受众不扩张）
            "INTERNAL" if str(src["visibility"] or "").upper() == "INTERNAL" else str(src["visibility"] or "OPEN"),
            "",  # behavior_rule 是群行为约束，不随个人事实复制
            str(src["source_kind"] or "PASSIVE"),
            str(src["origin_group_id"]) if src["origin_group_id"] is not None else None,
            OWNER_TYPE_PERSON,
            owner,
            subject,
            AUDIENCE_USER_SHARED,
            verdict.source_conversation_key,
            fact_key,
            POLICY_VERSION,
        ),
    )
    return new_id


def apply_manifest(
    manifest: dict, *, batch_id: str = "", db_path: Path = DB_PATH
) -> BackfillReport:
    """审查后执行：复制 PERSON 副本 + 审计 + 版本推进（幂等）。"""
    batch = batch_id or str(manifest.get("batch_id", "") or "")
    if not batch:
        raise SystemExit("apply 需要显式 --batch-id（审计与撤回的锚点）")
    fingerprint = _manifest_fingerprint(manifest)
    report = BackfillReport(batch_id=batch)
    conn = _connect(db_path, create_audit=True)
    try:
        from memory import scope_versions

        scope_version_conn: sqlite3.Connection | None = conn
        for entry in manifest.get("entries", []):
            verdict = _verdict_entry(conn, manifest, entry)
            if verdict.action != "copy":
                report.entries.append(verdict)
                continue
            # 幂等：同 memory_id + owner + policy_version 已回填过 → skip
            bot_id = str(manifest["bot_id"])
            owner = f"person:qq:{bot_id}:{verdict.user_id}"
            done = conn.execute(
                "SELECT copied_memory_id, revoked_at FROM personal_memory_backfill_audit"
                " WHERE memory_id = ? AND owner_key = ? AND policy_version = ?",
                (verdict.memory_id, owner, POLICY_VERSION),
            ).fetchone()
            if done is not None and done["revoked_at"] is None:
                verdict.action = "skip"
                verdict.reason = f"already_backfilled({done['copied_memory_id']})"
                report.entries.append(verdict)
                continue
            try:
                copied = _copy_one(conn, manifest, verdict)
                conn.execute(
                    "INSERT INTO personal_memory_backfill_audit ("
                    "batch_id, memory_id, copied_memory_id, owner_key, subject_key,"
                    " policy_version, manifest_fingerprint) VALUES (?,?,?,?,?,?,?)",
                    (batch, verdict.memory_id, copied, owner,
                     f"qq:{verdict.user_id}", POLICY_VERSION, fingerprint),
                )
                conn.commit()
                verdict.copied_memory_id = copied
                scope_versions.bump(owner, conn=scope_version_conn)
                conn.commit()
            except Exception as e:
                conn.rollback()
                verdict.action = "conflict"
                verdict.reason = f"copy_failed({type(e).__name__})"
            report.entries.append(verdict)
    finally:
        conn.close()
    return report


def revoke(batch_id: str, *, db_path: Path = DB_PATH) -> BackfillReport:
    """按批次撤回：删副本行（审计留 revoked_at），原 SPACE 行不受影响。"""
    report = BackfillReport(batch_id=batch_id)
    conn = _connect(db_path, create_audit=True)
    try:
        from memory import scope_versions

        rows = conn.execute(
            "SELECT memory_id, copied_memory_id, owner_key, revoked_at"
            " FROM personal_memory_backfill_audit WHERE batch_id = ?",
            (batch_id,),
        ).fetchall()
        if not rows:
            raise SystemExit(f"批次 {batch_id!r} 没有审计记录")
        for r in rows:
            verdict = EntryVerdict(
                memory_id=str(r["memory_id"]),
                action="skip",
                reason="already_revoked" if r["revoked_at"] else "revoked",
            )
            if r["revoked_at"] is None:
                conn.execute(
                    "DELETE FROM memories WHERE id = ? AND owner_type = 'PERSON'",
                    (r["copied_memory_id"],),
                )
                conn.execute(
                    "UPDATE personal_memory_backfill_audit SET revoked_at = CURRENT_TIMESTAMP"
                    " WHERE memory_id = ? AND copied_memory_id = ?",
                    (r["memory_id"], r["copied_memory_id"]),
                )
                scope_versions.bump(str(r["owner_key"]), conn=conn)
            report.entries.append(verdict)
        conn.commit()
    finally:
        conn.close()
    return report


def _load_manifest(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "entries" not in data:
        raise SystemExit("manifest 必须是含 entries 的 JSON 对象")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="backfill_personal_memory")
    parser.add_argument("command", choices=["preview", "apply", "revoke"])
    parser.add_argument("--manifest", help="manifest JSON 路径（preview/apply）")
    parser.add_argument("--batch-id", default="", help="批次 ID（apply 必填）")
    parser.add_argument("--db", default=str(DB_PATH), help="记忆库路径")
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    if args.command == "revoke":
        report = revoke(args.batch_id, db_path=db_path)
    else:
        if not args.manifest:
            raise SystemExit("preview/apply 需要 --manifest")
        manifest = _load_manifest(args.manifest)
        if args.command == "preview":
            report = preview(manifest, db_path=db_path)
        else:
            report = apply_manifest(manifest, batch_id=args.batch_id, db_path=db_path)

    for e in report.entries:
        print(f"{e.action.upper():8} {e.memory_id} {e.reason}")
        if e.copied_memory_id:
            print(f"         -> copy {e.copied_memory_id}")
    print(report.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
