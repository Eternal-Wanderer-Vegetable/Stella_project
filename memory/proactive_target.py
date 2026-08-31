# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 的目标选择与配额（Memory Verification Loop §4.2、§5-D2）。

职责：决定「该不该主动 @ 某人」以及「@ 谁、为什么」。不生成台词、不发消息，
只输出决策结果，便于单测与审计。


选人优先级：
  1. 有 OBSERVING 候选且 confidence 最接近晋升线的活跃用户 —— 验证一次即可
     跨过门槛，收益最高；
  2. 无候选但近期活跃、配额未用尽的用户 —— 冷启动，从日常话题切入；
  3. 都没有 → 不发言。


排除条件：当日配额已满、处于用户级冷却内、连续无回应超限。
"""
from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from nonebot import logger

from config import (
    DB_PATH,
    MEMORY_CONFIRM_HIGH_CONFIDENCE,
    MEMORY_OBSERVE_LOW_CONFIDENCE,
    PROACTIVE_AT_ACTIVE_WITHIN,
    PROACTIVE_AT_BONUS_MSGS_HIGH,
    PROACTIVE_AT_BONUS_MSGS_LOW,
    PROACTIVE_AT_ENABLED,
    PROACTIVE_AT_EXCLUDE_USERS,
    PROACTIVE_AT_QUOTA_BASE,
    PROACTIVE_AT_QUOTA_BONUS_MAX,
    PROACTIVE_AT_USER_COOLDOWN,
    PROACTIVE_COLDSTART_TOPICS,
    PROACTIVE_MAX_NO_REPLY,
)
from config.spaces import resolve_space
from memory.proactive import get_proactive
from memory.proactive_state import count_user_messages_24h, get_state


@dataclass
class ProactiveTarget:
    """一次主动 @ 的决策结果。"""

    user_id: int
    mode: str  # "verify"（验证候选）或 "coldstart"（冷启动话题）
    nickname: str = "对方"  # 群名片/昵称，用于生成自然的称呼
    candidate_id: str = ""
    candidate_content: str = ""
    candidate_type: str = ""
    topic: str = ""  # coldstart 模式下的话题
    reason: str = ""  # 供日志与审计


def at_quota(group_id: int, user_id: int) -> int:
    """该用户当日的主动 @ 配额上限：基础 + 按 24h 发言量的小幅奖励。

    msgs <= LOW  → BASE
    msgs >= HIGH → BASE + BONUS_MAX
    中间         → 线性插值后四舍五入

    奖励幅度刻意压小：高频用户信息产出多、容忍度也高，但「越活跃越被骚扰」
    是必须避免的失控模式，因此硬封顶在 BASE + BONUS_MAX。
    """
    msgs = count_user_messages_24h(group_id, user_id)
    low, high = PROACTIVE_AT_BONUS_MSGS_LOW, PROACTIVE_AT_BONUS_MSGS_HIGH
    if high <= low:
        t = 1.0 if msgs >= high else 0.0
    else:
        t = max(0.0, min(1.0, (msgs - low) / (high - low)))
    return PROACTIVE_AT_QUOTA_BASE + round(PROACTIVE_AT_QUOTA_BONUS_MAX * t)


def _cooldown_elapsed(last_at_at: str | None) -> bool:
    """距上次主动 @ 该用户是否已超过 PROACTIVE_AT_USER_COOLDOWN。


    必须用 UTC 解析：last_at_at 由 SQLite CURRENT_TIMESTAMP 写入（UTC），
    此前用 datetime.now()（本地时间）比较导致该冷却在 UTC+8 下永不生效。
    解析失败时保守放行——宁可多等一轮，不如因脏数据永久卡死。
    """
    from memory.timeutil import seconds_since


    if not last_at_at:
        return True
    elapsed = seconds_since(last_at_at)
    return True if elapsed is None else elapsed >= PROACTIVE_AT_USER_COOLDOWN


def can_at_user(group_id: int, user_id: int) -> tuple[bool, str]:
    """判断能否主动 @ 该用户，返回 (是否可以, 原因)。"""
    if not PROACTIVE_AT_ENABLED:
        return False, "主动 @ 已关闭"

    state = get_state(group_id, user_id)

    if state["consecutive_no_reply"] >= PROACTIVE_MAX_NO_REPLY:
        return False, f"连续 {state['consecutive_no_reply']} 次未获回应，已退避"

    quota = at_quota(group_id, user_id)
    if state["at_count_today"] >= quota:
        return False, f"当日配额已满（{state['at_count_today']}/{quota}）"

    if not _cooldown_elapsed(state["last_at_at"]):
        return False, "用户级冷却中"

    return True, f"可以（今日 {state['at_count_today']}/{quota}）"


def _fetch_observing_candidate(
    group_shared_space: str, user_id: int, exclude_id: str = ""
) -> tuple[str, str, str, float] | None:
    """取该用户 confidence 最接近晋升线的 OBSERVING 候选。

    返回 (id, content, type, confidence)；无则 None。
    候选按共享空间归属（``memory_candidates.group_shared_space``）。

    只取 confidence 在 [LOW-0.2, HIGH) 区间内的：太低的候选证据本身可疑，
    问了也难以定论；已达 HIGH 的会自动晋升、无需验证。

    ``exclude_id`` 排除上次已经问过这个人的那条候选（``proactive_state.
    last_asked_candidate_id``）。没有这层排除，一条晋升不了的候选会在每一轮
    都以最高 confidence 胜出，于是对同一个人反复问同一个问题——正是
    design_docs/bug_report/bug_report_2026_8_31#1.md 记录的复读现象。
    """
    lower = max(0.0, MEMORY_OBSERVE_LOW_CONFIDENCE - 0.2)
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            "SELECT id, content, type, confidence FROM memory_candidates "
            "WHERE group_shared_space = ? AND user_id = ? AND status = 'OBSERVING' "
            "AND confidence >= ? AND confidence < ? AND content != '' "
            "AND id != ? "
            "ORDER BY confidence DESC LIMIT 1",
            (
                group_shared_space,
                str(user_id),
                lower,
                MEMORY_CONFIRM_HIGH_CONFIDENCE,
                exclude_id or "",
            ),
        ).fetchone()
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveTarget] 读取候选失败: {e}")
        return None
    if not row:
        return None
    return str(row[0]), str(row[1] or ""), str(row[2] or "FACT"), float(row[3] or 0.0)


def _known_topics(group_shared_space: str, user_id: int) -> str:
    """该用户已有的 active 记忆内容（拼成一段），用于避免冷启动重复提问。

    只取内容文本，不含元信息——它只是用来做关键词避让，不进 prompt。
    记忆按共享空间归属（``memories.group_shared_space``）。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT content FROM memories WHERE group_shared_space = ? AND user_id = ? "
            "AND status = 'active' LIMIT 50",
            (group_shared_space, str(user_id)),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        # 静默 return "" 让避让逻辑失效却毫无痕迹——这正是本函数漏了按空间查、
        # 长期未被发现的原因，必须留痕
        logger.warning(f"⚠️ [ProactiveTarget] 读取已知话题失败: {e}")
        return ""
    return " ".join((r[0] or "") for r in rows)


