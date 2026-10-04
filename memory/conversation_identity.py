# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""会话内身份声明与纠错（多人身份修复计划 §6.3）。

职责边界（刻意收窄）：

- 只处理**当前会话**内的身份线索：本人自我介绍/改名、第三人有明确目标的
  纠正。不做跨群身份图，不把声明表当 PERSON 授权来源；
- subject 只能来自平台事实：本人声明的 subject = 平台 sender；第三人纠正
  只有在 reply/单-@/BOT_SELF 收件人给出**明确唯一目标**时才落带来源的
  纠正证据。目标不唯一就是普通对话，不写任何映射；
- 规则只覆盖已知失败形式（调查报告 §3 的 prefilter_miss 句式），不声称能
  解析任意中文纠正；引号/转述/第三人称转引/多个自称/超长内容一律 ambiguous；
- 身份陈述的使用优先级：平台 stable ID > 源消息校验的本人声明 > 显式称呼
  偏好（仅「怎么称呼」）> 带归属记忆 > 自由摘要。第三人或模型说法**永不**
  晋升为本人声明；
- 不改写 user_address_preferences（称呼命令仍走 classify_addressing/
  handle_addressing 权限链）；别名碰撞不合并 uid。

持久化：conversation_identity_claims（声明行，active/conflicted/inactive，
source_row_id 指向该会话已入库原消息）+ conversation_identity_versions
（每会话单调 revision）。声明写入与版本推进同一短事务；无 LLM 调用。
"""

from __future__ import annotations

import re
import sqlite3
import uuid

from nonebot import logger

from config import DB_PATH

# 声明种类（claim_kind 持久化值）
CLAIM_SELF_ALIAS = "self_alias"
CLAIM_THIRD_PERSON_CORRECTION = "third_person_correction"

# 声明状态
STATUS_ACTIVE = "active"
STATUS_CONFLICTED = "conflicted"
STATUS_INACTIVE = "inactive"

# 名字边界（计划 §6.3）：≤32 字符、复用 display name 的规范化要求
ALIAS_MAX_CHARS = 32
# 声明原文证据快照的有界摘要长度
EXCERPT_MAX_CHARS = 96

# 角色权限表达：不是名字，绝不产生身份或权限
_ROLE_TERMS = ("管理员", "群主", "机器人", "bot", "Bot", "AI", "ai", "助手")

# ── 有界规则（只认整条非引用文本的完整匹配） ──────────────────────────

# 本人声明 →（是否 supersedes 旧 self_alias）。「改名/才是/以后叫我」带更正
# 语义 → supersede；「我是X / X是我」是无更正语义的自我介绍 → 并存。
_SELF_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"^我才是(.+)$"), True),
    (re.compile(r"^那我改名叫(.+)$"), True),
    (re.compile(r"^我改名叫(.+)$"), True),
    (re.compile(r"^以后叫我(.+)$"), False),
    (re.compile(r"^我是(.+)$"), False),
    (re.compile(r"^(.+?)是我$"), False),
)

# 第三人纠正：他/她才是X（肯定指认）；X不是他 / 他不叫X（否定）。
_THIRD_POSITIVE = re.compile(r"^[他她它]才是(.+)$")
_THIRD_NEGATIVE = re.compile(r"^(.+?)(?:不是[他她它])$")
_THIRD_NEGATIVE2 = re.compile(r"^[他她它]不叫(.+)$")

# 分句符：多个分句各自命中自称模式 → ambiguous（一句话多个自称）
_CLAUSE_SPLIT = re.compile(r"[,，。！？!?；;]")

# 引号/转述标记：出现即判 ambiguous（转述别人的话不能当说话人自己的声明）
_QUOTE_MARKS = ("「", "」", "“", "”", "‘", "’", "\"", "'")


def normalize_alias(raw: str) -> str:
    """声明名字规范化：与 display name 同一清理规则 + 32 字符上限。"""
    from core.context import normalize_display_name

    return normalize_display_name(raw).strip()[:ALIAS_MAX_CHARS]


def parse_self_alias(text: str) -> tuple[str, bool] | None:
    """解析本人自我介绍/改名声明。返回 ``(alias, supersedes)`` 或 None。

    只匹配**整条**文本（strip 后全串）；含引号/转述标记、名字超限、名字是
    角色权限表达、一句话里有多个自称 → None（ambiguous，不落库）。
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 64:
        # 超长内容不是干净的自我介绍（聊天长句误命中风险）
        return None
    if any(mark in stripped for mark in _QUOTE_MARKS):
        return None
    match_count = 0
    parsed: tuple[str, bool] | None = None
    for pattern, supersedes in _SELF_PATTERNS:
        m = pattern.match(stripped)
        if not m:
            continue
        raw_name = m.group(1).strip()
        if not raw_name or len(raw_name) > ALIAS_MAX_CHARS:
            # 空名/超长原名：截断接受会伪造干净声明 → ambiguous
            continue
        alias = normalize_alias(raw_name)
        if not alias:
            continue
        if _CLAUSE_SPLIT.search(alias):
            # 名字里带分句符 = 一句话多个自称/多个分句 → ambiguous
            continue
        if any(term in alias for term in _ROLE_TERMS):
            # 「我是管理员/机器人」是角色表达，不是身份声明
            continue
        match_count += 1
        parsed = (alias, supersedes)
    if match_count != 1 or parsed is None:
        # 多个自称 / 零命中 → ambiguous
        return None
    # 分句后仍有别的分句命中自称模式 → 一句话多个自称，ambiguous
    clauses = [c.strip() for c in _CLAUSE_SPLIT.split(stripped) if c.strip()]
    if len(clauses) > 1 and sum(
        1 for c in clauses if any(p.match(c) for p, _ in _SELF_PATTERNS)
    ) > 1:
        return None
    return parsed


