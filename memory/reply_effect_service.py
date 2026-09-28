# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""回复效果服务：观察窗口、归因、评估与幂等结算（计划 §6.6）。

三件事严格分离（attribution / evaluation / adaptation）：

1. **观察**：确认送达（ACK）后开一行 ``social_effects``（status=observing），
   窗口 deadline 持久化为 UTC——monotonic 只用于进程内耗时，绝不入库；
2. **归因**：窗口关闭后从 ``social_events`` 取后续人类消息，按计划 §6.6
   优先级归因（direct / probable / weak / ambiguous）；一条群反馈被另一个
   effect 抢走 direct/probable 后不得重复计正向人数；
3. **结算**：job lease + 事务 CAS——``UPDATE ... WHERE status='observing'``
   命中才允许写证据与聚合贡献，同一事务内完成；定时任务与重启 sweep 共用
   :func:`resolve_effect`，重评按 ``evaluation_version`` 撤旧写新。

「无回应」记录 no_observed_response，**不是负反馈**；缺数据记录
insufficient。首版纯规则、零 LLM；可选后台 judge 属后续阶段。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from nonebot import logger

from config import REPLY_EFFECT_WINDOW_SECONDS
from core.social.contracts import (
    ConversationScope,
    parse_utc,
    utc_now_iso,
)
from memory import social_store
from memory.timeutil import log_sqlite_error, utc_now

# 规则评估版本：分类/归因逻辑变更时 +1，旧 aggregate 贡献按版本撤回
RULE_VERSION = "social-effects-r1"

# 观察窗口硬上限与事件条数上限（计划 §6.6 [assumed] 初值）
HARD_WINDOW_CAP_SECONDS = 180.0
MAX_FOLLOW_UP_EVENTS = 50

# 明确「停止/拒绝打扰」信号：规则层直接处理，不等任何后台判定
_REJECTION_MARKERS = ("别说了", "闭嘴", "安静", "别吵", "烦不烦", "住口", "别@我", "别@")
_CORRECTION_MARKERS = (
    "不对", "不是这样", "你说错", "说错了", "记错", "记错了", "胡说", "乱说", "搞错", "别瞎说",
)
_EMOJI_RE_RAW = r"[\U0001F300-\U0001FAFF\u2600-\u27BF]"

# 归因置信度（规则版初值；judge 介入后由评估版本区分）
_CONFIDENCE = {"direct": 0.95, "probable": 0.6, "weak": 0.35, "ambiguous": 0.1}

# 进入统计的归因档位（ambiguous 只存证，不计效果）
_COUNTED_ATTRIBUTIONS = ("direct", "probable", "weak")


# ============================================================
# 观察：开效果行（ACK 之后由学习入口调用）
# ============================================================


def social_effects_enabled() -> bool:
    """社交效果观察是否接管结算（接管后旧 reply_effects 路径停写，防双学习）。"""
    try:
        from config import settings

        return bool(settings.SOCIAL_ENABLED) and settings.SOCIAL_MODE in ("shadow", "active")
    except Exception:
        return False


def open_effect(
    *,
    group_id: int,
    user_id: int | str,
    trigger: str,
    turn_id: str,
    trace_id: str = "",
    intent: str = "",
) -> str | None:
    """按本轮已确认的投递回执开一行观察效果 + 一个延迟结算作业。

    target_user_id 语义（计划 §6.6）：user_id=0（主动群聊）→ NULL＝全群目标，
    收集全群后续人类事件；主动 @ 与普通回复保留目标用户。
    返回 effect_id；无已确认投递/落库失败返回 None（调用方记日志继续）。
    """
    try:
        social_store.ensure_tables()
        from config import settings

        scope = ConversationScope.for_qq(group_id)
        deliveries = social_store.deliveries_for_turn(turn_id)
        acked = [d for d in deliveries if d["status"] == "acknowledged" and d["acknowledged_at_utc"]]
        if not acked:
            return None
        first_ack = min(d["acknowledged_at_utc"] for d in acked)
        last_ack = max(d["acknowledged_at_utc"] for d in acked)
        window_end = _window_end(first_ack, last_ack)
        effect_id = uuid.uuid4().hex
        conn = sqlite3.connect(settings.DB_PATH, timeout=10.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO social_effects (effect_id, turn_id, trace_id, platform, bot_id, "
                "group_id, target_user_id, trigger, intent, first_ack_at_utc, last_ack_at_utc, "
                "window_end_utc, status, observation, rule_version, assessable, meta_json, "
                "created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    effect_id, turn_id, trace_id, scope.platform, scope.bot_id,
                    scope.group_id, str(user_id) if str(user_id) not in ("", "0") else None,
                    trigger, intent, first_ack, last_ack, window_end,
                    "observing", "", RULE_VERSION, 1,
                    json.dumps({"delivered_parts": len(acked)}, ensure_ascii=False),
                    utc_now_iso(),
                ),
            )
            from memory.social_worker import enqueue_job

            enqueue_job(
                "resolve_effect",
                dedupe_key=f"resolve:{effect_id}",
                payload_refs={"effect_id": effect_id},
                not_before_utc=window_end,
                conn=conn,
            )
            conn.execute("COMMIT")
            return effect_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("reply_effect_service.open_effect", e)
        return None


