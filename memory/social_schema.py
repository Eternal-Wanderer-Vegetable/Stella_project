# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""社交学习旁表的组件独立迁移（计划 §6.2）。

与核心记忆 schema（memory/schema.py）完全解耦：

- 版本记在 ``social_schema_meta``（component='social'），**事务成功才提升版本**
  ——建表、旧库导入、版本提升在同一个事务里，中途失败整体回滚，不留下
  「表建了一半」的中间态；
- 首次升级前用 SQLite backup API 生成一致备份（``*.pre-social-*.bak``），
  绝不在 WAL 写入中直接复制单个 .db 文件；
- 旧表达/黑话数据导入为 **legacy 候选**：能可靠确定真实群的源记录才赋
  scope（platform='qq' + group_id）；共享空间的旧资产保留隔离的
  ``legacy_unscoped``（group_id=''），需管理确认后才激活——不猜测回填；
- 旧 reply_effects 缺可靠回执、且 asked_at_mono 是不能跨重启比较的单调钟
  时间，全部标记 ``legacy_unverifiable``：不补造评价、不驱动阈值，
  旧统计只供历史显示，不混入新分母。

回退语义：旧代码可以完全忽略这些旁表（不删数据、不要求恢复整库）；
恢复备份只作为故障恢复手段，会丢升级后产生的数据。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

from nonebot import logger

from memory.timeutil import log_sqlite_error, utc_now

SOCIAL_SCHEMA_VERSION = 1

