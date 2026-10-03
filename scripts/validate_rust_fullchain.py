#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""native Rust 晋升全链路验证（计划 §13.14 M6 硬件项）。

前置：``memory_rust/_native.pyd`` 已构建（maturin build --release 后把
target/release/_native.dll 拷为 memory_rust/_native.pyd）。脚本在临时库上跑：

1. **真实晋升 happy path**：MEMORY_BACKEND=rust + 真 native promote →
   候选 CONFIRMED、长期记忆落行、flow 事件记录实际 backend 与 commit 事实
   （fact_kind=commit 在业务事务确认之后）。
2. **弱冲突 parity 实验**（计划 §6.3 登记的 Python/Rust 现存差异，只观测
   不修）：同一 fixture 分别经 Python 与 Rust 后端，输出双方行为对照。
3. **native retrieve 冒烟**。

输出：控制台报告 + ``--json`` 机器可读结果（供汇总报告引用）。
不做任何生产写入；模型/网络零调用。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _prepare(db: Path) -> None:
    import memory.memory_manager as mm

    mm.DB_PATH = db
    mm.get_compressor = lambda: SimpleNamespace(
        maybe_compress=lambda reason=None: None)
    mm.MemoryManager()  # 建 schema


def _seed_candidate(db: Path, cid: str, *, content: str, importance: float,
                    confidence: float, status: str = "NEW",
                    type_: str = "FACT", occurrence: int = 1) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memory_candidates "
        "(id, group_shared_space, user_id, type, content, importance, "
        "confidence, status, occurrence_count) VALUES (?, 'space', '100', ?, ?, ?, ?, ?, ?)",
        (cid, type_, content, importance, confidence, status, occurrence))
    conn.commit()
    conn.close()


