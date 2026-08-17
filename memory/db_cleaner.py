# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""数据库清理工具 —— 清理测试阶段因频繁重启产生的混乱记忆数据

用户画像（user_profiles）默认保留，短期/长期记忆可清理。
用法：
    手动运行:  python -m memory.db_cleaner --full
    或在 settings.py 中设置 DB_CLEANUP_ON_START = True 时，随程序启动自动清理。
"""
import argparse
import contextlib
import sqlite3
import time

from nonebot import logger

from config import (
    DB_PATH,
    MESSAGE_CLEANUP_KEEP_COUNT,
    MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED,
)

# 上次消息清理的时间戳文件
_LAST_CLEANUP_FILE = DB_PATH.parent / ".last_message_cleanup"


def clean_db(
    clear_short_term: bool = True,
    clear_long_term: bool = True,
    reset_checkpoint: bool = True,
    clear_messages: bool = False,
) -> dict:
    """清理记忆数据。返回各表清理的行数。"""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    results = {}
    if clear_short_term:
        cur.execute("DELETE FROM short_term_context")
        results["short_term_context"] = cur.rowcount
    if clear_long_term:
        for table_name in ["long_term_memories", "memory_candidates", "memories", "atomic_facts", "memory_traces"]:
            try:
                cur.execute(f"DELETE FROM {table_name}")
                results[table_name] = cur.rowcount
            except sqlite3.OperationalError:
                results[table_name] = 0
    if reset_checkpoint:
        cur.execute("DELETE FROM consolidation_state")
        results["consolidation_state"] = cur.rowcount
    if clear_messages:
        for table_name in ["group_messages", "messages"]:
            try:
                cur.execute(f"DELETE FROM {table_name}")
                results[table_name] = cur.rowcount
            except sqlite3.OperationalError:
                results[table_name] = 0
        # 重置自增序列，否则新消息 id 从旧最大值继续，导致 checkpoint 无法匹配
        for seq_name in ["group_messages", "messages"]:
            with contextlib.suppress(sqlite3.OperationalError):
                cur.execute("DELETE FROM sqlite_sequence WHERE name = ?", (seq_name,))
    # 清空消息但保留 checkpoint 时（reset_checkpoint=False + clear_messages=True），
    # checkpoint 会大于新的最大 id（sqlite_sequence 已重置），整合将永远不再触发。
    # 无论是否重置 checkpoint 都统一对齐一次，保证两者一致。
    for (gid,) in cur.execute("SELECT group_id FROM consolidation_state").fetchall():
        _align_checkpoint(cur, gid)
    conn.commit()
    conn.close()
    return results


def print_summary():
    """打印各表记录数，便于确认清理效果。"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    print(f"[DB] 数据库: {DB_PATH}")
    for table in ["user_profiles", "short_term_context", "memory_candidates", "memories", "atomic_facts", "long_term_memories", "group_messages", "consolidation_state"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table}: {cur.fetchone()[0]} 条")
        except sqlite3.OperationalError:
            print(f"  {table}: (表不存在)")
    conn.close()


