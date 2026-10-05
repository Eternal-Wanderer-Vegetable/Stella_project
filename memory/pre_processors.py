# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""
对话前处理器（Pre-processors）模块。

本模块位于记忆工作流的“读取侧 + 写入侧入口”：
- record_message：把每条群聊消息落库（group_messages，新消息统一写此，messages 为旧版回退）；
- build_context：为每次回复组装短期上下文——话题层摘要（过期时标注时长）+ 最近
  RECENT_TAIL_LIMIT 条原始消息尾巴（按时间窗过滤、内部空白处标注断层）；
- build_user_context：组装用户画像与长期记忆——@-回复时读用户画像 + 该用户相关记忆，
  主动发言时用群级记忆回顾；
- _extract_keywords / _STOP_WORDS：中文停用词与关键词提取，供记忆话题匹配使用。
"""
import contextlib
import json
import re
import sqlite3
import time

from nonebot import logger

from config import (
    DB_PATH,
    MEMORY_V2_ENABLED,
    PROACTIVE_LONG_TERM_LIMIT,
    RECENT_TAIL_GAP_MARK_MINUTES,
    RECENT_TAIL_LIMIT,
    RECENT_TAIL_MAX_AGE_MINUTES,
    REPLY_LONG_TERM_LIMIT,
    SHORT_TERM_SUMMARY_STALE_MINUTES,
)
from config.spaces import resolve_space
from core.context import ChatContext
from memory.cache_keys import POLICY_VERSION
from memory.conversation_projection import (
    PROJECTION_FORMAT_VERSION,
    TranscriptBubble,
    TranscriptRecord,
    canonical_message_id_text,
    render_transcript_record,
)
from memory.prompt_builder import build_memory_context, estimate_tokens
from memory.retriever import get_group_memories, get_related_memories, get_user_memories
from memory.schema import normalize_source_kind
from memory.session_context import ensure_initialized as session_ensure_initialized
from memory.session_context import get_summary as get_session_summary
from memory.session_context import (
    observe_identity_revision as session_observe_identity_revision,
)
from memory.session_context import summary_version as session_summary_version
from memory.timeutil import (
    humanize_duration,
    log_sqlite_error,
    parse_db_timestamp,
    seconds_since,
    utc_now,
)

# 尾巴中 Bot 自己发言的占比告警阈值（诊断用经验值，不进 config）：
# 尾巴里几乎全是「我」= 用户消息疑似未入库（2026-08-17 缺陷的表现）
_BOT_SELF_RATIO_WARN = 0.7
# 逻辑单元 tail 的扫描/预算上限（多人身份修复计划 §6.2）：
# 扫描最多 48 行（防极多气泡膨胀），单元数上限沿用 RECENT_TAIL_LIMIT，
# 估算 token 上限独立兜底（超出时更早的单元整体让位，不切半条）。
_TAIL_SCAN_ROW_CAP = 48
_TAIL_UNIT_TOKEN_CAP = 1400


# v16 group_messages 的完整建表 DDL（新库直建全列；旧库靠自补 ALTER 逐列加）。
# 关系列默认 NULL/[]/0 = 「关系未知」——消费方按 unknown 处理，绝不猜测。
_GROUP_MESSAGES_V16_DDL = """
CREATE TABLE IF NOT EXISTS group_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT,
    user_id TEXT,
    content TEXT,
    source_kind TEXT DEFAULT 'PASSIVE',
    msg_id INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    conversation_key TEXT,
    bot_id TEXT,
    sender_display_name TEXT,
    reply_to_msg_id TEXT,
    reply_target_user_id TEXT,
    mentioned_user_ids_json TEXT DEFAULT '[]',
    logical_message_id TEXT,
    part_index INTEGER DEFAULT 0,
    origin_msg_id TEXT,
    reply_recipient_user_id TEXT,
    turn_id TEXT,
    relation_version INTEGER DEFAULT 0
)
"""

# v16 信封列（自补顺序即列清单；旧库缺列时逐列 ALTER，失败 = 列已存在）
_ENVELOPE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("conversation_key", "TEXT"),
    ("bot_id", "TEXT"),
    ("sender_display_name", "TEXT"),
    ("reply_to_msg_id", "TEXT"),
    ("reply_target_user_id", "TEXT"),
    ("mentioned_user_ids_json", "TEXT DEFAULT '[]'"),
    ("logical_message_id", "TEXT"),
    ("part_index", "INTEGER DEFAULT 0"),
    ("origin_msg_id", "TEXT"),
    ("reply_recipient_user_id", "TEXT"),
    ("turn_id", "TEXT"),
    ("relation_version", "INTEGER DEFAULT 0"),
)


def _has_column(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    try:
        cursor.execute(f"PRAGMA table_info({table})")
        return any(row[1] == column for row in cursor.fetchall())
    except sqlite3.OperationalError:
        return False


async def record_message(ctx: ChatContext) -> ChatContext:
    """把本条消息写入群消息表（group_messages），供后续整合器消费。

    source_kind 由调用方（ai_gateway）按 event.is_tome() 决定：
    AT_MENTION=用户直接对 Bot 说，Bot 自己的发言传 BOT_SELF，其余为 PASSIVE。

    v16（多人身份修复计划 §6.2）：ctx 携带的身份信封（reply/@/逻辑分组）与
    正文在**同一 SQLite 短事务**落库，成功后回填 ``ctx.recorded_row_id``——
    身份声明（M3）以它为来源锚点。信封写入不跨 await/网络。

    参数：ctx — 拥有 group_id / user_id / message 及可选信封字段的上下文；
    副作用：插入一条群消息记录并建表（幂等）；
    返回：ctx（recorded_row_id 已回填；失败保持 0）。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(_GROUP_MESSAGES_V16_DDL)
        # 老库的 group_messages 已存在且 ensure_v2_schema 可能晚于首条消息执行，
        # 这里自补 source_kind / msg_id / v16 信封列（失败即说明列已存在）
        with contextlib.suppress(sqlite3.OperationalError):
            cursor.execute("ALTER TABLE group_messages ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'")
        with contextlib.suppress(sqlite3.OperationalError):
            cursor.execute("ALTER TABLE group_messages ADD COLUMN msg_id INTEGER")
        for column, decl in _ENVELOPE_COLUMNS:
            if not _has_column(cursor, "group_messages", column):
                with contextlib.suppress(sqlite3.OperationalError):
                    cursor.execute(
                        f"ALTER TABLE group_messages ADD COLUMN {column} {decl}"
                    )
        # messages 表为旧版兼容（只读回退），新消息统一写入 group_messages
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT,
                user_id TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_group_messages_group_id
            ON group_messages (group_id, id)
        """)
        cursor.execute("""
            INSERT INTO group_messages (
                group_id, user_id, content, source_kind, msg_id,
                conversation_key, bot_id, sender_display_name,
                reply_to_msg_id, reply_target_user_id, mentioned_user_ids_json,
                logical_message_id, part_index, origin_msg_id,
                reply_recipient_user_id, turn_id, relation_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(ctx.storage_key()), str(ctx.user_id), ctx.message,
            normalize_source_kind(ctx.source_kind), int(ctx.msg_id or 0),
            str(getattr(ctx, "conversation_key", "") or ""),
            str(getattr(ctx, "bot_id", "") or ""),
            str(getattr(ctx, "sender_display_name", "") or ""),
            str(getattr(ctx, "reply_to_msg_id", "") or ""),
            str(getattr(ctx, "reply_target_user_id", "") or ""),
            json.dumps(list(getattr(ctx, "mentioned_user_ids", ()) or ()), ensure_ascii=False),
            str(getattr(ctx, "logical_message_id", "") or ""),
            int(getattr(ctx, "part_index", 0) or 0),
            str(getattr(ctx, "origin_msg_id", "") or ""),
            str(getattr(ctx, "reply_recipient_user_id", "") or ""),
            str(getattr(ctx, "turn_id", "") or ""),
            int(getattr(ctx, "relation_version", 0) or 0),
        ))
        ctx.recorded_row_id = int(cursor.lastrowid or 0)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"记录消息失败: {e}")
    return ctx


