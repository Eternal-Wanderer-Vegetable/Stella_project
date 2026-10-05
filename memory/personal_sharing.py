# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""个人记忆共享 - 事实级授权与召回（整改计划 P3，复核 F3/F4/F5/F13）。

按计划 §6.3，私聊记忆默认 PRIVATE_ONLY，只有本人明确分享才允许
跨群可见（USER_SHARED）。授权必须绑定具体事实，并通过真实消息验证。

复核整改后的硬合同：

- **owner 绑定（F4）**：一切复制/已存在检查/撤回都按规范归属
  ``owner_key = person:{platform}:{bot_id}:{user_id}``
  （ownership.person_owner_key，检索缓存版本读的就是它）+ subject + fact_key；
  不再按 fact_key 全表匹配——不同用户同内容同键是正常数据，绝不能串。
- **来源绑定（F4）**：授权前服务端核验 source row（group_messages 存在、
  作者=本人、会话匹配、非 Bot）；核验不过一律拒绝。
- **pending（F4）**：事实尚未整合时授权落 pending，整合写入后同事务提升。
- **真实 DDL 复制（F3）**：副本逐列按 schema.py 规范 DDL；candidates 没有
  confirmation_count/last_confirmed_at，复制 SQL 不得引用。
- **台账（F13）**：副本逐条登记 personal_memory_sharing_copies；撤回只动
  本 grant 台账内的 record_id，regrant 按台账恢复副本并更新来源。
- **版本键（F5）**：bump 规范 person owner 键（strict，事务内，失败整体
  回滚）；``user:{uid}`` 是复核认定的错误键，不再使用。

模型输出不能授予 USER_SHARED；detect_sharing_intent 只是第一道有界词法，
授权必须经来源核验（§6.3：否定/引用/转述/Bot 台词都不是授权）。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from nonebot import logger

DEFAULT_PLATFORM = "qq"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SharingGrant:
    """共享授权记录。

    Attributes:
        grant_id: 授权 ID（自增主键）
        platform: 平台（默认 qq）
        bot_id: Bot ID
        user_id: 用户 ID（授权发起者，必须是事实主体本人）
        owner_key: 规范归属键 person:{platform}:{bot_id}:{user_id}
        subject_key: 主体键 qq:{user_id}
        fact_key: 事实键（memory 或 candidate 的 fact_key）
        source_conversation_key: 授权消息所在会话
        source_message_row_id: 授权消息的真实行 ID
        audience: 授权受众（USER_SHARED）
        status: 状态（pending / active / revoked）
        granted_at: 授权时间
        revoked_at: 撤回时间（若适用）
    """

    grant_id: int | None = None
    platform: str = DEFAULT_PLATFORM
    bot_id: str = ""
    user_id: str = ""
    owner_key: str = ""
    subject_key: str = ""
    fact_key: str = ""
    source_conversation_key: str = ""
    source_message_row_id: int = 0
    audience: str = "USER_SHARED"
    status: Literal["pending", "active", "revoked"] = "pending"
    granted_at: str = ""
    revoked_at: str | None = None


# ── 意图检测（有界词法，第一道防线；授权仍须来源核验） ──────────────────

# 分享范围词 + 分享动词**共现**才是分享（复核 F4 反例「我在群里玩游戏」
# 只有范围词、没有分享动词）
_SHARE_SCOPE_MARKS = ("群里", "群内", "在群")
_SHARE_VERB_MARKS = (
    "记得", "记住", "也能", "可以说", "可说", "提一嘴", "提一下", "提起",
    "提醒", "可分享", "可以分享", "分享到", "告诉他们", "让他们知道",
    "让他们也", "说出去",
)
# 转述/他人主张不是本人授权（「他说可以在群里分享这件事」）
_THIRD_PERSON_MARKS = ("他说", "她说", "他们说", "听说", "据说", "据介绍", "有人", "别人")
# 否定不是授权
_SHARE_NEGATIVE_MARKS = ("别", "不要", "不能", "禁止", "不可以", "先别", "不许")
# 显式撤回话术（P5 业务入口用；同样是有限词法，撤回路径做来源核验）
_REVOKE_MARKS = (
    "别在群里说", "不要在群里说", "先别在群里", "别在群里提", "不要在群里提",
    "别在群里用", "不要在群里用", "撤回共享", "收回共享", "别让大家知道",
)