# ---- 表清单（单事务创建；字段与索引的最小集，见计划 §6.2 表格） ----
_TABLES = (
    # 组件版本表：事务成功才提升版本（迁移步骤与 memory/migrations.py 同一原则）
    """
    CREATE TABLE IF NOT EXISTS social_schema_meta (
        component TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # 标准化消息证据：去重靠复合唯一索引（NULL 平台 ID 互不冲突）
    """
    CREATE TABLE IF NOT EXISTS social_events (
        event_id TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        bot_id TEXT NOT NULL DEFAULT '',
        group_id TEXT NOT NULL,
        platform_message_id TEXT,
        user_id TEXT NOT NULL DEFAULT '',
        source_kind TEXT NOT NULL DEFAULT 'PASSIVE',
        reply_to_id TEXT,
        mentioned_user_ids TEXT NOT NULL DEFAULT '[]',
        text_excerpt TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        received_at_utc TEXT NOT NULL,
        event_at_utc TEXT NOT NULL DEFAULT '',
        trace_id TEXT NOT NULL DEFAULT '',
        turn_id TEXT NOT NULL DEFAULT ''
    )
    """,
    # 投递回执：turn+片段唯一；ACK 平台 ID 反查索引支撑引用归因
    """
    CREATE TABLE IF NOT EXISTS social_deliveries (
        delivery_id TEXT PRIMARY KEY,
        turn_id TEXT NOT NULL,
        part_index INTEGER NOT NULL,
        trace_id TEXT NOT NULL DEFAULT '',
        epoch INTEGER NOT NULL DEFAULT 0,
        platform TEXT NOT NULL DEFAULT '',
        bot_id TEXT NOT NULL DEFAULT '',
        group_id TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending',
        platform_message_id TEXT,
        acknowledged_at_utc TEXT,
        text TEXT NOT NULL DEFAULT '',
        text_hash TEXT NOT NULL DEFAULT '',
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        UNIQUE (turn_id, part_index)
    )
    """,
    # 效果观察行：turn 唯一（一次生成一轮效果）；窗口 deadline 持久化为 UTC
    """
    CREATE TABLE IF NOT EXISTS social_effects (
        effect_id TEXT PRIMARY KEY,
        turn_id TEXT NOT NULL UNIQUE,
        trace_id TEXT NOT NULL DEFAULT '',
        platform TEXT NOT NULL DEFAULT '',
        bot_id TEXT NOT NULL DEFAULT '',
        group_id TEXT NOT NULL DEFAULT '',
        target_user_id TEXT,
        trigger TEXT NOT NULL DEFAULT 'reply',
        intent TEXT NOT NULL DEFAULT '',
        first_ack_at_utc TEXT,
        last_ack_at_utc TEXT,
        window_end_utc TEXT,
        status TEXT NOT NULL DEFAULT 'observing',
        observation TEXT NOT NULL DEFAULT '',
        rule_version TEXT NOT NULL DEFAULT '',
        evaluation_version TEXT NOT NULL DEFAULT '',
        assessable INTEGER NOT NULL DEFAULT 1,
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at_utc TEXT NOT NULL,
        resolved_at_utc TEXT
    )
    """,
    # 效果证据：一条消息可留候选关联；只有明确归因进入统计
    """
    CREATE TABLE IF NOT EXISTS social_effect_evidence (
        effect_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        attribution TEXT NOT NULL DEFAULT 'ambiguous',
        confidence REAL NOT NULL DEFAULT 0,
        classification TEXT NOT NULL DEFAULT '',
        polysemy_reason TEXT NOT NULL DEFAULT '',
        created_at_utc TEXT NOT NULL,
        UNIQUE (effect_id, event_id)
    )
    """,
    # 学习资产（表达/黑话）：group_id='' 即 legacy_unscoped，默认永不注入
    """
    CREATE TABLE IF NOT EXISTS social_assets (
        asset_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        platform TEXT NOT NULL DEFAULT '',
        bot_id TEXT NOT NULL DEFAULT '',
        group_id TEXT NOT NULL DEFAULT '',
        legacy_scope TEXT NOT NULL DEFAULT '',
        owner_user TEXT,
        content TEXT NOT NULL DEFAULT '',
        situation TEXT NOT NULL DEFAULT '',
        style TEXT NOT NULL DEFAULT '',
        term TEXT NOT NULL DEFAULT '',
        sense TEXT NOT NULL DEFAULT '',
        definition TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'candidate',
        confidence REAL NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL DEFAULT 1,
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )
    """,
    # 资产证据：去重与跨重启独立作者计数的事实来源
    """
    CREATE TABLE IF NOT EXISTS social_asset_evidence (
        asset_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL DEFAULT 'occurrence',
        excerpt TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '',
        author_user TEXT NOT NULL DEFAULT '',
        observed_at_utc TEXT NOT NULL,
        UNIQUE (asset_id, event_id, evidence_kind)
    )
    """,
    # 资产使用记录：selected ≠ injected ≠ applied，效果只关联 applied
    """
    CREATE TABLE IF NOT EXISTS social_asset_usage (
        usage_id TEXT PRIMARY KEY,
        turn_id TEXT NOT NULL,
        asset_id TEXT NOT NULL,
        revision INTEGER NOT NULL DEFAULT 1,
        selected INTEGER NOT NULL DEFAULT 0,
        injected INTEGER NOT NULL DEFAULT 0,
        applied INTEGER NOT NULL DEFAULT 0,
        effect_id TEXT,
        created_at_utc TEXT NOT NULL,
        UNIQUE (turn_id, asset_id, revision)
    )
    """,
    # 结算聚合贡献：一次结算只计一次；重评按 evaluation_version 撤旧写新
    """
    CREATE TABLE IF NOT EXISTS social_aggregate_events (
        aggregate_id TEXT PRIMARY KEY,
        effect_id TEXT NOT NULL,
        evaluation_version TEXT NOT NULL,
        metric TEXT NOT NULL,
        delta REAL NOT NULL DEFAULT 0,
        scope_user TEXT NOT NULL DEFAULT '',
        created_at_utc TEXT NOT NULL,
        UNIQUE (effect_id, evaluation_version, metric)
    )
    """,
    # 持久化有界工作队列：效果结算/补偿的统一作业模型（替代 sleep+sweep 双路）
    """
    CREATE TABLE IF NOT EXISTS social_jobs (
        job_id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        payload_refs TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        lease_until_utc TEXT,
        not_before_utc TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL
    )
    """,
)

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_social_events_scope_time "
    "ON social_events (platform, bot_id, group_id, received_at_utc)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_social_events_platform_msg "
    "ON social_events (platform, bot_id, group_id, platform_message_id) "
    "WHERE platform_message_id IS NOT NULL AND platform_message_id != ''",
    "CREATE INDEX IF NOT EXISTS idx_social_deliveries_ack_id "
    "ON social_deliveries (platform_message_id)",
    "CREATE INDEX IF NOT EXISTS idx_social_effects_window "
    "ON social_effects (status, window_end_utc)",
    "CREATE INDEX IF NOT EXISTS idx_social_assets_scope "
    "ON social_assets (platform, bot_id, group_id, kind, status)",
    "CREATE INDEX IF NOT EXISTS idx_social_jobs_due "
    "ON social_jobs (status, not_before_utc)",
    # 效果证据按事件反查（一条群消息关联到哪些 effect）
    "CREATE INDEX IF NOT EXISTS idx_social_effect_evidence_event "
    "ON social_effect_evidence (event_id)",
    "CREATE INDEX IF NOT EXISTS idx_social_asset_evidence_asset "
    "ON social_asset_evidence (asset_id, observed_at_utc)",
)

# 旧库导入的行级映射（重复运行不复制）
_MAP_TABLE = """
    CREATE TABLE IF NOT EXISTS social_migration_map (
        source_table TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_table TEXT NOT NULL,
        target_id TEXT NOT NULL,
        migrated_at_utc TEXT NOT NULL,
        UNIQUE (source_table, source_id, target_table)
    )
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(db_path), timeout=10.0)


