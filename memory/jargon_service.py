# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""群黑话服务：证据化候选、词义版本与本地匹配（计划 §6.4）。

核心原则：

- **「词形出现次数」与「词义确认」分离**：occurrence 证据只说明「这个词
  在本群被用过」（按 event_id 幂等——重复转发/同一消息不增加独立证据）；
  词义（definition）必须人工确认才升 active，自动提取永不直接生效；
- **同词异群分别维护**：资产按 ``(platform, bot_id, group_id)`` 隔离，
  legacy_unscoped（group_id=''）永不注入；
- **语义冲突新增 sense，不覆盖旧义**：同一词的每个词义是一行独立资产
  （sense 编号区分），旧 evidence 与旧 turn 快照仍可重现；
- 匹配是纯本地子串查找，最多返回 3 条；多义语境无法消歧时标注
  「本群有 N 种可能含义」，绝不冒充通用知识。

模型候选不是可信事实：后台批量提取（每批 ≤8 候选）属可选增强，当前
版本只有规则提取与人工确认两个入口。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from config import JARGON_CONFIRM_THRESHOLD
from core.social.contracts import ConversationScope
from memory import social_store
from memory.timeutil import log_sqlite_error

MAX_MATCHED_TERMS = 3

# 可注入状态白名单：candidate（无定义/未确认）与 disabled/quarantined 永不注入
_INJECTABLE_STATUSES = ("active",)


def normalize_term(term: str) -> str:
    """词形归一：去空白 + 小写（拉丁词）；中文不受影响。"""
    return (term or "").strip().lower()


def _connect() -> sqlite3.Connection:
    from config import settings

    return sqlite3.connect(settings.DB_PATH, timeout=10.0)


def get_or_create_asset(scope: ConversationScope, term: str) -> str | None:
    """取（或建）一个词的主资产行（sense=''，candidate）。"""
    term = normalize_term(term)
    if not term or len(term) > 32:
        return None
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT asset_id FROM social_assets WHERE kind='jargon' AND platform=? "
                "AND bot_id=? AND group_id=? AND term=? AND sense=''",
                (*scope.row(), term),
            ).fetchone()
            if row:
                return row[0]
            asset_id = uuid.uuid4().hex
            from core.social.contracts import utc_now_iso

            conn.execute(
                "INSERT INTO social_assets (asset_id, kind, platform, bot_id, group_id, "
                "content, term, sense, status, confidence, meta_json, created_at_utc, "
                "updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (asset_id, "jargon", *scope.row(), term, term, "", "candidate", 0.0,
                 "{}", utc_now_iso(), utc_now_iso()),
            )
            conn.commit()
            return asset_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.get_or_create_asset", e)
        return None


def note_occurrence(
    scope: ConversationScope,
    term: str,
    *,
    event_id: str,
    author_user: str = "",
    excerpt: str = "",
) -> bool:
    """记录一次词形出现（occurrence 证据）。同一 event_id 重复出现是 no-op。"""
    term = normalize_term(term)
    if not term or not event_id:
        return False
    asset_id = get_or_create_asset(scope, term)
    if asset_id is None:
        return False
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            from core.social.contracts import content_hash, utc_now_iso

            conn.execute(
                "INSERT OR IGNORE INTO social_asset_evidence (asset_id, event_id, "
                "evidence_kind, excerpt, content_hash, author_user, observed_at_utc) "
                "VALUES (?,?,?,?,?,?,?)",
                (asset_id, event_id, "occurrence", (excerpt or "")[:200],
                 content_hash(excerpt or ""), author_user or "", utc_now_iso()),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.note_occurrence", e)
        return False


def evidence_stats(asset_id: str) -> dict[str, int]:
    """一个资产的证据统计（独立事件数 / 独立作者数——跨重启可复现）。"""
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            events, authors = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT author_user) FROM social_asset_evidence "
                "WHERE asset_id = ? AND evidence_kind = 'occurrence'",
                (asset_id,),
            ).fetchone()
            return {"events": int(events or 0), "authors": int(authors or 0)}
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.evidence_stats", e)
        return {"events": 0, "authors": 0}


# ============================================================
# 词义管理（人工确认是唯一升级通道）
# ============================================================


def add_sense(
    scope: ConversationScope,
    term: str,
    definition: str,
    *,
    situation: str = "",
    positive_example: str = "",
    negative_example: str = "",
    source_event_id: str | None = None,
    origin: str = "manual",
) -> str | None:
    """为词新增一个词义行。同文重复返回既有行；语义冲突新增不覆盖。

    返回该词义行的 asset_id。定义空串直接拒绝（「没有定义」不是词义）。
    """
    term = normalize_term(term)
    definition = (definition or "").strip()
    if not term or not definition:
        return None
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT asset_id, definition FROM social_assets WHERE kind='jargon' "
                "AND platform=? AND bot_id=? AND group_id=? AND term=? "
                "AND sense != '' ORDER BY sense",
                (*scope.row(), term),
            ).fetchall()
            for asset_id, old_def in existing:
                if (old_def or "").strip() == definition:
                    return asset_id  # 同文：幂等返回，不建新行
            # 主资产行（词形容器）必须存在，证据才有归属
            head = get_or_create_asset(scope, term)
            if head is None:
                return None
            sense_id = f"s{len(existing) + 1}"
            from core.social.contracts import utc_now_iso

            asset_id = uuid.uuid4().hex
            # social_assets 无独立反例列：正/反例折进 style 与 meta_json
            conn.execute(
                "INSERT INTO social_assets (asset_id, kind, platform, bot_id, group_id, "
                "content, term, sense, definition, situation, style, status, confidence, "
                "meta_json, created_at_utc, updated_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, "jargon", *scope.row(), term, term, sense_id, definition,
                 situation, positive_example, "candidate", 0.0,
                 json.dumps({"origin": origin, "negative_example": negative_example},
                            ensure_ascii=False),
                 utc_now_iso(), utc_now_iso()),
            )
            if source_event_id:
                from core.social.contracts import content_hash

                conn.execute(
                    "INSERT OR IGNORE INTO social_asset_evidence (asset_id, event_id, "
                    "evidence_kind, excerpt, content_hash, author_user, observed_at_utc) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (asset_id, source_event_id, "definition", definition[:200],
                     content_hash(definition), "unknown", utc_now_iso()),
                )
            conn.commit()
            return asset_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.add_sense", e)
        return None