def detect_sharing_intent(
    message_text: str,
    sender_id: int | str,
    conversation_key: str,
) -> tuple[bool, str]:
    """检测用户是否明确表达分享意图。

    肯定分享需要**同时**满足：分享范围词 + 分享动词 + 第一人称/直指语境；
    否定句、问句、转述一律不是授权。

    Returns:
        (is_sharing_intent, reason)
    """
    text = (message_text or "").strip()
    if not text:
        return False, "empty"

    if any(mark in text for mark in _SHARE_NEGATIVE_MARKS):
        return False, "negative"

    if "吗" in text or "?" in text or "？" in text:
        return False, "question"

    if any(mark in text for mark in _THIRD_PERSON_MARKS):
        return False, "third_person"

    has_scope = any(mark in text for mark in _SHARE_SCOPE_MARKS)
    has_verb = any(mark in text for mark in _SHARE_VERB_MARKS)
    # 第一人称主语；「这个/那个在群里也能用」类直指省略主语也算本人语境
    first_person = ("我" in text) or text.startswith(("这个", "那个", "这", "那"))
    if has_scope and has_verb and first_person:
        return True, "explicit_sharing"

    return False, "no_clear_intent"


def detect_revoke_intent(message_text: str) -> tuple[bool, str]:
    """检测显式撤回话术。返回 (is_revoke, matched_mark)。"""
    text = (message_text or "").strip()
    for mark in _REVOKE_MARKS:
        if mark in text:
            return True, mark
    return False, ""


# ── 规范归属（复核 F4/F5 的单一真相） ──────────────────────────────────


def canonical_owner(platform: str, bot_id: str | int, user_id: str | int) -> tuple[str, str, str]:
    """(owner_type, owner_key, subject_key)——与 ownership/retrieval_v2 同一键。"""
    from memory.ownership import OWNER_TYPE_PERSON, person_owner_key

    platform = str(platform or DEFAULT_PLATFORM)
    bot = str(bot_id or "")
    user = str(user_id or "")
    return (
        OWNER_TYPE_PERSON,
        person_owner_key(platform, bot, user),
        f"{platform}:{user}",
    )


# ── 表 ─────────────────────────────────────────────────────────────────


def create_sharing_authorization_table(conn: sqlite3.Connection) -> None:
    """创建共享授权表（幂等）。v18 起带规范归属绑定列。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personal_memory_sharing (
            grant_id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            platform TEXT NOT NULL DEFAULT 'qq',
            owner_key TEXT NOT NULL DEFAULT '',
            subject_key TEXT NOT NULL DEFAULT '',
            fact_key TEXT NOT NULL,
            source_conversation_key TEXT NOT NULL DEFAULT '',
            source_message_row_id INTEGER NOT NULL DEFAULT 0,
            audience TEXT NOT NULL DEFAULT 'USER_SHARED',
            status TEXT NOT NULL DEFAULT 'pending',
            granted_at TEXT NOT NULL,
            revoked_at TEXT,
            scope_version INTEGER NOT NULL DEFAULT 0,
            UNIQUE(bot_id, user_id, fact_key)
        )
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sharing_bot_user_status
        ON personal_memory_sharing(bot_id, user_id, status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sharing_owner_key
        ON personal_memory_sharing(owner_key, status)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sharing_fact_key
        ON personal_memory_sharing(fact_key)
    """)