def resolve_reply_target(
    reply_to_msg_id: str,
    group_key: int | str,
    *,
    bot_id: str = "",
    conversation_key: str = "",
) -> str:
    """把平台被回复 message ID 解析为原消息作者（多人身份修复计划 §6.2）。

    只认**同 canonical conversation + bot** 的已入库原始消息；找不到、
    msg_id 缺失或命中多条（跨群重复 ID）一律返回空串 = unknown——禁止猜
    「最近发言的人」。DB 异常同样返回 unknown（历史渲染降级，不拖垮主链路）。

    平台 message ID 允许负数（QQ 回执实测 -558868042）：统一走投影模块的
    有符号解析；0/非法文本 = unknown（归属修复计划 §6.1）。
    """
    target = canonical_message_id_text(reply_to_msg_id)
    if not target:
        return ""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        params: list = [str(group_key), int(target)]
        sql = (
            "SELECT DISTINCT user_id FROM group_messages "
            "WHERE group_id = ? AND msg_id = ? AND user_id != ''"
        )
        if _has_column(cursor, "group_messages", "conversation_key"):
            sql += " AND conversation_key = ?"
            params.append(str(conversation_key or ""))
            if _has_column(cursor, "group_messages", "bot_id") and bot_id:
                sql += " AND bot_id = ?"
                params.append(str(bot_id))
        rows = cursor.execute(sql, params).fetchall()
        conn.close()
    except Exception as e:
        logger.debug(f"[PreProcessors.resolve_reply_target] 解析失败（unknown）: {e}")
        return ""
    if len(rows) != 1:
        return ""
    return str(rows[0][0] or "")


