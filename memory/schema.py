# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据库 Schema 迁移（记忆系统 v2）。

采用 Additive Migration（只加字段、不删数据）：
1. 首次迁移前把数据库备份为 ``stella_memory_backup.db``；
2. 为 ``long_term_memories`` / ``memory_candidates`` / ``memories`` 增加 v2 字段
   （memory_type / usage_tags / visibility / trigger_data / behavior_rule / confidence / status）；
3. 新增常用检索索引（group_id / user_id / memory_type / visibility / status）；
4. v3 为 ``group_messages`` / ``memory_candidates`` / ``memories`` 补 ``source_kind``
   列（消息来源分级：AT_MENTION / PASSIVE），并新增按来源归因的审计索引；
5. v4 为 ``memory_candidates`` 补候选强化字段（occurrence_count / first_seen_at /
   source_kinds），支撑「暂存 → 交叉验证 → 逐步强化」的累计证据语义；
6. v5 新增 ``proactive_state`` 表（主动发言的持久化状态：每用户 @ 配额计数、
   上次追问内容、连续无回应次数）。
7. v6 新增 ``group_runtime_state`` 表（主动发言的运行时静音开关与
   睡眠/苏醒播报的每日去重锚点）。
8. v7 ``user_profiles`` 主键改为按群隔离（v8 起为 ``(group_shared_space, user_id)``）：
   同一个人在技术群与闲聊群应当是不同画像，共用一份会让 _merge_traits 把两个群的特征混在一起，
   使「群A 一个形象、群B 另一个形象」在认知层面无法成立。
   **本版不做数据迁移**：SQLite 无法直接改主键，且旧库画像在严苛筛选下几乎为空，
   直接新建数据库比写一套只用一次的迁移代码更可靠（决策记录 2026-08-17）。
   旧库如需保留请手动改名后让程序重建。
9. v8 把 ``memories`` / ``memory_candidates`` / ``atomic_facts`` / ``user_profiles``
   / ``memories_fts`` 的 ``group_id`` 改名为 ``group_shared_space``：多个 QQ 群
   可以组成一个「群组共享空间」，共享画像、记忆与人格；而消息尾巴、checkpoint、
   短期话题、静音开关、@ 配额仍按真实 QQ 群归属（那些是「当下这场对话的状态」，
   混群会让 Bot 在 A 群回应 B 群）。列名改名而非复用 ``group_id``，是为了让两层
   归属在代码里不可混淆——同一个名字有时指 QQ 群、有时指空间，是必然踩坑的歧义。
   **本版不做数据迁移**（同 v7）：库为空，归档旧库重建即可。

迁移以 ``schema_meta`` 表记录版本号，幂等；所有 ALTER 都经过 ``PRAGMA table_info``
探测，绝不对已存在的列重复添加。任何情况都不删除旧数据。