def create_sharing_copies_table(conn: sqlite3.Connection) -> None:
    """创建共享副本台账（幂等；DDL 真相源在 schema.py，此处转发）。"""
    from memory.schema import create_sharing_copies_table as _create

    _create(conn)


# ── 来源核验（复核 F4：授权必须锚定真实消息） ──────────────────────────


def verify_grant_source(
    conn: sqlite3.Connection,
    platform: str,
    bot_id: str | int,
    user_id: str | int,
    source_conversation_key: str,
    source_message_row_id: int,
) -> tuple[bool, str]:
    """服务端核验授权来源消息：行存在、作者=本人、会话匹配、非 Bot。

    任何一项不满足都拒绝——引用消息、他人消息、编造 row id 都不能授权。
    """
    row_id = int(source_message_row_id or 0)
    key = str(source_conversation_key or "")
    if not row_id or not key:
        return False, "source_unspecified"
    try:
        row = conn.execute(
            "SELECT user_id, conversation_key, bot_id, source_kind"
            " FROM group_messages WHERE id = ?",
            (row_id,),
        ).fetchone()
    except sqlite3.OperationalError as e:
        return False, f"source_lookup_failed:{e}"
    if row is None:
        return False, "source_row_missing"
    author, conv_key, row_bot, source_kind = (str(c or "") for c in row)
    if author != str(user_id):
        return False, "source_author_mismatch"
    if conv_key != key:
        return False, "source_conversation_mismatch"
    if row_bot and row_bot != str(bot_id):
        return False, "source_bot_mismatch"
    if source_kind == "BOT_SELF":
        return False, "source_is_bot"
    return True, "ok"


# ── 事实定位与复制（复核 F3：按真实 DDL 逐列复制） ─────────────────────


def _find_private_fact(
    cursor: sqlite3.Cursor, owner_key: str, subject_key: str, fact_key: str
) -> str | None:
    """找该本人名下 fact_key 对应的 PRIVATE_ONLY 原件在哪张表。

    返回 'memories' / 'memory_candidates' / None。按 owner 精确匹配——
    同 fact_key 的他人行（F4）永不参与。缺表（轻量库）按无原件处理。
    """
    present = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name IN ('memories', 'memory_candidates')"
        ).fetchall()
    }
    if "memories" in present:
        row = cursor.execute(
            "SELECT id FROM memories"
            " WHERE fact_key = ? AND audience = 'PRIVATE_ONLY'"
            " AND owner_key = ? AND subject_key = ?"
            " AND (status IS NULL OR status != 'DEPRECATED') LIMIT 1",
            (fact_key, owner_key, subject_key),
        ).fetchone()
        if row:
            return "memories"
    if "memory_candidates" in present:
        row = cursor.execute(
            "SELECT id FROM memory_candidates"
            " WHERE fact_key = ? AND audience = 'PRIVATE_ONLY'"
            " AND owner_key = ? AND subject_key = ?"
            " AND (status IS NULL OR status != 'DEPRECATED') LIMIT 1",
            (fact_key, owner_key, subject_key),
        ).fetchone()
        if row:
            return "memory_candidates"
    return None


def _compat_space(owner_key: str) -> str:
    from memory.ownership import AUDIENCE_USER_SHARED, person_compat_space

    return person_compat_space(owner_key, AUDIENCE_USER_SHARED)


