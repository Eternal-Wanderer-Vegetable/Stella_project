# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""按版本注册的 schema 迁移（重命名、回填、主键变更）。

与 ``memory/schema.py`` 里的 ``_migrate()`` 分工明确：

- ``schema._migrate()``：**加列 + 建表 + 建索引**。幂等、可重复跑、与版本号无关，
  作为每次迁移的收尾步骤（兼容历史脏库）。
- 本模块：**改结构 + 改数据**。每个版本一个函数、一个事务，成功后才推进
  ``schema_meta.version``。加列那套表达不了重命名与主键变更，硬塞进去会变成
  一串 ``with contextlib.suppress(OperationalError)``，失败了也看不出来。

v8 的语义变化是本模块存在的理由：归属列的值从「真实 QQ 群号」变成「空间名」。
因此**必须逐表判定**，一个「凡是 group_id 就改名」的脚本会写坏三类表：

- 按空间归属、需要改名 + 改值：``memories`` / ``memory_candidates`` /
  ``atomic_facts`` / ``user_profiles``（外加不能 ALTER 的 ``memories_fts``）；
- 按空间归属、但列名至今仍叫 ``group_id``：``long_term_memories``
  （值早已是空间名，见 ``retriever.py`` 的兜底查询）——**只改值、不改名**；
- 按真实 QQ 群归属，一个字都不能动：``group_messages`` / ``messages`` /
  ``consolidation_state`` / ``short_term_context`` / ``proactive_state`` /
  ``group_runtime_state``（这些是「当下这场对话的状态」，混群会让 Bot 在 A 群
  回应 B 群）。

硬约束：迁移写进去的空间名，必须等于运行时 ``config.spaces.resolve_space()`` 对该群
返回的值。不一致的后果是检索 ``WHERE group_shared_space='casual'`` 而行里存着
``'space_1'``——查不到、不报错、不抛异常，即「一切正常但什么都不记」。所以映射判据
只能复用 ``config.space_map``，不能在这里另写一套。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from config import space_map

# 按空间归属，且 v8 需要把 group_id 改名为 group_shared_space 的表
SPACE_RENAME_TABLES = ("memories", "memory_candidates", "atomic_facts", "user_profiles")
# 按空间归属，但列名保持 group_id（值早已是空间名，改名会写坏它）
SPACE_VALUE_ONLY_TABLES = ("long_term_memories",)
# 按真实 QQ 群归属：迁移绝不触碰。列在这里是为了让「漏了哪张表」这件事可被审查。
GROUP_SCOPED_TABLES = (
    "group_messages",
    "messages",
    "consolidation_state",
    "short_term_context",
    "proactive_state",
    "group_runtime_state",
)

OWNER_COLUMN = "group_shared_space"
LEGACY_OWNER_COLUMN = "group_id"
# 溯源列：迁移时回填真实群号，让空间合并可回退（否则合并后拆不回来）
ORIGIN_COLUMN = "origin_group_id"


@dataclass
class MigrationContext:
    """迁移期需要的外部判据。

    ``resolver`` 是三级解析（显式 toml → 账本 → 分配 space_N 并落盘）；
    ``known_groups`` 是「允许为之分配新空间」的群集合（ALLOWED_GROUPS ∪ 显式配置
    ∪ 账本）。不在其中的群号视为孤儿（用户已退群），归入 ``legacy_<群号>``——
    不给它分配 ``space_N``，避免一个已经不存在的群占用编号。
    """

    resolver: Callable[[int], str]
    known_groups: frozenset[int] = frozenset()
    known_spaces: frozenset[str] = frozenset()
    seen_spaces: set[str] = field(default_factory=set)

    def resolve(self, qq_group_id: int) -> str:
        name = self.resolver(qq_group_id)
        self.seen_spaces.add(name)
        return name

    def map_owner(self, raw: object) -> str:
        """把归属列的旧值映射为空间名。

        - 空值 → ``legacy_unknown``
        - 非纯数字 → 原样返回（已经是空间名，含 ``legacy_*``；重跑迁移时走这条）
        - 纯数字且是已知群 → 三级解析
        - 纯数字但不是已知群 → ``legacy_<群号>``
        """
        text = "" if raw is None else str(raw).strip()
        if not text:
            return space_map.LEGACY_UNKNOWN
        if not text.isdigit():
            return text
        group = int(text)
        if group <= 0 or group not in self.known_groups:
            return space_map.legacy_space_name(text)
        return self.resolve(group)


