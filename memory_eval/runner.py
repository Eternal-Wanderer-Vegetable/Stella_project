# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""评测编排：逐场景 隔离回放摄入 → QA 检索作答 → judge 判分 → 报告。

checkpoint：每场景 workdir 内 ``meta.json``（已摄入会话数/漏斗）与
``qa_results.jsonl``（逐题结果追加）；``--resume`` 复用已有进度继续跑。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_eval.isolation import ReplayEnv, ensure_eval_home
from memory_eval.llm import CountingBackend, EvalLLM

# --pack-mode：auto=生产 detect_mode；其余为显式用法模式（对照实验用）
PACK_MODES = {"auto": None, "casual": "CASUAL_REPLY", "tech": "TECH_HELP",
              "conflict": "CONFLICT_AVOID"}
from memory_eval.metrics import (
    aggregate_qa,
    aggregate_run,
    coverage_flags,
    grams,
    has_gram_overlap,
)
from memory_eval.scenarios import evidence_texts, load_scenarios, select_qa


def _utcnow_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _meta_path(workdir: Path) -> Path:
    return workdir / "meta.json"


def _load_meta(workdir: Path) -> dict[str, Any]:
    path = _meta_path(workdir)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"inserted_sessions": 0}


def _save_meta(workdir: Path, meta: dict[str, Any]) -> None:
    _meta_path(workdir).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _results_path(workdir: Path) -> Path:
    return workdir / "qa_results.jsonl"


def _load_done_qids(workdir: Path) -> set[str]:
    path = _results_path(workdir)
    if not path.exists():
        return set()
    done: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("qid"):
            done.add(str(record["qid"]))
    return done


def _append_result(workdir: Path, record: dict[str, Any]) -> None:
    path = _results_path(workdir)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_results(workdir: Path) -> list[dict[str, Any]]:
    path = _results_path(workdir)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def build_embedding_service(args: Any) -> Any | None:
    """按 CLI/配置构建 EmbeddingService；构建失败返回 None（回退通道并记录）。"""
    if getattr(args, "mode", "rule") not in ("embedding", "hybrid"):
        return None
    try:
        from config import (
            MEMORY_EMBEDDING_BASE_URL,
            MEMORY_EMBEDDING_MODEL,
            MEMORY_EMBEDDING_TIMEOUT,
        )
        from memory.embeddings import EmbeddingService

        return EmbeddingService(
            getattr(args, "embedding_base_url", None) or MEMORY_EMBEDDING_BASE_URL,
            getattr(args, "embedding_model", None) or MEMORY_EMBEDDING_MODEL,
            MEMORY_EMBEDDING_TIMEOUT,
        )
    except Exception:
        return None


