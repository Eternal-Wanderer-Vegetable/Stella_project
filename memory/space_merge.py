# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""空间合并：把若干共享空间的记忆与画像并进一个空间。

什么时候需要：用户先让两个群各自自动拿到 ``space_1`` / ``space_2``，后来写了
``config/spaces/casual.toml`` 把两个群划进同一个空间。此时 ``resolve_space()`` 返回
``casual``，而历史记忆还挂在 ``space_1`` / ``space_2`` 下——查不到、不报错、不抛异常。

2026-08-27 之前的「修法」是让用户手工执行一串 UPDATE（六张表，还要重建 FTS 索引，
漏一张就是静默丢记忆）。现在是一条命令。

刻意**不做**「启动时自动跟随配置改名」：合并会撞 ``user_profiles`` 的主键、需要明确
的合并语义，而且不可逆（合并后没有任何信息能把两个群的画像拆回来，只有
``origin_group_id`` 能定位来源行）。让用户改一行 toml 就静默触发一次跨群画像合并，
风险与收益不对称。

用法::

    python -m deploy space-merge --from space_1,space_2 --to casual --dry-run
    python -m deploy space-merge --from space_1,space_2 --to casual
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from config import DB_PATH, space_map
from memory import migrations, schema


@dataclass
class MergeReport:
    """合并结果。``moved`` 是「表 → 改写行数」，``conflicts`` 是画像撞主键的明细。"""

    sources: list[str] = field(default_factory=list)
    target: str = ""
    dry_run: bool = False
    moved: dict[str, int] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    ledger_changes: list[str] = field(default_factory=list)
    fts_rows: int | None = None
    backup_path: Path | None = None
    error: str | None = None

    def to_markdown(self) -> str:
        lines = [
            "# 空间合并" + ("（预演，未落盘）" if self.dry_run else ""),
            "",
            f"- 源空间：{'、'.join(f'`{s}`' for s in self.sources)}",
            f"- 目标空间：`{self.target}`",
        ]
        if self.backup_path:
            lines.append(f"- 操作前备份：`{self.backup_path.name}`")
        if self.error:
            lines += ["", f"**失败**：{self.error}", "", "已回滚，数据库未被改动。"]
            return "\n".join(lines)
        lines += ["", "## 改写行数", "", "| 表 | 行数 |", "|---|---|"]
        for table, count in self.moved.items():
            lines.append(f"| `{table}` | {count} |")
        if self.fts_rows is not None:
            lines.append(f"| `memories_fts`（重建） | {self.fts_rows} |")
        if self.ledger_changes:
            lines += ["", "## 账本", ""] + [f"- {c}" for c in self.ledger_changes]
        if self.conflicts:
            lines += [
                "",
                "## 画像冲突（同一个人在多个源空间都有画像）",
                "",
                "保留互动次数多的那份，另一份已丢弃——合并不可逆，如需核对请看备份。",
                "",
            ] + [f"- {c}" for c in self.conflicts]
        lines += [
            "",
            "合并**不可逆**：拆回去只能靠 `origin_group_id` 溯源列或上面那份备份。",
        ]
        return "\n".join(lines)