async def build_context(ctx: ChatContext) -> ChatContext:
    """组装短期上下文：话题层摘要 + 最近原始消息尾巴（可同时存在）。

    摘要过期时改用「之前的话题」标题并注明时长；尾巴按时间窗过滤并在
    内部空白处插入断层标记。

    会话上下文缓存（设计阶段四）：key = session_id + history_version + mode +
    policy_version。历史版本 = 消息表 max(id) + 摘要 updated_at + 会话摘要版本，
    任一变化立即换桶；都不变时直接复用上次组装好的文本——既省重复读库，
    也保证同版本下拼出的上下文逐字节一致，不破坏 Prompt 前缀稳定性。
    尾巴的时间窗过滤随墙钟缓慢漂移，由 TTL 兜底（窗口以小时计，5 分钟内的
    陈旧无害）。

    参数：ctx — 会被写入 ctx.short_term；
    副作用：向 ctx.short_term 写入文本（读取 DB，不写库）；
    返回：ctx。
    """
    if not DB_PATH.exists():
        return ctx
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # ── 1) 短期摘要：只取「话题层」信息（active_summary / pending_topic） ──
        active_summary = pending_topic = ""
        summary_age: str | None = None
        stc_updated_at: str | None = None
        try:
            cursor.execute(
                "SELECT active_summary, pending_topic, updated_at FROM short_term_context "
                "WHERE group_id = ?",
                (str(ctx.storage_key()),),
            )
            row = cursor.fetchone()
            if row:
                active_summary, pending_topic = (row[0] or ""), (row[1] or "")
                stc_updated_at = row[2] if len(row) > 2 else None
                # 摘要由整合器产出、按设计滞后。不标注新鲜度会让模型
                # 把几小时前的话题当成当前话题。
                elapsed = seconds_since(row[2]) if len(row) > 2 else None
                if (
                    elapsed is not None
                    and SHORT_TERM_SUMMARY_STALE_MINUTES > 0
                    and elapsed > SHORT_TERM_SUMMARY_STALE_MINUTES * 60.0
                ):
                    summary_age = humanize_duration(elapsed)
        except sqlite3.OperationalError as e:
            # 摘要表尚不存在（新群首条消息）→ debug；列名不匹配等 → warning
            log_sqlite_error("PreProcessors.build_context", e)

        # ── 1.5) 会话上下文缓存：历史版本未变则整段复用，跳过尾巴等重查询 ──
        # v16（多人身份修复计划 §6.4）：身份版本入键——本人更名/第三人纠正
        # bump revision 后，携带旧身份的缓存立即失效，不等 TTL。
        identity_rev = 0
        if getattr(ctx, "conversation_key", ""):
            try:
                from memory.conversation_identity import get_identity_revision

                identity_rev = get_identity_revision(str(ctx.conversation_key))
            except Exception:
                identity_rev = 0
        session_observe_identity_revision(ctx.storage_key(), identity_rev)
        history_version = (
            _max_message_id(cursor, ctx.storage_key()),
            stc_updated_at,
            session_summary_version(ctx.storage_key()),
            identity_rev,
        )
        # key 含 DB_PATH：与检索缓存同款隔离（换库/测试临时库绝不互读缓存）
        cache_key = (
            str(DB_PATH),
            str(ctx.storage_key()),
            history_version,
            getattr(ctx, "memory_mode", "") or "",
            POLICY_VERSION,
        )
        cached = _SESSION_CONTEXT_CACHE.get(cache_key)
        if cached is not None and (time.monotonic() - cached[0]) < SESSION_CONTEXT_CACHE_TTL:
            conn.close()
            # 命中即刷新计时（与检索缓存同款简单 LRU 语义）
            _SESSION_CONTEXT_CACHE[cache_key] = cached
            if cached[1]:
                ctx.short_term = cached[1]
            ctx.tail_start_id = cached[2]
            logger.debug(
                f"🧠 [Context] 群 {ctx.group_id} 命中会话上下文缓存"
                f"（历史版本 {history_version[0]}/{history_version[2]}）"
            )
            return ctx

        # ── 2) 最近原始消息（含 Bot 自己的发言，带来源标注） ──
        tail, tail_start_id = _fetch_recent_tail(cursor, ctx.storage_key(), RECENT_TAIL_LIMIT)

        # ── 2.5) 会话摘要：覆盖已滚出尾巴窗口的较早内容 ──
        # 先对齐起点再取摘要：首次使用时把已压缩位置对齐到尾巴起点，
        # 避免把整个历史当成待压缩内容。
        if tail_start_id > 0:
            session_ensure_initialized(ctx.storage_key(), tail_start_id)
        session_summary = get_session_summary(ctx.storage_key())
        # 供 post 侧触发压缩（回复发出后异步进行，不阻塞本次回复）
        ctx.tail_start_id = tail_start_id

        # ── 3) recent_exchanges 只在没有原始尾巴时兜底 ──
        # 它是整合器产出的滞后快照，与原始尾巴并存会出现同一段对话的两个版本，
        # 模型会以摘要为准从而接错话题（2026-08-13 bug）。
        exchanges_text = "" if tail else _fetch_recent_exchanges_text(cursor, ctx.storage_key())

        conn.close()

        parts: list[str] = []
        if active_summary:
            if summary_age:
                parts.append(f"之前的话题（{summary_age}前）: {active_summary}")
            else:
                parts.append(f"对话摘要: {active_summary}")
        if pending_topic and pending_topic != "无":
            # 摘要已过期时，「进行中的话题」同样不再是进行中
            label = "之前未聊完的话题" if summary_age else "进行中的话题"
            parts.append(f"{label}: {pending_topic}")
        if exchanges_text:
            parts.append("近期关键发言:\n" + exchanges_text)
        if session_summary:
            parts.append("本场对话较早的内容（已压缩）:\n" + session_summary)
        if tail:
            # 段头声明投影版本与作者语义（归属修复计划 §6.2）：新投影以
            # 「作者=Bot(uid)」标注 Bot 自己的话；旧库降级路径仍是「我: 」。
            parts.append(
                f"最近的对话（时间正序，投影v{PROJECTION_FORMAT_VERSION}；"
                "「我:」或「Bot(...)」开头的行都是你自己说过的话）:\n" + tail
            )

        if parts:
            ctx.short_term = "\n".join(parts)
            logger.info(
                f"🧠 [Context] 摘要={'过期' if summary_age else '有' if active_summary else '无'} "
                f"原始尾巴={len(tail.splitlines()) if tail else 0} 行"
                f"{' 会话摘要=有' if session_summary else ''}"
            )

        # 组装结果写回缓存（parts 为空也写：空结果同样是该版本的确定产物）
        _SESSION_CONTEXT_CACHE[cache_key] = (
            time.monotonic(),
            "\n".join(parts),
            tail_start_id,
        )
        if len(_SESSION_CONTEXT_CACHE) > _SESSION_CONTEXT_CACHE_MAX_ENTRIES:
            for key in list(_SESSION_CONTEXT_CACHE)[
                : len(_SESSION_CONTEXT_CACHE) - _SESSION_CONTEXT_CACHE_MAX_ENTRIES
            ]:
                _SESSION_CONTEXT_CACHE.pop(key, None)
    except Exception as e:
        logger.warning(f"读取上下文异常（跳过）: {e}")
    return ctx


# ── 会话上下文缓存（进程内，key = (群, 历史版本, 模式, 策略版本)） ──
# 设计阶段四「缓存与快速路径」：会话上下文缓存 session_id + history_version
# + mode + policy_version。失效完全由版本驱动，TTL 只兜底墙钟相关的漂移
# （尾巴时间窗过滤）与容量逐出。
SESSION_CONTEXT_CACHE_TTL = 300.0  # 5 分钟
_SESSION_CONTEXT_CACHE_MAX_ENTRIES = 64
_SESSION_CONTEXT_CACHE: dict[
    tuple[str, str, tuple[int, str | None, int, int], str, str],
    tuple[float, str, int],
] = {}