async def run(args: Any) -> int:
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    ensure_eval_home(workdir)

    # env 就绪后才允许导入 config/memory 族模块
    from memory_eval.answer import answer_question
    from memory_eval.judge import (
        build_judge_prompt,
        parse_verdict,
    )
    from memory_eval.report import build_run_meta, write_report

    scenarios = load_scenarios(Path(args.data_dir), limit=args.conversations)
    if not scenarios:
        print("❌ 没有可用的场景（检查 --data-dir / --conversations）")
        return 1

    stage = args.stage
    llm: EvalLLM | None = None
    judge_llm: EvalLLM | None = None
    if stage in ("qa", "all"):
        llm = EvalLLM(args.llm_base_url, args.llm_model, args.llm_api_key)
        judge_llm = llm
        if args.judge_model and args.judge_model != llm.model:
            judge_llm = EvalLLM(args.llm_base_url, args.judge_model, args.llm_api_key)
    service = build_embedding_service(args)

    per_scenario: list[dict[str, Any]] = []
    for scenario in scenarios:
        sid = scenario["scenario_id"]
        env_workdir = workdir / sid
        env_workdir.mkdir(parents=True, exist_ok=True)
        env = ReplayEnv(env_workdir, scenario)
        print(f"── {sid} ──")
        with env.session():
            meta = _load_meta(env_workdir)
            meta.setdefault("inserted_sessions", 0)

            # ── 摄入回放（真实整合链路；live=生产 LLM，oracle=机械抽取）──
            if stage in ("ingest", "all") and meta["inserted_sessions"] < len(scenario["sessions"]):
                if getattr(args, "consolidation", "live") == "oracle":
                    from memory_eval.oracle import OracleConsolidationBackend

                    cons = env.build_consolidator(fake_backend=OracleConsolidationBackend())
                else:
                    cons = env.build_consolidator(live=True)
                    counted = CountingBackend(cons._backends[0][1])
                    cons._backends = [(cons._backends[0][0], counted)]
                sessions = scenario["sessions"]
                for session in sessions[meta["inserted_sessions"]:]:
                    wall_before = _utcnow_str()
                    env.set_batch_size(len(session.get("messages") or []))
                    env.insert_sessions([session])
                    await cons.consolidate_group(int(scenario["group_id"]), force=True)
                    env.backdate_new_rows(str(session["ts"]), wall_before)
                    meta["inserted_sessions"] += 1
                    _save_meta(env_workdir, meta)
                    print(f"  session {meta['inserted_sessions']}/{len(sessions)} done")
                if getattr(args, "consolidation", "live") == "live":
                    meta["consolidation_calls"] = counted.calls
                else:
                    meta["consolidation_calls"] = cons._backends[0][1].calls
                meta["funnel"] = env.funnel()
                _save_meta(env_workdir, meta)

            if getattr(args, "inject_gold", False) and stage in ("qa", "all"):
                from memory_eval.inject import inject_gold_memories

                injected = inject_gold_memories(env, scenario)
                if injected:
                    print(f"  oracle 注入金标准记忆 {injected} 条")
                meta["gold_injected_total"] = meta.get("gold_injected_total", 0) + injected
                _save_meta(env_workdir, meta)
                # 注入后重读漏斗，让 memories 计数反映金标准行
                funnel = env.funnel()
            else:
                funnel = meta.get("funnel") or env.funnel()
            qa_results = _load_results(env_workdir) if stage in ("qa", "all") else []
            per_scenario.append({
                "scenario_id": sid,
                "funnel": funnel,
                "gold_injected": meta.get("gold_injected_total", 0),
                "consolidation_calls": meta.get("consolidation_calls", 0),
                "qa_results": qa_results,
                "aggregate": aggregate_qa(qa_results) if qa_results else {},
            })

            # ── QA 检索作答 + judge ──
            if stage in ("qa", "all") and llm is not None and judge_llm is not None:
                done = _load_done_qids(env_workdir)
                qa_items = select_qa(scenario, args.qa_sample, args.seed)
                contents = env.table_contents()
                ev_texts = evidence_texts(scenario)
                memory_grams = grams(" \n ".join(contents["memories"]))
                candidate_grams = grams(" \n ".join(contents["candidates"]))
                for qa in qa_items:
                    if qa["qid"] in done:
                        continue
                    record = await answer_question(
                        env, scenario, qa, channel=args.mode, llm=llm, service=service,
                        pack_mode=PACK_MODES.get(getattr(args, "pack_mode", "auto")),
                    )
                    judge_raw = judge_llm.chat(
                        build_judge_prompt(
                            qa["question"], qa.get("gold_answer"), record["answer"],
                            adversarial_answer=qa.get("adversarial_answer"),
                        ),
                        max_tokens=2048,
                        temperature=0.0,
                    )
                    verdict = parse_verdict(judge_raw["text"])
                    record["verdict"] = verdict["verdict"]
                    record["judge_raw"] = verdict["raw"]
                    record["judge_prompt_tokens"] = judge_raw["prompt_tokens"]
                    record["judge_completion_tokens"] = judge_raw["completion_tokens"]
                    ev = [ev_texts[d] for d in record["evidence_dia_ids"] if d in ev_texts]
                    record["evidence_turns"] = len(ev)
                    record["write_coverage_memories"] = sum(
                        1 for t in ev if t and has_gram_overlap(t, memory_grams)
                    )
                    record["write_coverage_candidates"] = sum(
                        1 for t in ev if t and has_gram_overlap(t, candidate_grams)
                    )
                    record["retrieval_evidence_coverage"] = (
                        coverage_flags(qa, ev_texts, record["retrieved_contents"])["evidence_covered"]
                    )
                    _append_result(env_workdir, record)
                    qa_results = _load_results(env_workdir)
                    print(f"  [{len(qa_results)}/{len(qa_items)}] {qa['qid']} → {verdict['verdict']}")

        aggregate = aggregate_qa(_load_results(env_workdir)) if stage in ("qa", "all") else {}
        per_scenario[-1]["aggregate"] = aggregate
        per_scenario[-1]["qa_results"] = _load_results(env_workdir)

    summary = aggregate_run(per_scenario)
    run_meta = build_run_meta(args, _load_index_safe(args.data_dir), llm, judge_llm)
    out_dir = Path(args.out) if args.out else workdir / "report"
    json_path, md_path = write_report(out_dir, run_meta, per_scenario, summary)
    print(f"✅ 报告：{json_path}")
    print(f"✅ 摘要：{md_path}")
    _print_summary(summary)
    return 0


def _load_index_safe(data_dir: str) -> dict[str, Any]:
    try:
        from memory_eval.scenarios import load_index

        return load_index(Path(data_dir))
    except Exception:
        return {}


def _print_summary(summary: dict[str, Any]) -> None:
    print(f"  总体 J-accuracy : {summary.get('accuracy')}%  (n={summary.get('total')})")
    for name, row in (summary.get("by_category") or {}).items():
        print(f"    {name:<22} {row.get('accuracy')}%  (n={row.get('total')})")
    print(f"  adversarial 弃答 : {summary.get('adversarial_abstention_accuracy')}%")
    print(f"  漏斗             : {summary.get('funnel_totals')}")
