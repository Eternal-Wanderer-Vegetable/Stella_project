# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""会话上下文压缩的执行侧（Session Compact）。

与 memory/session_context.py 的分工：后者管状态与判定（纯逻辑、可离线单测），
本模块负责取待压缩消息、调 LLM、把结果写回状态。

**用哪个模型由配置决定**（角色 ``COMPACT``，见 core/llm/registry.py）：

- 纯本地默认绑到主聊天端点。压缩必须快——它在每次回复之后异步触发——而整合
  模型跑在 CPU 上单次 20~60 秒，27B 在 GPU 上约 2 秒。这也是改造前的行为。
- 切在线后按 D2 绑到**记忆域端点**，与整合、提取共用同一个 API key，
  于是共用同一份前缀缓存。

闸门跟着端点绑定走（``gate_of(ROLE_COMPACT)``）：绑主聊天端点就与主聊天串行
共享同一块显存，绑独立的在线端点就真正并行——这条不需要本模块做任何判断。

压缩 prompt 沿用捕获层的**防编造原则**：压不出内容就输出「无」，
宁可丢上下文也不能编造对话里没出现过的内容。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass

from nonebot import logger

from config import (
    DB_PATH,
    SESSION_SUMMARY_MAX_TOKENS,
)
from core.llm import ROLE_COMPACT, acquire, backend_for, gate_of
from core.llm.base import LLMBackend
from core.llm.usage_store import budget_blocked
from memory import session_context as sc
from memory.conversation_projection import (
    TranscriptBubble,
    TranscriptRecord,
    render_transcript_record,
)
from memory.prompt_builder import estimate_tokens
from memory.summary_packet import (
    SummaryEvidence,
    SummaryPacket,
    SummarySourceMessage,
    build_summary_evidence,
    build_summary_packet,
    render_summary_evidence,
    render_summary_packet,
    validate_summary_packet,
)

# 温度与生成上限现在是端点×角色配置的一部分：
# LLM_ROLE_COMPACT_TEMPERATURE（默认 0.3，信息提炼而非创作，稳定优先）、
# LLM_ROLE_COMPACT_MAX_TOKENS（默认 0 = 由 SESSION_SUMMARY_MAX_TOKENS 推导，
# prompt 里已按字数约束，上限只防极端情况下无限生成）。

# 正在压缩的群：同一群不并发压缩，否则两次调用会基于同一起点各自推进
_in_flight: set[int] = set()
_tasks: set[asyncio.Task] = set()
_protocol_failures: dict[tuple[int, tuple[int, int, int], int, int], int] = {}
_paused_sessions: dict[int, tuple[int, str]] = {}


def pending_tasks() -> set[asyncio.Task]:
    """返回在途压缩任务集合的副本（供优雅停止等待收尾）。"""
    return set(_tasks)


# 前缀缓存约束（2026-08-28 起）：可变的 {existing} / {messages} 必须排在最后。
# {max_chars} 由 SESSION_SUMMARY_MAX_TOKENS 推导、每次调用相同，属于固定前缀。
# 数据之后只保留一行输出格式提醒——它不进缓存，但只有十几个 token，
# 换来「最后一条指令」的位置优势，避免模型在回顾前加「好的，这是回顾：」之类前缀。
# 理由与守卫详见 memory/consolidation_prompt.py 的同名说明。
COMPACT_PROMPT = """你正在为后续对话筛选可回溯的原始发言记录。

每一行 REF 都是服务端从一条或多条原始消息构造的完整发言单元，包含稳定作者、
来源会话、Bot、回复对象、条件/转述元数据及原文。REF 不能拆分、改写或转交给
其他作者。你只负责选择值得保留的 REF；不要输出摘要、事实、作者解释或新台词。

必须保留原文中的否定、条件、假设、玩笑、引用、疑问与角色扮演限定；Bot 发言
只表示 Bot 说过这些话，不表示收件人实施了其中内容。无法确定是否值得保留时，
可以不选择。确实没有值得保留的记录时，返回空数组。

只返回一个 JSON 对象，结构严格为：{{"selected_refs":["ref_...", ...]}}。
ID 必须逐字来自下方旧 packet 或本批记录；不能重复 ID，不能附带任何其他字段。

===== 旧合法 packet 的可选原始记录 =====
{existing}
===== 本次开区间来源记录 =====
{messages}
"""