@dataclass
class MigrationResult:
    """单个版本的迁移结果（汇总进报告）。"""

    version: int
    changed_rows: int = 0
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── 上下文构造 ──────────────────────────────────────────


def context_from_paths(
    spaces_dir: Path,
    ledger_path: Path,
    allowed_groups: Iterable[int] = (),
    *,
    persist: bool = True,
) -> MigrationContext:
    """按目标安装目录的路径构造上下文（不 import ``config.settings``）。

    ``deploy migrate`` 用这条路径：迁移时目标 ``.env`` 可能刚写好，而
    ``config.settings`` 的常量在 import 时就冻结了，读到的会是空值。

    账本在分配新名后**立即落盘**：账本与 DB 必须在同一次迁移里一起写成，
    否则下次启动重新分配编号，记忆全挂在旧空间名下。``persist=False`` 供
    ``--dry-run`` 使用——预演不该改任何东西。
    """
    explicit = space_map.load_explicit_spaces(spaces_dir)
    ledger, ledger_error = space_map.load_ledger(ledger_path)
    known = frozenset(allowed_groups) | set(explicit.qq_to_space) | set(ledger)

    def resolver(qq_group_id: int) -> str:
        name = explicit.qq_to_space.get(qq_group_id)
        if name is not None:
            return name
        recorded = ledger.get(qq_group_id)
        if recorded is not None:
            return recorded
        if ledger_error:
            # 账本读不出时不分配新名，否则会覆盖一个存在但读不出的账本
            return space_map.legacy_space_name(qq_group_id)
        allocated = space_map.allocate_space_name(ledger)
        ledger[qq_group_id] = allocated
        if persist:
            space_map.save_ledger(ledger_path, ledger)
        return allocated

    return MigrationContext(
        resolver=resolver,
        known_groups=known,
        known_spaces=frozenset(explicit.space_to_qq) | set(ledger.values()),
    )


def runtime_context() -> MigrationContext:
    """运行时（Bot 启动 / doctor）用的上下文：直接复用 ``config.spaces``。

    刻意不另建一份解析器：账本只能有一个写入者，两份缓存各自分配会分到不同编号。
    """
    import config.spaces as spaces
    from config.settings import ALLOWED_GROUPS

    if spaces._qq_to_space is None:
        spaces._load()
    ledger = spaces._get_auto_ledger()
    return MigrationContext(
        resolver=spaces.resolve_space,
        known_groups=frozenset(ALLOWED_GROUPS) | set(spaces._qq_to_space) | set(ledger),
        known_spaces=frozenset(spaces._space_to_qq) | set(ledger.values()),
    )


# ── SQL 小工具 ──────────────────────────────────────────


def _columns(cursor: sqlite3.Cursor, table: str) -> list[str]:
    """返回表的列名；表不存在返回空列表。

    与 ``schema._column_exists`` 不同——后者在表不存在时返回 True（「无需加列」的
    语义）。迁移必须区分「没有这张表」与「有表但没这列」，所以另写一个严格版本。
    """
    try:
        rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return []
    return [row[1] for row in rows]