独立运行：``python -m memory.schema``（可先 ``--dry-run`` 预览）。
"""

from __future__ import annotations

import argparse
import contextlib
import sqlite3
from pathlib import Path

from nonebot import logger

from config import DB_PATH

# 当前 Schema 版本（v9：AstrBot 插件兼容层的会话与偏好表）
SCHEMA_VERSION = 9
# 备份文件名（放在数据库同目录）
BACKUP_FILENAME = "stella_memory_backup.db"

# 消息来源分级（source_kind）的合法取值——存储层的单一真相源。
# AT_MENTION：用户直接对 Bot 说（高密度证据，单次可晋升）
# PASSIVE   ：被动摄入的群聊（需复现才可晋升）
# BOT_SELF  ：Bot 自己的发言（**只作上下文，绝不产出候选**）
SOURCE_KINDS = frozenset({"AT_MENTION", "PASSIVE", "BOT_SELF"})
DEFAULT_SOURCE_KIND = "PASSIVE"


def normalize_source_kind(value: str | None) -> str:
    """把任意值规范为合法 source_kind；非法/缺省回退 PASSIVE。"""
    kind = (value or "").strip().upper()
    return kind if kind in SOURCE_KINDS else DEFAULT_SOURCE_KIND


# ── 表结构定义 ──────────────────────────────────────────
# (表名, 列名, ADD COLUMN 语句)
_ADDITIVE_COLUMNS: list[tuple[str, str, str]] = [
    # long_term_memories（旧表）：补上 v2 记忆字段
    (
        "long_term_memories",
        "memory_type",
        "ALTER TABLE long_term_memories ADD COLUMN memory_type TEXT DEFAULT 'FACT'",
    ),
    (
        "long_term_memories",
        "usage_tags",
        "ALTER TABLE long_term_memories ADD COLUMN usage_tags TEXT",
    ),
    (
        "long_term_memories",
        "visibility",
        "ALTER TABLE long_term_memories ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "long_term_memories",
        "trigger_data",
        "ALTER TABLE long_term_memories ADD COLUMN trigger_data TEXT",
    ),
    (
        "long_term_memories",
        "behavior_rule",
        "ALTER TABLE long_term_memories ADD COLUMN behavior_rule TEXT",
    ),
    (
        "long_term_memories",
        "confidence",
        "ALTER TABLE long_term_memories ADD COLUMN confidence REAL DEFAULT 1.0",
    ),
    (
        "long_term_memories",
        "status",
        "ALTER TABLE long_term_memories ADD COLUMN status TEXT DEFAULT 'ACTIVE'",
    ),
    # memory_candidates：补上 v2 记忆字段
    (
        "memory_candidates",
        "usage_tags",
        "ALTER TABLE memory_candidates ADD COLUMN usage_tags TEXT",
    ),
    (
        "memory_candidates",
        "visibility",
        "ALTER TABLE memory_candidates ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "memory_candidates",
        "trigger_data",
        "ALTER TABLE memory_candidates ADD COLUMN trigger_data TEXT",
    ),
    (
        "memory_candidates",
        "behavior_rule",
        "ALTER TABLE memory_candidates ADD COLUMN behavior_rule TEXT",
    ),
    # memories（主表）：补上 v2 记忆字段
    (
        "memories",
        "usage_tags",
        "ALTER TABLE memories ADD COLUMN usage_tags TEXT",
    ),
    (
        "memories",
        "visibility",
        "ALTER TABLE memories ADD COLUMN visibility TEXT DEFAULT 'OPEN'",
    ),
    (
        "memories",
        "trigger_data",
        "ALTER TABLE memories ADD COLUMN trigger_data TEXT",
    ),
    (
        "memories",
        "behavior_rule",
        "ALTER TABLE memories ADD COLUMN behavior_rule TEXT",
    ),
    # v3：消息来源分级（source_kind）——@ 对话 vs 被动摄入
    (
        "group_messages",
        "source_kind",
        "ALTER TABLE group_messages ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    (
        "memory_candidates",
        "source_kind",
        "ALTER TABLE memory_candidates ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    (
        "memories",
        "source_kind",
        "ALTER TABLE memories ADD COLUMN source_kind TEXT DEFAULT 'PASSIVE'",
    ),
    # v4：候选强化（交叉验证）——同一事实累积证据而非重复插入
    (
        "memory_candidates",
        "occurrence_count",
        "ALTER TABLE memory_candidates ADD COLUMN occurrence_count INTEGER DEFAULT 1",
    ),
    (
        "memory_candidates",
        "first_seen_at",
        "ALTER TABLE memory_candidates ADD COLUMN first_seen_at DATETIME",
    ),
    (
        "memory_candidates",
        "source_kinds",
        "ALTER TABLE memory_candidates ADD COLUMN source_kinds TEXT DEFAULT '[\"PASSIVE\"]'",
    ),
]

# 新增索引：按检索高频字段建索引，避免 SQLite 全表扫描
# 结构：(索引名, 所在表名, DDL)
_INDEXES: list[tuple[str, str, str]] = [
    (
        "idx_memories_space_type_status",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_space_type_status ON memories (group_shared_space, type, status)",
    ),
    (
        "idx_memories_space_visibility_status",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_space_visibility_status ON memories (group_shared_space, visibility, status)",
    ),
    (
        "idx_candidates_status",
        "memory_candidates",
        "CREATE INDEX IF NOT EXISTS idx_candidates_status ON memory_candidates (status)",
    ),
    (
        "idx_longterm_group_user_type",
        "long_term_memories",
        "CREATE INDEX IF NOT EXISTS idx_longterm_group_user_type ON long_term_memories (group_id, user_id, memory_type)",
    ),
    (
        "idx_memories_space_source_kind",
        "memories",
        "CREATE INDEX IF NOT EXISTS idx_memories_space_source_kind ON memories (group_shared_space, source_kind, status)",
    ),
    (
        "idx_group_messages_source_kind",
        "group_messages",
        "CREATE INDEX IF NOT EXISTS idx_group_messages_source_kind ON group_messages (group_id, source_kind, id)",
    ),
    (
        "idx_candidates_space_user_type_status",
        "memory_candidates",
        "CREATE INDEX IF NOT EXISTS idx_candidates_space_user_type_status "
        "ON memory_candidates (group_shared_space, user_id, type, status)",
    ),
    (
        "idx_astrbot_conversations_user",
        "astrbot_conversations",
        "CREATE INDEX IF NOT EXISTS idx_astrbot_conversations_user "
        "ON astrbot_conversations (user_id, updated_at DESC)",
    ),
]


# 记忆主表（memories）的规范 DDL：所有业务模块与该表打交道的建表/取数必须用它定义，
# 避免各处手抄一份导致加字段时漂移（benchmark 临时库也复用它）。
MEMORIES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    group_shared_space TEXT,
    user_id TEXT,
    type TEXT,
    content TEXT,
    content_raw TEXT,
    importance REAL,
    confidence REAL,
    status TEXT,
    confirmation_count INTEGER,
    last_confirmed_at DATETIME,
    last_accessed_at DATETIME,
    compressed_at DATETIME,
    compression_version INTEGER,
    is_atomized INTEGER,
    usage_tags TEXT,
    visibility TEXT DEFAULT 'OPEN',
    trigger_data TEXT,
    behavior_rule TEXT,
    source_kind TEXT DEFAULT 'PASSIVE',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_memories_table(conn: sqlite3.Connection) -> None:
    """确保 memories 表存在（幂等）。benchmark 临时库等场景复用规范 DDL。"""
    conn.execute(MEMORIES_TABLE_DDL)


# 主动发言状态的持久化表：每用户 @ 配额计数、上次追问内容、连续无回应次数。
# 独立于 additive column 体系（新表而非加列），升级路径见 _migrate。
PROACTIVE_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS proactive_state (
    group_id TEXT,
    user_id TEXT,
    at_count_today INTEGER DEFAULT 0,
    at_count_date TEXT,
    last_at_at DATETIME,
    last_asked_topic TEXT,
    last_asked_candidate_id TEXT,
    consecutive_no_reply INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_id, user_id)
)
"""


