# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""PersonaMem → Stella 检索层基准适配器（M3）。

映射（v2 benchmark.csv 行 → benchmark 用例 JSON）：
- ``user_query``                     → 用例 input（英文原文直接评，检索管道语言无关）
- ``preference``                     → 期望记忆 PREF（PREFERENCE/TOPIC_CONTINUE，携带
  ``related_conversation_snippet`` 作为 evidence 血缘行 → expect_evidence）
- ``prev_pref``（updated=True 时）   → 旧值记忆 PREV：status=superseded + forbidden
  （过时偏好绝不可再被激活——与自建 conflict-supersede 维度同语义）
- ``sensitive_info`` == True         → 敏感记忆 SENS：visibility=RESTRICTED + forbidden
  （隐私红线：相关也不得自行浮出；v2 无独立 ask_to_forget 字段，以此字段承接
  计划的 ask-to-forget 语义）
- 同 persona 其他行 preference       → 干扰记忆 DEC*（同空间噪音，允许被召回，
  检验 precision：期望项必须压过同域干扰）
- ``incorrect_answers``              → 不落库（答案层干扰项，检索层不评测；降权/禁止
  语义分别由 DEC*/PREV+SENS 承接）

判定：personamem_accuracy ≡ 该数据集目录上 run_benchmark 的 cases_ok_rate；
分题型 ≡ topic_metrics（按 case.topic 聚合，topic=topic_query 规范化小写）。

用法：
    python scripts/adapt_personamem.py                      # 固定 seed 抽样（CI 子集）
    python scripts/adapt_personamem.py --no-sample          # 全量 5000 行（离线）
    python scripts/adapt_personamem.py --sample 200 --seed 20261016
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# fetch_personamem 的落盘布局（HF 仓库内嵌套 benchmark/text/），勿改成扁平路径：
# CI 全新 checkout 只有嵌套这份，扁平 benchmark.csv 只是本机历史手工副本
DEFAULT_CSV = (
    PROJECT_ROOT / "memory" / "benchmark" / "_public" / "personamem"
    / "benchmark" / "text" / "benchmark.csv"
)
DEFAULT_OUT = PROJECT_ROOT / "memory" / "benchmark" / "_public" / "personamem" / "adapted"
DEFAULT_SEED = 20261016
DEFAULT_SAMPLE = 200
# 每个 persona 最多干扰记忆数（同 persona 其他行 preference）
MAX_DISTRACTORS = 2


def _parse_turns(raw: str) -> str:
    """snippet 是 python-literal 风格的对话轮列表字符串，抽取纯文本。"""
    text = (raw or "").strip()
    if not text or text.lower() == "false":
        return ""
    try:
        data = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    if isinstance(data, dict):
        data = [data]
    parts = []
    if isinstance(data, list):
        for turn in data:
            if isinstance(turn, dict):
                parts.append(str(turn.get("content") or ""))
            else:
                parts.append(str(turn))
    return "\n".join(p for p in parts if p)


def _normalize_topic(topic: str) -> str:
    return (topic or "misc").strip().lower() or "misc"