def owned_tables(cursor: sqlite3.Cursor) -> list[tuple[str, str]]:
    """列出「按空间归属」的表及其归属列，供改值/校验遍历。

    改名表用 ``group_shared_space``；``long_term_memories`` 用 ``group_id``。
    """
    result: list[tuple[str, str]] = []
    for table in SPACE_RENAME_TABLES:
        cols = _columns(cursor, table)
        if OWNER_COLUMN in cols:
            result.append((table, OWNER_COLUMN))
        elif LEGACY_OWNER_COLUMN in cols:
            result.append((table, LEGACY_OWNER_COLUMN))
    for table in SPACE_VALUE_ONLY_TABLES:
        cols = _columns(cursor, table)
        if LEGACY_OWNER_COLUMN in cols:
            result.append((table, LEGACY_OWNER_COLUMN))
        elif OWNER_COLUMN in cols:
            result.append((table, OWNER_COLUMN))
    return result


def _ensure_column(cursor: sqlite3.Cursor, table: str, column: str, ddl_type: str) -> bool:
    """表存在且缺列时加列；返回是否真的加了。"""
    cols = _columns(cursor, table)
    if not cols or column in cols:
        return False
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
    return True


# ── v7：user_profiles 主键改为按群隔离 ──────────────────


def migrate_v7(conn: sqlite3.Connection, ctx: MigrationContext) -> MigrationResult:
    """v7 只推进版本号，画像重建放在 v8 一并完成。

    为什么不在这里做：v7 的形状是 ``(group_id, user_id)``，那时还没有「空间」概念，
    所以这里只能按**真实群**挑一个归宿；而 v8 又要把群映射成空间，多个群可能落进
    同一空间——于是「消息量最大的群所在的空间」与「消息量最大的空间」会给出不同
    答案（40 条在 A 群/space_1，35+30 条在 B、C 群/casual）。已定的策略是后者，
    所以聚合必须在有空间名的那一级做。

    实践上也没有代价：公开发布过的版本只有 schema v5（2.2.0）与 v9（3.0.0），
    没有任何用户的库停在 v7/v8，v7→v8 永远是连着跑的。
    """
    return MigrationResult(
        version=7,
        notes=["user_profiles 的重建在 v8 一并完成（需要空间名才能按 C3 聚合）"],
    )


# ── v8：group_id → group_shared_space，值重写为空间名 ───


def _assign_legacy_profiles(
    conn: sqlite3.Connection, ctx: MigrationContext
) -> tuple[dict[str, str], list[str]]:
    """为旧的全局画像挑归宿：该用户**消息量最大的那个空间**（策略 C3）。

    2.2.0 的 ``user_profiles`` 主键是 ``user_id`` 单列，是一份跨所有群的全局画像；
    v8 起是 ``(group_shared_space, user_id)``，因此一条旧画像没有唯一归宿。
    其余空间的该用户从零开始建立认知——这与 v7 分群隔离的设计意图一致。

    并列时按空间名升序取先者（确定性；否则两次迁移可能给出不同结果）。
    查不到消息的用户归 ``legacy_unknown``：保留、不参与检索、绝不丢弃。
    """
    cursor = conn.cursor()
    message_cols = _columns(cursor, "group_messages")
    if "user_id" not in message_cols or LEGACY_OWNER_COLUMN not in message_cols:
        return {}, ["group_messages 不可用，旧画像全部归入 legacy_unknown"]
    stats: dict[str, dict[str, int]] = {}
    for user_id, group_id, count in cursor.execute(
        "SELECT user_id, group_id, COUNT(*) FROM group_messages GROUP BY user_id, group_id"
    ):
        space = ctx.map_owner(group_id)
        bucket = stats.setdefault(str(user_id), {})
        bucket[space] = bucket.get(space, 0) + int(count)
    assignments: dict[str, str] = {}
    notes: list[str] = []
    for user_id, counts in sorted(stats.items()):
        total = sum(counts.values())
        space = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        assignments[user_id] = space
        share = counts[space] * 100 // max(total, 1)
        notes.append(
            f"画像 {user_id} 已归入 {space}"
            f"（该用户 {counts[space]}/{total} ≈ {share}% 的消息在此空间），"
            f"其余空间将重新建立认知"
        )
    return assignments, notes


_PROFILE_CARRY_COLUMNS = (
    "nickname",
    "personality_traits",
    "agent_attitude",
    "interaction_count",
    "updated_at",
)