def _replicate_memories_copy(
    cursor: sqlite3.Cursor,
    owner_key: str,
    subject_key: str,
    fact_key: str,
    source_row_id: str,
    copy_id: str,
    compat_space: str,
) -> bool:
    """memories 副本：按规范 DDL 逐列（memories 有 confirmation_count）。

    只复制指定源行（同 owner+fact 可能存在多条历史行，逐行复制+逐条入台账，
    常量 copy_id 会撞主键）。
    """
    cursor.execute(
        """
        INSERT INTO memories (
            id, group_shared_space, user_id, type, content, content_raw,
            importance, confidence, status, confirmation_count,
            last_confirmed_at, last_accessed_at, compressed_at, compression_version,
            is_atomized, usage_tags, visibility, trigger_data, behavior_rule,
            source_kind, origin_group_id, owner_type, owner_key, subject_key,
            audience, source_conversation_key, fact_key, policy_version,
            created_at, updated_at
        )
        SELECT
            ?, ?, user_id, type, content, content_raw,
            importance, confidence, status, confirmation_count,
            last_confirmed_at, last_accessed_at, compressed_at, compression_version,
            is_atomized, usage_tags, visibility, trigger_data, behavior_rule,
            source_kind, origin_group_id, owner_type, owner_key, subject_key,
            'USER_SHARED', source_conversation_key, fact_key, policy_version,
            created_at, CURRENT_TIMESTAMP
        FROM memories
        WHERE id = ? AND fact_key = ? AND audience = 'PRIVATE_ONLY'
          AND owner_key = ? AND subject_key = ?
          AND (status IS NULL OR status != 'DEPRECATED')
        """,
        (copy_id, compat_space, source_row_id, fact_key, owner_key, subject_key),
    )
    return bool(cursor.rowcount and cursor.rowcount > 0)


def _replicate_candidates_copy(
    cursor: sqlite3.Cursor,
    owner_key: str,
    subject_key: str,
    fact_key: str,
    source_row_id: str,
    copy_id: str,
    compat_space: str,
) -> bool:
    """candidates 副本：按规范 DDL 逐列。

    复核 F3：memory_candidates **没有** confirmation_count/last_confirmed_at
    （见 schema.py MEMORY_CANDIDATES_TABLE_DDL）；有 evidence/
    source_message_ids/occurrence_count/first_seen_at/source_kinds/
    verification_contract_json。错列即 OperationalError。
    """
    cursor.execute(
        """
        INSERT INTO memory_candidates (
            id, group_shared_space, user_id, type, content, content_raw,
            importance, confidence, evidence, status, source_message_ids,
            usage_tags, visibility, trigger_data, behavior_rule,
            source_kind, occurrence_count, first_seen_at, source_kinds,
            origin_group_id, owner_type, owner_key, subject_key,
            audience, source_conversation_key, fact_key, policy_version,
            verification_contract_json, created_at, updated_at
        )
        SELECT
            ?, ?, user_id, type, content, content_raw,
            importance, confidence, evidence, status, source_message_ids,
            usage_tags, visibility, trigger_data, behavior_rule,
            source_kind, occurrence_count, first_seen_at, source_kinds,
            origin_group_id, owner_type, owner_key, subject_key,
            'USER_SHARED', source_conversation_key, fact_key, policy_version,
            verification_contract_json, created_at, CURRENT_TIMESTAMP
        FROM memory_candidates
        WHERE id = ? AND fact_key = ? AND audience = 'PRIVATE_ONLY'
          AND owner_key = ? AND subject_key = ?
          AND (status IS NULL OR status != 'DEPRECATED')
        """,
        (copy_id, compat_space, source_row_id, fact_key, owner_key, subject_key),
    )
    return bool(cursor.rowcount and cursor.rowcount > 0)