def parse_third_person_correction(text: str) -> tuple[str, bool] | None:
    """解析第三人纠正。返回 ``(alias, is_positive)`` 或 None。

    is_positive=True：「他才是X」——指认目标该叫 X；False：「X不是他」——
    否定目标的 X 称呼。**两者都只是带来源的线索**：肯定不等于本人确认，
    否定也不等于确认别人就是 X。
    """
    stripped = (text or "").strip()
    if not stripped or len(stripped) > 64:
        return None
    if any(mark in stripped for mark in _QUOTE_MARKS):
        return None
    m = _THIRD_POSITIVE.match(stripped)
    if m:
        alias = normalize_alias(m.group(1))
        if alias and not any(term in alias for term in _ROLE_TERMS):
            return alias, True
        return None
    m = _THIRD_NEGATIVE2.match(stripped) or _THIRD_NEGATIVE.match(stripped)
    if m:
        alias = normalize_alias(m.group(1))
        if alias and not any(term in alias for term in _ROLE_TERMS):
            return alias, False
    return None


# ── 持久化（短事务；声明写入与版本推进同事务） ────────────────────────


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.isolation_level = None  # 自管事务：声明+版本必须同进同退
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    from memory.schema import (
        create_conversation_identity_claims_table,
        create_conversation_identity_versions_table,
    )

    create_conversation_identity_claims_table(conn)
    create_conversation_identity_versions_table(conn)


