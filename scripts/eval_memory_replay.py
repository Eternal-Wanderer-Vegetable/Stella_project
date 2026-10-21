# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""写路径端到端回放运行器（M4）。

双模式：
- ``--recorded``（CI 确定性）：``recorded/recordings.json`` 的录制件驱动整合
  （假后端按序返回录制回复，其余全走生产路径：消息读取 → prompt → 解析 →
  证据验证 → 候选落库 → MemoryManager 晋升）；
- ``--live``（离线）：真实模型跑整合；``--record`` 把回复录成同格式 wire 文件
  供后续确定性回放。报告记录 endpoint/model/温度，取不到记 null。

写路径直接 await ``consolidate_group``（§4：生产调用方全部在 ai_gateway，
回放绕过插件层）。语料全部合成；生产库零接触（临时 DB + patch DB_PATH）。

指标（全部确定性判分，无 LLM judge）：
- ``extraction_hit_rate``   期望记忆在候选中出现（content_contains 匹配）
- ``fabrication_rate``      候选内容与窗口原文无 4-gram 交集即编造（规则判定）
- ``promotion_correctness`` 期望晋升的记忆确实进入 memories 表
- ``qa_accuracy``           抽取式问答：召回内容含期望子串
- ``memory_delta``          有/无记忆的 qa_accuracy 差值（记忆净贡献）

用法：
    python scripts/eval_memory_replay.py --suite memory/benchmark/_replay/daily-life
    python scripts/eval_memory_replay.py --suite ... --live --record recorded/new.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.spaces import resolve_space
from memory import consolidator as consolidator_mod
from memory.consolidator import MemoryConsolidator

