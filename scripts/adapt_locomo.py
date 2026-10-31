# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""把 LoCoMo 原始数据适配成 memory_eval 回放场景（MBENCH-002 M1）。

输入：``memory/benchmark/_public/locomo/data/locomo10.json``（fetch_locomo.py 产物，
CC BY-NC 4.0，不入库）。

输出：``memory/benchmark/_public/locomo/adapted/``
- ``<sample_id>.json``：单段对话的回放场景（sessions + qa + 空间/用户映射）；
- ``index.json``：场景清单与来源指纹（源文件 sha256、适配器版本）。

映射约定：
- 每段对话 → 一个合成群（group_id=8800xx），两名说话人 → 两个合成数字用户
  （9100xx01/9100xx02）；空间随群派生，与生产库零交集；
- session 的 ``*_date_time``（如 ``1:56 pm on 8 May, 2023``）解析为会话起始时间，
  缺失时按前一会话 +7 天顺延；批内消息按秒递增；
- QA 五类原样保留（1 single-hop / 2 multi-hop / 3 temporal / 4 open-domain /
  5 adversarial）；category 5 无 ``answer``，gold = 弃答，``adversarial_answer``
  是诱答陷阱，judge 按答「无此信息」判对。

用法：
    python scripts/adapt_locomo.py                 # 全量 10 段
    python scripts/adapt_locomo.py --limit 1       # smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = PROJECT_ROOT / "memory" / "benchmark" / "_public" / "locomo" / "data" / "locomo10.json"
DEFAULT_OUT = PROJECT_ROOT / "memory" / "benchmark" / "_public" / "locomo" / "adapted"

ADAPTER_VERSION = "locomo-adapter/1"
CATEGORY_NAMES = {
    1: "single_hop",
    2: "multi_hop",
    3: "temporal_reasoning",
    4: "open_domain_knowledge",
    5: "adversarial",
}
GROUP_ID_BASE = 880000
USER_ID_BASE = 9100000


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_session_time(raw: str) -> datetime | None:
    """解析 LoCoMo 会话时间串（如 ``1:56 pm on 8 May, 2023``）。"""
    if not raw:
        return None
    text = raw.strip().replace(",", "")
    for fmt in ("%I:%M %p on %d %B %Y", "%I:%M %p on %d %b %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def adapt_conversation(entry: dict, conv_index: int) -> dict:
    conv = entry["conversation"]
    sample_id = entry.get("sample_id") or f"conv-{conv_index}"
    gid = GROUP_ID_BASE + conv_index
    user_a = str(USER_ID_BASE + conv_index * 100 + 1)
    user_b = str(USER_ID_BASE + conv_index * 100 + 2)
    speaker_a = conv.get("speaker_a") or "speaker_a"
    speaker_b = conv.get("speaker_b") or "speaker_b"

    session_keys = sorted(
        (k for k in conv if k.startswith("session_") and not k.endswith("_date_time")),
        key=lambda s: int(s.split("_")[1]),
    )
    sessions: list[dict] = []
    prev_ts: datetime | None = None
    unmapped_dia: list[str] = []
    for key in session_keys:
        seq = int(key.split("_")[1])
        ts = _parse_session_time(conv.get(f"session_{seq}_date_time") or "")
        if ts is None:
            ts = (prev_ts or datetime(2023, 1, 1, 12, 0)) + timedelta(days=7)
        prev_ts = ts
        messages = []
        for turn in conv[key]:
            dia_id = str(turn.get("dia_id") or "")
            text = str(turn.get("text") or "").strip()
            speaker = str(turn.get("speaker") or "")
            if not dia_id or not text:
                unmapped_dia.append(dia_id)
                continue
            user_id = user_a if speaker == speaker_a else user_b
            messages.append({
                "dia_id": dia_id,
                "speaker": speaker,
                "user_id": user_id,
                "text": text,
            })
        sessions.append({
            "session_id": seq,
            "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "ts_source": "dataset" if conv.get(f"session_{seq}_date_time") else "fallback+7d",
            "messages": messages,
        })

    qa_items = []
    skipped_qa = 0
    for i, q in enumerate(entry.get("qa") or []):
        category = int(q.get("category") or 0)
        # gold 可能是 JSON 数字（如年份/数量），统一转 str 保证下游 .strip() 安全
        gold = q.get("answer")
        gold = str(gold) if gold is not None else None
        adversarial = q.get("adversarial_answer")
        adversarial = str(adversarial) if adversarial is not None else None
        if category == 5:
            gold = None
        if not gold and not adversarial:
            skipped_qa += 1
            continue
        qa_items.append({
            "qid": f"{sample_id}-q{i:03d}",
            "category": category,
            "category_name": CATEGORY_NAMES.get(category, f"unknown_{category}"),
            "question": str(q.get("question") or ""),
            "gold_answer": gold,
            "adversarial_answer": adversarial,
            "evidence_dia_ids": [str(e) for e in (q.get("evidence") or [])],
        })

    return {
        "schema": "memory-eval-locomo-scenario/1",
        "scenario_id": f"locomo-{sample_id}",
        "sample_id": sample_id,
        "group_id": gid,
        "conversation_key": f"qq:stella-bench:group:{gid}",
        "bot_id": "stella-bench",
        "speakers": {"a": speaker_a, "b": speaker_b},
        "user_ids": {"a": user_a, "b": user_b},
        "sessions": sessions,
        "qa": qa_items,
        "adapt_meta": {
            "adapter": ADAPTER_VERSION,
            "skipped_qa": skipped_qa,
            "unmapped_dia_ids": len(unmapped_dia),
        },
    }


def adapt(src: Path, out_dir: Path, *, limit: int | None = None) -> int:
    if not src.exists():
        print(f"❌ 源数据缺失：{src}（先运行 scripts/fetch_locomo.py）", file=sys.stderr)
        return 1
    data = json.loads(src.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = data if limit is None else data[:limit]
    index_entries = []
    for i, entry in enumerate(entries, start=1):
        scenario = adapt_conversation(entry, i)
        dest = out_dir / f"{scenario['sample_id']}.json"
        dest.write_text(json.dumps(scenario, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        turns = sum(len(s["messages"]) for s in scenario["sessions"])
        cats: dict[str, int] = {}
        for q in scenario["qa"]:
            cats[q["category_name"]] = cats.get(q["category_name"], 0) + 1
        index_entries.append({
            "scenario_id": scenario["scenario_id"],
            "file": dest.name,
            "sessions": len(scenario["sessions"]),
            "turns": turns,
            "qa": len(scenario["qa"]),
            "qa_by_category": cats,
        })
        print(f"  {scenario['scenario_id']}: sessions={len(scenario['sessions'])} "
              f"turns={turns} qa={len(scenario['qa'])}")

    index = {
        "schema": "memory-eval-locomo-index/1",
        "adapter": ADAPTER_VERSION,
        "source": {
            "path": "data/locomo10.json",
            "sha256": _sha256_file(src),
        },
        "adapted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "license": "CC-BY-NC-4.0",
        "scenarios": index_entries,
    }
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 适配完成：{len(index_entries)} 场景 → {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把 LoCoMo 原始数据适配成回放场景")
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=None, help="只适配前 N 段（smoke）")
    args = parser.parse_args(argv)
    return adapt(args.src, args.out, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