def _max_message_id(cursor: sqlite3.Cursor, group_id: int) -> int:
    """该群消息表的当前最大 id（历史版本的消息维度；无消息/表缺失为 0）。

    走 idx_group_messages_group_id (group_id, id) 索引，聚合代价可忽略；
    表缺失（新库）返回 0，与「无消息」同版本——两者组装结果都为空，等价。
    """
    try:
        row = cursor.execute(
            "SELECT MAX(id) FROM group_messages WHERE group_id = ?",
            (str(group_id),),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.OperationalError as e:
        log_sqlite_error("PreProcessors._max_message_id", e)
        return 0


def _query_tail_rows_with_relations(
    cursor: sqlite3.Cursor, group_id: int, row_cap: int
) -> list[tuple] | None:
    """取尾巴原始行（含 v16 关系列，id 倒序）；关系列不可用返回 None。

    返回行结构（前 11 列为既有索引含义，不得移动；11–14 为投影追加列，
    归属修复计划 §6.2）：(id, user_id, content, source_kind, timestamp,
    reply_to_msg_id, reply_target_user_id, mentioned_json,
    logical_message_id, part_index, reply_recipient_user_id,
    msg_id, origin_msg_id, bot_id, conversation_key)。
    """
    try:
        return cursor.execute(
            "SELECT id, user_id, content, source_kind, timestamp, "
            "reply_to_msg_id, reply_target_user_id, mentioned_user_ids_json, "
            "logical_message_id, part_index, reply_recipient_user_id, "
            "msg_id, origin_msg_id, bot_id, conversation_key "
            "FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (str(group_id), row_cap),
        ).fetchall()
    except sqlite3.OperationalError as e:
        # v16 之前的库：关系列不存在 → 走无关系旧路径（render 逐字旧行为）
        logger.debug(f"[PreProcessors._query_tail_rows_with_relations] 无关系列，旧路径: {e}")
        return None


def _mentioned_uids(raw_json: str) -> list[str]:
    try:
        parsed = json.loads(raw_json) if raw_json else []
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(u) for u in parsed if str(u or "").strip()]


def _render_tail_line(uid: str, text: str, kind: str, rel: dict) -> str:
    """渲染单条消息行；无任何关系信息时与旧格式逐字相同。"""
    if kind == "BOT_SELF":
        recipient = rel.get("reply_recipient_user_id") or ""
        if recipient:
            return f"我（回复给 用户({recipient})）: {text}"
        return f"我: {text}"
    suffix = ""
    parts: list[str] = []
    if rel.get("reply_to_msg_id"):
        target = rel.get("reply_target_user_id") or ""
        parts.append(f"回复 用户({target})" if target else "回复 对象未知")
    mentions = rel.get("mentions") or []
    if mentions:
        parts.append("提及 " + "、".join(f"用户({m})" for m in mentions))
    if parts:
        suffix = " [" + "；".join(parts) + "]"
    return f"用户({uid}){suffix}: {text}"


def _unit_signature(uid: str, kind: str, rel: dict) -> tuple:
    """逻辑单元的合组签名：logical ID + 作者/来源/收件人必须全部一致。

    归属修复计划 §6.2：连续 BOT_SELF 行只有 logical_message_id、作者、
    源输入、收件人（及 bot 维度）完全一致才允许合成一个「人」的发言；
    任何一项冲突都拆成独立记录、关系按各自行呈现——绝不合并成一个人。
    """
    return (
        str(rel.get("logical_message_id") or ""),
        uid,
        kind,
        str(rel.get("reply_recipient_user_id") or ""),
        str(rel.get("origin_msg_id") or ""),
        str(rel.get("bot_id") or ""),
    )


def _unit_record(unit: dict) -> TranscriptRecord:
    """把一个逻辑单元转成自足的投影记录（作者/收件人逐行显式）。"""
    rows = unit["rows"]
    uid, kind = rows[0][1], rows[0][3]
    rel = rows[0][5] or {}
    bubbles = tuple(
        TranscriptBubble(
            part_index=int((row[5] or {}).get("part_index") or 0), text=row[2]
        )
        for row in rows
    )
    if kind == "BOT_SELF":
        return TranscriptRecord(
            author_id=uid,
            author_is_bot=True,
            bubbles=bubbles,
            recipient_id=str(rel.get("reply_recipient_user_id") or ""),
            origin_msg_id=str(rel.get("origin_msg_id") or ""),
        )
    first = rows[0]
    mentions = tuple(first[5].get("mentions") or ()) if first[5] else ()
    return TranscriptRecord(
        author_id=uid,
        author_is_bot=False,
        bubbles=bubbles,
        reply_to_msg_id=str(first[5].get("reply_to_msg_id") or "") if first[5] else "",
        reply_target_user_id=str(first[5].get("reply_target_user_id") or "") if first[5] else "",
        mentioned_user_ids=mentions,
    )


