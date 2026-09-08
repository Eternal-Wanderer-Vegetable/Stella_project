# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""表达与插话效果学习的独立存储（《Stella 拟人化插话与低成本运行改进方案 v1.0》阶段六）。

四张表，与记忆系统（「知道什么」）完全分离——这里只存「怎么说效果好」：

    expression_examples  用户/群里出现过的表达样本（短语、表情用法）
    jargon_glossary      群黑话词条（候选 → 转正，带命中计数）
    behavior_patterns    每用户行为聚合（回应率、纠正次数、表情使用等，JSON 计数器）
    reply_effects        每次 Stella 发言的效果结算（回应/复用/表情/纠正/忽略）

本模块只有存储，没有学习逻辑（见 memory/expression_learning.py）；
所有写操作都由异步后处理调用，主回复路径不碰这些表。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from config import DB_PATH
from memory.timeutil import log_sqlite_error

_TABLES = (
    """
    CREATE TABLE IF NOT EXISTS expression_examples (
        id TEXT PRIMARY KEY,
        group_shared_space TEXT NOT NULL,
        user_id TEXT NOT NULL,
        text TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'phrase',
        source TEXT NOT NULL DEFAULT 'AT_MENTION',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS jargon_glossary (
        term TEXT NOT NULL,
        group_shared_space TEXT NOT NULL,
        hit_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'candidate',
        first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (term, group_shared_space)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS behavior_patterns (
        group_shared_space TEXT NOT NULL,
        user_id TEXT NOT NULL,
        pattern_key TEXT NOT NULL,
        pattern_value TEXT NOT NULL DEFAULT '{}',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (group_shared_space, user_id, pattern_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reply_effects (
        id TEXT PRIMARY KEY,
        group_shared_space TEXT NOT NULL,
        group_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        trigger TEXT NOT NULL DEFAULT 'reply',
        reply_excerpt TEXT NOT NULL DEFAULT '',
        asked_at_mono REAL NOT NULL,
        asked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        resolved INTEGER NOT NULL DEFAULT 0,
        outcome TEXT NOT NULL DEFAULT '',
        resolved_at DATETIME
    )
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_expression_examples_space "
    "ON expression_examples (group_shared_space, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_reply_effects_pending "
    "ON reply_effects (resolved, asked_at_mono)",
)


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def ensure_tables() -> None:
    """幂等建表。由本模块的写路径按需调用，不挂在 import 期。"""
    conn = _connect()
    try:
        for ddl in _TABLES + _INDEXES:
            conn.execute(ddl)
        conn.commit()
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.ensure_tables", e)
    finally:
        conn.close()


# ============================================================
# expression_examples
# ============================================================


def add_expression_example(
    group_shared_space: str,
    user_id: int | str,
    text: str,
    kind: str = "phrase",
    source: str = "AT_MENTION",
) -> bool:
    """存一条表达样本。text 为空或超长直接拒绝（样本表不是垃圾桶）。"""
    text = (text or "").strip()
    if not text or len(text) > 60:
        return False
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO expression_examples (id, group_shared_space, user_id, text, kind, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, group_shared_space, str(user_id), text, kind, source),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.add_expression_example", e)
        return False
    finally:
        conn.close()


def list_expression_examples(group_shared_space: str, limit: int = 20) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT text, kind, user_id, created_at FROM expression_examples "
            "WHERE group_shared_space = ? ORDER BY created_at DESC LIMIT ?",
            (group_shared_space, max(0, limit)),
        ).fetchall()
        return [
            {"text": r[0], "kind": r[1], "user_id": r[2], "created_at": r[3]} for r in rows
        ]
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.list_expression_examples", e)
        return []
    finally:
        conn.close()


# ============================================================
# jargon_glossary
# ============================================================


def upsert_jargon(
    group_shared_space: str,
    term: str,
    add_hits: int,
    confirm_threshold: int,
) -> bool:
    """累积一个黑话词条的命中数；总数跨过 confirm_threshold 时自动转正。

    计数在 SQL 侧累加（jargon_glossary.hit_count + 本批增量），进程内的
    计数器 flush 后清零也不丢历史。状态只升不降：已转正的词条不会被
    后续候选批次打回。
    """
    term = (term or "").strip()
    if not term or len(term) > 32 or add_hits <= 0:
        return False
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO jargon_glossary (term, group_shared_space, hit_count, status,
                                         first_seen_at, last_seen_at)
            VALUES (?, ?, ?, 'candidate', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (term, group_shared_space) DO UPDATE SET
                hit_count = jargon_glossary.hit_count + excluded.hit_count,
                status = CASE
                    WHEN jargon_glossary.status = 'confirmed'
                        THEN 'confirmed'
                    WHEN jargon_glossary.hit_count + excluded.hit_count >= ?
                        THEN 'confirmed'
                    ELSE 'candidate'
                END,
                last_seen_at = CURRENT_TIMESTAMP
            """,
            (term, group_shared_space, int(add_hits), int(confirm_threshold)),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.upsert_jargon", e)
        return False
    finally:
        conn.close()


def list_jargon(group_shared_space: str, status: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        if status:
            rows = conn.execute(
                "SELECT term, hit_count, status, first_seen_at, last_seen_at FROM jargon_glossary "
                "WHERE group_shared_space = ? AND status = ? ORDER BY hit_count DESC",
                (group_shared_space, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT term, hit_count, status, first_seen_at, last_seen_at FROM jargon_glossary "
                "WHERE group_shared_space = ? ORDER BY hit_count DESC",
                (group_shared_space,),
            ).fetchall()
        return [
            {
                "term": r[0],
                "hit_count": r[1],
                "status": r[2],
                "first_seen_at": r[3],
                "last_seen_at": r[4],
            }
            for r in rows
        ]
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.list_jargon", e)
        return []
    finally:
        conn.close()


# ============================================================
# behavior_patterns
# ============================================================


def merge_pattern(
    group_shared_space: str,
    user_id: int | str,
    pattern_key: str,
    deltas: dict[str, float],
) -> bool:
    """把一批计数增量合并进 (空间, 用户, 键) 的 JSON 聚合里。

    值全为数值：merge 即相加。非数值（旧版本残留）直接被新值覆盖。
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT pattern_value FROM behavior_patterns "
            "WHERE group_shared_space = ? AND user_id = ? AND pattern_key = ?",
            (group_shared_space, str(user_id), pattern_key),
        ).fetchone()
        current: dict[str, float] = {}
        if row and row[0]:
            try:
                parsed = json.loads(row[0])
                if isinstance(parsed, dict):
                    current = parsed
            except (ValueError, TypeError):
                current = {}
        for k, v in deltas.items():
            current[k] = float(current.get(k, 0.0)) + float(v)
        conn.execute(
            """
            INSERT INTO behavior_patterns (group_shared_space, user_id, pattern_key,
                                           pattern_value, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (group_shared_space, user_id, pattern_key) DO UPDATE SET
                pattern_value = excluded.pattern_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_shared_space, str(user_id), pattern_key, json.dumps(current, ensure_ascii=False)),
        )
        conn.commit()
        return True
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.merge_pattern", e)
        return False
    finally:
        conn.close()


def get_pattern(
    group_shared_space: str, user_id: int | str, pattern_key: str
) -> dict[str, float]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT pattern_value FROM behavior_patterns "
            "WHERE group_shared_space = ? AND user_id = ? AND pattern_key = ?",
            (group_shared_space, str(user_id), pattern_key),
        ).fetchone()
        if not row or not row[0]:
            return {}
        parsed = json.loads(row[0])
        return parsed if isinstance(parsed, dict) else {}
    except (sqlite3.Error, ValueError) as e:
        log_sqlite_error("expression_store.get_pattern", e)
        return {}
    finally:
        conn.close()


# ============================================================
# reply_effects
# ============================================================


def add_reply_effect(
    *,
    group_shared_space: str,
    group_id: int,
    user_id: int | str,
    trigger: str,
    reply_excerpt: str,
    asked_at_mono: float,
) -> str | None:
    """登记一次未结算的发言效果。返回行 id（结算时用）。"""
    excerpt = (reply_excerpt or "").strip()[:120]
    effect_id = uuid.uuid4().hex
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO reply_effects (id, group_shared_space, group_id, user_id, trigger, "
            "reply_excerpt, asked_at_mono) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                effect_id,
                group_shared_space,
                str(group_id),
                str(user_id),
                trigger,
                excerpt,
                float(asked_at_mono),
            ),
        )
        conn.commit()
        return effect_id
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.add_reply_effect", e)
        return None
    finally:
        conn.close()