def social_schema_version(db_path: Path | str | None = None) -> int:
    """读取社交组件版本；未初始化返回 0。"""
    if db_path is None:
        from config import DB_PATH

        db_path = Path(DB_PATH)
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    try:
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT version FROM social_schema_meta WHERE component = 'social'"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _backup(db_path: Path) -> Path | None:
    """SQLite backup API 生成一致备份（源库正在写也不怕，API 自带一致性）。"""
    target = db_path.with_name(
        f"{db_path.name}.pre-social-{utc_now().strftime('%Y%m%d-%H%M%S')}.bak"
    )
    try:
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(target))
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        return target
    except sqlite3.Error as e:
        log_sqlite_error("social_schema._backup", e)
        return None


# ============================================================
# 旧库导入（全部幂等：按 social_migration_map 跳过已迁移行）
# ============================================================


def _map_and_mark(
    conn: sqlite3.Connection,
    source_table: str,
    source_id: str,
    target_table: str,
    target_id: str,
    now: str,
) -> bool:
    """登记一条迁移映射；已存在返回 False（调用方跳过导入）。"""
    cur = conn.execute(
        "INSERT OR IGNORE INTO social_migration_map "
        "(source_table, source_id, target_table, target_id, migrated_at_utc) "
        "VALUES (?,?,?,?,?)",
        (source_table, str(source_id), target_table, str(target_id), now),
    )
    return cur.rowcount > 0


def _resolve_scope_group(space: str) -> str:
    """把旧 group_shared_space 解析为真实群号字符串；不可靠返回 ''（legacy_unscoped）。

    只有「该空间唯一对应一个真实群」才可赋 scope：多群共享空间或解析失败
    都保留隔离，绝不猜（计划 §6.2 迁移步骤 3）。
    """
    if not space or not str(space).isdigit():
        return ""
    try:
        from config.spaces import qq_groups_of

        groups = [g for g in qq_groups_of(str(space)) if int(g) > 0]
    except Exception:
        return ""
    return str(groups[0]) if len(groups) == 1 else ""


def _resolve_scope(space: str) -> tuple[str, str, str]:
    """把旧 group_shared_space 解析为 (platform, bot_id, group_id) 三元组。

    只有「该空间唯一对应一个真实群」才可赋 qq scope（数字空间名按项目约定
    即群号字符串，config.spaces.qq_groups_of 自带回退语义）；解析不可靠返回
    ('legacy', 'legacy', '')，legacy_scope 保留原名供人工核对——绝不猜。
    """
    group = _resolve_scope_group(space)
    if group:
        return ("qq", "", group)
    return ("legacy", "legacy", "")


def _legacy_timestamp(value) -> str:
    """旧表 CURRENT_TIMESTAMP（UTC naive）→ 本模块的 UTC ISO 串；空值返回 ''。"""
    text = str(value or "").strip()
    return f"{text}+00:00" if text else ""