def _replicate_as_user_shared(
    conn: sqlite3.Connection,
    grant_id: int,
    owner_key: str,
    subject_key: str,
    fact_key: str,
) -> int:
    """为授权复制 USER_SHARED 副本（复核 F3/F4/F13）。

    副本 ID = ``{源行id}:s{grant_id}``——同 fact_key 不同 grant（不同
    Bot/用户）互不冲突。副本逐条入台账；同时写授权证据行。
    返回复制的副本数。
    """
    cursor = conn.cursor()
    compat_space = _compat_space(owner_key)

    present = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name IN ('memories', 'memory_candidates')"
        ).fetchall()
    }
    if not present:
        return 0

    copied = 0
    for table_name, replicator in (
        ("memories", _replicate_memories_copy),
        ("memory_candidates", _replicate_candidates_copy),
    ):
        if table_name not in present:
            continue
        src_ids = [
            row[0]
            for row in cursor.execute(
                f"SELECT id FROM {table_name}"
                " WHERE fact_key = ? AND audience = 'PRIVATE_ONLY'"
                " AND owner_key = ? AND subject_key = ?"
                " AND (status IS NULL OR status != 'DEPRECATED')",
                (fact_key, owner_key, subject_key),
            ).fetchall()
        ]
        for src_id in src_ids:
            copy_id = f"{src_id}:s{grant_id}"
            if replicator(
                cursor, owner_key, subject_key, fact_key, src_id, copy_id, compat_space
            ):
                copied += 1
                conn.execute(
                    "INSERT OR IGNORE INTO personal_memory_sharing_copies"
                    " (grant_id, table_name, record_id) VALUES (?, ?, ?)",
                    (grant_id, table_name, copy_id),
                )
    return copied


def _write_copy_evidence(
    conn: sqlite3.Connection,
    grant_id: int,
    owner_key: str,
    subject_key: str,
    fact_key: str,
    source_conversation_key: str,
    source_message_row_id: int,
) -> None:
    """副本的授权证据行（audit 链的一部分；幂等）。"""
    cursor = conn.cursor()
    present = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name = 'memory_evidence'"
        ).fetchall()
    }
    if not present:
        return
    cursor.execute(
        "INSERT OR IGNORE INTO memory_evidence ("
        " id, owner_type, owner_key, subject_key, audience, fact_key,"
        " source_conversation_key, source_row_id, candidate_id)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            f"share:{grant_id}",
            "PERSON",
            owner_key,
            subject_key,
            "USER_SHARED",
            fact_key,
            source_conversation_key,
            int(source_message_row_id or 0),
            f"grant:{grant_id}",
        ),
    )


def _write_audit(
    conn: sqlite3.Connection,
    operation: str,
    grant_id: int,
    bot_id: str,
    user_id: str,
    fact_key: str,
    details: dict | None = None,
) -> None:
    """sharing_audit_log 写入（best-effort：旧库缺表不拖垮授权主流程）。"""
    cursor = conn.cursor()
    present = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name = 'sharing_audit_log'"
        ).fetchall()
    }
    if not present:
        return
    cursor.execute(
        "INSERT INTO sharing_audit_log"
        " (operation, grant_id, bot_id, user_id, fact_key, performed_at, details)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            operation,
            int(grant_id),
            str(bot_id),
            str(user_id),
            fact_key,
            _utcnow(),
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )


def _bump_owner_version(conn: sqlite3.Connection, owner_key: str) -> None:
    """推进规范 owner 的持久 scope 版本（复核 F5；strict：失败抛出回滚）。"""
    from memory import scope_versions

    try:
        scope_versions.bump(owner_key, conn=conn, strict=True)
    except Exception as e:
        logger.error(f"❌ [Sharing] scope_version bump failed for {owner_key}: {e}")
        raise


# ── 授权 / 提升 / 撤回 / 重授权 ────────────────────────────────────────