def create_proactive_state_table(conn: sqlite3.Connection) -> None:
    """确保 proactive_state 表存在（幂等）。

    主动发言状态必须落库：内存态用 time.monotonic()，重启后基准漂移无法持久化，
    而「问过谁什么」丢失会导致重启后重复追问同一个人同一件事。
    """
    conn.execute(PROACTIVE_STATE_TABLE_DDL)


GROUP_RUNTIME_STATE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS group_runtime_state (
    group_id TEXT PRIMARY KEY,
    proactive_muted INTEGER DEFAULT 0,
    muted_by TEXT,
    muted_at DATETIME,
    last_sleep_announce_date TEXT,
    last_wakeup_announce_date TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_group_runtime_state_table(conn: sqlite3.Connection) -> None:
    """确保 group_runtime_state 表存在（幂等）。

    保存两类必须跨重启存活的群级状态：

    - ``proactive_muted``：管理员的运行时静音开关。管理员关掉它通常是因为
      出了问题，重启不该把它悄悄打开；
    - ``last_*_announce_date``：睡眠/苏醒播报的去重锚点。播报由定时任务触发，
      不记录已播报日期的话，睡眠期内重启会重复播报「我去睡了」。
    """
    conn.execute(GROUP_RUNTIME_STATE_TABLE_DDL)


# 用户画像表（v8 起）：按群组共享空间隔离——同一空间内的多个 QQ 群共享一份画像，
# 不同空间彼此独立；共用一份会让 _merge_traits 把两个空间的特征混在一起，
# 使「群A 一个形象、群B 另一个形象」在认知层面无法成立；interaction_count
# （互动次数）也应分空间计数。
USER_PROFILES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    group_shared_space TEXT,
    user_id TEXT,
    nickname TEXT,
    personality_traits TEXT,
    agent_attitude TEXT,
    interaction_count INTEGER DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (group_shared_space, user_id)
)
"""


def create_user_profiles_table(conn: sqlite3.Connection) -> None:
    """确保 user_profiles 表存在（幂等）。

    v8 起画像按 (group_shared_space, user_id) 隔离：同一空间内的多个 QQ 群共享
    一份画像，不同空间彼此独立；交互计数（interaction_count）也应分空间统计。
    独立于 additive column 体系（新表而非加列），升级路径见 _migrate。
    """
    conn.execute(USER_PROFILES_TABLE_DDL)


# 记忆候选表（v8 起）：以 group_shared_space 归属。
# 此前在 consolidator 与 memory_manager 各手抄一份（字段易漂移），v8 起以本处为
# 单一真相源，建表一律从这里走。
MEMORY_CANDIDATES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS memory_candidates (
    id TEXT PRIMARY KEY,
    group_shared_space TEXT,
    user_id TEXT,
    type TEXT,
    content TEXT,
    importance REAL,
    confidence REAL,
    evidence TEXT,
    status TEXT,
    source_message_ids TEXT,
    usage_tags TEXT,
    visibility TEXT DEFAULT 'OPEN',
    trigger_data TEXT,
    behavior_rule TEXT,
    source_kind TEXT DEFAULT 'PASSIVE',
    occurrence_count INTEGER DEFAULT 1,
    first_seen_at DATETIME,
    source_kinds TEXT DEFAULT '["PASSIVE"]',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_memory_candidates_table(conn: sqlite3.Connection) -> None:
    """确保 memory_candidates 表存在（幂等）。

    字段与 consolidator / memory_manager 手抄版本一致，仅 ``group_id`` 改名为
    ``group_shared_space``。v8 起本处为单一真相源。
    """
    conn.execute(MEMORY_CANDIDATES_TABLE_DDL)


# 原子事实表（v8 起）：以 group_shared_space 归属。
# 此前在 consolidator 与 memory_manager 各手抄一份（字段易漂移），v8 起以本处为
# 单一真相源，建表一律从这里走。
ATOMIC_FACTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS atomic_facts (
    id TEXT PRIMARY KEY,
    memory_id TEXT,
    group_shared_space TEXT,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    confidence REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def create_atomic_facts_table(conn: sqlite3.Connection) -> None:
    """确保 atomic_facts 表存在（幂等）。

    字段与 consolidator / memory_manager 手抄版本一致，仅 ``group_id`` 改名为
    ``group_shared_space``。v8 起本处为单一真相源。
    """
    conn.execute(ATOMIC_FACTS_TABLE_DDL)


# AstrBot 插件兼容层的对话表（v9 起）。
# 刻意与 Stella 自己的记忆系统隔离：插件的多轮对话不参与记忆整合，也不会被记忆
# 压缩任务动到。user_id 存的是 unified_msg_origin（platform:type:session_id），
# 与上游 AstrBot 的语义一致。content 是 JSON 字符串而非 list——上游 Conversation
# 的 history 字段就是字符串，插件里到处 json.loads(conv.history)。
ASTRBOT_CONVERSATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS astrbot_conversations (
    cid TEXT PRIMARY KEY,
    platform_id TEXT,
    user_id TEXT,
    content TEXT,
    title TEXT,
    persona_id TEXT,
    token_usage INTEGER DEFAULT 0,
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
)
"""


