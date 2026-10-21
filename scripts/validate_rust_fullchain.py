#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""native Rust 晋升全链路验证（计划 §13.14 M6 硬件项）。

前置：当前 Python 环境可加载与 schema/API 合同匹配的
``memory_rust._native`` wheel（由 maturin 构建并安装）。脚本在临时库上跑：

1. **真实晋升 happy path**：通过 MemoryConsolidator 写入当前 accepted
   source evidence，再运行 MEMORY_BACKEND=rust 与真 native promote；验证候选
   CONFIRMED、长期记忆落行，以及 flow backend/commit 事实。
2. **弱冲突 parity 实验**：同一份带 accepted evidence 的低置信冲突候选，
   分别经 Python 与 Rust 后端；双方都应保留候选为 OBSERVING、旧记忆 active。
3. **native retrieve 冒烟**。

输出：控制台报告 + ``--output`` 指定的机器可读结果（供汇总报告引用）。
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
    import memory.consolidator as consolidator
    import memory.memory_manager as mm

    consolidator.DB_PATH = db
    mm.DB_PATH = db
    mm.get_compressor = lambda: SimpleNamespace(
        maybe_compress=lambda reason=None: None)
    mm.MemoryManager()  # 建 schema


def _seed_candidate(db: Path, source_id: int, *, content: str, importance: float,
                    confidence: float) -> str:
    """Create a candidate through the production accepted-evidence writer."""
    from memory.consolidator import MemoryConsolidator

    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS group_messages ("
        "id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT, "
        "source_kind TEXT, timestamp TEXT, msg_id TEXT, conversation_key TEXT, "
        "bot_id TEXT, reply_to_msg_id TEXT, reply_target_user_id TEXT, "
        "mentioned_user_ids_json TEXT, logical_message_id TEXT, part_index INTEGER, "
        "origin_msg_id TEXT, reply_recipient_user_id TEXT)"
    )
    conn.execute(
        "INSERT INTO group_messages "
        "(id, group_id, user_id, content, source_kind, msg_id, conversation_key, bot_id) "
        "VALUES (?, '1', '100', ?, 'AT_MENTION', ?, 'test-conversation', 'test-bot')",
        (source_id, content, str(source_id)),
    )
    conn.commit()
    conn.close()

    proposal = {
        "user_id": "100",
        "type": "PREFERENCE",
        "content": content,
        "importance": importance,
        "confidence": confidence,
        "source_message_ids": [source_id],
        "verification_contract": {
            "fact_subject_user_id": "100",
            "predicate_key": "preference.general",
            "canonical_value": content.removeprefix("我喜欢").removeprefix("我不喜欢"),
            "polarity": "negative" if content.startswith("我不喜欢") else "positive",
            "statement_kind": "explicit_preference",
            "temporal_qualifiers": [],
            "context_qualifiers": [],
            "supports": [
                {"source_message_id": source_id, "exact_support_span": content}
            ],
        },
    }
    writer = MemoryConsolidator.__new__(MemoryConsolidator)
    writer._write_memory_candidates(
        "space",
        [proposal],
        sender_ids=["100"],
        at_senders=["100"],
        origin_group_id=1,
        source_rows=[(source_id, "100", content, "AT_MENTION")],
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT id FROM memory_candidates WHERE group_shared_space = 'space' "
        "AND user_id = '100' AND content = ?",
        (content,),
    ).fetchone()
    conn.close()
    if row is None:
        raise RuntimeError(f"production candidate writer rejected fixture: {content}")
    return str(row[0])


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
        strong_candidate_id = _seed_candidate(
            db, 1, content="我喜欢打羽毛球", importance=0.8, confidence=0.95)
        # 低置信矛盾候选由 accepted AT_MENTION 来源进入冲突判断。
        _seed_memory(db, "m-old", content="用户喜欢Helldivers2",
                     confidence=0.9, type_="PREFERENCE", status="active")
        weak_candidate_id = _seed_candidate(
            db, 2, content="我不喜欢Helldivers2", importance=0.9, confidence=0.7)

        from core.observability import message_flow as mf

        root = mf.begin_trace(root_kind="memory_promotion", origin="spawn",
                              scope="space", process_kind="memory")
        manager = mm.MemoryManager()
        manager.process_new_candidates(flow_ctx=root)
        mf.end_trace(root, outcome="batch_done")
        mf.flush()

        conn = sqlite3.connect(db)
        result["candidate_strong"] = conn.execute(
            "SELECT status FROM memory_candidates WHERE id=?",
            (strong_candidate_id,),
        ).fetchone()[0]
        result["candidate_weak"] = conn.execute(
            "SELECT status FROM memory_candidates WHERE id=?",
            (weak_candidate_id,),
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
            if weak_candidate_id in (e[4] or "")
            or f"cand:{weak_candidate_id}" in (e[4] or "")
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
        db_path=db, group_shared_space="space", user_id="100", query="test",
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
    # parity 对照：当前合同下 Python/native 对 accepted evidence 和弱冲突应一致。
    report["parity_observation"] = {
        "rust": {
            "old_memory": rust.get("old_memory_status"),
            "weak_candidate": rust.get("candidate_weak"),
            "action": "observing_conflict" if rust.get(
                "candidate_weak") == "OBSERVING" else "见 rust_run",
        },
        "python": {
            "old_memory": py.get("old_memory_status"),
            "weak_candidate": py.get("candidate_weak"),
            "action": "observing_conflict" if py.get(
                "candidate_weak") == "OBSERVING" else "见 python_run",
        },
        "differ": (rust.get("candidate_weak") != py.get("candidate_weak")),
    }
    ok = (
        not rust.get("error") and not py.get("error")
        and rust.get("candidate_strong") == "CONFIRMED"
        and py.get("candidate_strong") == "CONFIRMED"
        and rust.get("candidate_weak") == "OBSERVING"
        and py.get("candidate_weak") == "OBSERVING"
        and rust.get("old_memory_status") == "active"
        and py.get("old_memory_status") == "active"
        and rust.get("new_memory") is not None
        and py.get("new_memory") is not None
        and not report["parity_observation"]["differ"]
        and report["retrieve_smoke"].get("native_loaded") is True
        and report["retrieve_smoke"].get("retrieve_ok") is True
        and any(
            event.get("metrics", {}).get("backend") == "rust"
            and event.get("status") == "succeeded"
            for event in rust.get("flow_backend_decisions", [])
        )
        and any(
            event.get("metrics", {}).get("backend") == "python"
            and event.get("status") == "succeeded"
            for event in py.get("flow_backend_decisions", [])
        )
        and any(
            event.get("status") == "succeeded"
            for event in rust.get("flow_commit_facts", [])
        )
        and any(
            event.get("status") == "succeeded"
            for event in py.get("flow_commit_facts", [])
        )
        and rust.get("flow_root_integrity", {}).get("integrity") == "complete"
        and py.get("flow_root_integrity", {}).get("integrity") == "complete"
    )
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