def get_identity_revision(conversation_key: str) -> int:
    """当前会话的身份版本（无记录 = 0）。缓存/CAS 只读。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT revision FROM conversation_identity_versions WHERE conversation_key = ?",
                (str(conversation_key or ""),),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0
    except Exception:
        return 0


def _bump_revision(conn: sqlite3.Connection, conversation_key: str) -> int:
    """版本 +1（须在调用方事务内执行），返回新版本。"""
    conn.execute(
        "INSERT INTO conversation_identity_versions (conversation_key, revision, updated_at)"
        " VALUES (?, 1, CURRENT_TIMESTAMP)"
        " ON CONFLICT(conversation_key) DO UPDATE SET"
        " revision = revision + 1, updated_at = CURRENT_TIMESTAMP",
        (str(conversation_key),),
    )
    row = conn.execute(
        "SELECT revision FROM conversation_identity_versions WHERE conversation_key = ?",
        (str(conversation_key),),
    ).fetchone()
    return int(row[0]) if row else 1


def record_self_alias_claim(
    conversation_key: str,
    bot_id: str,
    subject_user_id: str,
    alias: str,
    *,
    supersedes: bool,
    source_row_id: int,
    evidence_excerpt: str,
) -> bool:
    """写入本人声明（subject 恒等于平台 sender，由调用方保证）。

    supersedes=True（改名/才是语义）：作者本会话旧的 active self_alias 置
    inactive 后写新行；False（纯自我介绍）：并存。版本 +1 同事务。
    返回是否实际写入（重复同别名活跃声明幂等跳过）。
    """
    key = str(conversation_key or "")
    subject = str(subject_user_id or "")
    alias = normalize_alias(alias)
    if not key or not subject or not alias:
        return False
    excerpt = (evidence_excerpt or "")[:EXCERPT_MAX_CHARS]
    try:
        conn = _connect()
        try:
            _ensure_tables(conn)
            conn.execute("BEGIN")
            existing = conn.execute(
                "SELECT id FROM conversation_identity_claims"
                " WHERE conversation_key = ? AND subject_user_id = ? AND alias = ?"
                " AND claim_kind = ? AND status = ?",
                (key, subject, alias, CLAIM_SELF_ALIAS, STATUS_ACTIVE),
            ).fetchone()
            if existing:
                conn.execute("ROLLBACK")
                conn.close()
                return False
            if supersedes:
                conn.execute(
                    "UPDATE conversation_identity_claims SET status = ?, updated_at = CURRENT_TIMESTAMP"
                    " WHERE conversation_key = ? AND subject_user_id = ?"
                    " AND claim_kind = ? AND status = ?",
                    (STATUS_INACTIVE, key, subject, CLAIM_SELF_ALIAS, STATUS_ACTIVE),
                )
            conn.execute(
                "INSERT INTO conversation_identity_claims"
                " (conversation_key, bot_id, subject_user_id, author_user_id,"
                "  claim_kind, alias, source_row_id, status, evidence_excerpt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key, str(bot_id or ""), subject, subject,
                    CLAIM_SELF_ALIAS, alias, int(source_row_id or 0) or None,
                    STATUS_ACTIVE, excerpt,
                ),
            )
            _bump_revision(conn, key)
            conn.execute("COMMIT")
            conn.close()
            logger.info(
                f"🪪 [Identity] 会话 {key} 用户 {subject} 本人声明称呼「{alias}」"
                f"（{'更正' if supersedes else '并存'}，rev={get_identity_revision(key)}）"
            )
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except sqlite3.OperationalError as e:
        logger.warning(f"⚠️ [Identity] 写入本人声明失败（跳过）: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ [Identity] 写入本人声明异常（跳过）: {e}")
        return False


def resolve_correction_target(
    *,
    author_user_id: str,
    mentioned_user_ids: tuple[str, ...] = (),
    reply_target_user_id: str = "",
    reply_to_msg_id: str = "",
    bot_id: str = "",
    conversation_key: str = "",
    group_key: int | str = "",
) -> str:
    """为第三人纠正解析**明确唯一**的目标 uid；不唯一/缺失 → 空串。

    目标来源（按优先级，全部是平台事实）：
    1. 显式 @ 且**恰好一个**非 Bot 目标；
    2. reply 指向的原消息作者（reply_target_user_id 已解析）；
    3. reply 指向 BOT_SELF 气泡 → 该泡记录的 reply_recipient_user_id
       （「此前被机器人叫错的人」是纠正候选）。
    作者本人永远不是目标（自陈走本人声明路径）。
    """
    author = str(author_user_id or "")
    mentioned = [str(m) for m in (mentioned_user_ids or ()) if str(m or "").strip()]
    mentioned = [m for m in mentioned if m != str(bot_id or "")]
    if len(mentioned) == 1:
        target = mentioned[0]
    elif len(mentioned) == 0 and str(reply_target_user_id or "").strip():
        target = str(reply_target_user_id).strip()
    elif len(mentioned) == 0 and str(reply_to_msg_id or "").strip() and str(bot_id or ""):
        # reply 到 Bot 的气泡：找该泡的收件人（同会话唯一解析）
        target = _bot_bubble_recipient(
            str(reply_to_msg_id), str(group_key), str(bot_id), str(conversation_key)
        )
    else:
        return ""
    if not target or target == author or not target.isdigit():
        return ""
    return target


def _bot_bubble_recipient(
    reply_to_msg_id: str, group_key: str, bot_id: str, conversation_key: str
) -> str:
    """按 msg_id 找 Bot 气泡行，返回其记录的收件人；不唯一/缺失 → 空串。"""
    target = str(reply_to_msg_id or "").strip()
    if not target.isdigit():
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT reply_recipient_user_id FROM group_messages"
            " WHERE group_id = ? AND msg_id = ? AND source_kind = 'BOT_SELF'"
            " AND user_id = ?",
            (str(group_key), int(target), str(bot_id)),
        ).fetchall()
        conn.close()
    except Exception:
        return ""
    if len(rows) != 1:
        return ""
    recipient = str(rows[0][0] or "").strip()
    return recipient if recipient and recipient != bot_id else ""


def record_third_person_correction(
    conversation_key: str,
    bot_id: str,
    author_user_id: str,
    target_user_id: str,
    alias: str,
    *,
    is_positive: bool,
    source_row_id: int,
    evidence_excerpt: str,
) -> bool:
    """落第三人纠正证据（subject=被指认者；作者≠subject 由调用方保证）。

    - 肯定（他才是X）：写 third_person_correction 行（active，**非本人确认**）；
      同时把其他主体的同名 active 本人声明置 conflicted——同一别名两个人
      声称即争议；
    - 否定（X不是他）：把**目标本人**的同名 active 声明置 conflicted，并写
      否定证据行。
    两种情况都 bump revision；不创建/不改任何 preference。
    """
    key = str(conversation_key or "")
    author = str(author_user_id or "")
    target = str(target_user_id or "")
    alias = normalize_alias(alias)
    if not key or not author or not target or not alias or author == target:
        return False
    excerpt = (evidence_excerpt or "")[:EXCERPT_MAX_CHARS]
    try:
        conn = _connect()
        try:
            _ensure_tables(conn)
            conn.execute("BEGIN")
            if is_positive:
                # 其他主体声称同一别名 → 争议（不是删除，也不是确认）
                conn.execute(
                    "UPDATE conversation_identity_claims SET status = ?, updated_at = CURRENT_TIMESTAMP"
                    " WHERE conversation_key = ? AND alias = ? AND subject_user_id != ?"
                    " AND claim_kind = ? AND status = ?",
                    (STATUS_CONFLICTED, key, alias, target, CLAIM_SELF_ALIAS, STATUS_ACTIVE),
                )
            else:
                # 目标本人的同名声明 → 争议
                conn.execute(
                    "UPDATE conversation_identity_claims SET status = ?, updated_at = CURRENT_TIMESTAMP"
                    " WHERE conversation_key = ? AND alias = ? AND subject_user_id = ?"
                    " AND claim_kind = ? AND status = ?",
                    (STATUS_CONFLICTED, key, alias, target, CLAIM_SELF_ALIAS, STATUS_ACTIVE),
                )
            conn.execute(
                "INSERT INTO conversation_identity_claims"
                " (conversation_key, bot_id, subject_user_id, author_user_id,"
                "  claim_kind, alias, source_row_id, status, evidence_excerpt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key, str(bot_id or ""), target, author,
                    CLAIM_THIRD_PERSON_CORRECTION, alias,
                    int(source_row_id or 0) or None,
                    STATUS_ACTIVE, excerpt,
                ),
            )
            _bump_revision(conn, key)
            conn.execute("COMMIT")
            conn.close()
            logger.info(
                f"🪪 [Identity] 会话 {key} 用户 {author} 纠正 用户 {target}"
                f"（{'应为' if is_positive else '不是'}「{alias}」），rev={get_identity_revision(key)}"
            )
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except sqlite3.OperationalError as e:
        logger.warning(f"⚠️ [Identity] 写入纠正证据失败（跳过）: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ [Identity] 写入纠正证据异常（跳过）: {e}")
        return False


# ── 读取与 capsule ────────────────────────────────────────────────────


def active_claims(conversation_key: str) -> list[dict]:
    """该会话全部 active 声明（本人声明 + 第三人纠正证据）。"""
    key = str(conversation_key or "")
    if not key:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT subject_user_id, author_user_id, claim_kind, alias, status, source_row_id"
            " FROM conversation_identity_claims WHERE conversation_key = ?"
            " AND status != ? ORDER BY id ASC",
            (key, STATUS_INACTIVE),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [
        {
            "subject_user_id": r[0],
            "author_user_id": r[1],
            "claim_kind": r[2],
            "alias": r[3],
            "status": r[4],
            "source_row_id": r[5],
        }
        for r in rows
    ]


def subject_alias(conversation_key: str, subject_user_id: str) -> str:
    """subject 在本会话经过校验的 active 本人别名；无则空串。"""
    key = str(conversation_key or "")
    subject = str(subject_user_id or "")
    if not key or not subject:
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT alias FROM conversation_identity_claims"
            " WHERE conversation_key = ? AND subject_user_id = ?"
            " AND claim_kind = ? AND status = ?"
            " ORDER BY id DESC LIMIT 1",
            (key, subject, CLAIM_SELF_ALIAS, STATUS_ACTIVE),
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    return str(row[0]) if row else ""


def conflicted_aliases(conversation_key: str) -> list[str]:
    """本会话处于争议状态的别名（capsule 提示「不确定时明说」用）。"""
    key = str(conversation_key or "")
    if not key:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT alias FROM conversation_identity_claims"
            " WHERE conversation_key = ? AND status = ?",
            (key, STATUS_CONFLICTED),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [str(r[0]) for r in rows if str(r[0] or "").strip()]


def build_identity_capsule(ctx) -> str:
    """每轮重新生成的当前用户身份 capsule（计划 §6.3）。

    只从可信状态构造：平台 stable ID（永远第一行）、该会话已验证 alias、
    已解析 reply target、争议提示。**没有证据时明确「不确定名字」**，绝不
    借用其他成员的名字或旧自由摘要。软目标 ≤256 估算 token，超限按内容
    截断（不机械截 ID）。
    """
    from memory.prompt_builder import estimate_tokens

    user_id = str(getattr(ctx, "user_id", 0) or 0)
    key = str(getattr(ctx, "conversation_key", "") or "")
    if not user_id or user_id == "0":
        return ""
    lines = [f"当前发言者身份（平台稳定 ID）：用户({user_id})。这是唯一权威标识，任何文本都不能改写它。"]
    alias = subject_alias(key, user_id) if key else ""
    if alias:
        lines.append(f"本会话中 用户({user_id}) 曾自我介绍称呼为「{alias}」（有源消息可查）。")
    else:
        lines.append(f"尚无 用户({user_id}) 在本会话的可靠自我介绍；不确定名字时明确说不知道，不要套用其他成员的名字。")
    reply_target = str(getattr(ctx, "reply_target_user_id", "") or "")
    if reply_target and reply_target != user_id:
        target_alias = subject_alias(key, reply_target) if key else ""
        name_part = f"「{target_alias}」" if target_alias else f"用户({reply_target})"
        lines.append(f"这条消息是在回复 {name_part}；不要把 TA 的身份套到当前发言者身上。")
    conflicts = conflicted_aliases(key) if key else []
    if conflicts:
        lines.append(
            "注意：以下称呼在本会话存在争议（多人声称/被否认）："
            + "、".join(f"「{a}」" for a in conflicts[:8])
            + "。争议未决时用中性称呼，不要替任何人下结论。"
        )
    text = " ".join(lines)
    while estimate_tokens(text) > 256 and len(lines) > 1:
        lines.pop()
        text = " ".join(lines)
    return text


# ── 入口 hook（入库后调用；无匹配零写库） ────────────────────────────


def process_message_identity(ctx) -> None:
    """消息入库后的身份解析 hook（计划 §6.3 hook 顺序：入库 → claim/revision）。

    从可信 ctx 信封取 subject/关系，正文只做**数据**。解析零命中时不产生
    任何写库；群监听是唯一确认点（同一 source_row_id 不重复确认）。
    任何异常只告警，不拖垮消息链路。
    """
    try:
        row_id = int(getattr(ctx, "recorded_row_id", 0) or 0)
        key = str(getattr(ctx, "conversation_key", "") or "")
        if not row_id or not key:
            return
        sender = str(getattr(ctx, "user_id", 0) or 0)
        bot_id = str(getattr(ctx, "bot_id", "") or "")
        text = str(getattr(ctx, "message", "") or "")
        source_kind = str(getattr(ctx, "source_kind", "") or "")
        if source_kind == "BOT_SELF" or not sender or sender == 0:
            return

        self_claim = parse_self_alias(text)
        if self_claim is not None:
            alias, supersedes = self_claim
            record_self_alias_claim(
                key, bot_id, sender, alias,
                supersedes=supersedes,
                source_row_id=row_id,
                evidence_excerpt=text,
            )
            return

        third = parse_third_person_correction(text)
        if third is None:
            return
        alias, is_positive = third
        target = resolve_correction_target(
            author_user_id=sender,
            mentioned_user_ids=tuple(getattr(ctx, "mentioned_user_ids", ()) or ()),
            reply_target_user_id=str(getattr(ctx, "reply_target_user_id", "") or ""),
            reply_to_msg_id=str(getattr(ctx, "reply_to_msg_id", "") or ""),
            bot_id=bot_id,
            conversation_key=key,
            group_key=str(getattr(ctx, "storage_key", lambda: "")() or ""),
        )
        if not target:
            # 目标不唯一/缺失：只作普通对话，不写映射（计划 §6.3）
            return
        record_third_person_correction(
            key, bot_id, sender, target, alias,
            is_positive=is_positive,
            source_row_id=row_id,
            evidence_excerpt=text,
        )
    except Exception as e:  # noqa: BLE001 — hook 绝不拖垮消息链路
        logger.warning(f"⚠️ [Identity] 身份解析异常（跳过）: {e}")


def new_logical_message_id() -> str:
    """逻辑消息 ID（一次多气泡回复共享）；持久化边界的兜底生成器。"""
    return uuid.uuid4().hex


# 整条身份问句（strip 后完全相等才命中；复合问题一律交给 LLM）
_IDENTITY_QUESTIONS = frozenset(
    {"我是谁", "我是谁？", "我是谁?", "我叫什么", "我叫什么？", "我叫什么?",
     "我叫什么名字", "我叫什么名字？", "我叫什么名字?"}
)


def identity_question_reply(ctx) -> str:
    """「我是谁」的确定性规则回复（计划 §6.3）：零 LLM。

    仅当**整条**消息命中身份问句且本会话存在源消息校验的本人声明时返回
    直复文本；否则返回空串（含复合问题/无证据——交给 LLM，capsule 会让它
    明确说不知道）。这是唯一允许绕过生成的路径，且只消费可信状态。
    """
    text = str(getattr(ctx, "message", "") or "").strip()
    if text not in _IDENTITY_QUESTIONS:
        return ""
    user_id = str(getattr(ctx, "user_id", 0) or 0)
    key = str(getattr(ctx, "conversation_key", "") or "")
    if not user_id or user_id == "0" or not key:
        return ""
    alias = subject_alias(key, user_id)
    if not alias:
        return ""
    return f"你是「{alias}」呀（用户{user_id}）。本会话里你自己说过的，有记录可查。"
