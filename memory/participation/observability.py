# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""评分日志（实现方案 §3 补充要求 A，上游工程方案 §29）。

每次评分落三处：
1. loguru 实时一行摘要（📊 [参与评分]）；
2. logs/participation_decisions.jsonl（结构化，GUI/脚本消费）；
3. logs/participation_logs.md（人类可读分项表，直接翻阅调参）。

另有 participation_log 表落库（DB 写入由 manager 负责，本模块只管文件与日志）。

级别：full=每次评分都记 / summary=只记 CANDIDATE 以上 / off=只记 ALLOW_LLM。
ALLOW_LLM 级别**永远强制记录**——触发不可追溯就没法调参。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nonebot import logger

from memory.participation.decision import (
    ALLOW_LLM,
    CANDIDATE,
    OBSERVE,
    ParticipationDecision,
)
from memory.participation.state import ConversationState

LOG_FULL = "full"
LOG_SUMMARY = "summary"
LOG_OFF = "off"


def _level_rank(level: str) -> int:
    return {"IGNORE": 0, "OBSERVE": 1, "CANDIDATE": 2, "ALLOW_LLM": 3}.get(level, 0)


def should_record(level: str, configured: str) -> bool:
    """是否需要记录（ALLOW_LLM 恒真）。"""
    if level == ALLOW_LLM:
        return True
    if configured == LOG_FULL:
        return True
    if configured == LOG_SUMMARY:
        return _level_rank(level) >= _level_rank(CANDIDATE)
    return False


def _ensure_parent(path: Path) -> None:
    # LOG_DIR 可能指向不存在的目录（见 settings.py 对 THOUGHT_LOG_PATH 的说明）
    path.parent.mkdir(parents=True, exist_ok=True)


def log_decision(
    decision: ParticipationDecision,
    state: ConversationState,
    *,
    jsonl_path: Path,
    md_path: Path,
    configured_level: str = LOG_FULL,
    event: str = "decision",
    event_reason: str = "",
) -> None:
    """输出一次评分的全部日志。文件 IO 失败只告警，绝不影响决策链路。"""
    level = decision.level
    bd = decision.breakdown
    ts = datetime.now()

    if should_record(level, configured_level):
        # 1) loguru 实时摘要
        parts = []
        if bd is not None:
            deltas = []
            for name, value in (
                ("相关性", bd.relevance),
                ("机会", bd.opportunity),
                ("社交", bd.social_opportunity),
                ("参与", bd.topic_involvement),
                ("沉默", bd.silence_bonus),
                ("近期发言-", bd.recent_speech_penalty),
                ("速度-", bd.velocity_penalty),
                ("重复-", bd.repetition_penalty),
                ("过期-", bd.expired_penalty),
            ):
                if abs(value) >= 0.05:
                    deltas.append(f"{name}{value:.0f}")
            parts.append(" ".join(deltas))
        logger.info(
            f"📊 [参与评分] 群 {decision.group_id} topic={decision.topic_id} "
            f"event={event} score={decision.score:.0f} → {level} mode={decision.mode} "
            f"({'; '.join(parts) or '无显著加减分'})"
        )

        # 2) JSONL
        record = {
            "ts": ts.isoformat(timespec="seconds"),
            "group_id": decision.group_id,
            "topic_id": decision.topic_id,
            "trigger_msg_id": decision.trigger_msg_id,
            **(bd.as_dict() if bd else {}),
            "mode": decision.mode,
            "decision": level,
            "event": event,
            "event_reason": event_reason,
            "should_speak": decision.should_speak,
            "confidence": round(decision.confidence, 2),
            "reason_flags": decision.reason_flags,
            "snapshot": {
                "participants": sorted(state.topic.participants)[:10] if state.topic else [],
                "velocity": bd.velocity_count if bd else 0,
            },
        }
        try:
            _ensure_parent(jsonl_path)
            with jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:  # pragma: no cover - 日志失败不影响主链路
            logger.warning(f"⚠️ [参与评分] JSONL 写入失败: {e}")

        # 3) Markdown（按天分节的分项表，上游 §29 示例格式）
        try:
            _ensure_parent(md_path)
            lines = [
                f"## {ts.strftime('%Y-%m-%d %H:%M:%S')} 群 {decision.group_id}",
                f"- Topic: {decision.topic_id}（{bd.topic_status if bd else '?'}）"
                f" 速度: {bd.velocity_level if bd else '?'}({bd.velocity_count if bd else 0})",
            ]
            if bd is not None:
                lines += [
                    f"- Relevance: {bd.relevance:.0f}　Opportunity: {bd.opportunity:.0f}"
                    f"　SocialOpportunity: {bd.social_opportunity:.0f}"
                    f"　TopicInvolvement: {bd.topic_involvement:.0f}"
                    f"　SilenceBonus: {bd.silence_bonus:.0f}",
                    f"- RecentSpeechPenalty: {bd.recent_speech_penalty:.0f}"
                    f"　VelocityPenalty: {bd.velocity_penalty:.0f}"
                    f"　RepetitionPenalty: {bd.repetition_penalty:.0f}"
                    f"　ExpiredPenalty: {bd.expired_penalty:.0f}",
                ]
            lines += [
                f"- Score: {decision.score:.0f}　Decision: {level}　"
                f"Event: {event}　Mode: {decision.mode}",
                f"- Event reason: {event_reason or '无'}",
                f"- Flags: {', '.join(decision.reason_flags) or '无'}",
                "",
            ]
            with md_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except Exception as e:  # pragma: no cover
            logger.warning(f"⚠️ [参与评分] Markdown 写入失败: {e}")

    elif level == OBSERVE and configured_level == LOG_OFF:
        # off 档下 OBSERVE 不记文件，但 debug 级留一条线索
        logger.debug(f"[参与评分] 群 {decision.group_id} score={decision.score:.0f} → {level}")


def record_to_db(
    decision: ParticipationDecision,
    group_id: int,
    conn=None,
) -> None:
    """把决策写入 participation_log 表（由 manager 提供 conn；失败静默）。"""
    try:
        import sqlite3

        bd = decision.breakdown
        owned = conn is None
        db = conn if conn is not None else sqlite3.connect(_db_path())
        with db:
            db.execute(
                "INSERT INTO participation_log (ts, group_id, topic_id, relevance, opportunity,"
                " social_opportunity, topic_involvement, silence_bonus, recent_speech_penalty,"
                " velocity_penalty, repetition_penalty, expired_penalty, final_score,"
                " mode, decision, reason_flags)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    str(group_id),
                    decision.topic_id,
                    bd.relevance if bd else 0,
                    bd.opportunity if bd else 0,
                    bd.social_opportunity if bd else 0,
                    bd.topic_involvement if bd else 0,
                    bd.silence_bonus if bd else 0,
                    bd.recent_speech_penalty if bd else 0,
                    bd.velocity_penalty if bd else 0,
                    bd.repetition_penalty if bd else 0,
                    bd.expired_penalty if bd else 0,
                    decision.score,
                    decision.mode,
                    decision.level,
                    ",".join(decision.reason_flags),
                ),
            )
        if owned:
            db.close()
    except Exception as e:  # pragma: no cover - 落库失败不影响决策
        logger.debug(f"[参与评分] participation_log 写入失败（跳过）: {e}")


def _db_path() -> Path:
    from config import DB_PATH

    return Path(DB_PATH)