def create_astrbot_conversations_table(conn: sqlite3.Connection) -> None:
    """确保 astrbot_conversations 表存在（幂等）。"""
    conn.execute(ASTRBOT_CONVERSATIONS_TABLE_DDL)


# AstrBot 插件兼容层的偏好表（v9 起），对应上游的 sp（SharedPreferences）。
# 三段主键与上游一致：scope（umo / plugin / global）、scope_id、key。
ASTRBOT_PREFERENCES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS astrbot_preferences (
    scope TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at INTEGER DEFAULT 0,
    PRIMARY KEY (scope, scope_id, key)
)
"""


def create_astrbot_preferences_table(conn: sqlite3.Connection) -> None:
    """确保 astrbot_preferences 表存在（幂等）。"""
    conn.execute(ASTRBOT_PREFERENCES_TABLE_DDL)


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    """判断表是否存在。"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    )
    return cursor.fetchone() is not None


def _column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    """判断表中是否已存在某列。"""
    if not _table_exists(cursor, table):
        return True  # 表不存在视为“无需加列”，由建表语句负责
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def _get_schema_version(conn: sqlite3.Connection) -> int:
    """读取当前 schema 版本；无版本表时返回 0（表示旧库，需要迁移）。"""
    try:
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE k='version'"
        ).fetchone()
        return int(row[0]) if row and row[0] else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    """写入 schema 版本号（幂等 upsert）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            k TEXT PRIMARY KEY,
            version INTEGER,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        INSERT INTO schema_meta (k, version, updated_at)
        VALUES ('version', ?, CURRENT_TIMESTAMP)
        ON CONFLICT(k) DO UPDATE SET version = excluded.version, updated_at = CURRENT_TIMESTAMP
        """,
        (version,),
    )


