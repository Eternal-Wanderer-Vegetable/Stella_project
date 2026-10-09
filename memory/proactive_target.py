# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 的目标选择与配额（Memory Verification Loop §4.2、§5-D2）。

职责：决定「该不该主动 @ 某人」以及「@ 谁、为什么」。不生成台词、不发消息，
只输出决策结果，便于单测与审计。


选人优先级：
  1. 有 OBSERVING 候选且 confidence 最接近晋升线的活跃用户 —— 验证一次即可
     跨过门槛，收益最高；
  2. 都没有 → 不发言。主动 @ 的配额极其稀缺，只为把候选推过晋升线而花，
     不做无记忆锚点的日常话题搭话。

排除条件：当日配额已满、处于用户级冷却内、连续无回应超限。
"""
from __future__ import annotations

import json
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
    PROACTIVE_MAX_NO_REPLY,
    PROACTIVE_VERIFY_EXCLUDE_TYPES,
)
from config.spaces import resolve_space
from memory.proactive import get_proactive
from memory.proactive_state import count_user_messages_24h, get_state


@dataclass
class ProactiveTarget:
    """一次主动 @ 的决策结果。"""

    user_id: int
    nickname: str = "对方"  # 群名片/昵称，用于生成自然的称呼
    candidate_id: str = ""
    candidate_content: str = ""
    candidate_type: str = ""
    reason: str = ""  # 供日志与审计
    owner_type: str = ""
    owner_key: str = ""
    audience: str = ""
    fact_key: str = ""
    fact_subject_key: str = ""
    source_conversation_key: str = ""
    source_bot_id: str = ""
    evidence_ids: tuple[str, ...] = ()
    source_row_ids: tuple[int, ...] = ()
    source_digests: tuple[str, ...] = ()
    captured_scope_versions: dict[str, int] | None = None

    @property
    def skip_subject(self) -> str:
        """用于负向冷却的稳定主题键；候选变化会自然生成新键。"""
        return f"candidate:{self.candidate_id or self.candidate_content}"


@dataclass(frozen=True)
class _VerifiedCandidate:
    candidate_id: str
    content: str
    memory_type: str
    confidence: float
    owner_type: str
    owner_key: str
    audience: str
    fact_key: str
    fact_subject_key: str
    source_conversation_key: str
    source_bot_id: str
    evidence_ids: tuple[str, ...]
    source_row_ids: tuple[int, ...]
    source_digests: tuple[str, ...]
    scope_versions: dict[str, int]


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


def _exclude_types_clause() -> tuple[str, tuple[str, ...]]:
    """构造「不验证时效型候选」的 SQL 片段与绑定参数。

    配置为空时必须返回空片段：``NOT IN ()`` 在 SQLite 里是语法错误，而
    「留空」的语义是「所有类型都可以验证」，不能顺手塞一个默认类型进去。
    类型名一律走参数绑定，只有占位符个数进 SQL 文本。
    """
    types = tuple(sorted({str(t).strip().upper() for t in PROACTIVE_VERIFY_EXCLUDE_TYPES if str(t).strip()}))
    if not types:
        return "", ()
    holes = ",".join("?" * len(types))
    return f"AND UPPER(COALESCE(type, 'FACT')) NOT IN ({holes}) ", types


def _fetch_observing_candidate(
    group_shared_space: str,
    user_id: int,
    exclude_id: str = "",
    exclude_ids: set[str] | None = None,
    *,
    group_id: int,
    bot_id: str,
) -> _VerifiedCandidate | None:
    """取该用户 confidence 最接近晋升线的 OBSERVING 候选。

    只返回有当前 accepted evidence、active candidate/claim lineage 且能在原
    group_messages 行重核的候选。群主动验证仅读取 SPACE/CURRENT_SPACE 候选；
    PERSON 私聊事实不会因为 recording user 相同而变成群内追问依据。

    只取 confidence 在 [LOW-0.2, HIGH) 区间内的：太低的候选证据本身可疑，
    问了也难以定论；已达 HIGH 的会自动晋升、无需验证。

    ``exclude_id`` 排除上次已经问过这个人的那条候选（``proactive_state.
    last_asked_candidate_id``）。没有这层排除，一条晋升不了的候选会在每一轮
    都以最高 confidence 胜出，于是对同一个人反复问同一个问题——正是
    design_docs/bug_report/bug_report_2026_8_31#1.md 记录的复读现象。

    ``PROACTIVE_VERIFY_EXCLUDE_TYPES`` 里的类型（默认 EVENT / PLAN /
    GROUP_CONTEXT）一律不取：验证的目的是把候选推过晋升线变成**长期**记忆，
    而时效信息等确认下来时本身已经过期，这笔极稀缺的配额就花错了；语义上
    「你听到地震预警了吗」隔一周问也是荒谬的（同一份报告的现象 2）。
    """
    lower = max(0.0, MEMORY_OBSERVE_LOW_CONFIDENCE - 0.2)
    type_clause, type_params = _exclude_types_clause()
    excluded = {str(item) for item in (exclude_ids or set()) if str(item)}
    if exclude_id:
        excluded.add(str(exclude_id))
    id_clause = ""
    id_params: tuple[str, ...] = ()
    if excluded:
        placeholders = ",".join("?" * len(excluded))
        id_clause = f"AND id NOT IN ({placeholders}) "
        id_params = tuple(sorted(excluded))
    expected_conversation = f"qq:{bot_id}:group:{group_id}"
    if not bot_id or group_id <= 0 or not expected_conversation:
        return None
    try:
        from memory.evidence_contract import ASSESSMENT_VERSION, verify_source_snapshot

        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT c.id, c.content, c.type, c.confidence, c.owner_type, c.owner_key, "
            "c.audience, c.fact_key, c.source_conversation_key "
            "FROM memory_candidates c "
            "WHERE group_shared_space = ? AND user_id = ? AND status = 'OBSERVING' "
            "AND c.owner_type = 'SPACE' AND c.owner_key = ? "
            "AND c.audience = 'CURRENT_SPACE' AND c.fact_key != '' "
            "AND confidence >= ? AND confidence < ? AND content != '' "
            f"{id_clause}"
            f"{type_clause}"
            "ORDER BY confidence DESC, c.created_at ASC, c.id ASC",
            (
                group_shared_space,
                str(user_id),
                f"space:{group_shared_space}",
                lower,
                MEMORY_CONFIRM_HIGH_CONFIDENCE,
                *id_params,
                *type_params,
            ),
        ).fetchall()
        for candidate in rows:
            (
                candidate_id, content, memory_type, confidence, owner_type,
                owner_key, audience, fact_key, candidate_conversation,
            ) = candidate
            if candidate_conversation and str(candidate_conversation) != expected_conversation:
                continue
            evidence_rows = conn.execute(
                "SELECT e.id, e.source_row_id, e.source_conversation_key, e.source_digest, "
                "e.fact_subject_key, e.provenance_json "
                "FROM memory_evidence e "
                "JOIN memory_claim_links l ON l.evidence_id = e.id "
                "JOIN memory_claim_links s ON s.owner_key = e.owner_key "
                "AND s.audience = e.audience AND s.entity_type = 'claim_state' "
                "AND s.entity_id = e.fact_key AND s.claim_key = e.fact_key "
                "AND s.projection_slot = 'eligibility' AND s.status = 'active' "
                "WHERE e.candidate_id = ? AND e.owner_key = ? AND e.audience = ? "
                "AND e.fact_key = ? AND e.fact_subject_key = ? "
                "AND e.verification_status = 'accepted' "
                "AND l.entity_type = 'memory_candidate' AND l.entity_id = ? "
                "AND l.claim_key = e.fact_key AND l.projection_slot = 'candidate' "
                "AND l.status = 'active' ORDER BY e.id",
                (
                    str(candidate_id), str(owner_key), str(audience), str(fact_key),
                    f"qq:{user_id}", str(candidate_id),
                ),
            ).fetchall()
            if not evidence_rows:
                continue
            valid_evidence = []
            for evidence in evidence_rows:
                evidence_id, source_row_id, source_conversation, digest, subject, raw = evidence
                try:
                    provenance = json.loads(raw or "{}")
                except (TypeError, ValueError):
                    valid_evidence = []
                    break
                snapshot = provenance.get("source_snapshot")
                if not isinstance(snapshot, dict):
                    valid_evidence = []
                    break
                if (
                    provenance.get("assessment_version") != ASSESSMENT_VERSION
                    or provenance.get("verification_status") != "accepted"
                    or provenance.get("claim_key") != fact_key
                    or provenance.get("recording_author_key") != subject
                    or provenance.get("fact_object_key") != subject
                    or provenance.get("exact_support_span") != content
                    or provenance.get("conversation_key") != source_conversation
                    or str(provenance.get("source_id")) != str(source_row_id)
                    or str(snapshot.get("id")) != str(source_row_id)
                    or str(snapshot.get("group_id")) != str(group_id)
                    or str(snapshot.get("user_id")) != str(user_id)
                    or str(snapshot.get("bot_id")) != bot_id
                    or str(snapshot.get("conversation_key")) != expected_conversation
                    or str(source_conversation) != expected_conversation
                    or str(subject) != f"qq:{user_id}"
                    or str(snapshot.get("source_kind") or "").upper() == "BOT_SELF"
                    or not verify_source_snapshot(snapshot, str(digest), conn=conn)
                ):
                    valid_evidence = []
                    break
                valid_evidence.append(
                    (str(evidence_id), int(source_row_id), str(digest))
                )
            if len(valid_evidence) != len(evidence_rows):
                continue
            version_rows = conn.execute(
                "SELECT scope_key, version FROM memory_scope_versions "
                "WHERE scope_key IN (?, 'global')",
                (str(owner_key),),
            ).fetchall()
            scope_versions = {str(key): int(version) for key, version in version_rows}
            scope_versions.setdefault(str(owner_key), 0)
            scope_versions.setdefault("global", 0)
            return _VerifiedCandidate(
                candidate_id=str(candidate_id),
                content=str(content or ""),
                memory_type=str(memory_type or "FACT"),
                confidence=float(confidence or 0.0),
                owner_type=str(owner_type or ""),
                owner_key=str(owner_key or ""),
                audience=str(audience or ""),
                fact_key=str(fact_key or ""),
                fact_subject_key=f"qq:{user_id}",
                source_conversation_key=expected_conversation,
                source_bot_id=bot_id,
                evidence_ids=tuple(item[0] for item in valid_evidence),
                source_row_ids=tuple(item[1] for item in valid_evidence),
                source_digests=tuple(item[2] for item in valid_evidence),
                scope_versions=scope_versions,
            )
        conn.close()
    except sqlite3.Error as e:
        logger.warning(f"⚠️ [ProactiveTarget] 读取候选失败: {e}")
        return None
    finally:
        if "conn" in locals():
            conn.close()
    return None


def _probe(ctx, node_id: str, **kw) -> None:
    """流程观测探针（计划 §6.4 主动@选择）：ctx 缺省或任何异常都不影响选人。

    旁路纪律：选人业务绝不因观测失败改变结果；reason 直接复用 can_at_user
    返回文本（计数与原因，不含昵称/原文）。
    """
    if ctx is None:
        return
    try:
        from core.observability import message_flow

        message_flow.decision(ctx, node_id, **kw)
    except Exception:
        pass


def pick_target(
    group_id: int,
    exclude_user_ids: set[int] | None = None,
    *,
    bot_id: str = "",
    flow_ctx=None,
    instance_key: str = "",
) -> ProactiveTarget | None:
    """挑选本次主动 @ 的对象；无合适目标时返回 None。

    exclude_user_ids 用于排除 Bot 自身等不该被搭话的账号；
    排除名单同时来自调用方传入与 PROACTIVE_AT_EXCLUDE_USERS 配置。

    ``flow_ctx``/``instance_key``：调用方显式传入的观测上下文与实例键
    （计划 §6.2 拒绝 ambient 传播）。资格预检逐项落
    ``proactive.at.preflight``，选择与淘汰原因落 ``proactive.at.select``——
    无候选 = noop 但有原因可查（计划 §6.4）。

    归属分界：候选与已知话题（memory_candidates / memories）按**共享空间**查
    （``resolve_space(group_id)``）；活跃度、配额、冷却（active_users /
    can_at_user / get_state）仍按真实 **QQ 群**——前者是「对人的长期认知」，
    后者是「当下这场对话的状态」。
    """
    if not PROACTIVE_AT_ENABLED:
        _probe(flow_ctx, "proactive.at.preflight", status="blocked",
               reason_code="主动 @ 已关闭", instance_key=instance_key)
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
        _probe(flow_ctx, "proactive.at.preflight", status="skipped",
               reason_code="无活跃用户",
               metrics={"active_within": PROACTIVE_AT_ACTIVE_WITHIN},
               instance_key=instance_key)
        return None

    proactive = get_proactive()
    eligible: list[int] = []
    for uid in actives:
        ok, reason = can_at_user(group_id, uid)
        # 资格逐项落 decision（计划 §6.4）：配额/冷却/未回应退避都有原因
        _probe(flow_ctx, "proactive.at.preflight",
               status="succeeded" if ok else "blocked",
               reason_code=reason,
               metrics={"user_id": uid},
               instance_key=instance_key)
        if ok:
            eligible.append(uid)
        else:
            logger.debug(f"[ProactiveTarget] 跳过用户 {uid}：{reason}")
    if not eligible:
        _probe(flow_ctx, "proactive.at.select", status="skipped",
               reason_code="无通过资格预检的用户",
               metrics={"considered": len(actives)},
               instance_key=instance_key)
        return None

    # 优先级 1：有可验证候选的用户（按 confidence 降序，最接近晋升线的先问）
    # 每人排除上次已经问过的那条候选，否则同一条候选会在每轮都胜出 → 复读
    verify_pool: list[tuple[float, int, _VerifiedCandidate]] = []
    for uid in eligible:
        state = get_state(group_id, uid)
        excluded_candidate_ids: set[str] = set()
        while True:
            found = _fetch_observing_candidate(
                space,
                uid,
                exclude_id=state["last_asked_candidate_id"],
                exclude_ids=excluded_candidate_ids,
                group_id=group_id,
                bot_id=bot_id,
            )
            if not found:
                break
            if proactive.proactive_skip_active(group_id, uid, f"candidate:{found.candidate_id}"):
                # 候选淘汰原因（计划 §6.4：记录被淘汰候选的原因）
                _probe(flow_ctx, "proactive.at.select", status="skipped",
                       reason_code="候选在自然承接冷却中",
                       metrics={"user_id": uid, "candidate_id": found.candidate_id},
                       instance_key=instance_key)
                excluded_candidate_ids.add(found.candidate_id)
                continue
            verify_pool.append((found.confidence, uid, found))
            break
    if verify_pool:
        verify_pool.sort(key=lambda item: item[0], reverse=True)
        _, uid, found = verify_pool[0]
        target = ProactiveTarget(
            user_id=uid,
            candidate_id=found.candidate_id,
            candidate_content=found.content,
            candidate_type=found.memory_type,
            reason=(
                f"验证候选（conf={found.confidence:.2f}，距晋升线 "
                f"{MEMORY_CONFIRM_HIGH_CONFIDENCE}）"
            ),
            owner_type=found.owner_type,
            owner_key=found.owner_key,
            audience=found.audience,
            fact_key=found.fact_key,
            fact_subject_key=found.fact_subject_key,
            source_conversation_key=found.source_conversation_key,
            source_bot_id=found.source_bot_id,
            evidence_ids=found.evidence_ids,
            source_row_ids=found.source_row_ids,
            source_digests=found.source_digests,
            captured_scope_versions=found.scope_versions,
        )
        _probe(flow_ctx, "proactive.at.select", status="succeeded",
               reason_code="选中验证候选",
               metrics={
                   "user_id": uid,
                   "candidate_id": found.candidate_id,
                   "candidate_type": found.memory_type,
                   "confidence": round(found.confidence, 3),
                   "confirm_line": MEMORY_CONFIRM_HIGH_CONFIDENCE,
               },
               summary=target.reason,
               instance_key=instance_key)
        return target

    # 无可验证候选 → 不发言：主动 @ 的配额极其稀缺，只为把候选推过晋升线而花，
    # 不做无记忆锚点的日常话题搭话。
    # 计划 §6.4：无候选 = noop，但淘汰/区间事实必须可查询。
    _probe(flow_ctx, "proactive.at.select", status="skipped",
           reason_code="无可验证的 OBSERVING 候选",
           metrics={
               "eligible": len(eligible),
               "conf_floor": round(max(0.0, MEMORY_OBSERVE_LOW_CONFIDENCE - 0.2), 3),
               "conf_ceiling": MEMORY_CONFIRM_HIGH_CONFIDENCE,
           },
           instance_key=instance_key)
    return None
