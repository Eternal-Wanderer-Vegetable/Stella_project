# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""参与评分 benchmark 回放驱动器（实现方案 §5 补充要求 C）。

从 ``group_messages`` 表按时间序回放真实群聊数据：

- PASSIVE 消息逐条喂 ``ParticipationManager.observe()``；
- BOT_SELF 行用于还原「Stella 刚发言」的惩罚输入（note_stella_spoke proactive）；
- AT_MENTION 行不进评分层（Hard Trigger 旁路，场景 A 的验证对象），
  仅近似还原被动应答记账（note_stella_spoke passive）。

用法::

    python -m tests.benchmark.participation.runner \
        [--db PATH] [--group 12345] [--since 2026-08-01] [--until 2026-09-01] \
        [--limit 5000] [--tables config/participation] [--no-anonymize]

输出 ``reports/<时间戳>_summary.md`` + ``.jsonl`` 决策明细（两次运行可 diff，
定位打分表改动的影响——这就是实现方案 §5 的调参闭环）。

脱敏：默认对 user_id 做稳定哈希，报告不含真实 QQ 号。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
SCENARIOS_TOML = Path(__file__).resolve().parent / "scenarios.toml"
DEFAULT_TABLES = REPO_ROOT / "config" / "participation"


def _parse_ts(value: str) -> float | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value[: len(fmt) + 2], fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_rows(
    db_path: Path,
    *,
    group_id: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
) -> list[tuple]:
    sql = (
        "SELECT group_id, user_id, content, source_kind, timestamp FROM group_messages"
        " WHERE content IS NOT NULL AND TRIM(content) <> '' AND content NOT LIKE '/%'"
    )
    params: list = []
    if group_id:
        sql += " AND group_id = ?"
        params.append(str(group_id))
    if since:
        sql += " AND timestamp >= ?"
        params.append(since)
    if until:
        sql += " AND timestamp <= ?"
        params.append(until)
    sql += " ORDER BY CAST(timestamp AS INTEGER), CAST(group_id AS INTEGER), id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def anonymize(user_id: str) -> str:
    return "u" + hashlib.sha1(user_id.encode()).hexdigest()[:8]


async def run(args: argparse.Namespace) -> int:
    from memory.participation import ParticipationManager

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[benchmark] 数据库不存在: {db_path}")
        return 1

    rows = fetch_rows(
        db_path, group_id=args.group, since=args.since, until=args.until, limit=args.limit
    )
    print(f"[benchmark] 回放 {len(rows)} 条消息（db={db_path}）")
    if not rows:
        return 1

    manager = ParticipationManager(
        tables_dir=Path(args.tables),
        persist=False,  # benchmark 永不写生产库
        jsonl_path=REPORTS_DIR / "_replay_scratch.jsonl",
        md_path=REPORTS_DIR / "_replay_scratch.md",
        log_level="off",  # 不刷实时日志；决策进 reports 的明细文件
    )
    if not manager.enabled:
        print(f"[benchmark] 打分表加载失败: {manager._store.last_error}")
        return 1
    if args.no_embedding:
        manager._embedding = False

    decisions: list[dict] = []
    last_spoke: dict[str, float] = {}
    for gid, uid, content, source_kind, ts_raw in rows:
        ts = _parse_ts(ts_raw) or 0.0
        gid_i = int(float(gid)) if gid else 0
        if source_kind == "BOT_SELF":
            manager.note_stella_spoke(gid_i, "proactive")
            last_spoke[str(gid)] = ts
            continue
        if source_kind == "AT_MENTION":
            manager.note_stella_spoke(gid_i, "passive")
            last_spoke[str(gid)] = ts
            continue
        # 重放时钟推进：话题生命周期用消息时间戳近似（真实系统另有 tick 定时任务）
        state = manager._state_for(gid_i)
        state.advance_lifecycle(manager._store.tables, now=ts)
        d = await manager.observe(gid_i, int(float(uid or 0)), content, now=ts)
        if d is None:
            continue
        bd = d.breakdown
        decisions.append({
            **(bd.as_dict() if bd else {}),
            "group": anonymize(str(gid)) if not args.no_anonymize else str(gid),
            "user": anonymize(str(uid)) if not args.no_anonymize else str(uid),
            "text": content,
            "decision": d.level,
            "mode": d.mode,
            "confidence": round(d.confidence, 2),
            "reason_flags": d.reason_flags,
            "is_tome": False,
        })

    # 清掉 scratch 日志（log_level=off 时本来也没写，防御性删除）
    for p in (REPORTS_DIR / "_replay_scratch.jsonl", REPORTS_DIR / "_replay_scratch.md"):
        with __import__("contextlib").suppress(FileNotFoundError):
            p.unlink()

    from tests.benchmark.participation import metrics

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_md = REPORTS_DIR / f"{stamp}_summary.md"
    results = metrics.evaluate(decisions, SCENARIOS_TOML, Path(args.tables))
    source_desc = (
        f"{db_path}（group={args.group or '全部'}, since={args.since or '起'}, "
        f"until={args.until or '止'}, {len(rows)} 行）"
    )
    metrics.write_report(results, decisions, out_md, source_desc=source_desc, tables_desc=str(args.tables))
    print(f"[benchmark] 报告: {out_md}")
    for r in results:
        verdict = "PASS" if r.passed else "FAIL" if r.passed is False else "SKIP"
        print(f"  [{verdict}] {r.name}: {r.detail}")
    failed = [r for r in results if r.passed is False]
    return 1 if failed else 0


def main() -> int:
    from config import DB_PATH

    ap = argparse.ArgumentParser(description="参与评分 benchmark（真实群聊数据回放）")
    ap.add_argument("--db", default=str(DB_PATH), help="数据库路径（默认生产库）")
    ap.add_argument("--group", default=None, help="只回放该群")
    ap.add_argument("--since", default=None, help="起始时间（YYYY-MM-DD）")
    ap.add_argument("--until", default=None, help="截止时间（YYYY-MM-DD）")
    ap.add_argument("--limit", type=int, default=None, help="最多回放条数")
    ap.add_argument("--tables", default=str(DEFAULT_TABLES), help="打分表目录（A/B 对比时各跑一份）")
    ap.add_argument("--no-anonymize", action="store_true", help="报告不脱敏（默认哈希 user_id）")
    ap.add_argument(
        "--no-embedding", action="store_true", default=False,
        help="关闭 embedding 语义通道（默认开启，走 MEMORY_EMBEDDING_* 配置）",
    )
    args = ap.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