def _import_expression_examples(conn: sqlite3.Connection, now: str) -> dict[str, int]:
    """expression_examples → social_events（LEGACY 证据）+ social_assets（表达候选）。

    同 (space, text) 聚成一个表达资产，旧行各自成为该资产的证据行——
    证据行数与旧表行数守恒，资产数 ≤ 旧行数。
    """
    stats = {"events": 0, "assets": 0, "evidence": 0, "skipped": 0}
    try:
        rows = conn.execute(
            "SELECT id, group_shared_space, user_id, text, kind, source, created_at "
            "FROM expression_examples ORDER BY id"
        ).fetchall()
    except sqlite3.Error as e:
        log_sqlite_error("social_schema._import_expression_examples", e)
        return stats
    asset_by_key: dict[tuple[str, str], str] = {}
    for _idx, (old_id, space, user_id, text, kind, _source, created_at) in enumerate(rows):
        text = (text or "").strip()
        if not text:
            stats["skipped"] += 1
            continue
        if not _map_and_mark(conn, "expression_examples", old_id, "social_assets", old_id, now):
            stats["skipped"] += 1
            continue
        platform, bot_id, group_id = _resolve_scope(space)
        observed = _legacy_timestamp(created_at) or now
        event_id = f"legacy-expr-{old_id}"
        conn.execute(
            "INSERT OR IGNORE INTO social_events (event_id, platform, bot_id, group_id, "
            "platform_message_id, user_id, source_kind, text_excerpt, content_hash, "
            "received_at_utc, event_at_utc) VALUES (?,?,?,?,NULL,?,?,?,?,?,?)",
            (
                event_id, platform, bot_id, group_id, str(user_id or ""), "LEGACY",
                text[:200], _hash(text), observed, observed,
            ),
        )
        stats["events"] += 1
        key = (str(space or ""), text)
        asset_id = asset_by_key.get(key)
        if asset_id is None:
            # 稳定 id：同名资产重复迁移也不会复制（映射表已挡，这里再保一道）
            asset_id = f"legacy-expr-{abs(hash(key)) % 10**12:012d}"
            conn.execute(
                "INSERT OR IGNORE INTO social_assets (asset_id, kind, platform, bot_id, "
                "group_id, legacy_scope, owner_user, content, status, confidence, "
                "meta_json, created_at_utc, updated_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    asset_id, "expression", platform, bot_id, group_id,
                    str(space or ""), None, text, "candidate", 0.0,
                    json.dumps({"legacy": True, "legacy_kind": kind or "phrase"},
                               ensure_ascii=False),
                    observed, now,
                ),
            )
            asset_by_key[key] = asset_id
            stats["assets"] += 1
        conn.execute(
            "INSERT OR IGNORE INTO social_asset_evidence (asset_id, event_id, "
            "evidence_kind, excerpt, content_hash, author_user, observed_at_utc) "
            "VALUES (?,?,?,?,?,?,?)",
            (asset_id, event_id, "occurrence", text[:200], _hash(text),
             str(user_id or ""), observed),
        )
        stats["evidence"] += 1
    return stats


def _hash(text: str) -> str:
    from core.social.contracts import content_hash

    return content_hash(text)


def _import_jargon(conn: sqlite3.Connection, now: str) -> dict[str, int]:
    """jargon_glossary → social_assets（黑话候选）。

    旧表只有词形与聚合计数，没有逐次出现的独立事件：**不伪造证据行**，
    hit_count 原样进 meta_json，作者数记 0（跨重启用户数待新证据重建）。
    """
    stats = {"assets": 0, "skipped": 0}
    try:
        rows = conn.execute(
            "SELECT term, group_shared_space, hit_count, status, first_seen_at "
            "FROM jargon_glossary ORDER BY term"
        ).fetchall()
    except sqlite3.Error as e:
        log_sqlite_error("social_schema._import_jargon", e)
        return stats
    for old_term, space, hit_count, _status, first_seen in rows:
        term = (old_term or "").strip()
        if not term:
            stats["skipped"] += 1
            continue
        if not _map_and_mark(conn, "jargon_glossary", f"{space}\x00{term}", "social_assets", term, now):
            stats["skipped"] += 1
            continue
        platform, bot_id, group_id = _resolve_scope(space)
        conn.execute(
            "INSERT OR IGNORE INTO social_assets (asset_id, kind, platform, bot_id, "
            "group_id, legacy_scope, content, term, status, confidence, meta_json, "
            "created_at_utc, updated_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"legacy-jargon-{abs(hash((space or '', term))) % 10**12:012d}",
                "jargon", platform, bot_id, group_id, str(space or ""),
                term, term, "candidate",
                min(1.0, float(hit_count or 0) / 12.0),
                json.dumps({"legacy": True, "legacy_hit_count": int(hit_count or 0)},
                           ensure_ascii=False),
                _legacy_timestamp(first_seen) or now, now,
            ),
        )
        stats["assets"] += 1
    return stats


