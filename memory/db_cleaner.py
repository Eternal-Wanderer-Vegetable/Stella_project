"""数据库清理工具 —— 清理测试阶段因频繁重启产生的混乱记忆数据

用户画像（user_profiles）默认保留，短期/长期记忆可清理。
用法：
    手动运行:  python -m memory.db_cleaner --full
    或在 settings.py 中设置 DB_CLEANUP_ON_START = True 时，随程序启动自动清理。
"""
import argparse
import sqlite3
from config import DB_PATH


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
        cur.execute("DELETE FROM long_term_memories")
        results["long_term_memories"] = cur.rowcount
    if reset_checkpoint:
        cur.execute("DELETE FROM consolidation_state")
        results["consolidation_state"] = cur.rowcount
    if clear_messages:
        cur.execute("DELETE FROM group_messages")
        results["group_messages"] = cur.rowcount
        # 重置自增序列，否则新消息 id 从旧最大值继续，导致 checkpoint 无法匹配
        try:
            cur.execute("DELETE FROM sqlite_sequence WHERE name = 'group_messages'")
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
    for table in ["user_profiles", "short_term_context", "long_term_memories", "group_messages", "consolidation_state"]:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"  {table}: {cur.fetchone()[0]} 条")
        except sqlite3.OperationalError:
            print(f"  {table}: (表不存在)")
    conn.close()


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
