# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""表达与插话效果学习（设计阶段六）的异步后处理。

学习四件事（设计第 8 节）：用户是否继续回应、是否复用 Stella 的表达、
是否使用表情、是否纠正 Stella、是否忽略主动发言。

硬约束：**全部学习都在回复发出之后的后台任务里完成**——主回复路径只调用
``on_reply_sent``（登记 + 派生任务，微秒级返回），不等待任何结算；学习过程
零 LLM 调用（纯本地规则 + SQLite），坏了只影响学习不影响聊天。

进程内状态丢失的兜底：延迟结算任务被取消（重启/关机）时行保持未结算，
``sweep_pending_effects``（定时任务）会扫描超窗行补结算。
"""

from __future__ import annotations

import asyncio
import re
import sqlite3
import time

from nonebot import logger

from config import (
    DB_PATH,
    EXPRESSION_EXAMPLES_KEEP_DAYS,
    EXPRESSION_HARVEST_PER_MESSAGE,
    EXPRESSION_LEARNING_ENABLED,
    JARGON_CONFIRM_THRESHOLD,
    JARGON_HIT_THRESHOLD,
    JARGON_TRACKER_MAX_TERMS,
    REPLY_EFFECT_WINDOW_SECONDS,
    REPLY_EFFECTS_KEEP_DAYS,
)
from memory import expression_store as store
from memory.timeutil import log_sqlite_error

# ── 回复效果分类 ──
_CORRECTION_MARKERS = (
    "不对", "不是这样", "你说错", "说错了", "记错", "记错了", "胡说", "乱说", "搞错", "别瞎说",
)
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
# 复用表达的最小重合长度：4 个连续汉字（更短的撞词几乎全是常用词）
_REUSE_NGRAM = 4

# ── 黑话信号提取 ──
# 只统计两类低噪声信号（见 settings.py 的 JARGON_* 注释）：
#   拉丁/字母数字混排词（yyds、xswl、Helldivers2）
#   引号内的中文词（「绝绝子」）
_JARGON_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9]{1,15}")
_JARGON_QUOTED = re.compile(r"[「『“\"]([\u4e00-\u9fffA-Za-z0-9]{2,8})[」』”\"]")
# 拉丁词的黑名单：英文常用词在中文群聊里出现不代表黑话
_JARGON_LATIN_STOP = frozenset(
    ["the", "a", "an", "and", "or", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at", "for", "with", "by", "from", "this", "that", "it", "its", "as", "not", "no", "yes", "ok", "okay", "good", "bad", "nice", "hello", "hi", "hey", "thanks", "thank", "please", "sorry", "http", "https", "www", "com", "net", "org", "cn", "me", "you", "he", "she", "they", "we", "i", "my", "your"]
)

# 表达样本的切分与筛选
_CLAUSE_SPLIT = re.compile(r"[，。！？；、\n,.!?;:~～]+")

# 派生任务的引用集合：asyncio.create_task 的返回值必须持有，否则可能在完成前被 GC
_tasks: set[asyncio.Task] = set()
_tables_ready = False


def pending_tasks() -> list[asyncio.Task]:
    """在途学习任务（优雅关闭时取消用——结算可由 sweep 补齐）。"""
    return list(_tasks)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _ensure_tables() -> None:
    global _tables_ready
    if not _tables_ready:
        store.ensure_tables()
        _tables_ready = True


# ============================================================
# 入口：回复发出后调用（非阻塞）
# ============================================================


def on_reply_sent(
    *,
    group_id: int,
    group_shared_space: str,
    user_id: int,
    message: str,
    lines: list[str],
    trigger: str,
) -> None:
    """登记一次发言并派生异步学习任务。同步部分只有一次 DB 插入。

    :param message: 触发本次发言的用户消息（主动发言传空串——罐头指令
        不是用户的表达，不该进表达样本）
    :param lines: Stella 实际发出的台词（结算时判断「复用表达」的对照物）
    :param trigger: reply / proactive（写进 reply_effects 供分层统计）
    """
    if not EXPRESSION_LEARNING_ENABLED:
        return
    try:
        _ensure_tables()
        if trigger == "reply" and (message or "").strip():
            _spawn(_harvest_expression(group_shared_space, user_id, message))
        effect_id = store.add_reply_effect(
            group_shared_space=group_shared_space,
            group_id=group_id,
            user_id=user_id,
            trigger=trigger,
            reply_excerpt=" | ".join(lines or []),
            asked_at_mono=time.monotonic(),
        )
        if effect_id:
            _spawn(_resolve_effect_later(effect_id))
    except Exception as e:
        # 学习是纯旁路：这里炸了连日志都不该刷屏
        logger.debug(f"[Expression] 登记发言学习失败（跳过）: {e}")


def note_passive_message(group_shared_space: str, user_id: int, text: str) -> None:
    """被动消息的黑话计数（静默监听器热路径调用，纯内存操作）。

    命中数达到 JARGON_HIT_THRESHOLD 才碰一次数据库（upsert 累加）。
    """
    if not EXPRESSION_LEARNING_ENABLED:
        return
    try:
        for term in _extract_jargon_terms(text or ""):
            _bump_jargon(group_shared_space, term, user_id)
    except Exception as e:
        logger.debug(f"[Expression] 黑话计数失败（跳过）: {e}")


# ============================================================
# 表达样本采集
# ============================================================


async def _harvest_expression(group_shared_space: str, user_id: int, message: str) -> None:
    """从用户的 @ 消息里提取表达样本（短语/表情用法），异步执行。"""
    try:
        for text, kind in _extract_expression_candidates(message)[:EXPRESSION_HARVEST_PER_MESSAGE]:
            store.add_expression_example(group_shared_space, user_id, text, kind=kind)
    except Exception as e:
        logger.debug(f"[Expression] 表达采样失败（跳过）: {e}")


def _extract_expression_candidates(message: str) -> list[tuple[str, str]]:
    """提取候选表达：4~20 字的自然子句 + 独立表情串。

    返回 (文本, kind)；kind ∈ phrase / emoji。排序上子句优先——表情满天飞，
    值得学的是「这句话怎么说的」。
    """
    out: list[tuple[str, str]] = []
    for clause in _CLAUSE_SPLIT.split(message or ""):
        clause = clause.strip()
        if 4 <= len(clause) <= 20:
            out.append((clause, "phrase"))
    for emoji_run in _EMOJI_RE.findall(message or ""):
        out.append((emoji_run, "emoji"))
    return out


# ============================================================
# 回复效果结算
# ============================================================


async def _resolve_effect_later(effect_id: str) -> None:
    try:
        await asyncio.sleep(REPLY_EFFECT_WINDOW_SECONDS)
    except asyncio.CancelledError:
        # 进程关闭取消：行保持未结算，由 sweep_pending_effects 补
        return
    try:
        _resolve_effect(effect_id)
    except Exception as e:
        logger.debug(f"[Expression] 回复效果结算失败（effect={effect_id}）: {e}")


def _resolve_effect(effect_id: str) -> None:
    row = store.get_reply_effect(effect_id)
    if row is None or row["resolved"]:
        return
    messages = _fetch_user_messages_since(row["group_id"], row["user_id"], row["asked_at"])
    outcome = classify_response(row["reply_excerpt"].split(" | "), messages)
    store.resolve_reply_effect(effect_id, outcome)
    deltas = {"total": 1.0, outcome: 1.0}
    store.merge_pattern(row["group_shared_space"], row["user_id"], "reply_interactions", deltas)


def classify_response(stella_lines: list[str], user_messages: list[str]) -> str:
    """对窗口内用户的后续消息分类。纯函数。

    优先级：纠正 > 复用表达 > 使用表情 > 有回应 > 忽略——越靠前的信号
    越具体，一旦命中就不必再看后面（「复用了表达」本身就包含「有回应」）。
    """
    if not user_messages:
        return "ignored"
    joined = " ".join(user_messages)
    if any(marker in joined for marker in _CORRECTION_MARKERS):
        return "corrected"
    if _shares_expression(stella_lines, user_messages):
        return "reused_expression"
    if _EMOJI_RE.search(joined):
        return "emoji"
    return "responded"


def _shares_expression(stella_lines: list[str], user_messages: list[str]) -> bool:
    """用户是否复用了 Stella 的表达：共享 ≥4 字连续片段，或复用了同一表情。"""
    stella_grams: set[str] = set()
    for line in stella_lines:
        line = line or ""
        for emoji in _EMOJI_RE.findall(line):
            stella_grams.add(emoji)
        for i in range(len(line) - _REUSE_NGRAM + 1):
            gram = line[i : i + _REUSE_NGRAM]
            if all("\u4e00" <= ch <= "\u9fff" for ch in gram):
                stella_grams.add(gram)
    if not stella_grams:
        return False
    for msg in user_messages:
        if any(emoji in stella_grams for emoji in _EMOJI_RE.findall(msg)):
            return True
        for i in range(len(msg) - _REUSE_NGRAM + 1):
            if msg[i : i + _REUSE_NGRAM] in stella_grams:
                return True
    return False


def _fetch_user_messages_since(group_id: int, user_id: str, since_db_ts) -> list[str]:
    """取窗口内该用户在 group_messages 里的消息文本（UTC 时间戳比较，秒粒度）。"""
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT content FROM group_messages "
            "WHERE group_id = ? AND user_id = ? AND timestamp >= ? AND source_kind != 'BOT_SELF' "
            "ORDER BY id ASC LIMIT 50",
            (str(group_id), str(user_id), since_db_ts),
        ).fetchall()
        conn.close()
        return [(r[0] or "").strip() for r in rows if (r[0] or "").strip()]
    except sqlite3.Error as e:
        log_sqlite_error("expression_learning._fetch_user_messages_since", e)
        return []


# ============================================================
# 黑话计数
# ============================================================

# 进程内计数器：key=(空间, 词) -> {"hits": 批内计数, "users": 见过的用户}
_jargon: dict[tuple[str, str], dict] = {}


def _extract_jargon_terms(text: str) -> list[str]:
    terms: list[str] = []
    for m in _JARGON_QUOTED.findall(text):
        terms.append(m)
    for m in _JARGON_LATIN.findall(text):
        low = m.lower()
        if low not in _JARGON_LATIN_STOP:
            terms.append(low)
    return terms


def _bump_jargon(group_shared_space: str, term: str, user_id: int) -> None:
    key = (group_shared_space, term)
    entry = _jargon.get(key)
    if entry is None:
        # 容量控制：超限先踢掉批内计数最少的词条（新词给机会，冷词让位）
        if len(_jargon) >= JARGON_TRACKER_MAX_TERMS:
            for cold in sorted(_jargon, key=lambda k: _jargon[k]["hits"])[
                : max(1, len(_jargon) - JARGON_TRACKER_MAX_TERMS + 1)
            ]:
                _jargon.pop(cold, None)
        entry = {"hits": 0, "users": set()}
        _jargon[key] = entry
    entry["hits"] += 1
    entry["users"].add(int(user_id))
    if entry["hits"] >= JARGON_HIT_THRESHOLD:
        _ensure_tables()
        store.upsert_jargon(group_shared_space, term, entry["hits"], JARGON_CONFIRM_THRESHOLD)
        entry["hits"] = 0  # 已入库，批内计数清零（DB 侧累加）


# ============================================================
# 维护任务（定时调度）
# ============================================================


def sweep_pending_effects() -> int:
    """补结算超窗未结算的回复效果行（进程重启后的兜底）。返回结算行数。"""
    if not EXPRESSION_LEARNING_ENABLED:
        return 0
    try:
        _ensure_tables()
        cutoff = time.monotonic() - REPLY_EFFECT_WINDOW_SECONDS - 60.0
        rows = store.stale_reply_effects(cutoff)
        for row in rows:
            _resolve_effect(row["id"])
        return len(rows)
    except Exception as e:
        logger.debug(f"[Expression] sweep 异常（跳过本轮）: {e}")
        return 0


def prune_learning() -> dict[str, int]:
    """按保留期裁剪表达样本与已结算效果行（每日清理任务调用）。"""
    try:
        _ensure_tables()
        return store.prune(
            examples_keep_days=EXPRESSION_EXAMPLES_KEEP_DAYS,
            effects_keep_days=REPLY_EFFECTS_KEEP_DAYS,
        )
    except Exception as e:
        logger.debug(f"[Expression] prune 异常（跳过本轮）: {e}")
        return {}