def _seed_memory(db: Path, mid: str, *, content: str, confidence: float,
                 importance: float = 0.9, type_: str = "FACT",
                 status: str = "CONFIRMED") -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO memories (id, group_shared_space, user_id, type, content, "
        "importance, confidence, status, created_at, updated_at) "
        "VALUES (?, 'space', '100', ?, ?, ?, ?, ?, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        (mid, type_, content, importance, confidence, status))
    conn.commit()
    conn.close()


def _run_promotion(mode: str) -> dict:
    import os

    import memory.memory_manager as mm
    from core.observability import turn_trace

    old_env = os.environ.get("MEMORY_BACKEND")
    os.environ["MEMORY_BACKEND"] = mode
    tmp = Path(tempfile.mkdtemp(prefix="rust-fullchain-"))
    db = tmp / "memory.db"
    trace_db = tmp / "turn_trace.db"
    turn_trace.configure(trace_db)
    result: dict[str, any] = {"mode": mode, "db": str(db)}
    try:
        _prepare(db)
        # 高质量候选走真实晋升
        _seed_candidate(db, "c-strong", content="用户名叫小明，住在杭州",
                        importance=0.8, confidence=0.95)
        # 弱冲突 fixture（与 tests/observability M2 parity 用例同参：
        # gate 通过 → conflict 扫描 → 弱候选 OBSERVING 后被晋升循环改写）
        _seed_memory(db, "m-old", content="用户喜欢Helldivers2",
                     confidence=0.9, type_="PREFERENCE", status="active")
        _seed_candidate(db, "c-weak", content="用户不喜欢Helldivers2",
                        importance=0.9, confidence=0.7, type_="PREFERENCE",
                        occurrence=2)

        from core.observability import message_flow as mf

        root = mf.begin_trace(root_kind="memory_promotion", origin="spawn",
                              scope="space", process_kind="memory")
        manager = mm.MemoryManager()
        manager.process_new_candidates(flow_ctx=root)
        mf.end_trace(root, outcome="batch_done")
        mf.flush()

        conn = sqlite3.connect(db)
        result["candidate_strong"] = conn.execute(
            "SELECT status FROM memory_candidates WHERE id='c-strong'"
        ).fetchone()[0]
        result["candidate_weak"] = conn.execute(
            "SELECT status FROM memory_candidates WHERE id='c-weak'"
        ).fetchone()[0]
        mem_row = conn.execute(
            "SELECT id, content, status FROM memories WHERE id NOT IN "
            "('m-old') ORDER BY created_at DESC LIMIT 1").fetchone()
        result["new_memory"] = list(mem_row) if mem_row else None
        result["old_memory_status"] = conn.execute(
            "SELECT status FROM memories WHERE id='m-old'").fetchone()[0]
        conn.close()

        tconn = sqlite3.connect(trace_db)
        events = tconn.execute(
            "SELECT node_id, kind, status, reason_code, metrics FROM flow_events "
            "WHERE trace_id=? ORDER BY id", (root.trace_id,)).fetchall()
        result["weak_candidate_events"] = [
            {"node": e[0], "kind": e[1], "status": e[2], "reason": e[3]}
            for e in events
            if "c-weak" in (e[4] or "") or "cand:c-weak" in (e[4] or "")
            or (e[0] == "memory.promotion.conflict")]
        tconn.close()
        result["flow_backend_decisions"] = [
            {"status": e[2], "reason": e[3], "metrics": json.loads(e[4] or "{}")}
            for e in events
            if e[0] == "memory.promotion.backend" and e[1] == "decision"]
        result["flow_commit_facts"] = [
            {"status": e[2], "reason": e[3]} for e in events
            if (e[1] == "decision" and "commit" in (e[3] or ""))
            or e[0] == "memory.promotion.commit"]
        result["flow_gate_count"] = sum(
            1 for e in events if e[0] == "memory.promotion.gate")
        result["flow_root_integrity"] = _root_integrity(trace_db, root.trace_id)
    except Exception as exc:  # 验证脚本自身要如实报告失败
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        turn_trace.configure(None)
        if old_env is None:
            os.environ.pop("MEMORY_BACKEND", None)
        else:
            os.environ["MEMORY_BACKEND"] = old_env
    return result


def _root_integrity(trace_db: Path, trace_id: str) -> dict:
    conn = sqlite3.connect(trace_db)
    row = conn.execute(
        "SELECT status, integrity, lost_events, producer_ended FROM message_traces "
        "WHERE trace_id=?", (trace_id,)).fetchone()
    conn.close()
    return {"status": row[0], "integrity": row[1], "lost": row[2],
            "producer_ended": bool(row[3])} if row else {}


def _retrieve_smoke() -> dict:
    """native retrieve 冒烟：真库无数据时返回空集即算通。"""
    import tempfile

    from memory_rust.backend import PromotionRequest  # noqa: F401
    from memory_rust.selector import resolve_backend

    decision, backend = resolve_backend("rust")
    if decision.selected != "rust":
        return {"native_loaded": False, "fallback_reason": decision.fallback_reason}
    import memory.memory_manager as mm

    tmp = Path(tempfile.mkdtemp(prefix="rust-retrieve-"))
    db = tmp / "memory.db"
    saved = mm.DB_PATH
    mm.DB_PATH = db
    try:
        mm.MemoryManager()  # 真 schema（含 schema_meta）
    finally:
        mm.DB_PATH = saved
    from memory_rust.backend import RetrievalRequest

    out = backend.retrieve(RetrievalRequest(
        db_path=db, group_shared_space="space", user_id=100, query="test",
        trigger="smoke", mode="hybrid", pool_limit=5))
    return {"native_loaded": True, "retrieve_ok": out is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None,
                        help="JSON 报告输出文件（绕开 stdout 上的 loguru 日志）")
    args = parser.parse_args()

    from memory_rust.selector import resolve_backend

    decision, _backend = resolve_backend("rust")
    report: dict = {
        "native_selected": decision.selected,
        "native_fallback_reason": decision.fallback_reason,
    }
    if decision.selected != "rust":
        print(f"native 不可用: {decision.fallback_reason}", file=sys.stderr)
        report["verdict"] = "BLOCKED"
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 3

    report["retrieve_smoke"] = _retrieve_smoke()
    report["rust_run"] = _run_promotion("rust")
    report["python_run"] = _run_promotion("python")

    rust = report["rust_run"]
    py = report["python_run"]
    ok = (
        not rust.get("error") and not py.get("error")
        and rust.get("candidate_strong") == "CONFIRMED"
        and rust.get("flow_root_integrity", {}).get("integrity") == "complete"
    )
    # parity 观察（计划 §6.3：现存差异如实报告，不判对错）
    report["parity_observation"] = {
        "rust": {
            "old_memory": rust.get("old_memory_status"),
            "weak_candidate": rust.get("candidate_weak"),
            "action": "observing_conflict(立即返回)" if rust.get(
                "candidate_weak") == "OBSERVING" else "见 rust_run",
        },
        "python": {
            "old_memory": py.get("old_memory_status"),
            "weak_candidate": py.get("candidate_weak"),
            "action": "weak_candidate_observing 后被晋升循环改写 CONFIRMED"
            if py.get("candidate_weak") == "CONFIRMED" else "见 python_run",
        },
        "differ": (rust.get("candidate_weak") != py.get("candidate_weak")),
    }
    report["verdict"] = "PASS" if ok else "FAIL"

    payload = json.dumps(report, ensure_ascii=False, indent=1, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"report written: {args.output}")
    else:
        print(payload)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