def resolve_reply_effect(effect_id: str, outcome: str) -> bool:
    """结算一行回复效果（outcome: responded / reused_expression / emoji / corrected / ignored）。"""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE reply_effects SET resolved = 1, outcome = ?, resolved_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND resolved = 0",
            (outcome, effect_id),
        )
        conn.commit()
        return conn.total_changes > 0
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.resolve_reply_effect", e)
        return False
    finally:
        conn.close()


def get_reply_effect(effect_id: str) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, group_shared_space, group_id, user_id, trigger, reply_excerpt, "
            "asked_at_mono, asked_at, resolved, outcome FROM reply_effects WHERE id = ?",
            (effect_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "group_shared_space": row[1],
            "group_id": int(row[2]),
            "user_id": row[3],
            "trigger": row[4],
            "reply_excerpt": row[5],
            "asked_at_mono": float(row[6]),
            "asked_at": row[7],
            "resolved": bool(row[8]),
            "outcome": row[9],
        }
    except (sqlite3.Error, ValueError) as e:
        log_sqlite_error("expression_store.get_reply_effect", e)
        return None
    finally:
        conn.close()


def stale_reply_effects(older_than_mono: float, limit: int = 100) -> list[dict[str, Any]]:
    """超窗仍未结算的行（进程重启后由 sweep 补结算）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id FROM reply_effects WHERE resolved = 0 AND asked_at_mono < ? LIMIT ?",
            (float(older_than_mono), max(0, limit)),
        ).fetchall()
        return [{"id": r[0]} for r in rows]
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.stale_reply_effects", e)
        return []
    finally:
        conn.close()


# ============================================================
# 清理
# ============================================================


def prune(
    *,
    examples_keep_days: float,
    effects_keep_days: float,
) -> dict[str, int]:
    """按保留期裁剪表达样本与回复效果行；黑话表不裁（词条是长期资产）。

    reply_effects 不区分结算状态一并清理：正常超窗行早被 sweep 结算，
    还留在库里的超龄未结算行只可能是「重启导致单调钟不可比」的僵尸数据
    （机器重启后 time.monotonic() 归零，重启前的 asked_at_mono 永远判不出
    超窗），留着没有学习价值。

    各表的时间列不同（expression_examples 用 created_at，reply_effects 用
    asked_at），逐表指定，拼错列名只会让那一表裁剪失败并留痕，不影响其他表。
    """
    conn = _connect()
    out = {"expression_examples": 0, "reply_effects": 0}
    try:
        for table, ts_column, days in (
            ("expression_examples", "created_at", examples_keep_days),
            ("reply_effects", "asked_at", effects_keep_days),
        ):
            if days <= 0:
                continue
            cur = conn.execute(
                f"DELETE FROM {table} WHERE julianday('now') - julianday({ts_column}) > ?",
                (float(days),),
            )
            out[table] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    except sqlite3.Error as e:
        log_sqlite_error("expression_store.prune", e)
    finally:
        conn.close()
    return out