def _fetch_recent_tail(cursor: sqlite3.Cursor, group_id: int, limit: int) -> tuple[str, int]:
    """取最近消息，按时间正序拼成文本（v16：按逻辑单元选取与渲染）。

    返回 ``(文本, 尾巴起点消息 id)``。起点 id 供会话压缩计算不重叠的待压缩
    区间——摘要必须严格覆盖尾巴之前的内容（见 memory/session_context.py）。
    无消息时返回 ``("", 0)``。

    与旧行为的关系（多人身份修复计划 §6.2）：

    1. **自足单行投影**：带 v16 关系列时，每个逻辑单元（一次多气泡机器人
       回复，或单条用户消息）渲染为**一个物理行**，作者/收件人/源输入逐行
       显式——收件人不靠跨行继承，预算按物理行整存整取，不会留下孤立的
       第 2/3 气泡；正文经 JSON 转义，换行/伪造头不会变成新的说话人；
    2. **逻辑单元选取**：连续后缀最多 ``limit`` 个单元（缺省 12），扫描上限
       48 行；token 限额按**最终渲染文本**（含作者/ID/引用/转义开销）计算，
       超出时更早的单元整体让位，不切半条；
    3. 其余（时间窗过滤、断层标记、BOT_SELF 占比告警、旧库降级）与旧实现
       一致；旧库（无关系列）逐字保持旧格式（``我: `` / ``用户(uid): ``）。
    """
    if limit <= 0:
        return "", 0

    rel_rows = _query_tail_rows_with_relations(cursor, group_id, _TAIL_SCAN_ROW_CAP)
    legacy = rel_rows is None
    rows = _query_tail_rows(cursor, group_id, limit) if legacy else rel_rows
    if not rows:
        return "", 0
    rows.reverse()  # id 倒序 → 时间正序

    now = utc_now().timestamp()
    max_age = RECENT_TAIL_MAX_AGE_MINUTES * 60.0
    gap_threshold = RECENT_TAIL_GAP_MARK_MINUTES * 60.0

    # 先把行归组成逻辑单元：BOT_SELF 且签名完全一致的相邻行合组
    units: list[dict] = []
    for row in rows:
        mid, uid, content, kind, ts = row[0], row[1], row[2], row[3], row[4]
        text = (content or "").strip()
        if legacy or len(row) <= 8:
            rel: dict = {}
        else:
            rel = {
                "reply_to_msg_id": str(row[5] or ""),
                "reply_target_user_id": str(row[6] or ""),
                "mentions": _mentioned_uids(str(row[7] or "")),
                "logical_message_id": str(row[8] or ""),
                "reply_recipient_user_id": str(row[10] or ""),
                "part_index": int(row[9] or 0),
                "origin_msg_id": str(row[12] or "") if len(row) > 12 else "",
                "bot_id": str(row[13] or "") if len(row) > 13 else "",
            }
        if not text:
            continue

        epoch = parse_db_timestamp(ts)
        # 时间窗过滤：解析失败的消息（旧库无 timestamp）不过滤，保留原有行为
        if max_age > 0 and epoch is not None and (now - epoch) > max_age:
            continue

        signature = _unit_signature(uid, kind, rel)
        joins_previous = (
            kind == "BOT_SELF"
            and bool(signature[0])
            and units
            and units[-1]["signature"] == signature
        )
        if joins_previous:
            units[-1]["rows"].append((mid, uid, text, kind, epoch, rel))
            continue
        units.append(
            {
                "signature": signature,
                "rows": [(mid, uid, text, kind, epoch, rel)],
            }
        )

    # 先渲染每个单元（单物理行），再按**最终渲染成本**从最新向回收集
    rendered: list[tuple[dict, str]] = []
    for unit in units:
        unit_rows = unit["rows"]
        if legacy or not unit_rows[0][5]:
            # 旧库/无关系行：逐字旧行为（BOT_SELF 逐行「我: 」，无合组）
            line = "\n".join(
                _render_tail_line(r[1], r[2], r[3], {}) for r in unit_rows
            )
        else:
            line = render_transcript_record(_unit_record(unit))
        if line:
            rendered.append((unit, line))

    token_budget = _TAIL_UNIT_TOKEN_CAP
    selected: list[tuple[dict, str]] = []
    for unit, line in reversed(rendered):
        if len(selected) >= limit:
            break
        line_tokens = estimate_tokens(line)
        if selected and token_budget - line_tokens < 0:
            break
        selected.append((unit, line))
        token_budget -= line_tokens
    selected.reverse()

    # BOT_SELF 占比告警：尾巴里几乎全是 Bot 自己的发言 = 用户消息疑似未入库
    tail_total = sum(len(u["rows"]) for u, _ in selected)
    tail_bot_self = sum(
        1
        for u, _ in selected
        for row in u["rows"]
        if row[3] == "BOT_SELF"
    )
    if (
        tail_total >= 5
        and tail_bot_self > 0
        and tail_bot_self / tail_total > _BOT_SELF_RATIO_WARN
    ):
        ratio = round(tail_bot_self / tail_total * 100)
        logger.warning(
            f"⚠️ [Tail] 尾巴 {tail_total} 行中 Bot 自己的发言占 {ratio}%，"
            "看起来像在自言自语；若持续出现请检查用户消息是否正常入库"
        )

    lines: list[str] = []
    prev_epoch: float | None = None
    tail_start_id = 0
    for unit, line in selected:
        unit_rows = unit["rows"]
        if tail_start_id == 0:
            tail_start_id = int(unit_rows[0][0])
        first_epoch = unit_rows[0][4]
        if (
            gap_threshold > 0
            and prev_epoch is not None
            and first_epoch is not None
            and (first_epoch - prev_epoch) > gap_threshold
        ):
            lines.append(f"（……中间隔了{humanize_duration(first_epoch - prev_epoch)}……）")
        lines.append(line)
        for row in unit_rows:
            if row[4] is not None:
                prev_epoch = row[4]

    return "\n".join(lines), tail_start_id