def _preference_text(raw: str) -> str:
    """preference 字段同样可能是 literal 对话串，抽取内容并压成单条陈述。"""
    return _parse_turns(raw).replace("\n", " ").strip()


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build_cases(rows: list[dict], *, revision: str = "") -> list[dict]:
    """行 → 用例（确定性；同输入同输出，无随机数）。"""
    by_persona: dict[str, list[dict]] = defaultdict(list)
    for idx, row in enumerate(rows):
        row = dict(row)
        row["_row_index"] = idx
        by_persona[row["persona_id"]].append(row)

    cases: list[dict] = []
    for persona_id in sorted(by_persona, key=lambda p: int(p)):
        persona_rows = by_persona[persona_id]
        for row in persona_rows:
            pref = _preference_text(row.get("preference") or "")
            query = (row.get("user_query") or "").strip()
            if not pref or not query:
                continue
            pid = int(persona_id)
            memories: dict[str, dict] = {
                "PREF": {
                    "content": pref,
                    "type": "PREFERENCE",
                    "usage_tags": ["TOPIC_CONTINUE"],
                    "visibility": "OPEN",
                    "confidence": 0.9,
                    "importance": 0.8,
                    "last_accessed_at_offset_minutes": -60,
                    "evidence": [{
                        "fact_key": "personamem_preference",
                        "source_row_id": row["_row_index"],
                        "source_conversation_key": f"pm-snippet-{row['_row_index']}",
                    }],
                },
            }
            forbidden: list[str] = []
            prev = _preference_text(row.get("prev_pref") or "")
            if (row.get("updated") or "").strip().lower() == "true" and prev:
                memories["PREV"] = {
                    "content": prev,
                    "type": "PREFERENCE",
                    "usage_tags": ["TOPIC_CONTINUE"],
                    "visibility": "OPEN",
                    "confidence": 0.6,
                    "importance": 0.4,
                    "status": "superseded",
                    "last_accessed_at_offset_minutes": -86400,
                }
                forbidden.append("PREV")
            if (row.get("sensitive_info") or "").strip().lower() == "true":
                snippet = _parse_turns(row.get("related_conversation_snippet") or "")
                if snippet:
                    # 敏感内容只在 snippet 里真实存在；作为记忆必须 RESTRICTED——
                    # 相关性高（同话题），若可见性过滤失效即激活，红线立刻报警
                    memories["SENS"] = {
                        "content": snippet[:500],
                        "type": "FACT",
                        "usage_tags": ["TOPIC_CONTINUE"],
                        "visibility": "RESTRICTED",
                        "confidence": 0.9,
                        "importance": 0.8,
                    }
                    forbidden.append("SENS")
            # 同 persona 其他行 preference 作为同域干扰（in-scope noise）。
            # 干扰项同样携带其来源行的 evidence（数据集每行都有 snippet 出处）——
            # expect_evidence 断言「所有被激活记忆都有血缘」，缺证据即失败。
            others = [r for r in persona_rows if r["_row_index"] != row["_row_index"]]
            for i, other in enumerate(others[:MAX_DISTRACTORS]):
                text = _preference_text(other.get("preference") or "")
                if not text or text == pref:
                    continue
                memories[f"DEC{i + 1}"] = {
                    "content": text,
                    "type": "PREFERENCE",
                    "usage_tags": ["TOPIC_CONTINUE"],
                    "visibility": "OPEN",
                    "confidence": 0.8,
                    "importance": 0.75,
                    "last_accessed_at_offset_minutes": -1440,
                    "evidence": [{
                        "fact_key": "personamem_preference",
                        "source_row_id": other["_row_index"],
                        "source_conversation_key": f"pm-snippet-{other['_row_index']}",
                    }],
                }
            cases.append({
                "id": f"pm-p{pid}-r{row['_row_index']}",
                "scenario": {"group_id": 3000 + pid % 1000, "user_id": pid},
                "input": query,
                "mode": "CASUAL_REPLY",
                "trigger": "reply",
                "memories": memories,
                "expected_memory": ["PREF"],
                "forbidden_memory": forbidden,
                "expect_evidence": True,
                "max_retrieved": 3,
                "topic": _normalize_topic(row.get("topic_query") or ""),
                "public": {
                    "benchmark": "personamem",
                    "revision": revision,
                    "persona_id": pid,
                    "row_index": row["_row_index"],
                    "topic_query": row.get("topic_query") or "",
                },
                "notes": "PersonaMem 检索层适配（英文域外部参照，不得外推中文群聊质量）",
            })
    return cases


def sample_cases(cases: list[dict], sample: int, seed: int) -> list[dict]:
    """固定 seed 抽样：按 (persona, row) 有序后随机取样，跨机器可复现。"""
    if sample >= len(cases):
        return list(cases)
    rng = random.Random(seed)
    indices = sorted(rng.sample(range(len(cases)), sample))
    return [cases[i] for i in indices]


def write_cases(cases: list[dict], out_dir: Path) -> None:
    if out_dir.exists():
        for p in sorted(out_dir.rglob("*.json")):
            p.unlink(missing_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (out_dir / f"{case['id']}.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="适配 PersonaMem 行为 benchmark 用例")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="benchmark.csv 路径")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="适配用例输出目录")
    parser.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                        help=f"抽样行数（默认 {DEFAULT_SAMPLE}，CI 子集）")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="抽样种子")
    parser.add_argument("--no-sample", action="store_true", help="全量适配（离线运行）")
    args = parser.parse_args(argv)

    if not args.csv.exists():
        print(json.dumps({
            "status": "skipped_data_missing",
            "hint": "先运行 scripts/fetch_personamem.py 下载数据",
            "csv": str(args.csv),
        }, ensure_ascii=False), file=sys.stderr)
        return 3

    rows = load_rows(args.csv)
    cases = build_cases(rows)
    if not args.no_sample:
        cases = sample_cases(cases, args.sample, args.seed)
    write_cases(cases, args.out)
    topics = sorted({c["topic"] for c in cases})
    print(f"✅ 适配 {len(cases)} 条用例 → {args.out}（topics={len(topics)}, "
          f"sample={'off' if args.no_sample else args.sample}, seed={args.seed}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
