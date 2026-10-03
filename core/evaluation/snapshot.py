# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""沙箱快照（计划 §6.7.3 snapshot 合同）：cutoff 冻结候选/记忆/checkpoint 状态。

纪律：

- **backup API**：导出用 SQLite 在线 ``backup`` 复制到沙箱——打开中的库
  带 WAL 时复制裸 db 文件会撕裂（丢已提交事务），**绝不允许**；backup 在
  一致性点上取到完整页。
- **缺表标 partial**：目标表不存在记入 manifest 并把快照标 ``partial``，
  不报错也不伪称完整复现（计划 §6.7.3「missing 模块标 partial snapshot，
  不能宣称完整复现」）。
- **cutoff 冻结**：带时间戳列的表在沙箱副本内剔除 ``ts > cutoff`` 的行，
  快照绝不包含 cutoff 之后的状态（防泄漏）。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.evaluation.dataset import _parse_utc

__all__ = [
    "SNAPSHOT_DB_NAME",
    "SNAPSHOT_MANIFEST_NAME",
    "SNAPSHOT_SCHEMA_VERSION",
    "SNAPSHOT_TABLES",
    "export_snapshot",
    "load_snapshot",
]

SNAPSHOT_MANIFEST_NAME = "manifest.json"
SNAPSHOT_DB_NAME = "snapshot.db"
SNAPSHOT_SCHEMA_VERSION = 1

# （表名，cutoff 可用的时间戳列）；consolidation_state 的 checkpoint 列
# last_processed_id 是消息水位，不按时间裁剪。
SNAPSHOT_TABLES: tuple[tuple[str, str | None], ...] = (
    ("memories", "created_at"),
    ("memory_candidates", "first_seen_at"),
    ("consolidation_state", None),
    ("participation_topics", None),
    ("proactive_state", None),
    ("group_runtime_state", "updated_at"),
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _trim_after_cutoff(
    conn: sqlite3.Connection, table: str, ts_column: str, cutoff_utc: datetime
) -> int:
    """在沙箱副本内删除 ``ts > cutoff`` 的行；返回删除行数。

    时间戳在 Python 侧容错解析后比较（SQLite 里 CURRENT_TIMESTAMP 与 ISO
    的空格/'T' 分隔符字典序不可靠，字符串直接比会在午夜附近错杀）。
    """
    stale_rowids: list[int] = []
    for row_id, ts_value in conn.execute(
        f"SELECT rowid, {ts_column} FROM {table} WHERE {ts_column} IS NOT NULL"
    ):
        parsed = _parse_utc(ts_value)
        if parsed is not None and parsed > cutoff_utc:
            stale_rowids.append(int(row_id))
    for start in range(0, len(stale_rowids), 500):
        chunk = stale_rowids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        with conn:
            conn.execute(f"DELETE FROM {table} WHERE rowid IN ({marks})", chunk)
    return len(stale_rowids)


def export_snapshot(
    db_path: Path | str,
    out_dir: Path | str,
    *,
    cutoff_utc: datetime,
) -> dict[str, Any]:
    """用 backup API 把源库冻结到 ``out_dir/snapshot.db``；返回 manifest dict。

    缺表不报错（标 partial）；带时间戳列的表剔除 cutoff 之后行。
    """
    source = Path(db_path)
    if not source.is_file():
        msg = f"源库不存在（拒绝回退生产默认路径）: {source}"
        raise FileNotFoundError(msg)
    if cutoff_utc.tzinfo is None:
        raise ValueError("cutoff_utc 必须是 aware datetime")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    target_path = out / SNAPSHOT_DB_NAME
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target_path)
        try:
            src.backup(dst)  # 一致性点整库复制，防打开中库 WAL 撕裂
            tables: dict[str, Any] = {}
            partial = False
            for name, ts_column in SNAPSHOT_TABLES:
                if not _table_exists(dst, name):
                    tables[name] = {"present": False, "rows": 0, "trimmed_after_cutoff": 0}
                    partial = True
                    continue
                rows = int(dst.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                trimmed = 0
                if ts_column is not None:
                    trimmed = _trim_after_cutoff(dst, name, ts_column, cutoff_utc)
                tables[name] = {
                    "present": True,
                    "rows": rows - trimmed,
                    "trimmed_after_cutoff": trimmed,
                }
        finally:
            dst.close()
    finally:
        src.close()

    manifest: dict[str, Any] = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "kind": "stella-evaluation-snapshot",
        "source_db_name": source.name,
        "cutoff_utc": cutoff_utc.astimezone(timezone.utc).isoformat(),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
        "partial": partial,
        "policy": "backup API 一致性复制；缺表标 partial 不报错；cutoff 后状态在副本内剔除",
    }
    (out / SNAPSHOT_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_snapshot(snapshot_dir: Path | str, target_db: Path | str) -> dict[str, Any]:
    """把沙箱快照装载为实验 workdir 内的状态库；返回 manifest 摘要。

    快照文件由本模块自建自管（导出后连接已关闭），复制它不是「复制打开中
    的裸 db 文件」；目标路径由调用方保证在实验 workdir 之下。
    """
    directory = Path(snapshot_dir)
    manifest_path = directory / SNAPSHOT_MANIFEST_NAME
    snapshot_path = directory / SNAPSHOT_DB_NAME
    if not manifest_path.is_file() or not snapshot_path.is_file():
        msg = f"快照目录不完整（缺 manifest.json 或 snapshot.db）: {directory}"
        raise FileNotFoundError(msg)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    target = Path(target_db)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(snapshot_path, target)
    return {
        "partial": bool(manifest.get("partial", False)),
        "cutoff_utc": manifest.get("cutoff_utc"),
        "tables": manifest.get("tables", {}),
        "loaded_to": str(target),
    }