def grant_sharing_authorization(
    conn: sqlite3.Connection,
    platform: str,
    bot_id: str | int,
    user_id: str | int,
    fact_key: str,
    source_conversation_key: str,
    source_message_row_id: int,
) -> tuple[bool, str]:
    """授予共享授权（幂等；复核 F3/F4/F5/F13 合同）。

    必须在调用方短事务内执行（本函数不 BEGIN/COMMIT）：

    1. 服务端核验来源消息（作者/会话/Bot）；
    2. 定位本人名下 PRIVATE_ONLY 原件——没有 → pending（等整合写入后由
       ``promote_pending_grants_for_fact`` 同事务提升）；
    3. active：复制副本（带 grant_id 的 ID + 台账）+ 证据 + 审计；
    4. revoked（重授权，F13）：按台账恢复本 grant 副本原状态、来源更新为
       本次授权消息；其他 grant 副本不动；
    5. bump 规范 owner 版本键（strict，失败抛出让调用方整体回滚）。

    Returns:
        (success, reason)：reason ∈ already_active / granted / pending /
        pending_no_fact / regranted / source_unverified:* / invalid_input
    """
    _owner_type, owner_key, subject_key = canonical_owner(platform, bot_id, user_id)
    fact_key = str(fact_key or "").strip()
    if not owner_key or not subject_key or not fact_key:
        return False, "invalid_input"

    ok, reason = verify_grant_source(
        conn, platform, bot_id, user_id, source_conversation_key, source_message_row_id
    )
    if not ok:
        return False, reason

    cursor = conn.cursor()
    existing = cursor.execute(
        """
        SELECT grant_id, status FROM personal_memory_sharing
        WHERE bot_id = ? AND user_id = ? AND fact_key = ?
        """,
        (str(bot_id), str(user_id), fact_key),
    ).fetchone()

    now = _utcnow()

    if existing:
        grant_id, status = int(existing[0]), str(existing[1])
        if status == "active":
            return True, "already_active"

        if status == "revoked":
            # 重授权（F13）：更新来源为本消息，按台账恢复本 grant 副本
            cursor.execute(
                """
                UPDATE personal_memory_sharing
                SET status = 'active', granted_at = ?, revoked_at = NULL,
                    source_conversation_key = ?, source_message_row_id = ?,
                    owner_key = ?, subject_key = ?, platform = ?
                WHERE grant_id = ?
                """,
                (now, str(source_conversation_key), int(source_message_row_id),
                 owner_key, subject_key, str(platform or DEFAULT_PLATFORM), grant_id),
            )
            restored = 0
            ledger = cursor.execute(
                "SELECT table_name, record_id, prior_status"
                " FROM personal_memory_sharing_copies WHERE grant_id = ?",
                (grant_id,),
            ).fetchall()
            for table_name, record_id, prior_status in ledger:
                if table_name not in ("memories", "memory_candidates"):
                    continue
                cursor.execute(
                    f"UPDATE {table_name} SET status = ?, updated_at = CURRENT_TIMESTAMP"
                    " WHERE id = ? AND audience = 'USER_SHARED' AND owner_key = ?",
                    (prior_status or "ACTIVE", record_id, owner_key),
                )
                if cursor.rowcount and cursor.rowcount > 0:
                    restored += 1
                cursor.execute(
                    "UPDATE personal_memory_sharing_copies SET prior_status = NULL"
                    " WHERE grant_id = ? AND table_name = ? AND record_id = ?",
                    (grant_id, table_name, record_id),
                )
            if restored == 0:
                # 台账为空（旧数据）→ 重新复制兜底
                restored = _replicate_as_user_shared(
                    conn, grant_id, owner_key, subject_key, fact_key
                )
            _write_copy_evidence(
                conn, grant_id, owner_key, subject_key, fact_key,
                str(source_conversation_key), int(source_message_row_id),
            )
            _write_audit(conn, "regrant", grant_id, bot_id, user_id, fact_key,
                         {"restored": restored,
                          "source_row": int(source_message_row_id)})
            _bump_owner_version(conn, owner_key)
            return True, "regranted"

        # pending → 事实仍未整合：更新来源绑定后维持 pending
        cursor.execute(
            """
            UPDATE personal_memory_sharing
            SET source_conversation_key = ?, source_message_row_id = ?,
                granted_at = ?, owner_key = ?, subject_key = ?, platform = ?
            WHERE grant_id = ?
            """,
            (str(source_conversation_key), int(source_message_row_id), now,
             owner_key, subject_key, str(platform or DEFAULT_PLATFORM), grant_id),
        )
        fact_table = _find_private_fact(cursor, owner_key, subject_key, fact_key)
        if fact_table is None:
            return True, "pending"
        cursor.execute(
            "UPDATE personal_memory_sharing SET status = 'active' WHERE grant_id = ?",
            (grant_id,),
        )
        copied = _replicate_as_user_shared(
            conn, grant_id, owner_key, subject_key, fact_key
        )
        _write_copy_evidence(
            conn, grant_id, owner_key, subject_key, fact_key,
            str(source_conversation_key), int(source_message_row_id),
        )
        _write_audit(conn, "grant", grant_id, bot_id, user_id, fact_key,
                     {"copied": copied, "from": "pending"})
        _bump_owner_version(conn, owner_key)
        return True, "granted"

    # 全新授权
    fact_table = _find_private_fact(cursor, owner_key, subject_key, fact_key)
    status = "active" if fact_table is not None else "pending"
    cursor.execute(
        """
        INSERT INTO personal_memory_sharing
        (bot_id, user_id, platform, owner_key, subject_key, fact_key,
         source_conversation_key, source_message_row_id, audience, status,
         granted_at, scope_version)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USER_SHARED', ?, ?, 0)
        """,
        (str(bot_id), str(user_id), str(platform or DEFAULT_PLATFORM),
         owner_key, subject_key, fact_key, str(source_conversation_key),
         int(source_message_row_id), status, now),
    )
    grant_id = int(cursor.lastrowid)
    if status == "pending":
        return True, "pending"

    copied = _replicate_as_user_shared(conn, grant_id, owner_key, subject_key, fact_key)
    _write_copy_evidence(
        conn, grant_id, owner_key, subject_key, fact_key,
        str(source_conversation_key), int(source_message_row_id),
    )
    _write_audit(conn, "grant", grant_id, bot_id, user_id, fact_key,
                 {"copied": copied, "source_row": int(source_message_row_id)})
    _bump_owner_version(conn, owner_key)
    return True, "granted"