def _rebuild_legacy_user_profiles(
    conn: sqlite3.Connection, ctx: MigrationContext, result: MigrationResult
) -> None:
    """把「全局画像」重建为按空间归属的表（SQLite 改主键的标准三步）。

    只在旧形状（既无 ``group_shared_space`` 也无 ``group_id``）下动手；已经有群/空间
    维度的库交给后面的改名 + 改值步骤。
    """
    from memory.schema import USER_PROFILES_TABLE_DDL

    cursor = conn.cursor()
    cols = _columns(cursor, "user_profiles")
    if not cols or OWNER_COLUMN in cols or LEGACY_OWNER_COLUMN in cols:
        return

    assignments, notes = _assign_legacy_profiles(conn, ctx)
    result.notes.extend(notes)
    carry = [c for c in _PROFILE_CARRY_COLUMNS if c in cols]
    temp = "user_profiles_v8_new"
    cursor.execute(
        USER_PROFILES_TABLE_DDL.replace(
            "IF NOT EXISTS user_profiles", f"IF NOT EXISTS {temp}", 1
        )
    )
    rows = cursor.execute(f"SELECT user_id, {', '.join(carry)} FROM user_profiles").fetchall()
    placeholders = ", ".join(["?"] * (len(carry) + 2))
    for row in rows:
        user_id = str(row[0])
        space = assignments.get(user_id, space_map.LEGACY_UNKNOWN)
        cursor.execute(
            f"INSERT INTO {temp} ({OWNER_COLUMN}, user_id, {', '.join(carry)}) "
            f"VALUES ({placeholders})",
            (space, user_id, *row[1:]),
        )
        result.changed_rows += 1
    cursor.execute("DROP TABLE user_profiles")
    cursor.execute(f"ALTER TABLE {temp} RENAME TO user_profiles")
    result.notes.append(
        f"user_profiles 主键 user_id → (group_shared_space, user_id)，迁移 {len(rows)} 条画像"
    )
    if rows:
        result.warnings.append(
            "重建后的旧画像没有 origin_group_id（真实群号在全局画像里本就不存在）"
        )


def rebuild_fts(conn: sqlite3.Connection, result: MigrationResult) -> None:
    """DROP 重建 ``memories_fts`` 并从主表重灌（FTS5 虚拟表不能 ALTER）。

    分词沿用 ``retriever._segment_text``——分词方式必须与查询侧完全一致，各写一份
    必然漂移。retriever 不可用（未编译 FTS5 等）时降级为原文入库并记 warning。
    """
    cursor = conn.cursor()
    if not _columns(cursor, "memories"):
        return
    # 关掉 FTS 的部署不该被迁移偷偷建出索引表来；已经有表就必须修（旧结构的列名
    # 对不上会让检索静默降级）。开关读 retriever 的模块全局量——那是全项目唯一的读点。
    existed = bool(_columns(cursor, "memories_fts"))
    enabled = True
    try:
        from memory import retriever

        enabled = bool(retriever.RAG_SQLITE_FTS_ENABLED)
    except Exception:  # pragma: no cover - 配置缺失时按开启处理
        enabled = True
    if not existed and not enabled:
        result.notes.append("FTS 已关闭且库内无索引表，跳过全文索引重建")
        return
    try:
        from memory.retriever import _segment_text
    except Exception as e:  # pragma: no cover - 仅在依赖缺失时
        result.warnings.append(f"无法复用 retriever 分词（{e}），FTS 索引以原文入库")

        def _segment_text(text: str) -> str:  # type: ignore[misc]
            return text or ""

    fts_ddl = (
        "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5("
        "mem_id UNINDEXED, content, group_shared_space UNINDEXED, user_id UNINDEXED)"
    )
    # 索引可以随时从主表重建（retriever 发现行数不符时也会自愈），所以这里的任何失败
    # 都只降级为 warning——不能让一个可再生的索引把整级迁移拖回滚。
    try:
        cursor.execute("DROP TABLE IF EXISTS memories_fts")
        cursor.execute(fts_ddl)
        memory_cols = _columns(cursor, "memories")
        select_list = ", ".join(
            col if col in memory_cols else "NULL"
            for col in ("id", "group_shared_space", "user_id", "content")
        )
        where = "WHERE content IS NOT NULL" if "content" in memory_cols else ""
        if "status" in memory_cols:
            where = (where + " AND " if where else "WHERE ") + "status = 'active'"
        rows = cursor.execute(f"SELECT {select_list} FROM memories {where}").fetchall()
    except sqlite3.Error as e:
        result.warnings.append(f"FTS 索引重建失败（可后续自愈）: {e}")
        return
    records = []
    for memory_id, space, user_id, content in rows:
        text = _segment_text(content or "")
        if not text:
            continue
        records.append((memory_id, text, space, user_id))
    try:
        if records:
            cursor.executemany(
                "INSERT INTO memories_fts (mem_id, content, group_shared_space, user_id) "
                "VALUES (?, ?, ?, ?)",
                records,
            )
    except sqlite3.Error as e:
        result.warnings.append(f"FTS 索引重灌失败（可后续自愈）: {e}")
        return
    result.notes.append(f"memories_fts 已重建并重灌 {len(records)} 行")