def _window_end(first_ack_iso: str, last_ack_iso: str) -> str:
    """末个 ACK + 观察窗口，与首个 ACK + 硬上限取小（计划 §6.6）。"""
    first_dt = parse_utc(first_ack_iso) or utc_now()
    last_dt = parse_utc(last_ack_iso) or first_dt
    planned = last_dt + timedelta(seconds=float(REPLY_EFFECT_WINDOW_SECONDS))
    capped = first_dt + timedelta(seconds=HARD_WINDOW_CAP_SECONDS)
    return min(planned, capped).isoformat(timespec="milliseconds")


# ============================================================
# 归因
# ============================================================


def attribute_events(
    follow_ups: list[dict[str, Any]],
    *,
    acked_platform_ids: set[str],
    target_user_id: str | None,
) -> list[dict[str, Any]]:
    """给每条 follow-up 一个归因档位（计划 §6.6 优先级，纯函数）。

    1. 引用已发平台 message ID → direct（强证据）；
    2. @bot（source_kind=AT_MENTION，静默监听器落库时即 is_tome）→ probable；
    3. 同一目标用户紧邻（窗口内该用户的第一条，且之前没有其他人的消息）→ weak；
    4. 其余 → ambiguous（保存但不直接计效果）。

    「不把发送后的下一句话自动归属本轮」：weak 只属于目标用户本人，且
    前面没有其他竞争发言。
    """
    out: list[dict[str, Any]] = []
    first_other_user_seen = False
    for ev in follow_ups:
        attribution, reason = "ambiguous", ""
        reply_to = ev.get("reply_to_id")
        if reply_to and str(reply_to) in acked_platform_ids:
            attribution, reason = "direct", "quotes_delivered_segment"
        elif reply_to:
            # 明确引用了别人（或别轮）的消息：不许再被弱归因到本轮
            attribution, reason = "ambiguous", "quotes_other_message"
        elif ev.get("source_kind") == "AT_MENTION":
            attribution, reason = "probable", "to_bot_after_ack"
        elif (
            target_user_id
            and str(ev.get("user_id") or "") == str(target_user_id)
            and not first_other_user_seen
        ):
            attribution, reason = "weak", "target_user_first_follow_up"
        if ev.get("user_id") and ev.get("user_id") != target_user_id:
            first_other_user_seen = True
        out.append({**ev, "attribution": attribution, "polysemy_reason": reason})
    return out


def _claim_conflicts(evidence_rows: list[dict[str, Any]], effect_id: str, conn) -> None:
    """同一条明确群反馈只归一个 effect（计划 §6.6）。

    事件已被**其他** effect 以 direct/probable 认领时，本 effect 降为
    ambiguous——降级在结算事务内完成，保证统计一致。
    """
    for row in evidence_rows:
        if row["attribution"] not in ("direct", "probable"):
            continue
        claimed = conn.execute(
            "SELECT effect_id FROM social_effect_evidence WHERE event_id = ? "
            "AND effect_id != ? AND attribution IN ('direct','probable') LIMIT 1",
            (row["event_id"], effect_id),
        ).fetchone()
        if claimed:
            row["attribution"] = "ambiguous"
            row["polysemy_reason"] = f"claimed_by_effect:{claimed[0]}"


# ============================================================
# 分类（分维度，纯规则）
# ============================================================


def classify_dimensions(events: list[dict[str, Any]], *, capped: bool) -> dict[str, Any]:
    """把归因后的窗口消息折算成计划 §6.6 的分维度结果（纯函数）。"""
    counted = [e for e in events if e["attribution"] in _COUNTED_ATTRIBUTIONS]
    joined = " ".join(str(e.get("text_excerpt") or "") for e in counted)
    import re as _re

    has_emoji = bool(_re.search(_EMOJI_RE_RAW, joined))
    corrected = any(m in joined for m in _CORRECTION_MARKERS)
    rejected = any(m in joined for m in _REJECTION_MARKERS)
    distinct_users = {str(e.get("user_id") or "") for e in counted if e.get("user_id")}

    if not counted:
        observation = "capped" if capped else "insufficient"
    else:
        observation = "capped" if capped else "complete"
    reception = (
        "refused" if rejected
        else "corrected" if corrected
        else "neutral" if counted
        else "uncertain"
    )
    return {
        "engagement": {
            "responded_events": len(counted),
            "responded_users": len(distinct_users),
            "conversation_advanced": len(counted) > 0,
        },
        "reception": reception,
        # 有帮助与否不允许由字数/表情自动判定（计划 §6.6 红线）——留给 judge
        "usefulness": "not_evaluable",
        "expression_fit": "unknown",
        "observation": observation,
        "confidence": max((_CONFIDENCE[e["attribution"]] for e in counted), default=0.0),
        "has_emoji": has_emoji,
    }