@dataclass(frozen=True, slots=True)
class PendingSourceBatch:
    conversation_key: str
    bot_id: str
    source_guard: tuple[int, int, int]
    source_low_id: int
    source_high_id: int
    source_watermark: int
    source_row_count: int
    entries: tuple[SummaryEvidence, ...]

    def render(self) -> str:
        return "\n".join(render_summary_evidence(entry) for entry in self.entries)


class CompactSourceError(ValueError):
    """当前来源行缺少/冲突的会话身份或完整逻辑单元。"""


def build_compact_prompt(
    entries: tuple[SummaryEvidence, ...] | list[SummaryEvidence],
    existing_packet: SummaryPacket | None = None,
) -> str:
    """仅向模型提供服务端 ref；旧摘要文本不再作为可改写输入。"""
    existing = render_summary_packet(existing_packet) if existing_packet else ""
    messages = "\n".join(render_summary_evidence(entry) for entry in entries)
    if not messages:
        raise ValueError("Compact requires at least one validated source ref")
    return COMPACT_PROMPT.format(existing=existing, messages=messages)

def _get_backend() -> LLMBackend | None:
    """压缩用的后端；角色 ``COMPACT`` 没绑到可用端点时返回 ``None``。

    不在本模块缓存实例：``core.llm.registry`` 已按角色缓存，再存一份会在
    ``registry.reset_state()``（改配置后重载）之后继续用旧端点——那种 bug
    表现为「GUI 改完保存了但摘要还发去旧地址」，极难查。

    返回 ``None`` 而不是抛异常：压缩是异步后台任务，抛异常只会变成一行
    warning，反而不如显式判空后给一条能照着改的日志。
    """
    return backend_for(ROLE_COMPACT)