def _owner_sort_key(value: object) -> tuple[int, int, str]:
    """归属值的全序：NULL 最前，其次按群号升序，最后按字符串。让报告与编号可复现。"""
    if value is None:
        return (0, 0, "")
    text = str(value)
    if text.isdigit():
        return (1, int(text), text)
    return (2, 0, text)


def _prewarm_spaces(conn: sqlite3.Connection, ctx: MigrationContext) -> None:
    """按群号**升序**先把空间名分配一遍，让 ``space_N`` 的编号与扫描顺序无关。

    否则编号取决于 ``SELECT DISTINCT`` 的返回顺序与表的遍历顺序——同一个旧库两次
    迁移可能给出不同编号，测试也无法断言。账本一旦写成就以账本为准，所以这个顺序
    只在「第一次分配」时起作用，但那一次必须可复现。
    """
    cursor = conn.cursor()
    groups: set[int] = set()
    scan = [*owned_tables(cursor), ("group_messages", LEGACY_OWNER_COLUMN)]
    for table, owner in scan:
        if owner not in _columns(cursor, table):
            continue
        for (value,) in cursor.execute(f"SELECT DISTINCT {owner} FROM {table}"):
            text = "" if value is None else str(value).strip()
            if text.isdigit() and int(text) in ctx.known_groups:
                groups.add(int(text))
    for group in sorted(groups):
        ctx.resolve(group)