def _align_checkpoint(cur: sqlite3.Cursor, group_id: str) -> int:
    """把该群的 checkpoint 夹到消息表的实际 id 范围内。

    checkpoint（consolidation_state.last_processed_id）与 group_messages 必须
    一起维护，否则会出现两种相反的故障：

    - checkpoint 指向**已被删除**的旧 id → `id > checkpoint` 命中全部剩余消息，
      整合器把已处理过的消息重新整理一遍（2026-08-15 实测 1487 条）；
    - checkpoint 大于表内最大 id（清空消息并重置 sqlite_sequence 后）→
      `id > checkpoint` 永远为空，整合彻底停摆。

    对齐规则：低于最小 id 时抬到 `min_id - 1`（表示「最旧的那条还没处理」）；
    高于最大 id 时压到 `max_id`（表示「都处理完了」）。表为空时归零。
    返回调整后的值（未调整则返回原值）。
    """
    row = cur.execute(
        "SELECT last_processed_id FROM consolidation_state WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    if row is None:
        return 0
    checkpoint = int(row[0] or 0)

    bounds = cur.execute(
        "SELECT MIN(id), MAX(id) FROM group_messages WHERE group_id = ?",
        (group_id,),
    ).fetchone()
    min_id, max_id = (bounds or (None, None))

    if min_id is None:
        # 该群消息已被清空：checkpoint 归零，等新消息进来重新开始
        target = 0
    elif checkpoint < min_id - 1:
        target = min_id - 1
    elif checkpoint > max_id:
        target = max_id
    else:
        return checkpoint

    cur.execute(
        "UPDATE consolidation_state SET last_processed_id = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE group_id = ?",
        (target, group_id),
    )
    logger.warning(
        f"🔧 [DBCleaner] 群 {group_id} checkpoint 越界，已对齐: {checkpoint} → {target}"
        f"（消息 id 范围 {min_id}~{max_id}）"
    )
    return target


def trim_group_messages(keep_count: int = MESSAGE_CLEANUP_KEEP_COUNT) -> dict[str, int]:
    """定期清理 group_messages 表：每个群仅保留最近 keep_count 条消息。

    删除旧消息后会把该群的整合 checkpoint 对齐到剩余消息范围，避免
    `id > checkpoint` 命中全部剩余消息导致重复整理。
    启用 MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED 时，清理边界不会超过
    checkpoint——积压中的未整合消息不会被删（否则内容永远进不了记忆系统）。

    返回 {"deleted": 总删除行数, "groups": 处理的群数}。
    """
    if not DB_PATH.exists():
        return {"deleted": 0, "groups": 0}

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 获取所有群 ID
    cur.execute("SELECT DISTINCT group_id FROM group_messages")
    group_ids = [row[0] for row in cur.fetchall()]

    total_deleted = 0
    for gid in group_ids:
        # 找到该群第 keep_count 条消息的 id
        cur.execute(
            "SELECT id FROM group_messages WHERE group_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
            (gid, keep_count - 1),
        )
        row = cur.fetchone()
        if row is None:
            # 该群消息不足 keep_count 条，无需清理
            continue
        cutoff_id = row[0]

        # 保护未整合的消息：只删 checkpoint 之前的部分。
        # 积压超过 keep_count 时，按条数算出的 cutoff 会落在未整合区间内，
        # 那些消息一旦删除就永远不会进入记忆系统。
        if MESSAGE_CLEANUP_PROTECT_UNCONSOLIDATED:
            ck_row = cur.execute(
                "SELECT last_processed_id FROM consolidation_state WHERE group_id = ?",
                (gid,),
            ).fetchone()
            checkpoint = int(ck_row[0] or 0) if ck_row else 0
            if checkpoint and checkpoint < cutoff_id:
                logger.warning(
                    f"⚠️ [DBCleaner] 群 {gid} 存在未整合积压，清理边界从 {cutoff_id} "
                    f"收紧到 checkpoint {checkpoint}（保留未整合消息）"
                )
                cutoff_id = checkpoint
            if cutoff_id <= 0:
                continue
        for table_name in ["group_messages", "messages"]:
            try:
                cur.execute(
                    f"DELETE FROM {table_name} WHERE group_id = ? AND id <= ?",
                    (gid, cutoff_id),
                )
                total_deleted += cur.rowcount
            except sqlite3.OperationalError:
                continue
        # 删掉旧消息后 checkpoint 可能指向已不存在的 id，必须立即对齐，
        # 否则 `id > checkpoint` 会命中全部剩余消息，导致重复整理
        _align_checkpoint(cur, gid)

    conn.commit()
    conn.close()
    _mark_cleanup_done()
    return {"deleted": total_deleted, "groups": len(group_ids)}


def align_all_checkpoints() -> int:
    """把所有群的 checkpoint 夹到消息表实际范围内；返回调整的群数。

    启动时调用，修正历史遗留的错位（如清理与 checkpoint 未对齐的旧库）。
    幂等：已对齐的群不产生任何写入。
    """
    if not DB_PATH.exists():
        return 0
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT group_id, last_processed_id FROM consolidation_state"
        ).fetchall()
        adjusted = 0
        for gid, before in rows:
            if _align_checkpoint(cur, gid) != int(before or 0):
                adjusted += 1
        conn.commit()
        conn.close()
        return adjusted
    except sqlite3.OperationalError:
        return 0