# ============================================================
# 结算（事务 CAS；定时与 sweep 共用）
# ============================================================


def _load_effect(effect_id: str) -> dict[str, Any] | None:
    from config import settings

    conn = sqlite3.connect(settings.DB_PATH, timeout=10.0)
    try:
        row = conn.execute(
            "SELECT effect_id, turn_id, trace_id, platform, bot_id, group_id, "
            "target_user_id, trigger, intent, first_ack_at_utc, last_ack_at_utc, "
            "window_end_utc, status, rule_version, evaluation_version, meta_json "
            "FROM social_effects WHERE effect_id = ?",
            (effect_id,),
        ).fetchone()
        if not row:
            return None
        keys = (
            "effect_id", "turn_id", "trace_id", "platform", "bot_id", "group_id",
            "target_user_id", "trigger", "intent", "first_ack_at_utc", "last_ack_at_utc",
            "window_end_utc", "status", "rule_version", "evaluation_version", "meta_json",
        )
        return dict(zip(keys, row, strict=True))
    finally:
        conn.close()


def resolve_effect(effect_id: str, *, evaluation_version: str = RULE_VERSION) -> str:
    """结算一行效果：窗口归因 → 事务 CAS → 证据 + 聚合贡献同事务写入。

    幂等：同版本重入直接返回（不重复累加）；版本不同（重评）先在同一事务
    撤回旧版本贡献再写新贡献（计划 §6.2/§6.6）。返回最终状态文本。
    """
    try:
        row = _load_effect(effect_id)
        if row is None:
            return "missing"
        if row["status"] == "legacy_unverifiable":
            return "legacy_unverifiable"
        from config import settings

        scope = ConversationScope(row["platform"], row["bot_id"], row["group_id"])
        first_ack = row["first_ack_at_utc"] or ""
        window_end = row["window_end_utc"]
        follow_ups: list[dict[str, Any]] = []
        capped = False
        if window_end:
            follow_ups = social_store.events_since(
                scope,
                since_utc=first_ack,
                until_utc=window_end,
                exclude_source_kinds=("BOT_SELF", "LEGACY"),
                limit=MAX_FOLLOW_UP_EVENTS + 1,
            )
            if len(follow_ups) > MAX_FOLLOW_UP_EVENTS:
                follow_ups = follow_ups[:MAX_FOLLOW_UP_EVENTS]
                capped = True
        acked_ids = {
            str(d["platform_message_id"])
            for d in social_store.deliveries_for_turn(row["turn_id"])
            if d["status"] == "acknowledged" and d["platform_message_id"]
        }
        attributed = attribute_events(
            follow_ups, acked_platform_ids=acked_ids, target_user_id=row["target_user_id"]
        )
        dims = classify_dimensions(attributed, capped=capped)
        if not attributed:
            dims["observation"] = "complete" if not capped else "capped"

        now = utc_now_iso()
        conn = sqlite3.connect(settings.DB_PATH, timeout=10.0)
        try:
            conn.execute("BEGIN IMMEDIATE")
            # CAS 之一：首结算（observing → resolved）
            cur = conn.execute(
                "UPDATE social_effects SET status = 'resolved', resolved_at_utc = ?, "
                "observation = ?, evaluation_version = ? "
                "WHERE effect_id = ? AND status = 'observing'",
                (now, dims["observation"], evaluation_version, effect_id),
            )
            if cur.rowcount == 1:
                settlement_path = "fresh"
            else:
                # CAS 之二：重评（已 resolved 且版本不同 → 原子切换版本）
                cur = conn.execute(
                    "UPDATE social_effects SET observation = ?, evaluation_version = ? "
                    "WHERE effect_id = ? AND status = 'resolved' "
                    "AND evaluation_version != ?",
                    (dims["observation"], evaluation_version, effect_id, evaluation_version),
                )
                settlement_path = "reeval" if cur.rowcount == 1 else None
            if settlement_path is None:
                existing = conn.execute(
                    "SELECT evaluation_version FROM social_effects WHERE effect_id = ?",
                    (effect_id,),
                ).fetchone()
                conn.execute("ROLLBACK")
                if existing and existing[0] == evaluation_version:
                    return "already_resolved"
                return "state_conflict"
            # 重评：撤回旧版本贡献（同事务）
            conn.execute(
                "DELETE FROM social_aggregate_events WHERE effect_id = ? "
                "AND evaluation_version != ?",
                (effect_id, evaluation_version),
            )
            evidence_rows = [
                {
                    "event_id": e["event_id"],
                    "attribution": e["attribution"],
                    "confidence": _CONFIDENCE[e["attribution"]],
                    "classification": str(e.get("source_kind") or ""),
                    "polysemy_reason": e.get("polysemy_reason") or "",
                }
                for e in attributed
            ]
            _claim_conflicts(evidence_rows, effect_id, conn)
            for er in evidence_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO social_effect_evidence (effect_id, event_id, "
                    "attribution, confidence, classification, polysemy_reason, created_at_utc) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (effect_id, er["event_id"], er["attribution"], er["confidence"],
                     er["classification"], er["polysemy_reason"], now),
                )
            for metric, delta in _aggregate_metrics(dims).items():
                conn.execute(
                    "INSERT OR IGNORE INTO social_aggregate_events (aggregate_id, effect_id, "
                    "evaluation_version, metric, delta, scope_user, created_at_utc) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (uuid.uuid4().hex, effect_id, evaluation_version, metric, delta,
                     row["target_user_id"] or "", now),
                )
            conn.execute(
                "UPDATE social_effects SET meta_json = ? WHERE effect_id = ?",
                (json.dumps(dims, ensure_ascii=False), effect_id),
            )
            conn.execute("COMMIT")
            return "resolved"
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("reply_effect_service.resolve_effect", e)
        return "error"