def promote_pending_grants_for_fact(
    conn: sqlite3.Connection,
    platform: str,
    bot_id: str | int,
    user_id: str | int,
    fact_key: str,
    source_conversation_key: str = "",
) -> int:
    """事实整合写入后，提升同 owner/fact 的 pending 授权为 active（复核 F4）。

    由整合写入路径在**同一事务**内调用（PERSON/PRIVATE_ONLY 行落库后）。
    返回提升的授权数。来源绑定用授权消息本身的 row（创建 pending 时已存）。
    """
    _owner_type, owner_key, subject_key = canonical_owner(platform, bot_id, user_id)
    fact_key = str(fact_key or "").strip()
    if not owner_key or not fact_key:
        return 0
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT grant_id FROM personal_memory_sharing"
        " WHERE owner_key = ? AND fact_key = ? AND status = 'pending'",
        (owner_key, fact_key),
    ).fetchall()
    promoted = 0
    for (grant_id,) in rows:
        row = cursor.execute(
            "SELECT source_conversation_key, source_message_row_id"
            " FROM personal_memory_sharing WHERE grant_id = ?",
            (grant_id,),
        ).fetchone()
        if not row:
            continue
        src_conv, src_row = str(row[0] or ""), int(row[1] or 0)
        cursor.execute(
            "UPDATE personal_memory_sharing SET status = 'active' WHERE grant_id = ?",
            (grant_id,),
        )
        copied = _replicate_as_user_shared(conn, grant_id, owner_key, subject_key, fact_key)
        _write_copy_evidence(
            conn, grant_id, owner_key, subject_key, fact_key, src_conv, src_row
        )
        _write_audit(conn, "promote", grant_id, bot_id, user_id, fact_key,
                     {"copied": copied})
        promoted += 1
    if promoted:
        _bump_owner_version(conn, owner_key)
    return promoted