def _query_tail_rows(cursor: sqlite3.Cursor, group_id: int, limit: int) -> list[tuple]:
    """取尾巴原始行（id 倒序），带 id / source_kind / timestamp；旧库自动降级。

    返回 (id, user_id, content, source_kind, timestamp) 五元组列表。
    """
    try:
        return cursor.execute(
            "SELECT id, user_id, content, source_kind, timestamp FROM group_messages "
            "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (str(group_id), limit),
        ).fetchall()
    except sqlite3.OperationalError as e:
        # 前两级是刻意的向下兼容降级（新库→旧库→更旧库），debug 即可
        logger.debug(f"[PreProcessors._query_tail_rows] 新表结构不可用，尝试旧查询: {e}")
    try:
        return [
            (mid, uid, content, "PASSIVE", ts)
            for mid, uid, content, ts in cursor.execute(
                "SELECT id, user_id, content, timestamp FROM group_messages "
                "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(group_id), limit),
            ).fetchall()
        ]
    except sqlite3.OperationalError as e:
        logger.debug(f"[PreProcessors._query_tail_rows] 旧表结构不可用，尝试最旧查询: {e}")
    try:
        return [
            (mid, uid, content, "PASSIVE", None)
            for mid, uid, content in cursor.execute(
                "SELECT id, user_id, content FROM group_messages "
                "WHERE group_id = ? ORDER BY id DESC LIMIT ?",
                (str(group_id), limit),
            ).fetchall()
        ]
    except sqlite3.OperationalError as e:
        # 三级全部失败：不是降级而是真问题（表被删/列被改），必须 warning
        logger.warning(f"⚠️ [PreProcessors._query_tail_rows] 全部查询均失败: {e}")
        return []


def _fetch_recent_exchanges_text(cursor: sqlite3.Cursor, group_id: int) -> str:
    """读整合器产出的 recent_exchanges（带说话人归属），拼成文本；无则空串。"""
    try:
        raw = cursor.execute(
            "SELECT recent_exchanges FROM short_term_context WHERE group_id = ?",
            (str(group_id),),
        ).fetchone()
    except sqlite3.OperationalError as e:
        log_sqlite_error("PreProcessors._fetch_recent_exchanges_text", e)
        return ""
    if not raw or not raw[0]:
        return ""
    try:
        parsed = json.loads(raw[0])
    except (json.JSONDecodeError, TypeError):
        return ""
    lines = [
        f"用户({e.get('user_id')}): {e.get('content')}"
        for e in parsed
        if isinstance(e, dict) and e.get("user_id") and e.get("content")
    ]
    return "\n".join(lines)


async def build_user_context(ctx: ChatContext) -> ChatContext:
    """组装用户画像与长期记忆上下文（写到 ctx.user_profile / ctx.memories_for_prompt）。

    参数：ctx — 触发方式（ctx.trigger）决定走主动发言还是 @-回复路径；
    副作用：写入 ctx.user_profile（画像段落）与 ctx.memories_for_prompt（记忆列表）；
    返回：ctx。

    v2：当 MEMORY_V2_ENABLED 时走记忆系统 v2 检索（Context-aware Memory Activation），
    把结果写入 ctx.conversation_memories / ctx.behavior_constraints / ctx.memory_mode /
    ctx.memory_trace，供 pipeline 做分区注入。
    """
    if not DB_PATH.exists():
        return ctx

    if MEMORY_V2_ENABLED:
        return await _build_user_context_v2(ctx)

    # 共享空间：同一空间内的多个 QQ 群共享画像与记忆（M2.5-1 的 __post_init__ 应已填好，or 只是防御）
    space = ctx.group_shared_space or resolve_space(ctx.group_id)
    _load_preferred_address(ctx, space)

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        parts = []

        is_proactive = ctx.trigger == "proactive"

        if not is_proactive:
            # ── @-回复：读取用户画像（性格 + 对 bot 态度） ──
            # 按共享空间隔离：同一空间内的多个 QQ 群共享一份画像
            cursor.execute(
                "SELECT personality_traits, agent_attitude FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
                (space, str(ctx.user_id)),
            )
            row = cursor.fetchone()
            if row:
                traits = []
                if row[0]:
                    traits.append(f"性格: {row[0]}")
                if row[1]:
                    traits.append(f"对bot态度: {row[1]}")
                if traits:
                    parts.append(f"关于用户{ctx.user_id}的了解: {'，'.join(traits)}")

        # ── 长期记忆 ──
        # 主动发言：回顾全空间记忆；@-回复：检索该用户相关记忆 + 其他相关记忆
        if is_proactive:
            memories = get_group_memories(
                space,
                query=ctx.message,
                limit=PROACTIVE_LONG_TERM_LIMIT,
            )
            if memories:
                parts.append("最近的记忆回顾：\n" + build_memory_context(memories))
        else:
            user_memories = get_user_memories(
                space,
                ctx.user_id,
                query=ctx.message,
                limit=REPLY_LONG_TERM_LIMIT,
            )
            if user_memories:
                parts.append(
                    f"关于用户{ctx.user_id}的重要记忆：\n" + build_memory_context(user_memories)
                )

            related = get_related_memories(space, ctx.user_id, ctx.message, limit=3)
            if related:
                parts.append("其他相关记忆：\n" + build_memory_context(related))

        conn.close()

        if parts:
            # 结构化字段交给 prompt_builder 构建提示，不再写 ctx.context
            ctx.short_term = ctx.short_term or ""
            # 尝试提取关于用户的段落作为 user_profile（以 '关于用户' 开头的段落）
            up = ""
            for p in parts:
                if p.startswith((f"关于用户{ctx.user_id}", "关于用户", "关于当前用户")):
                    up = p
                    break
            ctx.user_profile = up
            # 构造用于 prompt 的 memories 列表（从之前检索得到的记忆片段）
            memories: list[dict] = []
            # 主动发言时 parts 中第一项为群记忆回顾（build_context 已把短期赋给 short_term）
            if ctx.trigger == "proactive":
                try:
                    memories = get_group_memories(
                        space,
                        query=ctx.message,
                        limit=PROACTIVE_LONG_TERM_LIMIT,
                    )
                except Exception:
                    memories = []
            else:
                try:
                    user_memories = get_user_memories(
                        space,
                        ctx.user_id,
                        query=ctx.message,
                        limit=REPLY_LONG_TERM_LIMIT,
                    )
                except Exception:
                    user_memories = []
                try:
                    related = get_related_memories(space, ctx.user_id, ctx.message, limit=3)
                except Exception:
                    related = []
                memories = (user_memories or []) + (related or [])
            ctx.memories_for_prompt = memories
    except Exception as e:
        logger.warning(f"读取用户画像异常（跳过）: {e}")
    return ctx