def _fetch_rows_with_relations(
    conn: sqlite3.Connection, group_id: int, low_id: int, high_id: int, limit: int
) -> list[tuple] | None:
    """读区间原始行（带 v16 关系列）；关系列不可用返回 None（旧路径降级）。"""
    try:
        return conn.execute(
            "SELECT id, user_id, content, source_kind, "
            "reply_to_msg_id, reply_target_user_id, mentioned_user_ids_json, "
            "logical_message_id, part_index, reply_recipient_user_id, "
            "origin_msg_id, bot_id "
            "FROM group_messages "
            "WHERE group_id = ? AND id > ? AND id < ? ORDER BY id ASC LIMIT ?",
            (str(group_id), low_id, high_id, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return None


def _render_relation_rows(rows: list[tuple]) -> list[str]:
    """把带关系的行渲染成与实时尾巴同款的自足投影（归属修复计划 §6.4）。

    连续 BOT_SELF 且签名一致（logical ID/作者/收件人/来源）的行合为一个
    逻辑单元、渲染成一个物理行；任何元数据冲突都拆开呈现。每行自足，
    批次切在单元中间时每段仍带完整作者/收件人。
    """
    rows = [row for row in rows if (row[2] or "").strip()]  # 空内容行不渲染
    units: list[list[tuple]] = []

    def _signature(row: tuple) -> tuple:
        return (
            str(row[7] or ""),
            str(row[1] or ""),
            str(row[3] or ""),
            str(row[9] or ""),
            str(row[10] or ""),
            str(row[11] or ""),
        )

    for row in rows:
        if (
            row[3] == "BOT_SELF"
            and str(row[7] or "")
            and units
            and _signature(units[-1][-1]) == _signature(row)
        ):
            units[-1].append(row)
            continue
        units.append([row])

    lines: list[str] = []
    for unit in units:
        first = unit[0]
        if first[3] == "BOT_SELF":
            record = TranscriptRecord(
                author_id=str(first[1] or ""),
                author_is_bot=True,
                bubbles=tuple(
                    TranscriptBubble(part_index=int(row[8] or 0), text=(row[2] or "").strip())
                    for row in unit
                ),
                recipient_id=str(first[9] or ""),
                origin_msg_id=str(first[10] or ""),
            )
        else:
            try:
                mentioned = tuple(
                    str(m)
                    for m in (json.loads(first[6]) if first[6] else [])
                    if str(m or "").strip()
                )
            except (ValueError, TypeError):
                mentioned = ()
            record = TranscriptRecord(
                author_id=str(first[1] or ""),
                author_is_bot=False,
                bubbles=(TranscriptBubble(0, (first[2] or "").strip()),),
                reply_to_msg_id=str(first[4] or ""),
                reply_target_user_id=str(first[5] or ""),
                mentioned_user_ids=mentioned,
            )
        line = render_transcript_record(record)
        if line:
            lines.append(line)
    return lines


def fetch_pending_messages(
    group_id: int, low_id: int, high_id: int, limit: int
) -> tuple[str, int, int]:
    """取待压缩消息（``low_id < id < high_id``），返回 (文本, 实际处理到的 id, 条数)。

    区间左右均为开区间：左侧排除已压缩的，右侧排除尾巴（防止同一段对话
    在摘要与尾巴里各出现一次）。

    条数超过 limit 时只取**最旧的 limit 条**并返回其末尾 id，
    剩余部分留给下一次压缩，保证增量推进而非一次吞下全部。

    v16 关系列可用时，渲染与实时尾巴共用同一纯投影（作者/收件人/状态
    保留；归属修复计划 §6.4）；``count`` 恒为**原始非空行数**——合组只
    改变呈现，不改变计数与水位语义。旧库（无关系列）保持旧格式逐字不变。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        rel_rows = _fetch_rows_with_relations(conn, group_id, low_id, high_id, limit)
        rows: list[tuple]
        if rel_rows is None:
            rows = conn.execute(
                "SELECT id, user_id, content, source_kind FROM group_messages "
                "WHERE group_id = ? AND id > ? AND id < ? ORDER BY id ASC LIMIT ?",
                (str(group_id), low_id, high_id, limit),
            ).fetchall()
        else:
            rows = [(r[0], r[1], r[2], r[3]) for r in rel_rows]
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [Compact] 读取待压缩消息失败: {e}")
        return "", low_id, 0

    lines: list[str] = []
    max_id = low_id
    non_empty = 0
    for row in rows:
        max_id = row[0]
        if not (row[2] or "").strip():
            continue
        non_empty += 1
    if rel_rows is not None:
        lines = _render_relation_rows(rel_rows)
    else:
        for _mid, uid, content, kind in rows:
            text = (content or "").strip()
            if not text:
                continue
            lines.append(f"我: {text}" if kind == "BOT_SELF" else f"用户({uid}): {text}")

    return "\n".join(lines), max_id, non_empty


_COMPACT_UNIT_EXTENSION_CAP = 64
_COMPACT_SOURCE_COLUMNS = (
    "id",
    "group_id",
    "user_id",
    "content",
    "source_kind",
    "timestamp",
    "msg_id",
    "conversation_key",
    "bot_id",
    "reply_to_msg_id",
    "reply_target_user_id",
    "mentioned_user_ids_json",
    "logical_message_id",
    "part_index",
    "origin_msg_id",
    "reply_recipient_user_id",
)


def _source_signature(row: dict) -> tuple[str, ...]:
    return (
        str(row.get("logical_message_id") or ""),
        str(row.get("user_id") or ""),
        str(row.get("source_kind") or ""),
        str(row.get("bot_id") or ""),
        str(row.get("reply_recipient_user_id") or ""),
        str(row.get("origin_msg_id") or ""),
        str(row.get("conversation_key") or ""),
    )


def _decode_mentions(raw: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(value, list):
        return ()
    return tuple(str(uid) for uid in value if str(uid or "").strip())


def _complete_unit_rows(
    conn: sqlite3.Connection,
    rows: list[dict],
    *,
    group_id: int,
    low_id: int,
    high_id: int,
    limit: int,
    columns: set[str],
) -> list[dict]:
    """Keep a batch cut at a complete BOT_SELF logical bubble group."""
    if len(rows) <= limit:
        selected = rows
    else:
        end = limit
        boundary = rows[end - 1]
        signature = _source_signature(boundary)
        logical_id = signature[0]
        if boundary.get("source_kind") == "BOT_SELF" and logical_id:
            while end < len(rows) and _source_signature(rows[end]) == signature:
                end += 1
            if (
                end == len(rows)
                and len(rows) == limit + _COMPACT_UNIT_EXTENSION_CAP + 1
                and _source_signature(rows[-1]) == signature
            ):
                raise CompactSourceError("logical utterance exceeds bounded batch extension")
        selected = rows[:end]

    first = selected[0] if selected else None
    if (
        first
        and first.get("source_kind") == "BOT_SELF"
        and first.get("logical_message_id")
        and columns.issuperset({"logical_message_id", "user_id", "source_kind"})
    ):
        cursor = conn.execute(
            "SELECT id, user_id, source_kind, logical_message_id, "
            "bot_id, reply_recipient_user_id, origin_msg_id, conversation_key "
            "FROM group_messages WHERE group_id = ? AND id <= ? "
            "AND logical_message_id = ? ORDER BY id DESC LIMIT 1",
            (str(group_id), low_id, first["logical_message_id"]),
        )
        prior = cursor.fetchone()
        if prior:
            prior_row = dict(zip(
                ("id", "user_id", "source_kind", "logical_message_id", "bot_id",
                 "reply_recipient_user_id", "origin_msg_id", "conversation_key"),
                prior,
                strict=True,
            ))
            if _source_signature(prior_row) == _source_signature(first):
                raise CompactSourceError("open range begins inside a logical utterance")

    last = selected[-1] if selected else None
    if last and last.get("source_kind") == "BOT_SELF" and last.get("logical_message_id"):
        cursor = conn.execute(
            "SELECT id, user_id, source_kind, logical_message_id, "
            "bot_id, reply_recipient_user_id, origin_msg_id, conversation_key "
            "FROM group_messages WHERE group_id = ? AND id >= ? "
            "AND logical_message_id = ? ORDER BY id ASC LIMIT ?",
            (str(group_id), high_id, last["logical_message_id"], _COMPACT_UNIT_EXTENSION_CAP + 1),
        )
        following = cursor.fetchall()
        expected = _source_signature(last)
        signature_columns = (
            "id", "user_id", "source_kind", "logical_message_id", "bot_id",
            "reply_recipient_user_id", "origin_msg_id", "conversation_key",
        )
        if any(
            _source_signature(dict(zip(signature_columns, row, strict=True))) == expected
            for row in following
        ):
            raise CompactSourceError("open range ends inside a logical utterance")
    return selected


def fetch_pending_records(
    group_id: int,
    low_id: int,
    high_id: int,
    limit: int,
    source_guard: tuple[int, int, int],
) -> PendingSourceBatch:
    """Read an open ID range into complete, exact-source evidence units."""
    if limit <= 0:
        raise ValueError("Compact source limit must be positive")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(group_messages)").fetchall()
        }
        required = {"id", "group_id", "user_id", "content", "source_kind"}
        if not required.issubset(columns):
            raise CompactSourceError("group_messages lacks required source columns")
        selected_columns = [name for name in _COMPACT_SOURCE_COLUMNS if name in columns]
        projection = ", ".join(selected_columns)
        raw_rows = conn.execute(
            f"SELECT {projection} FROM group_messages "
            "WHERE group_id = ? AND id > ? AND id < ? ORDER BY id ASC LIMIT ?",
            (
                str(group_id),
                low_id,
                high_id,
                limit + _COMPACT_UNIT_EXTENSION_CAP + 1,
            ),
        ).fetchall()
        rows = [dict(row) for row in raw_rows]
        rows = _complete_unit_rows(
            conn,
            rows,
            group_id=group_id,
            low_id=low_id,
            high_id=high_id,
            limit=limit,
            columns=columns,
        )
    except sqlite3.Error as exc:
        raise CompactSourceError(f"cannot read Compact source rows: {exc}") from exc
    finally:
        conn.close()

    watermark = int(rows[-1]["id"]) if rows else low_id
    non_empty_rows = [row for row in rows if str(row.get("content") or "").strip()]
    conversation_values = {str(row.get("conversation_key") or "").strip() for row in rows}
    known_conversations = {value for value in conversation_values if value}
    if len(known_conversations) > 1 or (known_conversations and "" in conversation_values):
        raise CompactSourceError("source rows disagree on canonical conversation")
    if known_conversations:
        conversation_key = next(iter(known_conversations))
    elif group_id > 0:
        # Pre-v16 group rows have no conversation_key; the exact group_id predicate
        # remains the scoped legacy key and is explicitly represented in the packet.
        conversation_key = f"legacy:group:{group_id}"
    else:
        raise CompactSourceError("private Compact rows require a canonical conversation_key")

    known_bots = {str(row.get("bot_id") or "").strip() for row in rows}
    known_bots.discard("")
    if len(known_bots) > 1:
        raise CompactSourceError("source rows disagree on Bot identity")
    bot_id = next(iter(known_bots), "")
    if any(
        row.get("source_kind") == "BOT_SELF"
        and (not bot_id or str(row.get("user_id") or "") != bot_id)
        for row in non_empty_rows
    ):
        raise CompactSourceError("Bot speech lacks a matching stored Bot identity")

    units: list[list[dict]] = []
    for row in non_empty_rows:
        if (
            row.get("source_kind") == "BOT_SELF"
            and row.get("logical_message_id")
            and units
            and _source_signature(units[-1][-1]) == _source_signature(row)
        ):
            units[-1].append(row)
        else:
            units.append([row])

    entries: list[SummaryEvidence] = []
    for unit in units:
        messages = tuple(
            SummarySourceMessage(
                message_id=int(row["id"]),
                author_id=str(row.get("user_id") or ""),
                source_kind=str(row.get("source_kind") or ""),
                content=str(row.get("content") or ""),
                timestamp=str(row.get("timestamp") or ""),
                platform_message_id=str(row.get("msg_id") or ""),
                part_index=max(0, int(row.get("part_index") or 0)),
                recipient_id=str(row.get("reply_recipient_user_id") or ""),
                origin_msg_id=str(row.get("origin_msg_id") or ""),
                reply_to_msg_id=str(row.get("reply_to_msg_id") or ""),
                reply_target_user_id=str(row.get("reply_target_user_id") or ""),
                mentioned_user_ids=_decode_mentions(
                    str(row.get("mentioned_user_ids_json") or "")
                ),
                mentioned_user_ids_json=str(row.get("mentioned_user_ids_json") or ""),
                logical_message_id=str(row.get("logical_message_id") or ""),
            )
            for row in unit
        )
        entry = build_summary_evidence(conversation_key, bot_id, messages)
        if not entry.ref_id or not entry.source_digest:
            raise CompactSourceError("could not seal source evidence")
        entries.append(entry)

    return PendingSourceBatch(
        conversation_key=conversation_key,
        bot_id=bot_id,
        source_guard=tuple(source_guard),
        source_low_id=low_id,
        source_high_id=high_id,
        source_watermark=watermark,
        source_row_count=len(non_empty_rows),
        entries=tuple(entries),
    )


def parse_selected_refs(result: str, allowed_refs: set[str]) -> tuple[str, ...]:
    """Parse the only model output accepted by Compact; reject duplicates/extra keys."""
    if not isinstance(result, str) or len(result.encode("utf-8")) > 16_384:
        raise ValueError("Compact selection response is missing or exceeds byte limit")

    def _unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON object key")
            value[key] = item
        return value

    try:
        parsed = json.loads(result, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Compact selection response is not JSON") from exc
    if not isinstance(parsed, dict) or set(parsed) != {"selected_refs"}:
        raise ValueError("Compact response must contain only selected_refs")
    refs = parsed["selected_refs"]
    if not isinstance(refs, list) or len(refs) > len(allowed_refs):
        raise ValueError("selected_refs must be a bounded array")
    if any(not isinstance(ref, str) or not ref for ref in refs):
        raise ValueError("selected_refs contains a non-string/empty ref")
    if len(refs) != len(set(refs)):
        raise ValueError("selected_refs contains duplicate refs")
    if any(ref not in allowed_refs for ref in refs):
        raise ValueError("selected_refs contains an unknown ref")
    return tuple(refs)


def _is_empty_result(text: str) -> bool:
    """模型是否判定「无可摘要内容」。

    容忍常见变体：无 / 无。/ （无）/ 空串。不做模糊匹配——
    「无法确定…」这类正常回顾不应被误判为空。
    """
    stripped = (text or "").strip().strip("（）()。.、 \n")
    return stripped in ("", "无", "None", "none")


def _flow_ctx(group_id: int):
    """压缩后台 root（schedule_compact 建；无 root 时全部空转）。"""
    try:
        from core.observability import message_flow

        found = message_flow.by_source_key(f"compact:{group_id}")
        return None if (found is None or found.ended) else found
    except Exception:
        return None


def _flow_span(fctx, node_id: str, **kw):
    try:
        from core.observability import message_flow

        return message_flow.span(fctx, node_id, **kw)
    except Exception:
        import contextlib

        return contextlib.nullcontext()


def _flow_decision(fctx, node_id: str, **kw) -> None:
    try:
        from core.observability import message_flow

        message_flow.decision(fctx, node_id, **kw)
    except Exception:
        pass


def _packet_for_entries(batch: PendingSourceBatch, entries: list[SummaryEvidence]) -> SummaryPacket:
    return build_summary_packet(
        conversation_key=batch.conversation_key,
        bot_id=batch.bot_id,
        source_guard=batch.source_guard,
        source_low_id=batch.source_low_id,
        source_high_id=batch.source_high_id,
        source_watermark=batch.source_watermark,
        source_row_count=batch.source_row_count,
        entries=entries,
    )


def _clear_protocol_failures(group_id: int) -> None:
    for key in tuple(_protocol_failures):
        if key[0] == group_id:
            _protocol_failures.pop(key, None)


def _record_protocol_failure(
    key: tuple[int, tuple[int, int, int], int, int], reason: str
) -> int:
    attempts = _protocol_failures.get(key, 0) + 1
    _protocol_failures[key] = attempts
    logger.warning(
        f"[Compact] 群 {key[0]} packet 协议/预算校验失败（同守卫区间第 {attempts} 次：{reason}）"
    )
    return attempts


def _deterministic_fallback(
    batch: PendingSourceBatch,
    existing: SummaryPacket | None,
) -> SummaryPacket | None:
    """Prefer a complete old+current record packet, then bounded current-source-only."""
    candidates: list[list[SummaryEvidence]] = []
    if existing:
        candidates.append([*existing.entries, *batch.entries])
    candidates.append(list(batch.entries))
    for entries in candidates:
        # Database row IDs are the stable chronology, including multi-bubble units.
        ordered = sorted(entries, key=lambda entry: min(entry.source_ids))
        packet = _packet_for_entries(batch, ordered)
        rendered = render_summary_packet(packet)
        if (
            validate_summary_packet(
                packet,
                conversation_key=batch.conversation_key,
                bot_id=batch.bot_id,
            )
            and rendered
            and estimate_tokens(rendered) <= SESSION_SUMMARY_MAX_TOKENS
        ):
            return packet
    return None


def _commit_packet(
    group_id: int,
    packet: SummaryPacket,
    source_count: int,
    guard: tuple[int, int, int],
) -> bool:
    """Keep guard validation and synchronous state CAS adjacent; there is no await."""
    if not sc.compact_guard_ok(group_id, guard):
        _flow_decision(None, "compact.commit", status="skipped", reason_code="stale_guard")
        return False
    before = sc.session_stats(group_id)
    sc.apply_summary(group_id, packet, packet.source_watermark, source_count)
    after = sc.session_stats(group_id)
    committed = (
        after.get("compact_count") == before.get("compact_count", 0) + 1
        and after.get("summarized_up_to_id") == packet.source_watermark
    )
    if committed:
        _clear_protocol_failures(group_id)
        _paused_sessions.pop(group_id, None)
    return committed


async def compact_once(group_id: int, tail_start_id: int) -> bool:
    """执行一次 source-backed Compact；协议错误不按“无内容”推进。"""
    fctx = _flow_ctx(group_id)
    with _flow_span(fctx, "compact.preflight"):
        blocked = budget_blocked(ROLE_COMPACT)
        if blocked:
            _flow_decision(fctx, "compact.preflight", status="blocked",
                           reason_code=f"budget:{blocked}")
            logger.warning(f"⚠️ [Compact] 群 {group_id} 跳过压缩：已被预算拦下（{blocked}）")
            return False

        bounds = sc.pending_bounds(group_id, tail_start_id)
        if bounds is None:
            _flow_decision(fctx, "compact.preflight", status="skipped",
                           reason_code="no_pending_range")
            return False
        low_id, high_id = bounds
        guard = sc.compact_guard(group_id)
        paused = _paused_sessions.get(group_id)
        if paused and paused[0] == guard[0]:
            _flow_decision(fctx, "compact.preflight", status="blocked",
                           reason_code="summary_packet_over_budget")
            logger.warning(
                f"[Compact] 群 {group_id} 的 Compact 因最小完整记录包超预算暂停；"
                "保留原始尾巴，需会话 reset 后重试"
            )
            return False
        if paused:
            _paused_sessions.pop(group_id, None)

        try:
            batch = fetch_pending_records(
                group_id,
                low_id,
                high_id,
                sc.compact_message_limit(),
                guard,
            )
        except (CompactSourceError, sqlite3.Error, ValueError) as exc:
            _flow_decision(fctx, "compact.preflight", status="blocked",
                           reason_code="source_packet_invalid")
            logger.warning(f"[Compact] 群 {group_id} 来源包校验失败，保留水位不动: {exc}")
            return False

        if batch.source_row_count == 0:
            _flow_decision(fctx, "compact.preflight", status="skipped",
                           reason_code="empty_content")
            if batch.source_watermark > low_id:
                sc.skip_range(group_id, batch.source_watermark, 0)
            return False
        if not batch.entries:
            _flow_decision(fctx, "compact.preflight", status="blocked",
                           reason_code="source_packet_empty")
            return False

        source_text = batch.render()
        if not sc.should_compact(source_text):
            _flow_decision(fctx, "compact.preflight", status="skipped",
                           reason_code="below_threshold")
            return False

        existing = sc.get_summary_packet(group_id)
        if existing and not validate_summary_packet(
            existing,
            conversation_key=batch.conversation_key,
            bot_id=batch.bot_id,
        ):
            sc.invalidate_summary(group_id, "conversation_or_bot_changed")
            existing = None

        failure_key = (group_id, guard, low_id, high_id)
        for key in tuple(_protocol_failures):
            if key[0] == group_id and key != failure_key:
                _protocol_failures.pop(key, None)
        if _protocol_failures.get(failure_key, 0) >= 2:
            fallback = _deterministic_fallback(batch, existing)
            if fallback is None:
                _paused_sessions[group_id] = (
                    guard[0],
                    "minimum complete record packet exceeds summary budget",
                )
                _flow_decision(fctx, "compact.commit", status="blocked",
                               reason_code="minimum_packet_over_budget")
                logger.error(
                    f"[Compact] 群 {group_id} 最小完整记录包超过预算；暂停该会话 Compact"
                )
                return False
            if not sc.compact_guard_ok(group_id, guard):
                _flow_decision(fctx, "compact.commit", status="skipped",
                               reason_code="stale_guard")
                return False
            logger.warning(
                f"[Compact] 群 {group_id} 同守卫区间连续协议失败，提交确定性原文 packet"
            )
            return _commit_packet(group_id, fallback, batch.source_row_count, guard)

        prompt = build_compact_prompt(batch.entries, existing)
        logger.info(
            f"🗜️ [Compact] 群 {group_id} 开始验证式压缩 {batch.source_row_count} 条消息"
            f"（至 id {batch.source_watermark}）"
        )
        backend = _get_backend()
        if backend is None:
            _flow_decision(fctx, "compact.preflight", status="blocked",
                           reason_code="no_backend")
            logger.warning(
                f"⚠️ [Compact] 群 {group_id} 跳过压缩：COMPACT 角色没有可用端点"
                "（LLM_ROLE_COMPACT_ENDPOINT 指向的槽未配 BASE_URL）。"
                "运行 python -m deploy doctor 查看解析结果。"
            )
            return False

    try:
        with _flow_span(fctx, "compact.generate"):
            async with acquire(gate_of(ROLE_COMPACT), tag=f"compact:{group_id}"):
                result = await backend.generate(prompt)
        _flow_decision(fctx, "compact.generate", status="succeeded",
                       metrics={"messages": batch.source_row_count})
    except Exception as exc:
        logger.warning(f"⚠️ [Compact] 群 {group_id} 压缩失败（保留待重试）: {exc}")
        return False

    if not sc.compact_guard_ok(group_id, guard):
        _flow_decision(fctx, "compact.commit", status="skipped",
                       reason_code="stale_guard")
        logger.info(f"🗜️ [Compact] 群 {group_id} 丢弃过期压缩结果（guard 变化，待重试）")
        return False

    allowed = {entry.ref_id: entry for entry in batch.entries}
    if existing:
        allowed.update({entry.ref_id: entry for entry in existing.entries})
    try:
        selected_refs = parse_selected_refs(result, set(allowed))
    except ValueError as exc:
        _record_protocol_failure(failure_key, str(exc))
        _flow_decision(fctx, "compact.commit", status="blocked",
                       reason_code="invalid_selection_protocol")
        return False

    if not selected_refs:
        # 明确、合法的空选择保持旧语义：保留旧摘要，只推进本区间水位。
        sc.skip_range(group_id, batch.source_watermark, batch.source_row_count)
        _clear_protocol_failures(group_id)
        return True

    selected = sorted(
        (allowed[ref] for ref in selected_refs),
        key=lambda entry: min(entry.source_ids),
    )
    packet = _packet_for_entries(batch, selected)
    rendered = render_summary_packet(packet)
    if (
        not validate_summary_packet(
            packet,
            conversation_key=batch.conversation_key,
            bot_id=batch.bot_id,
        )
        or not rendered
        or estimate_tokens(rendered) > SESSION_SUMMARY_MAX_TOKENS
    ):
        _record_protocol_failure(failure_key, "packet integrity/final budget check failed")
        _flow_decision(fctx, "compact.commit", status="blocked",
                       reason_code="invalid_or_over_budget_packet")
        return False

    committed = _commit_packet(group_id, packet, batch.source_row_count, guard)
    if not committed:
        _flow_decision(fctx, "compact.commit", status="blocked",
                       reason_code="packet_commit_rejected")
    return committed

def schedule_compact(group_id: int, tail_start_id: int,
                     parent_trace_id: str = "") -> None:
    """在后台异步触发一次压缩（不等待）。

    压缩放在回复发出**之后**：不阻塞当前回复，摘要从下一轮开始生效。
    同一群不并发压缩——两次调用会基于同一起点各自推进，导致重复或跳过。
    ``parent_trace_id``：触发回复的流程 trace（计划 §6.2），压缩跑在独立
    root 上，靠显式 relation 关联。
    """
    if group_id in _in_flight:
        logger.debug(f"[Compact] 群 {group_id} 已有压缩任务在跑，跳过本次触发")
        return

    # 在途占位必须在 create_task **之前**同步完成（计划 §6.2）：create_task
    # 的新任务可能到下一个事件循环 tick 才执行 _run()，同 tick 的第二次触发
    # 会在占位发生前通过检查、基于同一起点各自推进（重复/跳过）。
    _in_flight.add(group_id)

    async def _run() -> None:
        fctx = None
        try:
            from core.observability import message_flow

            fctx = message_flow.begin_trace(
                root_kind="compact", platform="qq", scope=f"qq:{group_id}",
                source_message_key=f"compact:{group_id}",
            )
            if parent_trace_id:
                message_flow.link(parent_trace_id, fctx.trace_id,
                                  kind="caused_by", evidence="post_reply_compact")
                # 实际派生事实（修复计划 §6.4）：worker 成功创建才记录
                parent_ctx = message_flow.by_trace(parent_trace_id)
                if parent_ctx is not None and not parent_ctx.ended:
                    message_flow.transition(
                        parent_ctx, from_node="reply.compact",
                        to_node="compact.spawn", relation_kind="spawn",
                        summary="compact worker spawned")
            message_flow.transition(
                fctx, from_node="compact.spawn", to_node="compact.preflight",
                relation_kind="cause")
        except Exception:
            fctx = None
        outcome = "done"
        try:
            await compact_once(group_id, tail_start_id)
        except Exception:
            outcome = "error"
            logger.exception(f"❌ [Compact] 群 {group_id} 压缩任务异常")
        finally:
            _in_flight.discard(group_id)
            try:
                from core.observability import message_flow

                if fctx is not None and not fctx.ended:
                    message_flow.end_trace(fctx, outcome=outcome)
            except Exception:
                pass

    task = asyncio.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reset_state() -> None:
    """清空进程内状态（供测试使用）。"""
    global _backend
    _backend = None
    _in_flight.clear()
    _protocol_failures.clear()
    _paused_sessions.clear()