def set_sense_status(asset_id: str, status: str) -> bool:
    """人工启停：candidate / active / quarantined / disabled。

    人工关闭立即生效（matcher 只查库、无进程内缓存），自动负反馈走
    quarantine 保留证据，不永久删除（计划 §6.3 状态机同款）。
    """
    if status not in ("candidate", "active", "quarantined", "disabled"):
        return False
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            from core.social.contracts import utc_now_iso

            cur = conn.execute(
                "UPDATE social_assets SET status = ?, updated_at_utc = ? WHERE asset_id = ?",
                (status, utc_now_iso(), asset_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.set_sense_status", e)
        return False


def list_terms(scope: ConversationScope, status: str | None = None) -> list[dict[str, Any]]:
    """管理视图：某群的黑话词条与词义（含无定义的主资产行）。"""
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            sql = (
                "SELECT asset_id, term, sense, definition, situation, status, confidence, "
                "updated_at_utc FROM social_assets WHERE kind='jargon' AND platform=? "
                "AND bot_id=? AND group_id=?"
            )
            params: list[Any] = [*scope.row()]
            if status:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY term, sense"
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "asset_id": r[0], "term": r[1], "sense": r[2], "definition": r[3],
                    "situation": r[4], "status": r[5], "confidence": r[6],
                    "updated_at_utc": r[7],
                }
                for r in rows
            ]
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.list_terms", e)
        return []


# ============================================================
# 本地匹配（理解用；「模仿使用」是另一个独立开关）
# ============================================================


def match_jargon(
    scope: ConversationScope, text: str, *, limit: int = MAX_MATCHED_TERMS
) -> list[dict[str, Any]]:
    """在文本中匹配本群黑话，返回带定义与可信度的解释条目。

    - 只匹配本群 scope 的词条（同词异群不串义；legacy_unscoped 永不出现）；
    - 只有 status=active 的词义参与匹配（candidate 没有可信定义）；
    - 一词多义：条目标注 ambiguous，列出全部可能含义，由模型自行判断
      或省略——绝不替群选一个「正确」义；
    - confidence 由 occurrence 证据量折算（JARGON_CONFIRM_THRESHOLD 归一），
      是「群内使用广度」的度量，不是词义正确性。
    """
    text = text or ""
    if not text.strip():
        return []
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT asset_id, term, sense, definition, situation, style, status, "
                "confidence FROM social_assets WHERE kind='jargon' AND platform=? "
                "AND bot_id=? AND group_id=? AND sense != '' AND definition != '' "
                "ORDER BY term, sense",
                (*scope.row(),),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service.match_jargon", e)
        return []

    by_term: dict[str, list[dict[str, Any]]] = {}
    for asset_id, term, sense, definition, situation, style, status, _confidence in rows:
        if status not in _INJECTABLE_STATUSES:
            continue
        if term and term in text:
            by_term.setdefault(term, []).append({
                "asset_id": asset_id, "term": term, "sense": sense or "default",
                "definition": definition, "situation": situation or "",
                "positive_example": style or "",
            })
    out: list[dict[str, Any]] = []
    for term, senses in by_term.items():
        if not senses:
            continue
        head = _head_stats(term, scope)
        confidence = min(1.0, head / max(1, int(JARGON_CONFIRM_THRESHOLD)))
        if len(senses) == 1:
            s = senses[0]
            out.append({**s, "ambiguous": False, "confidence": confidence})
        else:
            out.append({
                "term": term, "ambiguous": True, "confidence": confidence,
                "senses": [s["definition"] for s in senses],
                "asset_ids": [s["asset_id"] for s in senses],
            })
        if len(out) >= limit:
            break
    return out


def _head_stats(term: str, scope: ConversationScope) -> int:
    """主资产行的 occurrence 证据数（词形在群内的使用广度）。"""
    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT a.asset_id FROM social_assets a WHERE a.kind='jargon' "
                "AND a.platform=? AND a.bot_id=? AND a.group_id=? AND a.term=? AND a.sense=''",
                (*scope.row(), term),
            ).fetchone()
            if not row:
                return 0
            n = conn.execute(
                "SELECT COUNT(*) FROM social_asset_evidence WHERE asset_id=? "
                "AND evidence_kind='occurrence'",
                (row[0],),
            ).fetchone()
            return int(n[0]) if n else 0
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("jargon_service._head_stats", e)
        return 0