async def _build_user_context_v2(ctx: ChatContext) -> ChatContext:
    """记忆系统 v2 的上下文组装：Policy 检索 + 分区记忆 + 决策轨迹。"""
    from config import MEMORY_EMBEDDING_ENABLED
    from memory.retrieval_v2 import retrieve_memories

    # 共享空间：同一空间内的多个 QQ 群共享画像与记忆（M2.5-1 的 __post_init__ 应已填好，or 只是防御）
    space = ctx.group_shared_space or resolve_space(ctx.group_id)
    _load_preferred_address(ctx, space)

    # 会话内身份 capsule（多人身份修复计划 §6.3）：每轮从可信状态重建、
    # 不走缓存——本人更名/第三人纠正下一轮立即生效。identity_revision
    # 供上下文缓存与 compact CAS 使用（M4）。
    if getattr(ctx, "conversation_key", ""):
        try:
            from memory.conversation_identity import (
                build_identity_capsule,
                get_identity_revision,
            )

            ctx.identity_capsule = build_identity_capsule(ctx)
            ctx.identity_revision = get_identity_revision(str(ctx.conversation_key))
        except Exception as exc:
            logger.debug(f"身份 capsule 生成失败（跳过）: {exc}")
    # v3 访问范围（计划 §6.6）：由服务端身份生成，模型输入不可构造。
    # 主体统一由可信 helper 决定（多人身份修复计划 §6.1）：群聊/私聊都用
    # ctx.user_id（平台 sender）；群号 peer_id 是会话地址不是人，绝不当主体。
    # 主动发言（无目标用户）与旧入口返回 None——SPACE-only / 旧 user_id 过滤。
    access_scope = None
    if getattr(ctx, "conversation_kind", ""):
        from memory.ownership import scope_for_chat_context

        access_scope = scope_for_chat_context(ctx, memory_space=space)

    # 先组装稳定画像（只读稳定事实，过滤人格判断）
    profile = _read_stable_profile(space, ctx.user_id)
    ctx.user_profile = profile

    # v2 检索（Context-aware Memory Activation），按群组共享空间检索。
    # 开启 MEMORY_EMBEDDING_ENABLED 时走 embedding 语义分（失败自动回退规则版）。
    # 复核 F1：typed 检索查询优先——主动验证等场景由服务端生成查询文本
    # （候选主题+目标近期对话），不再拿整段任务指令当查询。
    retrieval_query = (getattr(ctx, "retrieval_query", "") or "").strip() or ctx.message
    if MEMORY_EMBEDDING_ENABLED:
        from memory.retrieval_v2 import retrieve_memories_emb

        result = await retrieve_memories_emb(
            group_shared_space=space,
            user_id=ctx.user_id,
            query=retrieval_query,
            trigger=ctx.trigger,
            access_scope=access_scope,
        )
    else:
        result = retrieve_memories(
            group_shared_space=space,
            user_id=ctx.user_id,
            query=retrieval_query,
            trigger=ctx.trigger,
            access_scope=access_scope,
        )
    ctx.memory_mode = result.mode
    ctx.conversation_memories = result.conversation_memories
    ctx.behavior_constraints = result.behavior_constraints
    ctx.memory_trace = result.trace
    # 兼容旧字段（memories_for_prompt），供仍读取它的模块使用
    ctx.memories_for_prompt = result.conversation_memories

    # 归属证据表（复核 F1）：guard 模式非 off 时由服务端构建（可信近期消息
    # + 受众内已检索事实 + 当前纠正），供 prompt 协议段与发送前 guard 使用。
    if _reply_guard_mode() != "off":
        try:
            ctx.attribution_evidence = build_attribution_evidence(ctx)
        except Exception as exc:
            logger.debug(f"归属证据表构建失败（按无证据继续）: {exc}")

    if ctx.conversation_memories or ctx.behavior_constraints:
        logger.info(
            f"🧠 [Context v2] 空间={space} 模式={result.mode} 聊天素材={len(result.conversation_memories)} "
            f"行为约束={len(result.behavior_constraints)}"
        )
    return ctx


def _load_preferred_address(ctx: ChatContext, space: str) -> str | None:
    """只为明确的目标用户读取称呼偏好，群级主动发言保持为空。"""
    ctx.preferred_address = None
    if ctx.trigger == "proactive" or ctx.user_id in (None, 0):
        return None
    try:
        from memory.addressing import get_preference

        preference = get_preference(space, ctx.user_id)
        if preference is not None:
            ctx.preferred_address = preference.address_term
            return preference.address_term
    except Exception as error:
        logger.debug(f"读取称呼偏好失败（跳过）: {error}")
    return None


def _reply_guard_mode() -> str:
    """回复归属守护模式（复核 F1）：读取配置，异常按 off。"""
    try:
        from config.settings import REPLY_ATTRIBUTION_GUARD_MODE

        return str(REPLY_ATTRIBUTION_GUARD_MODE or "off").strip().lower()
    except Exception:
        return "off"


_RECENT_EVIDENCE_MESSAGES = 8
_EVIDENCE_FACTS = 6
_EVIDENCE_TEXT_MAX = 120


