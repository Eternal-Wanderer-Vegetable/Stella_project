# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""表达学习：从候选到实际使用的闭环（计划 §6.3）。

状态机：``candidate → active → quarantined/disabled``。

- **自动提取永不直接升 active**（人格保护红线）：证据（独立事件数、独立
  作者、跨日期）攒够只是把资产标记为「可人工确认」（meta.promotable），
  激活仍需管理动作；这确保自动通道永远不会复读某个人或污染人格；
- 本地选择器只注入 active 资产，每轮最多 2 条；无合适材料返回空——
  表达是可选风格参考，不是「必须使用」的指令；
- 最近 N 次本群回复已用过的同表达默认不再注入（可配置，防复读）；
  使用量从 social_asset_usage × social_deliveries 联查，重启不失忆；
- 排序用平滑置信（证据量与作者多样性折算），效果数据不足时只依赖
  适用性与新鲜度，**绝不自称效果已提升**；
- 效果反馈（纠正/拒绝打扰）到达阈值 → quarantine 保留证据，不删除。

采集侧复用 expression_learning 的候选抽取规则（短子句 + 表情），拒绝
BOT_SELF / 命令 / 超长复述的纪律在抽取层已生效。
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any

from core.social.contracts import ConversationScope
from memory import social_store
from memory.timeutil import log_sqlite_error

MAX_SELECT_PER_TURN = 2

# 反馈降权阈值：一个资产在被「纠正/拒绝」的结算里被 applied 关联到该次数
# 即先 quarantine（保留证据，人工复核后可恢复）
_NEGATIVE_FEEDBACK_QUARANTINE_THRESHOLD = 2

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _connect() -> sqlite3.Connection:
    from config import settings

    return sqlite3.connect(settings.DB_PATH, timeout=10.0)


def _now() -> str:
    from core.social.contracts import utc_now_iso

    return utc_now_iso()


# ============================================================
# 采集：表达候选 → 证据
# ============================================================


def note_expression_candidates(
    scope: ConversationScope,
    message: str,
    *,
    event_id: str,
    author_user: str = "",
) -> int:
    """把一条人类消息的表达候选落成证据（幂等，同 event 不重复计）。

    返回新增证据条数。候选抽取复用 legacy 的短子句 + 表情规则；BOT_SELF
    与命令消息在采集入口已被排除。
    """
    message = message or ""
    if not message.strip() or not event_id:
        return 0
    from memory.expression_learning import _extract_expression_candidates

    added = 0
    for text, kind in _extract_expression_candidates(message):
        if not text:
            continue
        asset_id = _get_or_create_expression_asset(scope, text, kind)
        if asset_id is None:
            continue
        try:
            from core.social.contracts import content_hash

            social_store.ensure_tables()
            conn = _connect()
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO social_asset_evidence (asset_id, event_id, "
                    "evidence_kind, excerpt, content_hash, author_user, observed_at_utc) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (asset_id, event_id, "occurrence", text[:200], content_hash(text),
                     author_user or "", _now()),
                )
                conn.commit()
                added += cur.rowcount or 0
            finally:
                conn.close()
        except sqlite3.Error as e:
            log_sqlite_error("expression_selector.note_expression_candidates", e)
    return added


def _get_or_create_expression_asset(scope: ConversationScope, text: str, kind: str) -> str | None:
    text = (text or "").strip()
    if not text or len(text) > 60:
        return None
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT asset_id FROM social_assets WHERE kind='expression' AND platform=? "
                "AND bot_id=? AND group_id=? AND content=?",
                (*scope.row(), text),
            ).fetchone()
            if row:
                return row[0]
            asset_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO social_assets (asset_id, kind, platform, bot_id, group_id, "
                "content, situation, style, status, confidence, meta_json, created_at_utc, "
                "updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, "expression", *scope.row(), text, "", kind,
                 "candidate", 0.0,
                 json.dumps({"legacy_kind": kind, "promotable": False}, ensure_ascii=False),
                 _now(), _now()),
            )
            conn.commit()
            return asset_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector._get_or_create_expression_asset", e)
        return None


def refresh_promotable(scope: ConversationScope, asset_id: str, *,
                       min_evidence: int = 3, min_authors: int = 2,
                       min_dates: int = 2) -> bool:
    """按证据门槛刷新「可人工确认」标记（计划 §6.3 [assumed] 初值）。

    只标记、不激活：激活永远需要管理动作或后续评估门槛（本期未启用）。
    """
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT meta_json FROM social_assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
            if not row:
                return False
            try:
                meta = json.loads(row[0] or "{}")
            except ValueError:
                meta = {}
            events, authors, dates = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT author_user), "
                "COUNT(DISTINCT substr(observed_at_utc, 1, 10)) "
                "FROM social_asset_evidence WHERE asset_id = ? AND evidence_kind='occurrence'",
                (asset_id,),
            ).fetchone()
            meta["promotable"] = (
                int(events or 0) >= min_evidence
                and int(authors or 0) >= min_authors
                and int(dates or 0) >= min_dates
            )
            meta["evidence"] = {"events": int(events or 0), "authors": int(authors or 0),
                                "dates": int(dates or 0)}
            conn.execute(
                "UPDATE social_assets SET meta_json = ?, updated_at_utc = ? WHERE asset_id = ?",
                (json.dumps(meta, ensure_ascii=False), _now(), asset_id),
            )
            conn.commit()
            return bool(meta["promotable"])
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector.refresh_promotable", e)
        return False