def backup_database(db_path: Path = DB_PATH) -> Path:
    """把数据库备份为同目录下 ``stella_memory_backup.db``。

    用 SQLite 在线备份 API 复制，避免文件被占用时直接复制失败。
    若备份已存在则跳过（保留第一次的原始库，防止误覆盖）。
    """
    backup = db_path.parent / BACKUP_FILENAME
    if backup.exists():
        logger.info(f"📦 [Schema] 备份已存在，跳过: {backup}")
        return backup
    conn = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(backup)
        try:
            conn.backup(dst)
        finally:
            dst.close()
    finally:
        conn.close()
    logger.info(f"📦 [Schema] 数据库已备份到 {backup}")
    return backup


def _migrate(conn: sqlite3.Connection, dry_run: bool = False) -> int:
    """执行增量迁移：加列 + 建索引。返回本次变更的列/索引数量（dry_run 时不落盘）。

    每条变更独立 try/except：单个失败（如旧表结构异常）不拖垮整批迁移，
    剩余项照常执行（幂等，重跑会续上失败的项）。
    """
    cursor = conn.cursor()
    changes = 0
    # v8：旧库检测——记忆/画像表仍使用 group_id 列时给出明确告警。
    # v8 不做自动迁移（同 v7），继续运行会因列名不匹配导致记忆读写失败。
    # 注意 _column_exists 在表不存在时返回 True，必须先 _table_exists 再判断。
    # 有明确报错比静默失败好得多：别人（或几个月后的自己）拿旧库跑起来时不会
    # 看着记忆「读不到、写不进」而毫无头绪。
    if (
        _table_exists(cursor, "memories") and _column_exists(cursor, "memories", "group_id")
    ) or (
        _table_exists(cursor, "user_profiles") and _column_exists(cursor, "user_profiles", "group_id")
    ):
        logger.error(
            "检测到 v8 之前的旧库（记忆表仍使用 `group_id` 列）。v8 不做自动迁移——"
            "请停止程序、把 `DB_PATH` 对应文件与 `stella_memory_backup.db` 一起归档，"
            "重启后程序会建立 v8 新库。当前运行会因列名不匹配导致记忆读写失败。"
        )
    # v5：主动发言状态表（新表，不属于 additive column 范畴）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(PROACTIVE_STATE_TABLE_DDL)
    # v6：群级运行时状态表（新表，不属于 additive column 范畴）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(GROUP_RUNTIME_STATE_TABLE_DDL)
    # v7：用户画像表（新表，不属于 additive column 范畴；规范 DDL 与
    # consolidator 建表共用，避免手抄两份造成字段漂移）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(USER_PROFILES_TABLE_DDL)
    # v8：记忆/画像表统一按 group_shared_space 归属（新库直接建新列名；
    # 旧库见上方旧库检测告警）。create_memories_table 一并加上——memories 表
    # 目前由业务模块惰性建，schema 迁移时顺手保证存在更稳。
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            create_user_profiles_table(conn)
            create_memory_candidates_table(conn)
            create_atomic_facts_table(conn)
            create_memories_table(conn)
    # v9：AstrBot 插件兼容层的会话与偏好表（新表，与记忆系统隔离）
    if not dry_run:
        with contextlib.suppress(sqlite3.OperationalError):
            create_astrbot_conversations_table(conn)
            create_astrbot_preferences_table(conn)
    for table, column, ddl in _ADDITIVE_COLUMNS:
        if _column_exists(cursor, table, column):
            continue
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [Schema] 加列失败 {table}.{column}: {e}")
    for name, table, ddl in _INDEXES:
        # 表还不存在（业务表由各模块惰性建）→ 跳过索引，避免 CREATE INDEX 报 no such table
        if not _table_exists(cursor, table):
            if dry_run:
                changes += 1
            continue
        if _index_exists(cursor, name):
            continue
        if dry_run:
            changes += 1
            continue
        try:
            cursor.execute(ddl)
            changes += 1
        except sqlite3.OperationalError as e:
            logger.warning(f"⚠️ [Schema] 建索引失败 {name}: {e}")
    return changes