def migrate_v8(conn: sqlite3.Connection, ctx: MigrationContext) -> MigrationResult:
    """归属列改名 + 值从「真实 QQ 群号」重写为「空间名」。

    步骤顺序不能调：溯源列必须在改值**之前**回填，改完值就再也拿不到真实群号了。
    """
    result = MigrationResult(version=8)
    cursor = conn.cursor()

    # -1. 先按群号升序分配空间名，保证编号可复现
    _prewarm_spaces(conn, ctx)

    # 0. 旧的全局画像先按 C3 重建（此时写进去的已是最终空间名）
    _rebuild_legacy_user_profiles(conn, ctx, result)

    # 1. 列改名（SQLite 3.25+ 支持 RENAME COLUMN；嵌入式 Python 3.12 自带 3.4x）
    for table in SPACE_RENAME_TABLES:
        cols = _columns(cursor, table)
        if not cols or OWNER_COLUMN in cols:
            continue
        if LEGACY_OWNER_COLUMN in cols:
            cursor.execute(
                f"ALTER TABLE {table} RENAME COLUMN {LEGACY_OWNER_COLUMN} TO {OWNER_COLUMN}"
            )
            result.notes.append(f"{table}: 列 group_id → group_shared_space")

    # 2. 溯源列 + 改值（同一遍扫描：先记真实群号，再改归属值）
    for table, owner in owned_tables(cursor):
        if table in SPACE_RENAME_TABLES:
            _ensure_column(cursor, table, ORIGIN_COLUMN, "TEXT")
        has_origin = ORIGIN_COLUMN in _columns(cursor, table)
        raw_values = sorted(
            (row[0] for row in cursor.execute(f"SELECT DISTINCT {owner} FROM {table}")),
            key=_owner_sort_key,
        )
        for raw in raw_values:
            text = "" if raw is None else str(raw)
            mapped = ctx.map_owner(raw)
            where = f"{owner} IS NULL" if raw is None else f"{owner} = ?"
            params: tuple = () if raw is None else (raw,)
            if has_origin and text.isdigit():
                cursor.execute(
                    f"UPDATE {table} SET {ORIGIN_COLUMN} = ? "
                    f"WHERE {where} AND {ORIGIN_COLUMN} IS NULL",
                    (text, *params),
                )
            if mapped != text:
                cursor.execute(
                    f"UPDATE {table} SET {owner} = ? WHERE {where}", (mapped, *params)
                )
                result.changed_rows += cursor.rowcount
                result.notes.append(
                    f"{table}.{owner}: {text or '(空)'} → {mapped}（{cursor.rowcount} 行）"
                )

    # 3. memory_traces：两列并存，回填空间列（诊断数据，重建会丢，只能 ALTER 补）
    _backfill_memory_traces(conn, ctx, result)

    # 4. FTS 索引重建
    rebuild_fts(conn, result)
    return result


def _backfill_memory_traces(
    conn: sqlite3.Connection, ctx: MigrationContext, result: MigrationResult
) -> None:
    """``memory_traces`` 两列并存：``group_id`` 是真实群、``group_shared_space`` 是空间。

    旧库只有前者，补上后者并回填。表名可由 ``MEMORY_TRACE_TABLE`` 改，所以从配置读。
    """
    try:
        from config.settings import MEMORY_TRACE_TABLE

        table = MEMORY_TRACE_TABLE
    except Exception:  # pragma: no cover - 迁移在无 .env 环境下跑
        table = "memory_traces"
    cursor = conn.cursor()
    cols = _columns(cursor, table)
    if not cols or LEGACY_OWNER_COLUMN not in cols:
        return
    _ensure_column(cursor, table, OWNER_COLUMN, "TEXT")
    raw_values = [
        row[0]
        for row in cursor.execute(
            f"SELECT DISTINCT {LEGACY_OWNER_COLUMN} FROM {table} WHERE {OWNER_COLUMN} IS NULL"
        )
    ]
    for raw in raw_values:
        mapped = ctx.map_owner(raw)
        where = (
            f"{LEGACY_OWNER_COLUMN} IS NULL" if raw is None else f"{LEGACY_OWNER_COLUMN} = ?"
        )
        params: tuple = () if raw is None else (raw,)
        cursor.execute(
            f"UPDATE {table} SET {OWNER_COLUMN} = ? WHERE {where} AND {OWNER_COLUMN} IS NULL",
            (mapped, *params),
        )
        result.changed_rows += cursor.rowcount
    if raw_values:
        result.notes.append(f"{table}: 已回填 {OWNER_COLUMN}")


# ── v9 / v10：建表与加列（结构变化交给收尾的 additive 步骤） ──


def migrate_v9(conn: sqlite3.Connection, ctx: MigrationContext) -> MigrationResult:
    """v9：AstrBot 兼容层的会话与偏好表（新表，与记忆系统隔离）。"""
    from memory.schema import (
        create_astrbot_conversations_table,
        create_astrbot_preferences_table,
    )

    create_astrbot_conversations_table(conn)
    create_astrbot_preferences_table(conn)
    return MigrationResult(version=9, notes=["astrbot_conversations / astrbot_preferences 已就绪"])