def _topic_covered(topic: str, known: str) -> bool:
    """该话题是否已被现有记忆覆盖（粗判：话题里的关键词元已出现在记忆中）。

    用 text_similarity 的分词做交集，命中即认为已知。宁可漏判（多问一次）
    也不要误判（把没问过的话题当成已知），因此要求全部关键词都命中。
    """
    if not known:
        return False
    from memory.text_similarity import normalize_text

    words = [w for w in normalize_text(topic).split() if len(w) >= 2]
    if not words:
        return False
    known_norm = normalize_text(known)
    return all(w in known_norm for w in words)


def pick_target(group_id: int, exclude_user_ids: set[int] | None = None) -> ProactiveTarget | None:
    """挑选本次主动 @ 的对象；无合适目标时返回 None。

    exclude_user_ids 用于排除 Bot 自身等不该被搭话的账号；
    排除名单同时来自调用方传入与 PROACTIVE_AT_EXCLUDE_USERS 配置。

    归属分界：候选与已知话题（memory_candidates / memories）按**共享空间**查
    （``resolve_space(group_id)``）；活跃度、配额、冷却（active_users /
    can_at_user / get_state）仍按真实 **QQ 群**——前者是「对人的长期认知」，
    后者是「当下这场对话的状态」。
    """
    if not PROACTIVE_AT_ENABLED:
        return None

    # 候选/已知话题按共享空间归属，只解析一次；其余仍用 group_id
    space = resolve_space(group_id)

    # 调用方传入的排除项（Bot 自身）+ 配置的排除名单（其他 AI 等）
    excluded = set(exclude_user_ids or set()) | PROACTIVE_AT_EXCLUDE_USERS
    actives = [
        uid
        for uid in get_proactive().active_users(group_id, PROACTIVE_AT_ACTIVE_WITHIN)
        if uid not in excluded
    ]
    if not actives:
        return None

    eligible: list[int] = []
    for uid in actives:
        ok, reason = can_at_user(group_id, uid)
        if ok:
            eligible.append(uid)
        else:
            logger.debug(f"[ProactiveTarget] 跳过用户 {uid}：{reason}")
    if not eligible:
        return None

    # 优先级 1：有可验证候选的用户（按 confidence 降序，最接近晋升线的先问）
    # 每人排除上次已经问过的那条候选，否则同一条候选会在每轮都胜出 → 复读
    verify_pool: list[tuple[float, int, tuple[str, str, str, float]]] = []
    for uid in eligible:
        found = _fetch_observing_candidate(
            space, uid, exclude_id=get_state(group_id, uid)["last_asked_candidate_id"]
        )
        if found:
            verify_pool.append((found[3], uid, found))
    if verify_pool:
        verify_pool.sort(key=lambda item: item[0], reverse=True)
        _, uid, (cid, content, ctype, conf) = verify_pool[0]
        return ProactiveTarget(
            user_id=uid,
            mode="verify",
            candidate_id=cid,
            candidate_content=content,
            candidate_type=ctype,
            reason=f"验证候选（conf={conf:.2f}，距晋升线 {MEMORY_CONFIRM_HIGH_CONFIDENCE}）",
        )

    # 优先级 2：冷启动——取最近发言的那位（actives 已按时间倒序）
    if not PROACTIVE_COLDSTART_TOPICS:
        return None
    uid = eligible[0]
    state = get_state(group_id, uid)
    known = _known_topics(space, uid)
    # 依次避开：上次问过的话题、已经知道答案的话题（关键词出现在已有记忆里）
    topics = [
        t
        for t in PROACTIVE_COLDSTART_TOPICS
        if t != state["last_asked_topic"] and not _topic_covered(t, known)
    ]
    topic = random.choice(topics or PROACTIVE_COLDSTART_TOPICS)
    return ProactiveTarget(
        user_id=uid,
        mode="coldstart",
        topic=topic,
        reason="无可验证候选，冷启动获取初始信息",
    )