def _index_exists(cursor: sqlite3.Cursor, index: str) -> bool:
    """判断索引是否已存在（用于幂等，避免 IF NOT EXISTS 每次都被计入变更）。"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index,),
    )
    return cursor.fetchone() is not None


def _missing_v2_columns(conn: sqlite3.Connection) -> list[str]:
    """返回现有业务表中仍缺的 v2 列（用于版本号已到位但缺列时修补）。"""
    cursor = conn.cursor()
    return [
        f"{table}.{column}"
        for table, column, _ in _ADDITIVE_COLUMNS
        if _table_exists(cursor, table) and not _column_exists(cursor, table, column)
    ]


def ensure_v2_schema(db_path: Path = DB_PATH) -> bool:
    """幂等地把数据库升级到 v2 Schema；返回是否发生了实际迁移。

    - 数据库不存在 → 直接返回 False（由各业务模块建表即可）；
    - 已经是 v2 → 跳过，返回 False；
    - 首次迁移 → 先备份，再加列/建索引，最后写版本号，返回 True。
    """
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        changes = 0
        # 版本已到位但实际缺列（历史脏库：旧建表语句没带 v2 列）→ 仍然补齐
        if _get_schema_version(conn) >= SCHEMA_VERSION:
            missing = _missing_v2_columns(conn)
            if not missing:
                return False
            logger.warning(f"⚠️ [Schema] 版本已到 v{SCHEMA_VERSION} 但缺列，正在修补: {missing}")
        # 首次迁移才备份，避免每次启动都生成多余备份
        if _get_schema_version(conn) < SCHEMA_VERSION:
            backup_database(db_path)
        changes = _migrate(conn, dry_run=False)
        conn.commit()
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        if changes:
            logger.info(f"🔧 [Schema] 记忆系统已补齐到 v{SCHEMA_VERSION}（变更 {changes} 项）")
        return changes > 0
    except Exception as e:
        logger.warning(f"⚠️ [Schema] 迁移失败（回滚重试）: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def dry_run_report(db_path: Path = DB_PATH) -> None:
    """打印迁移预览：列出将要添加的列与索引，不落盘。"""
    if not db_path.exists():
        print(f"[Schema] 数据库不存在: {db_path}")
        return
    conn = sqlite3.connect(db_path)
    try:
        version = _get_schema_version(conn)
        print(f"[Schema] 当前版本: {version}（目标 v{SCHEMA_VERSION}）")
        if version >= SCHEMA_VERSION:
            print("[Schema] 已是最新版本，无需迁移")
            return
        print("\n[Schema] 将执行以下变更（dry-run，未落盘）:")
        for table, column, _ in _ADDITIVE_COLUMNS:
            if not _column_exists(conn.cursor(), table, column):
                print(f"  + {table}.{column}")
        for name, _, _ in _INDEXES:
            print(f"  + 索引 {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stella 记忆系统 Schema 迁移")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际迁移")
    parser.add_argument("--backup", action="store_true", help="仅备份数据库，不迁移")
    args = parser.parse_args()
    if args.backup:
        backup_database()
        print(f"[Schema] 备份完成: {DB_PATH.parent / BACKUP_FILENAME}")
    elif args.dry_run:
        dry_run_report()
    else:
        if ensure_v2_schema():
            print("[Schema] 迁移完成")
        else:
            print("[Schema] 无需迁移或迁移失败（详见日志）")