def migrate_v10(conn: sqlite3.Connection, ctx: MigrationContext) -> MigrationResult:
    """v10：溯源列 ``origin_group_id``（让空间合并可回退）。

    加列本身由收尾的 additive 步骤完成，这里负责**能补的回填**：v8 之前的库在
    migrate_v8 里已按真实群号填好；已经是 v9 的库（3.0.0 用户）值里只剩空间名，
    真实群号唯一的残留来源是 ``memory_traces``（两列并存）。补不齐的留 NULL，
    由 pipeline 在新写入时填上。
    """
    result = MigrationResult(version=10)
    cursor = conn.cursor()
    for table in SPACE_RENAME_TABLES:
        if _ensure_column(cursor, table, ORIGIN_COLUMN, "TEXT"):
            result.notes.append(f"{table}: 新增 {ORIGIN_COLUMN} 列")
    try:
        from config.settings import MEMORY_TRACE_TABLE

        trace_table = MEMORY_TRACE_TABLE
    except Exception:  # pragma: no cover
        trace_table = "memory_traces"
    trace_cols = _columns(cursor, trace_table)
    if LEGACY_OWNER_COLUMN in trace_cols and OWNER_COLUMN in trace_cols:
        # 一个空间只能回填出唯一群号时才敢填：空间里有多个群时无法判断是哪一个
        pairs = cursor.execute(
            f"SELECT {OWNER_COLUMN}, COUNT(DISTINCT {LEGACY_OWNER_COLUMN}), "
            f"MIN({LEGACY_OWNER_COLUMN}) FROM {trace_table} "
            f"WHERE {OWNER_COLUMN} IS NOT NULL AND {LEGACY_OWNER_COLUMN} IS NOT NULL "
            f"GROUP BY {OWNER_COLUMN}"
        ).fetchall()
        for space, distinct_groups, group_id in pairs:
            if int(distinct_groups) != 1:
                continue
            for table in SPACE_RENAME_TABLES:
                if ORIGIN_COLUMN not in _columns(cursor, table):
                    continue
                cursor.execute(
                    f"UPDATE {table} SET {ORIGIN_COLUMN} = ? "
                    f"WHERE {OWNER_COLUMN} = ? AND {ORIGIN_COLUMN} IS NULL",
                    (str(group_id), space),
                )
                result.changed_rows += cursor.rowcount
    if result.changed_rows:
        result.notes.append(f"由 {trace_table} 回填 {ORIGIN_COLUMN} 共 {result.changed_rows} 行")
    return result


MIGRATIONS: dict[int, Callable[[sqlite3.Connection, MigrationContext], MigrationResult]] = {
    7: migrate_v7,
    8: migrate_v8,
    9: migrate_v9,
    10: migrate_v10,
}


# ── 执行器 ──────────────────────────────────────────────