def log_source_kind_distribution() -> None:
    """输出各群消息的 source_kind 分布；某群 AT_MENTION=0 而 BOT_SELF>0 时告警。

    分布形如 ``📊 [Messages] 群 263402786: PASSIVE=530 AT_MENTION=42 BOT_SELF=88``。
    告警依据：AT_MENTION 是设计上唯一稳定的用户信息源（见 check_point#1），
    它长期为 0 与「Bot 有发言」是矛盾的——这个矛盾是 2026-08-17 缺陷
    （@ 消息因监听器优先级被拦截而从不入库）唯一可自动发现的信号。
    表不存在 / 查询失败 → 静默返回（不影响启动）。
    """
    if not DB_PATH.exists():
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        rows = cur.execute(
            "SELECT group_id, source_kind, COUNT(*) FROM group_messages "
            "GROUP BY group_id, source_kind"
        ).fetchall()
        conn.close()
    except sqlite3.OperationalError:
        return
    if not rows:
        return

    by_group: dict[str, dict[str, int]] = {}
    for gid, kind, count in rows:
        by_group.setdefault(str(gid), {})[str(kind)] = int(count)

    # 固定展示顺序：PASSIVE / AT_MENTION / BOT_SELF，其余来源按字母序附后
    known_kinds = ("PASSIVE", "AT_MENTION", "BOT_SELF")

    def _kind_key(k: str) -> tuple[int, str]:
        return (known_kinds.index(k) if k in known_kinds else len(known_kinds), k)

    for gid, kinds in by_group.items():
        parts = " ".join(
            f"{k}={v}" for k, v in sorted(kinds.items(), key=lambda kv: _kind_key(kv[0]))
        )
        logger.info(f"📊 [Messages] 群 {gid}: {parts}")
        if kinds.get("AT_MENTION", 0) == 0 and kinds.get("BOT_SELF", 0) > 0:
            logger.warning(
                f"⚠️ [Messages] 群 {gid} 有 Bot 发言但无 AT_MENTION 记录，"
                "@ 消息可能未入库（检查监听器优先级）"
            )


def needs_cleanup(max_age_hours: float = 24.0) -> bool:
    """检查是否需要执行消息清理（距上次清理超过 max_age_hours 小时）。"""
    if not _LAST_CLEANUP_FILE.exists():
        return True
    try:
        last_ts = float(_LAST_CLEANUP_FILE.read_text().strip())
        return (time.time() - last_ts) > max_age_hours * 3600
    except (ValueError, OSError):
        return True


def _mark_cleanup_done():
    """记录本次清理时间戳。"""
    with contextlib.suppress(OSError):
        _LAST_CLEANUP_FILE.write_text(str(time.time()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理 Stella 测试阶段产生的混乱记忆数据")
    parser.add_argument("--full", action="store_true", help="彻底清理（含原始消息记录 group_messages）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不实际清理")
    args = parser.parse_args()

    print("清理前状态：")
    print_summary()
    if args.dry_run:
        print("\n[dry-run] 未执行任何清理")
    else:
        results = clean_db(
            clear_short_term=True,
            clear_long_term=True,
            reset_checkpoint=True,
            clear_messages=args.full,
        )
        print(f"\n清理完成：{results}")
        print("（用户画像 user_profiles 已保留）")
        print("\n清理后状态：")
        print_summary()