def revoke_sharing_authorization(
    conn: sqlite3.Connection,
    platform: str,
    bot_id: str | int,
    user_id: str | int,
    fact_key: str,
) -> tuple[bool, str]:
    """撤回共享授权（复核 F4/F5/F13 合同）。

    只失活**本 grant 台账内**的副本（保留合法 PRIVATE_ONLY 原件与其他
    grant 的副本），原状态记入台账 prior_status 供 regrant 恢复；bump 规范
    owner 版本键（strict，失败抛出让调用方整体回滚）。须在调用方事务内。
    """
    _owner_type, owner_key, subject_key = canonical_owner(platform, bot_id, user_id)
    fact_key = str(fact_key or "").strip()
    if not owner_key or not fact_key:
        return False, "invalid_input"

    cursor = conn.cursor()
    grant = cursor.execute(
        """
        SELECT grant_id, status FROM personal_memory_sharing
        WHERE bot_id = ? AND user_id = ? AND fact_key = ?
        """,
        (str(bot_id), str(user_id), fact_key),
    ).fetchone()

    if not grant:
        return False, "not_found"

    grant_id, status = int(grant[0]), str(grant[1])
    if status == "revoked":
        return True, "already_revoked"

    now = _utcnow()

    cursor.execute(
        "UPDATE personal_memory_sharing"
        " SET status = 'revoked', revoked_at = ? WHERE grant_id = ?",
        (now, grant_id),
    )

    # 台账精确失活（复核 F4：不按 fact_key 全表 UPDATE）
    affected = 0
    ledger = cursor.execute(
        "SELECT table_name, record_id, prior_status"
        " FROM personal_memory_sharing_copies WHERE grant_id = ?",
        (grant_id,),
    ).fetchall()
    for table_name, record_id, prior_status in ledger:
        if table_name not in ("memories", "memory_candidates"):
            continue
        if not prior_status:
            row = cursor.execute(
                f"SELECT status FROM {table_name} WHERE id = ?",
                (record_id,),
            ).fetchone()
            conn.execute(
                "UPDATE personal_memory_sharing_copies SET prior_status = ?"
                " WHERE grant_id = ? AND table_name = ? AND record_id = ?",
                (str(row[0]) if row and row[0] else "ACTIVE",
                 grant_id, table_name, record_id),
            )
        cursor.execute(
            f"UPDATE {table_name} SET status = 'DEPRECATED', updated_at = CURRENT_TIMESTAMP"
            " WHERE id = ? AND audience = 'USER_SHARED' AND owner_key = ?",
            (record_id, owner_key),
        )
        affected += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

    # 台账为空（旧数据无副本登记）→ 按 owner 限定兜底失活（仍不跨用户）
    if not ledger:
        for table_name in ("memories", "memory_candidates"):
            present = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if not present:
                continue
            cursor.execute(
                f"UPDATE {table_name} SET status = 'DEPRECATED', updated_at = CURRENT_TIMESTAMP"
                " WHERE fact_key = ? AND audience = 'USER_SHARED'"
                " AND owner_key = ? AND subject_key = ?",
                (fact_key, owner_key, subject_key),
            )
            affected += cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0

    _write_audit(conn, "revoke", grant_id, bot_id, user_id, fact_key,
                 {"affected": affected})
    _bump_owner_version(conn, owner_key)
    return True, "revoked"


def get_user_shared_facts(
    conn: sqlite3.Connection,
    bot_id: str | int,
    user_id: str | int,
    platform: str = DEFAULT_PLATFORM,
) -> list[str]:
    """获取用户已授权共享的事实键列表（按规范 owner 绑定）。"""
    _owner_type, owner_key, _subject_key = canonical_owner(platform, bot_id, user_id)
    rows = conn.execute(
        """
        SELECT fact_key FROM personal_memory_sharing
        WHERE owner_key = ? AND status = 'active'
        ORDER BY granted_at DESC
        """,
        (owner_key,),
    ).fetchall()

    return [row[0] for row in rows]