def snapshot_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """按空间归属的表 + 按群归属的表的行数快照，用于迁移后校验行数守恒。"""
    cursor = conn.cursor()
    counts: dict[str, int] = {}
    for table in (*SPACE_RENAME_TABLES, *SPACE_VALUE_ONLY_TABLES, *GROUP_SCOPED_TABLES):
        if not _columns(cursor, table):
            continue
        try:
            counts[table] = int(cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        except sqlite3.OperationalError:
            continue
    return counts


def run_migrations(
    conn: sqlite3.Connection,
    from_version: int,
    to_version: int,
    ctx: MigrationContext,
    *,
    dry_run: bool = False,
) -> list[MigrationResult]:
    """逐级执行迁移：每级一个事务，成功后才在**同一事务内**推进版本号。

    必须把 ``isolation_level`` 设为 None 自己管事务：Python sqlite3 的默认模式只在
    INSERT/UPDATE/DELETE 前隐式开事务，**DDL 走 autocommit**——那样 ALTER/DROP 失败
    时回滚不了，会留下一个改了一半的库。SQLite 本身支持事务性 DDL。

    ``dry_run`` 就是「照跑一遍再 ROLLBACK」：这是最准确的预览，代价是大库上要多花
    一次全量写入的时间。
    """
    from memory.schema import _set_schema_version

    results: list[MigrationResult] = []
    conn.commit()  # 关掉可能存在的隐式事务，否则 BEGIN 会报 nested transaction
    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        for version in range(from_version + 1, to_version + 1):
            step = MIGRATIONS.get(version)
            if step is None:
                continue
            conn.execute("BEGIN")
            try:
                result = step(conn, ctx)
                if dry_run:
                    conn.execute("ROLLBACK")
                else:
                    _set_schema_version(conn, version)
                    conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            results.append(result)
    finally:
        conn.isolation_level = previous_isolation
    return results


def verify_after_migration(
    conn: sqlite3.Connection,
    before: dict[str, int],
    ctx: MigrationContext,
) -> list[str]:
    """迁移后校验，返回失败项列表（空 = 通过）。

    迁移只改值不增删行，所以行数必须守恒——这条能抓住「改主键时漏了几行」这类
    最难发现的错误。空间名集合的检查抓的是另一类：值写成了运行时查不到的名字。
    """
    problems: list[str] = []
    cursor = conn.cursor()
    after = snapshot_row_counts(conn)
    for table, count in before.items():
        if table not in after:
            problems.append(f"{table}: 迁移后表消失（迁移前 {count} 行）")
        elif after[table] != count:
            problems.append(f"{table}: 行数 {count} → {after[table]}（迁移不应增删行）")

    allowed = set(ctx.known_spaces) | set(ctx.seen_spaces)
    for table, owner in owned_tables(cursor):
        empty = cursor.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {owner} IS NULL OR TRIM({owner}) = ''"
        ).fetchone()[0]
        if empty:
            problems.append(f"{table}.{owner}: 仍有 {empty} 行归属为空")
        for (value,) in cursor.execute(f"SELECT DISTINCT {owner} FROM {table}"):
            name = str(value or "")
            if not name or space_map.is_legacy_space(name) or name in allowed:
                continue
            problems.append(
                f"{table}.{owner}: 空间名 {name!r} 既不在配置/账本里也不是 legacy_*，"
                f"运行时可能查不到这些行"
            )

    if _columns(cursor, "memories") and _columns(cursor, "memories_fts"):
        active = cursor.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'active' AND content IS NOT NULL "
            "AND TRIM(COALESCE(content, '')) != ''"
        ).fetchone()[0]
        indexed = cursor.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        if int(indexed) != int(active):
            problems.append(
                f"memories_fts: 索引 {indexed} 行 ≠ active 记忆 {active} 行（检索会静默漏召回）"
            )
    return problems


@dataclass
class MigrationReport:
    """一次完整迁移的结果，供 ``deploy migrate`` 写报告、GUI 渲染。"""

    from_version: int
    to_version: int
    steps: list[MigrationResult] = field(default_factory=list)
    additive_changes: int = 0
    problems: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    error: str | None = None
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.problems

    @property
    def changed_rows(self) -> int:
        return sum(step.changed_rows for step in self.steps)

    def to_markdown(self) -> str:
        lines = [
            "### 数据库迁移",
            "",
            f"- 版本：v{self.from_version} → v{self.to_version}"
            + ("（预演，未落盘）" if self.dry_run else ""),
            f"- 改动行数：{self.changed_rows}",
            f"- 加列/建索引：{self.additive_changes} 项",
        ]
        if self.backup_path:
            lines.append(f"- 迁移前备份：`{self.backup_path.name}`")
        for step in self.steps:
            lines.append(f"- **v{step.version}**")
            lines.extend(f"  - {note}" for note in step.notes)
            lines.extend(f"  - ⚠️ {warning}" for warning in step.warnings)
        if self.error:
            lines += ["", f"**迁移失败**：{self.error}", "", "旧库已回滚，备份仍在原处。"]
        if self.problems:
            lines += ["", "**校验未通过**："] + [f"- {p}" for p in self.problems]
        if self.ok and not self.dry_run:
            lines += ["", "校验通过：行数守恒、归属非空、空间名可解析、FTS 索引对齐。"]
        return "\n".join(lines)