def _resolve_profile_conflicts(
    conn: sqlite3.Connection, sources: list[str], target: str, report: MergeReport
) -> None:
    """``user_profiles`` 主键是 ``(group_shared_space, user_id)``：同一个人在多个源
    空间各有一份画像时，合并会撞主键。

    策略：保留 ``interaction_count`` 最大的那份（互动最多的那个空间最了解他），其余
    删除并写进报告。并列时按空间名升序取先者，保证可复现。
    """
    cursor = conn.cursor()
    if "user_profiles" not in {t for t, _ in migrations.owned_tables(cursor)}:
        return
    spaces = [*sources, target]
    placeholders = ", ".join(["?"] * len(spaces))
    rows = cursor.execute(
        f"SELECT user_id, group_shared_space, COALESCE(interaction_count, 0) "
        f"FROM user_profiles WHERE group_shared_space IN ({placeholders})",
        spaces,
    ).fetchall()
    by_user: dict[str, list[tuple[str, int]]] = {}
    for user_id, space, count in rows:
        by_user.setdefault(str(user_id), []).append((str(space), int(count)))
    for user_id, entries in sorted(by_user.items()):
        if len(entries) < 2:
            continue
        winner = min(entries, key=lambda kv: (-kv[1], kv[0]))
        losers = [space for space, _ in entries if space != winner[0]]
        for space in losers:
            cursor.execute(
                "DELETE FROM user_profiles WHERE group_shared_space = ? AND user_id = ?",
                (space, user_id),
            )
        report.conflicts.append(
            f"用户 {user_id}：保留 `{winner[0]}`（互动 {winner[1]} 次），"
            f"丢弃 {'、'.join(f'`{s}`' for s in losers)}"
        )


def merge_spaces(
    sources: list[str],
    target: str,
    *,
    db_path: Path | None = None,
    ledger_path: Path | None = None,
    dry_run: bool = False,
) -> MergeReport:
    """把 ``sources`` 里的空间并进 ``target``，返回结构化报告。

    单个大事务：要么全成，要么整体回滚。``dry_run`` 就是「照跑一遍再 ROLLBACK」，
    所以预览里的行数与真实执行完全一致。
    """
    report = MergeReport(sources=list(sources), target=target, dry_run=dry_run)
    path = db_path or DB_PATH
    if target in sources:
        report.error = "目标空间不能同时出现在 --from 里。"
        return report
    if not path.is_file():
        report.error = f"数据库不存在：{path}"
        return report
    if not dry_run:
        report.backup_path = schema.backup_snapshot(path, "pre-merge")

    conn = sqlite3.connect(path)
    previous_isolation = conn.isolation_level
    conn.isolation_level = None
    try:
        conn.execute("BEGIN")
        cursor = conn.cursor()
        _resolve_profile_conflicts(conn, list(sources), target, report)
        placeholders = ", ".join(["?"] * len(sources))
        for table, owner in migrations.owned_tables(cursor):
            cursor.execute(
                f"UPDATE {table} SET {owner} = ? WHERE {owner} IN ({placeholders})",
                (target, *sources),
            )
            report.moved[table] = cursor.rowcount
        fts_result = migrations.MigrationResult(version=schema.SCHEMA_VERSION)
        migrations.rebuild_fts(conn, fts_result)
        report.fts_rows = cursor.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
        _update_ledger(sources, target, report, ledger_path or path.parent, dry_run=dry_run)
        if dry_run:
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
    except Exception as e:
        conn.execute("ROLLBACK")
        report.error = f"{type(e).__name__}: {e}"
    finally:
        conn.isolation_level = previous_isolation
        conn.close()
    return report


def _update_ledger(
    sources: list[str],
    target: str,
    report: MergeReport,
    ledger_dir: Path,
    *,
    dry_run: bool,
) -> None:
    """账本必须跟着改：否则下次启动 resolve_space 又把群解析回旧空间名。"""
    ledger_path = ledger_dir / space_map.LEDGER_FILENAME
    ledger, error = space_map.load_ledger(ledger_path)
    if error:
        report.ledger_changes.append(f"账本读取失败，未更新：{error}")
        return
    changed = {g: name for g, name in ledger.items() if name in sources}
    if not changed:
        report.ledger_changes.append("账本里没有指向源空间的群，无需更新")
        return
    for group in changed:
        ledger[group] = target
    if not dry_run:
        save_error = space_map.save_ledger(ledger_path, ledger)
        if save_error:
            report.ledger_changes.append(f"账本写入失败：{save_error}")
            return
    report.ledger_changes.append(
        "群 " + "、".join(str(g) for g in sorted(changed)) + f" 的空间已指向 `{target}`"
    )

