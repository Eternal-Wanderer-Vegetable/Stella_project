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
import sqlite3
import time
from config import DB_PATH, MESSAGE_CLEANUP_KEEP_COUNT

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
            try:
                cur.execute("DELETE FROM sqlite_sequence WHERE name = ?", (seq_name,))
            except sqlite3.OperationalError:
                pass
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


def trim_group_messages(keep_count: int = MESSAGE_CLEANUP_KEEP_COUNT) -> dict[str, int]:
    """定期清理 group_messages 表：每个群仅保留最近 keep_count 条消息。

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
        for table_name in ["group_messages", "messages"]:
            try:
                cur.execute(
                    f"DELETE FROM {table_name} WHERE group_id = ? AND id <= ?",
                    (gid, cutoff_id),
                )
                total_deleted += cur.rowcount
            except sqlite3.OperationalError:
                continue

    conn.commit()
    conn.close()
    _mark_cleanup_done()
    return {"deleted": total_deleted, "groups": len(group_ids)}


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
    try:
        _LAST_CLEANUP_FILE.write_text(str(time.time()))
    except OSError:
        pass


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