def _recent_trusted_messages(ctx: ChatContext, limit: int = _RECENT_EVIDENCE_MESSAGES) -> list[dict]:
    """同会话近期真实消息（作者来自库行，复核 F12：作者边界由服务端定）。"""
    key = str(getattr(ctx, "conversation_key", "") or "")
    if not key:
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT id, user_id, content, sender_display_name, timestamp"
            " FROM group_messages WHERE conversation_key = ?"
            " AND source_kind != 'BOT_SELF' AND content != ''"
            " ORDER BY id DESC LIMIT ?",
            (key, int(limit)),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    messages = []
    for row_id, user_id, content, display, ts in reversed(rows):
        author_id = int(user_id) if str(user_id or "").isdigit() else 0
        messages.append(
            {
                "id": row_id,
                "text": str(content or "")[:_EVIDENCE_TEXT_MAX],
                "author_id": author_id,
                "author_display": str(display or "") or (f"用户({user_id})" if user_id else ""),
                "object_id": None,
                "row_id": row_id,
                "conversation_key": key,
                "timestamp": str(ts or ""),
            }
        )
    return messages


def _current_corrections(ctx: ChatContext, limit: int = 2) -> list[dict]:
    """当前会话的纠正证据（conflicted/第三人纠正行；复核 F12：受限 ack 来源）。"""
    key = str(getattr(ctx, "conversation_key", "") or "")
    if not key:
        return []
    try:
        from memory.conversation_identity import active_claims

        claims = [
            c for c in active_claims(key)
            if c.get("status") == "conflicted"
            or c.get("claim_kind") == "third_person_correction"
        ][-int(limit):]
    except Exception:
        return []
    corrections = []
    for c in claims:
        author = str(c.get("author_user_id") or "")
        corrections.append(
            {
                "id": c.get("source_row_id") or 0,
                "author_id": int(author) if author.isdigit() else 0,
                "author_display": f"用户({author})" if author else "",
                "text": str(c.get("alias") or ""),
                "conversation_key": key,
                "source_row_id": c.get("source_row_id"),
                "timestamp": "",
                "polarity": "negative",
            }
        )
    return [c for c in corrections if c["text"]]


def build_attribution_evidence(ctx: ChatContext) -> dict:
    """构建归属证据表投影（复核 F1/F12）。

    来源全部服务端可信：同会话近期消息（真实作者）、受众内已检索的
    PERSON 事实（access_scope 决定可见性，不复权）、当前纠正。上限
    16 单元（build_evidence_table 内截断）。
    """
    from core.dialogue_attribution import build_evidence_table, evidence_projection

    recent = _recent_trusted_messages(ctx)
    facts = []
    for mem in (getattr(ctx, "conversation_memories", None) or [])[:_EVIDENCE_FACTS]:
        content = str(mem.get("content") or "").strip()
        if not content:
            continue
        subject_key = str(mem.get("subject_key") or "")
        subject_uid = subject_key.split(":", 1)[-1] if subject_key else str(mem.get("user_id") or "")
        facts.append(
            {
                "id": mem.get("id") or mem.get("fact_key") or len(facts),
                "content": content[:_EVIDENCE_TEXT_MAX],
                "author_id": int(subject_uid) if subject_uid.isdigit() else 0,
                "author_display": f"用户({subject_uid})" if subject_uid else "",
                "object_id": None,
                "source_row_id": None,
                "conversation_key": getattr(ctx, "conversation_key", ""),
                "timestamp": "",
                "polarity": "neutral",
            }
        )
    corrections = _current_corrections(ctx)
    table = build_evidence_table(recent, facts, corrections, max_units=16)
    return evidence_projection(table)


def _read_stable_profile(group_shared_space: str, user_id: int) -> str:
    """读取用户画像，只保留「稳定事实」（语言偏好/技术水平/可观察行为），
    过滤人格判断与心理状态（见 Memory Policy / User Profile 治理方案）。
    按共享空间隔离——同一空间内的多个 QQ 群共享一份画像（v8 user_profiles 主键
    (group_shared_space, user_id)）。"""
    from memory.policy import stable_profile_facts

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT personality_traits, agent_attitude FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
            (group_shared_space, str(user_id)),
        )
        row = cursor.fetchone()
        conn.close()
    except sqlite3.OperationalError as e:
        # user_profiles 表尚不存在（新库）→ debug；列名不匹配等 → warning
        log_sqlite_error("PreProcessors._read_stable_profile", e)
        return ""
    if not row:
        return ""
    parts = []
    traits = stable_profile_facts(row[0] or "")
    if traits:
        parts.append(f"关于用户{user_id}的可观察特征: {'，'.join(traits)}")
    if row[1]:
        parts.append(f"对bot态度: {row[1]}")
    return "；".join(parts)


# 中文停用词（高频无意义词，匹配时排除）
_STOP_WORDS = frozenset(
    ["的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些", "什么", "怎么", "如何", "可以", "可能", "已经", "还", "但", "而", "且", "或", "虽然", "因为", "所以", "如果", "被", "把", "让", "从", "对", "为", "与", "向", "以", "及", "等", "之", "其", "此", "该", "本", "中", "里", "后", "前", "时", "年", "月", "日", "个", "些", "多", "少", "更", "最"]
)


def _extract_keywords(text: str, max_keywords: int) -> list[str]:
    """从中文文本中提取关键词（2-4 字词组），用于记忆话题匹配。

    算法：先按连续汉字段落（2-8 字）切分，长的再按 3-2 字滑动窗口切，过滤停用词，
    按出现频率降序取前 max_keywords 个。
    """
    # 提取连续中文字符片段
    segments = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    # 按 2-3 字切分
    candidates: list[str] = []
    for seg in segments:
        if len(seg) <= 4:
            candidates.append(seg)
        else:
            for size in (3, 2):
                for i in range(len(seg) - size + 1):
                    candidates.append(seg[i : i + size])
    # 过滤停用词，按出现次数取 top N
    freq: dict[str, int] = {}
    for c in candidates:
        if c not in _STOP_WORDS:
            freq[c] = freq.get(c, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [word for word, _ in ranked[:max_keywords]]