REPORT_SCHEMA = "memory-replay-report/1"
# 编造判定：候选内容任一 4-gram 出现在会话窗口原文即视为有据；完全没有 = 编造
FABRIC_GRAM = 4
# 候选相似强化允许的窗口：整 suite 全部会话文本
_SUITE_BASE_DATE = "2026-08-09"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_suite(suite_dir: Path) -> dict[str, Any]:
    sessions = [
        json.loads(line)
        for line in (suite_dir / "sessions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    expected = json.loads((suite_dir / "expected_memories.json").read_text(encoding="utf-8"))
    questions = json.loads((suite_dir / "questions.json").read_text(encoding="utf-8"))
    recorded_path = suite_dir / "recorded" / "recordings.json"
    recordings = (
        json.loads(recorded_path.read_text(encoding="utf-8")) if recorded_path.exists() else []
    )
    return {
        "sessions": sessions,
        "expected": expected.get("memories") or [],
        "questions": questions.get("questions") or [],
        "recordings": recordings,
        "recordings_sha256": _sha256_bytes(recorded_path.read_bytes()) if recorded_path.exists() else "",
    }


def _suite_digest(suite_dir: Path) -> str:
    h = hashlib.sha256()
    for name in sorted(p.name for p in suite_dir.rglob("*") if p.is_file() and "recorded" not in p.parts):
        h.update(name.encode())
        h.update((suite_dir / name).read_bytes())
    return h.hexdigest()


class _RecordingBackend:
    """按序吐出录制回复的假后端（recorded 模式；不发起任何 HTTP）。"""

    backend_name = "recorded"
    model = "recorded-replay"

    def __init__(self, reply_texts: list[str]):
        self._queue = list(reply_texts)
        self.consumed = 0

    async def generate_detailed(self, prompt: str) -> tuple[str, str]:
        if not self._queue:
            raise RuntimeError("录制件已耗尽：会话批次多于录制条目")
        self.consumed += 1
        return self._queue.pop(0), "stop"


def _schema_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.close()


def _provision_db(db_path: Path, sessions: list[dict[str, Any]]) -> None:
    """建规范 schema 并写入全部会话消息（时间戳按 day_offset 推移）。"""
    _schema_conn(db_path)
    from memory.pre_processors import _GROUP_MESSAGES_V16_DDL

    conn = sqlite3.connect(db_path)
    try:
        MemoryConsolidator.__new__(MemoryConsolidator)._ensure_common_tables(conn)
        # v16 全列 group_messages（consolidator._get_message_table 优先选它）
        conn.execute(_GROUP_MESSAGES_V16_DDL)
        conn.commit()
    finally:
        conn.close()
    conn = sqlite3.connect(db_path)
    base = datetime.strptime(_SUITE_BASE_DATE, "%Y-%m-%d")
    try:
        for session in sessions:
            ts = base + timedelta(days=int(session.get("day_offset") or 0), hours=10)
            for msg in session.get("messages") or []:
                conn.execute(
                    "INSERT INTO group_messages (group_id, user_id, content, source_kind, timestamp, "
                    "conversation_key, bot_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(session["group_id"]),
                        str(msg["user_id"]),
                        msg["content"],
                        "AT_MENTION" if msg.get("at_bot") else "PASSIVE",
                        ts.strftime("%Y-%m-%d %H:%M:%S"),
                        # conversation_key 必须显式：留空会让快照（空串）与证据列
                        # （legacy 回填值）不一致，晋升期 verify 断链
                        f"qq:stella-replay:group:{session['group_id']}",
                        "stella-replay",
                    ),
                )
                ts += timedelta(minutes=1)
        conn.commit()
    finally:
        conn.close()


def _isolate_paths(db_path: Path, tmp_path: Path, sessions: list[dict[str, Any]]) -> None:
    """DB / 日志路径全部指向隔离目录（评测不触生产库与仓库文件）。"""
    import memory.memory_manager as memory_manager_mod
    import memory.post_processors as post_processors
    import memory.pre_processors as pre_processors
    import memory.retriever as retriever

    for mod in (pre_processors, consolidator_mod, retriever, memory_manager_mod):
        mod.DB_PATH = db_path
    # 批次大小 = 单会话最大消息数：每个会话恰好一批（阈值 ≤ 批内消息数不会跳过，
    # limit ≥ 批内消息数不会拆批——录制件按「一个会话一条回复」对齐）
    session_batch = max(
        (len(s.get("messages") or []) for s in sessions), default=1
    ) if sessions else 1
    consolidator_mod.CONSOLIDATION_LOCAL_BATCH_SIZE = session_batch
    consolidator_mod.CONSOLIDATION_LOCAL_FORCE_BATCH_SIZE = session_batch
    post_processors.THOUGHT_LOG_PATH = tmp_path / "thought_log.md"
    consolidator_mod.append_consolidation_log = lambda entry: None

    class _NoCompressor:
        def maybe_compress(self, reason=""):
            return None

    memory_manager_mod.get_compressor = lambda: _NoCompressor()


def _make_consolidator(backend: Any) -> MemoryConsolidator:
    cons = MemoryConsolidator.__new__(MemoryConsolidator)
    cons._backends = [("recorded", backend)]
    cons._extract_backend = None  # 阶段2 候选提取录制在阶段1 输出里
    return cons


def _window_corpus(sessions: list[dict[str, Any]]) -> str:
    parts = []
    for s in sessions:
        for m in s.get("messages") or []:
            parts.append(str(m.get("content") or ""))
    return "\n".join(parts)


def _grams(text: str, n: int = FABRIC_GRAM) -> set[str]:
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def _fabricated(content: str, corpus_grams: set[str]) -> bool:
    """编造判定（规则）：候选内容没有任何 FABRIC_GRAM-gram 落在窗口原文里。"""
    grams = _grams(content)
    return bool(grams) and not (grams & corpus_grams)


def _candidate_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, user_id, type, content, confidence, importance, status FROM memory_candidates"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _memory_rows(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, user_id, type, content, status FROM memories"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _replay_recorded(suite: dict[str, Any], tmp: Path) -> sqlite3.Connection:
    """录制件驱动整合：返回评测用 DB 连接路径。"""
    db_path = tmp / "replay.db"
    _provision_db(db_path, suite["sessions"])
    _isolate_paths(db_path, tmp, suite["sessions"])
    replies = [r["reply_text"] for r in suite["recordings"]]
    backend = _RecordingBackend(replies)
    cons = _make_consolidator(backend)
    for session in suite["sessions"]:
        # 直接 await consolidate_group（§4：不经过 ai_gateway）
        asyncio.run(cons.consolidate_group(int(session["group_id"])))
    return db_path


def _evaluate_metrics(
    db_path: Path,
    suite: dict[str, Any],
) -> dict[str, Any]:
    corpus_grams = _grams(_window_corpus(suite["sessions"]))
    candidates = _candidate_rows(db_path)
    memories = _memory_rows(db_path)

    # ── extraction_hit_rate / fabrication_rate ──
    expected = suite["expected"]
    extraction_hits = []
    for exp in expected:
        hit = any(
            str(exp["content_contains"]) in (c["content"] or "")
            and str(c["user_id"]) == str(exp["user_id"])
            for c in candidates
        )
        extraction_hits.append({"id": exp["id"], "hit": hit})
    fabrication_flags = [
        {"id": c["id"], "content": c["content"][:60], "fabricated": _fabricated(c["content"] or "", corpus_grams)}
        for c in candidates
    ]

    # ── promotion_correctness ──
    promotion = []
    for exp in expected:
        if not exp.get("expect_promoted"):
            continue
        hit = any(
            str(exp["content_contains"]) in (m["content"] or "")
            and str(m["user_id"]) == str(exp["user_id"])
            for m in memories
        )
        promotion.append({"id": exp["id"], "promoted": hit})

    # ── qa_accuracy（生产检索语义，rule 模式） ──
    import memory.retrieval_v2 as retrieval_v2

    old_db, old_v2, old_rag = (
        retrieval_v2.DB_PATH,
        retrieval_v2.MEMORY_V2_ENABLED,
        retrieval_v2.RAG_ENABLED,
    )
    retrieval_v2.DB_PATH = db_path
    retrieval_v2.MEMORY_V2_ENABLED = True
    retrieval_v2.RAG_ENABLED = False
    retrieval_v2._CACHE.clear()

    def _run_qa() -> list[dict[str, Any]]:
        results = []
        # suite 单群语义：全部问题落在第一个会话的群空间
        space = resolve_space(int(suite["sessions"][0]["group_id"]))
        for q in suite["questions"]:
            result = retrieval_v2.retrieve_memories(
                space,
                int(q.get("user_id") or 0),
                q["query"],
                trigger=q.get("trigger", "reply"),
                mode=q.get("mode"),
            )
            recalled = [m.get("content") or "" for m in result.conversation_memories]
            recalled += [m.get("content") or "" for m in result.behavior_constraints]
            hits = {
                str(expect): any(expect in content for content in recalled)
                for expect in q.get("expect_contains") or []
            }
            results.append({
                "id": q["id"],
                "query": q["query"],
                "recalled_ids": [m.get("id") for m in result.conversation_memories],
                "expect_hits": hits,
                "pass": bool(hits) and all(hits.values()),
            })
        return results

    try:
        qa_with = _run_qa()
        # memory_delta：清空 memories 后重跑（临时库，恢复无意义但保持卫生）
        conn = sqlite3.connect(db_path)
        conn.execute("DELETE FROM memories")
        conn.commit()
        conn.close()
        retrieval_v2._CACHE.clear()
        qa_without = _run_qa()
    finally:
        retrieval_v2.DB_PATH = old_db
        retrieval_v2.MEMORY_V2_ENABLED = old_v2
        retrieval_v2.RAG_ENABLED = old_rag
        retrieval_v2._CACHE.clear()

    def _acc(results: list[dict[str, Any]]) -> float:
        return round(sum(1 for r in results if r["pass"]) / max(1, len(results)) * 100, 1)

    qa_acc = _acc(qa_with)
    qa_acc_without = _acc(qa_without)

    metrics = {
        "candidates_total": len(candidates),
        "memories_total": len(memories),
        "extraction_hit_rate": round(
            sum(1 for h in extraction_hits if h["hit"]) / max(1, len(extraction_hits)) * 100, 1),
        "fabrication_rate": round(
            sum(1 for f in fabrication_flags if f["fabricated"]) / max(1, len(fabrication_flags)) * 100, 1),
        "promotion_correctness": round(
            sum(1 for p in promotion if p["promoted"]) / max(1, len(promotion)) * 100, 1),
        "qa_accuracy": qa_acc,
        "qa_accuracy_without_memory": qa_acc_without,
        "memory_delta": round(qa_acc - qa_acc_without, 1),
    }
    details = {
        "extraction": extraction_hits,
        "fabrication": fabrication_flags,
        "promotion": promotion,
        "qa_with": qa_with,
        "qa_without": qa_without,
    }
    return {"metrics": metrics, "details": details}


def _gate(metrics: dict[str, Any]) -> list[str]:
    violations = []
    if metrics["extraction_hit_rate"] != 100.0:
        violations.append("extraction_hit_rate")
    if metrics["fabrication_rate"] != 0.0:
        violations.append("fabrication_rate")
    if metrics["promotion_correctness"] != 100.0:
        violations.append("promotion_correctness")
    if metrics["qa_accuracy"] != 100.0:
        violations.append("qa_accuracy")
    if metrics["memory_delta"] <= 0.0:
        violations.append("memory_delta")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="记忆写路径端到端回放评测")
    parser.add_argument("--suite", type=Path,
                        default=PROJECT_ROOT / "memory" / "benchmark" / "_replay" / "daily-life")
    parser.add_argument("--live", action="store_true",
                        help="离线真实模型跑整合（默认 recorded 确定性回放）")
    parser.add_argument("--record", type=Path, default=None,
                        help="live 模式下把模型回复录成 wire 文件供确定性回放")
    parser.add_argument("--json", type=Path, default=None, help="报告输出路径")
    args = parser.parse_args(argv)

    suite = _load_suite(args.suite)
    live_meta: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(prefix="stella_replay_") as td:
        tmp = Path(td)
        if args.live:
            from core.llm.registry import ROLE_CONSOLIDATION, backend_for, endpoint_of

            inner = backend_for(ROLE_CONSOLIDATION)
            if inner is None:
                print(json.dumps({"status": "skipped_no_live_backend"}, ensure_ascii=False),
                      file=sys.stderr)
                return 3
            endpoint = endpoint_of(ROLE_CONSOLIDATION)
            live_meta = {
                "endpoint": str(getattr(endpoint, "base_url", "") or ""),
                "model": str(getattr(inner, "model", "") or ""),
                # 生产 LLMBackend.generate 合同不透出温度，诚实记 null
                "temperature": getattr(endpoint, "temperature", None),
            }
            transcripts: list[str] = []
            if args.record:
                from gravitas.model_calls import observe_model_backend

                backend = observe_model_backend(
                    inner, lambda _prompt, reply, _finish: transcripts.append(reply)
                )
            else:
                backend = inner
            # live 用真实装配：阶段2（EXTRACT）按当前配置解析——可用则两阶段齐全，
            # 未配置则与生产同款回退阶段1（回退事实进日志与报告，不粉饰）
            cons = MemoryConsolidator()
            cons._backends = [("live", backend)]
            db_path = tmp / "replay.db"
            _provision_db(db_path, suite["sessions"])
            _isolate_paths(db_path, tmp, suite["sessions"])
            for session in suite["sessions"]:
                asyncio.run(cons.consolidate_group(int(session["group_id"])))
            if args.record:
                args.record.parent.mkdir(parents=True, exist_ok=True)
                recordings = [
                    {"session_id": s["session_id"], "reply_text": text}
                    for s, text in zip(suite["sessions"], transcripts, strict=True)
                ]
                args.record.write_text(
                    json.dumps(recordings, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                print(f"📼 已录制 {len(recordings)} 条回复 → {args.record}")
        else:
            db_path = _replay_recorded(suite, tmp)

        evaluation = _evaluate_metrics(db_path, suite)

    report_mode = "live" if args.live else "recorded"
    # 成本段（M5）：live 记 usage_sink 进程记账差值；recorded 无 LLM 调用，
    # token 诚实记 0 并注明口径。db_bytes 量级两种模式都记录。
    try:
        from core.llm import usage_sink

        usage = usage_sink.snapshot()
        cost = {
            "llm_calls": usage.get("calls", usage.get("total_calls", 0)),
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
            "accounting": "usage_sink(process)",
        }
    except Exception as exc:
        cost = {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0,
                "accounting": f"unavailable: {type(exc).__name__}"}
    if report_mode != "live":
        cost["note"] = "recorded 模式零 LLM 调用，token=0 是口径事实而非缺席"

    report = {
        "schema": REPORT_SCHEMA,
        "cost": cost,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": report_mode,
        "suite": args.suite.name,
        "suite_sha256": _suite_digest(args.suite),
        "recordings_sha256": suite["recordings_sha256"],
        "run_fingerprint": _sha256_bytes(
            json.dumps({
                "suite": _suite_digest(args.suite),
                "recordings": suite["recordings_sha256"],
                "mode": "live" if args.live else "recorded",
            }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
        "metrics": evaluation["metrics"],
        "details": evaluation["details"],
        "live": live_meta,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    m = evaluation["metrics"]
    print("=" * 60)
    print(f"Memory Replay [{report['mode']}] suite={report['suite']}")
    print("=" * 60)
    print(f"  候选 {m['candidates_total']} 条 / 记忆 {m['memories_total']} 条")
    print(f"  Extraction Hit Rate   : {m['extraction_hit_rate']}%")
    print(f"  Fabrication Rate      : {m['fabrication_rate']}%  （目标 ≈ 0%）")
    print(f"  Promotion Correctness : {m['promotion_correctness']}%")
    print(f"  QA Accuracy           : {m['qa_accuracy']}%")
    print(f"  Memory Delta          : {m['memory_delta']:+} （有/无记忆差）")
    if live_meta:
        print(f"  Live                  : {live_meta}")
    print("=" * 60)
    if not args.live:
        violations = _gate(m)
        if violations:
            print(f"❌ 门禁失败：{violations}")
            return 1
        print("✅ 回放门禁全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