def _import_reply_effects(conn: sqlite3.Connection, now: str) -> dict[str, int]:
    """reply_effects → social_effects（全部 legacy_unverifiable）。

    asked_at_mono 是单调钟时间，跨重启不可比；缺平台回执 ID。两者都意味着
    新系统不能基于旧行补造任何评价——只保留历史显示价值。
    """
    stats = {"effects": 0, "skipped": 0}
    try:
        rows = conn.execute(
            "SELECT id, group_shared_space, group_id, user_id, trigger, reply_excerpt, "
            "asked_at, resolved, outcome FROM reply_effects ORDER BY id"
        ).fetchall()
    except sqlite3.Error as e:
        log_sqlite_error("social_schema._import_reply_effects", e)
        return stats
    for old_id, _space, group_id, user_id, trigger, excerpt, asked_at, resolved, outcome in rows:
        if not _map_and_mark(conn, "reply_effects", old_id, "social_effects", old_id, now):
            stats["skipped"] += 1
            continue
        # 旧表 group_id 存的是真实群号字符串：可信（效果观察本来就是按群查的）
        real_group = str(group_id or "").strip()
        platform, bot_id = ("qq", "") if real_group.isdigit() else ("legacy", "legacy")
        conn.execute(
            "INSERT OR IGNORE INTO social_effects (effect_id, turn_id, platform, bot_id, "
            "group_id, target_user_id, trigger, status, observation, assessable, "
            "meta_json, created_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"legacy-effect-{old_id}", f"legacy-turn-{old_id}", platform, bot_id,
                real_group if real_group not in ("", "0") else "",
                str(user_id) if str(user_id) not in ("", "0") else None,
                trigger or "reply", "legacy_unverifiable", "insufficient", 0,
                json.dumps(
                    {
                        "legacy": True,
                        "legacy_outcome": outcome or "",
                        "legacy_resolved": bool(resolved),
                        "legacy_reply_excerpt": (excerpt or "")[:120],
                    },
                    ensure_ascii=False,
                ),
                _legacy_timestamp(asked_at) or now,
            ),
        )
        stats["effects"] += 1
    return stats


def import_legacy_data(conn: sqlite3.Connection, now: str) -> dict[str, int]:
    """导入旧表达/黑话/效果数据（幂等）。任何失败抛出让整体事务回滚。"""
    stats: dict[str, int] = {}
    for importer in (_import_expression_examples, _import_jargon, _import_reply_effects):
        try:
            result = importer(conn, now)
        except sqlite3.Error as e:
            # 单个导入器的意外 SQL 错误 → 整体失败回滚（迁移步骤 6：失败整级回滚）
            raise RuntimeError(f"social 迁移导入失败（{importer.__name__}）: {e}") from e
        for k, v in result.items():
            stats[k] = stats.get(k, 0) + v
    return stats


# ============================================================
# 入口
# ============================================================


def ensure_social_schema(
    db_path: Path | str | None = None, *, backup: bool = True
) -> dict[str, int]:
    """幂等初始化与升级社交旁表。返回导入/跳过统计（首建时）。

    单事务：建表 + 索引 + 映射表 + 旧库导入 + 版本提升，全部成功才提交；
    中途任何异常整体回滚，组件版本保持不变。
    """
    if db_path is None:
        from config import DB_PATH

        db_path = Path(DB_PATH)
    db_path = Path(db_path)
    if social_schema_version(db_path) >= SOCIAL_SCHEMA_VERSION:
        return {}
    if backup and db_path.exists() and db_path.stat().st_size > 0:
        made = _backup(db_path)
        if made:
            logger.info(f"💾 [Social] 迁移前备份: {made.name}")

    conn = _connect(db_path)
    stats: dict[str, int] = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        for ddl in _TABLES + _INDEXES + (_MAP_TABLE,):
            conn.execute(ddl)
        # 旧库导入只在这台库有旧表达系统数据时才有行可导
        legacy_present = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('expression_examples','jargon_glossary','reply_effects')"
            ).fetchall()
        )
        if legacy_present:
            stats = import_legacy_data(conn, utc_now().isoformat(timespec="milliseconds"))
        conn.execute(
            "INSERT INTO social_schema_meta (component, version, updated_at) "
            "VALUES ('social', ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT (component) DO UPDATE SET version = excluded.version, "
            "updated_at = CURRENT_TIMESTAMP",
            (SOCIAL_SCHEMA_VERSION,),
        )
        conn.execute("COMMIT")
    except Exception as e:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("ROLLBACK")
        log_sqlite_error("social_schema.ensure_social_schema", e)
        raise
    finally:
        conn.close()
    if stats:
        logger.info(
            f"📦 [Social] 旧库导入完成: {stats}（重复执行不增量复制，见 social_migration_map）"
        )
    return stats