def add_expression_asset(
    scope: ConversationScope, content: str, *, situation: str = "", style: str = "",
) -> str | None:
    """人工/管理通道：直接建一个表达资产（默认 candidate，可再激活）。"""
    content = (content or "").strip()
    if not content or len(content) > 60:
        return None
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            asset_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO social_assets (asset_id, kind, platform, bot_id, group_id, "
                "content, situation, style, status, confidence, meta_json, created_at_utc, "
                "updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (asset_id, "expression", *scope.row(), content, situation, style,
                 "candidate", 0.0, json.dumps({"origin": "manual"}, ensure_ascii=False),
                 _now(), _now()),
            )
            conn.commit()
            return asset_id
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector.add_expression_asset", e)
        return None


# ============================================================
# 选择与使用
# ============================================================


def _recent_group_use(conn, asset_id: str, group_id: str, window_turns: int) -> int:
    """该表达是否出现在本群最近 ``window_turns`` 次回复里（1=是，0=否）。

    「最近 N 次回复」= 本群首段投递（part_index=0）按时间倒序取 N 轮；
    usage × 投递联查，重启不失忆。
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM social_asset_usage u WHERE u.asset_id = ? AND u.turn_id IN ("
        "SELECT turn_id FROM social_deliveries WHERE part_index = 0 AND group_id = ? "
        "ORDER BY created_at_utc DESC LIMIT ?)",
        (asset_id, group_id, max(1, int(window_turns))),
    ).fetchone()
    return int(row[0]) if row else 0


def select(
    scope: ConversationScope,
    current_text: str,
    *,
    limit: int = MAX_SELECT_PER_TURN,
    recent_window_turns: int = 10,
) -> list[dict[str, Any]]:
    """为当前轮选择表达资产（active only，每轮最多 limit 条）。

    排序（计划 §6.3.7）：先按「最近未被使用」（防复读），再按证据平滑置信
    与更新新鲜度；无 active 资产返回空——绝不降级注入 candidate。
    """
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT asset_id, content, situation, style, confidence, meta_json, "
                "updated_at_utc FROM social_assets WHERE kind='expression' AND platform=? "
                "AND bot_id=? AND group_id=? AND status='active' ORDER BY updated_at_utc DESC",
                (*scope.row(),),
            ).fetchall()
            scored: list[dict[str, Any]] = []
            for asset_id, content, situation, style, confidence, meta_json, _updated in rows:
                recent = _recent_group_use(conn, asset_id, scope.group_id, recent_window_turns)
                if recent:
                    continue  # 最近 N 次本群回复已用过：本轮不再注入
                try:
                    meta = json.loads(meta_json or "{}")
                except ValueError:
                    meta = {}
                evidence = meta.get("evidence", {})
                authors = max(1, int(evidence.get("authors", 1)))
                events = max(1, int(evidence.get("events", 1)))
                # 平滑置信下界：样本越少越收敛到保守值，绝不用小样本高比例压过长期资产
                smoothed = (float(confidence or 0.0) * authors + 0.5) / (authors + 1.0)
                scored.append({
                    "asset_id": asset_id, "content": content, "situation": situation,
                    "style": style, "confidence": round(min(1.0, smoothed * 0.8
                                                            + min(1.0, events / 10.0) * 0.2), 3),
                    "recent_use": recent,
                    "asset_ids": [asset_id],
                    "term": content[:12],
                })
            scored.sort(key=lambda e: (e["recent_use"], -e["confidence"]))
            return scored[: max(0, limit)]
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector.select", e)
        return []


def mark_applied(turn_id: str, delivered_lines: list[str]) -> int:
    """输出匹配：注入的表达真的出现在已发文本里 → applied=1。

    只有可确认 applied 的表达才关联使用结果；未匹配保持 unknown
    （不把整条回复的成功归给所有候选，计划 §6.3.4）。返回标记条数。
    """
    if not turn_id or not delivered_lines:
        return 0
    joined = " ".join(delivered_lines)
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT u.usage_id, a.content, a.style FROM social_asset_usage u "
                "JOIN social_assets a ON a.asset_id = u.asset_id "
                "WHERE u.turn_id = ? AND u.injected = 1 AND u.applied = 0",
                (turn_id,),
            ).fetchall()
            marked = 0
            for usage_id, content, _style in rows:
                needle = (content or "").strip()
                if needle and needle in joined:
                    conn.execute(
                        "UPDATE social_asset_usage SET applied = 1 WHERE usage_id = ?",
                        (usage_id,),
                    )
                    marked += 1
            conn.commit()
            return marked
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector.mark_applied", e)
        return 0


def handle_effect_feedback(effect_id: str) -> bool:
    """效果结算后的反馈降权：applied 且被纠正/拒绝的资产先 quarantine。

    自动负反馈不删除证据（保留可复核），人工可恢复（计划 §6.3.6）。
    """
    try:
        social_store.ensure_tables()
        conn = _connect()
        try:
            dims_row = conn.execute(
                "SELECT meta_json FROM social_effects WHERE effect_id = ?", (effect_id,)
            ).fetchone()
            if not dims_row:
                return False
            try:
                dims = json.loads(dims_row[0] or "{}")
            except ValueError:
                return False
            reception = str(dims.get("reception") or "")
            if reception not in ("corrected", "refused"):
                return False
            rows = conn.execute(
                "SELECT u.asset_id, COUNT(*) FROM social_asset_usage u "
                "WHERE u.effect_id = ? AND u.applied = 1 GROUP BY u.asset_id",
                (effect_id,),
            ).fetchall()
            changed = False
            for asset_id, _n in rows:
                cur = conn.execute(
                    "UPDATE social_assets SET status = 'quarantined', updated_at_utc = ? "
                    "WHERE asset_id = ? AND status = 'active'",
                    (_now(), asset_id),
                )
                changed = changed or cur.rowcount > 0
            if changed:
                conn.commit()
            return changed
        finally:
            conn.close()
    except sqlite3.Error as e:
        log_sqlite_error("expression_selector.handle_effect_feedback", e)
        return False