def _aggregate_metrics(dims: dict[str, Any]) -> dict[str, float]:
    """分维度 → 聚合贡献键值（一次结算只计一次，键固定）。"""
    engagement = dims.get("engagement", {})
    metrics = {
        "engagement_responded_events": float(engagement.get("responded_events", 0)),
        "engagement_responded_users": float(engagement.get("responded_users", 0)),
        "no_observed_response": 0.0,
    }
    if not engagement.get("responded_events"):
        # 明确记录「没观察到回应」——它不是负反馈，只是空事实
        metrics["no_observed_response"] = 1.0
    if dims.get("reception") == "corrected":
        metrics["reception_corrected"] = 1.0
    if dims.get("reception") == "refused":
        metrics["reception_refused"] = 1.0
    return metrics


def get_effect_summary(effect_id: str) -> dict[str, Any] | None:
    """给 WebUI / 调试用的单行摘要（含证据计数）。"""
    row = _load_effect(effect_id)
    if row is None:
        return None
    try:
        from config import settings

        conn = sqlite3.connect(settings.DB_PATH, timeout=10.0)
        try:
            evidence_n = conn.execute(
                "SELECT COUNT(*) FROM social_effect_evidence WHERE effect_id = ?",
                (effect_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        row["evidence_count"] = evidence_n
        row["meta_json"] = json.loads(row.get("meta_json") or "{}")
        return row
    except sqlite3.Error as e:
        log_sqlite_error("reply_effect_service.get_effect_summary", e)
        return row


def sweep_due_effects(now_iso: str | None = None) -> int:
    """补偿：observing 且窗口已过、但没有在途/待执行作业的行，补一个结算作业。

    重启会丢在途延迟任务，持久作业表是唯一事实来源；本函数只补作业、
    不直接结算（结算统一走 worker → resolve_effect，计划 §6.6）。
    """
    try:
        from config import settings

        now = now_iso or utc_now_iso()
        social_store.ensure_tables()
        conn = sqlite3.connect(settings.DB_PATH, timeout=10.0)
        try:
            rows = conn.execute(
                "SELECT e.effect_id FROM social_effects e WHERE e.status = 'observing' "
                "AND e.window_end_utc IS NOT NULL AND e.window_end_utc <= ? "
                "AND NOT EXISTS (SELECT 1 FROM social_jobs j WHERE j.dedupe_key = "
                "('resolve:' || e.effect_id) AND j.status IN ('pending','running'))",
                (now,),
            ).fetchall()
            conn.execute("BEGIN IMMEDIATE")
            from memory.social_worker import enqueue_job

            count = 0
            for (effect_id,) in rows:
                if enqueue_job("resolve_effect", dedupe_key=f"resolve:{effect_id}",
                               payload_refs={"effect_id": effect_id}, conn=conn):
                    count += 1
            conn.execute("COMMIT")
            return count
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("reply_effect_service.sweep_due_effects", e)
        return 0


def log_settlement(effect_id: str, status: str) -> None:
    if status == "resolved":
        logger.debug(f"[Social] 效果已结算 effect={effect_id}")
    elif status != "already_resolved":
        logger.debug(f"[Social] 效果结算未落账 effect={effect_id} status={status}")
