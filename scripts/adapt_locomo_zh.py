# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""把 LoCoMo 适配场景的会话文本翻译成中文（MBENCH-002 Next-2 里程碑 1）。

目的：验证证据合同刻板句型在**自然中文群聊**上的覆盖率（英文基线 17/5882=0.29%）。
里程碑 1 只翻译会话（sessions），供 live 整合漏斗使用；QA 翻译留待里程碑 2。

翻译协议（版本固定 ``locomo-zh-v1``）：
- 逐 session 一批，整段一次性翻译；输出 JSONL（``dia_id`` + ``text``），逐条对应，
  不增删、不合并不拆分；
- 第一人称自我陈述必须保持第一人称陈述句（保证证据合同的句型可匹配性）；
- 断点缓存：``<cache-dir>/<sample_id>.jsonl``（按 dia_id 去重追加），重跑只补缺失；
- 模型/温度/协议版本写入输出场景的 ``translation`` 元数据。

用法（仓库根目录）：
    python scripts/adapt_locomo_zh.py --scenarios memory/benchmark/_public/locomo/adapted \
        --conversations 2 --out memory/benchmark/_public/locomo/adapted-zh \
        --llm-base-url http://127.0.0.1:8081/v1 --llm-model qwen3.8-flash-next-iq2_xs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TRANSLATION_PROTOCOL = "locomo-zh-v1"

_SYSTEM_PROMPT = (
    "你是专业字幕翻译。把英文群聊逐条翻译成自然的简体中文群聊对话。规则："
    "1) 一条消息对应一条译文，不增、不减、不合并、不拆分；"
    "2) 译成自然的中文口语，不要书面腔；"
    "3) 人名保留英文原文，同一会话内保持一致；"
    "4) 说话人的自我陈述（住处、来历、姓名、工作、喜好等）必须译成第一人称陈述句；"
    "5) 只输出 JSONL：每行一个 JSON 对象，形如 {\"dia_id\":\"D1:1\",\"text\":\"译文\"}，"
    "不要输出任何其他内容。"
)


def _parse_jsonl(text: str) -> dict[str, str]:
    """解析模型输出的 JSONL（容忍 ``` 围栏与散落的空行）。"""
    out: dict[str, str] = {}
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body[body.find("\n") + 1 :] if "\n" in body else body
    for line in body.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        dia = str(obj.get("dia_id") or "")
        txt = str(obj.get("text") or "").strip()
        if dia and txt:
            out[dia] = txt
    return out


def load_cache(cache_dir: Path, sample_id: str) -> dict[str, str]:
    path = cache_dir / f"{sample_id}.jsonl"
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("dia_id") and obj.get("text"):
            out[str(obj["dia_id"])] = str(obj["text"])
    return out


def append_cache(cache_dir: Path, sample_id: str, items: dict[str, str]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{sample_id}.jsonl"
    with path.open("a", encoding="utf-8") as f:
        for dia, text in items.items():
            f.write(json.dumps({"dia_id": dia, "text": text}, ensure_ascii=False) + "\n")


def translate_scenario(scenario: dict, llm: Any, cache_dir: Path) -> tuple[dict, int]:
    """翻译单个场景的全部会话；返回 (新场景 dict, 本次调用数)。"""
    from memory_eval.scenarios import SCENARIO_SCHEMA

    sample_id = scenario["sample_id"]
    cache = load_cache(cache_dir, sample_id)
    calls = 0
    sessions_out = []
    for session in scenario["sessions"]:
        messages = session.get("messages") or []
        missing = [m for m in messages if m["dia_id"] not in cache]
        # 分块翻译：reasoning 模型的思考会消耗输出预算，整段大块易被截断
        # （conv-26 实测 30 条一批只产出 109/419）；8 条/批 + 8192 预算实测稳定。
        for chunk_start in range(0, len(missing), 8):
            chunk = missing[chunk_start : chunk_start + 8]
            payload = "\n".join(f'{m["dia_id"]}\t{m["text"]}' for m in chunk)
            completion = llm.chat(
                f"{payload}\n\n请按系统规则输出上述 {len(chunk)} 条消息的中文 JSONL。",
                system=_SYSTEM_PROMPT,
                max_tokens=8192,
                temperature=0.0,
            )
            calls += 1
            got = _parse_jsonl(completion["text"])
            # 只接受本次请求里 missing 的 dia_id，避免缓存污染
            new = {d: t for d, t in got.items() if d in {m["dia_id"] for m in chunk}}
            if new:
                append_cache(cache_dir, sample_id, new)
                cache.update(new)
        sessions_out.append({
            **session,
            "messages": [
                {**m, "text": cache.get(m["dia_id"], m["text"])}
                for m in messages
            ],
        })
    translated = sum(
        1 for s in sessions_out for m in s["messages"]
        if cache.get(m["dia_id"]) and m["dia_id"] in cache
    )
    total = sum(len(s["messages"]) for s in sessions_out)
    zh = {
        **scenario,
        "schema": SCENARIO_SCHEMA,
        "scenario_id": f"{scenario['scenario_id']}-zh",
        "sample_id": f"{sample_id}-zh",
        "sessions": sessions_out,
        "translation": {
            "protocol": TRANSLATION_PROTOCOL,
            "model": llm.model,
            "base_url": llm.base_url,
            "temperature": 0.0,
            "messages_translated": translated,
            "messages_total": total,
            "note": "里程碑 1：仅翻译 sessions；qa 保留英文原文（live 漏斗不使用 QA）",
        },
    }
    return zh, calls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LoCoMo 场景中文翻译（会话，逐条对齐）")
    parser.add_argument("--scenarios", type=Path,
                        default=Path("memory/benchmark/_public/locomo/adapted"))
    parser.add_argument("--out", type=Path,
                        default=Path("memory/benchmark/_public/locomo/adapted-zh"))
    parser.add_argument("--cache", type=Path, default=None,
                        help="翻译缓存目录（缺省 <out>/.translation-cache）")
    parser.add_argument("--conversations", type=int, default=0, help="只翻译前 N 段（0=全部）")
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:8081/v1")
    parser.add_argument("--llm-model", default=None)
    args = parser.parse_args(argv)

    import os
    import tempfile

    os.environ.setdefault("STELLA_HOME", tempfile.mkdtemp(prefix="stella-zh-adapt-"))

    from memory_eval.llm import EvalLLM
    from memory_eval.scenarios import load_scenarios

    llm = EvalLLM(args.llm_base_url, args.llm_model)
    scenarios = load_scenarios(args.scenarios, limit=args.conversations or None)
    cache_dir = args.cache or (args.out / ".translation-cache")
    args.out.mkdir(parents=True, exist_ok=True)

    total_calls = 0
    for scenario in scenarios:
        print(f"── {scenario['scenario_id']} ──")
        zh, calls = translate_scenario(scenario, llm, cache_dir)
        total_calls += calls
        dest = args.out / f"{zh['sample_id']}.json"
        dest.write_text(json.dumps(zh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        t = zh["translation"]
        print(f"  {dest.name}: {t['messages_translated']}/{t['messages_total']} 条已译（调用 {calls} 次）")
        if t["messages_translated"] < t["messages_total"]:
            print(f"  ⚠️ {t['messages_total'] - t['messages_translated']} 条缺失（缓存续跑可补）",
                  file=sys.stderr)
    index_src = args.scenarios / "index.json"
    if index_src.exists():
        index = json.loads(index_src.read_text(encoding="utf-8"))
        index["schema"] = "memory-eval-locomo-index/1"
        index["adapter"] = f"adapt_locomo_zh/{TRANSLATION_PROTOCOL}"
        index["note"] = "中文对照集（里程碑 1）：sessions 已译，qa 保留英文"
        # 只列出实际产出的场景——部分翻译时 index 不得引用缺失文件
        translated_names = {f"{s['sample_id']}-zh.json" for s in scenarios}
        index["scenarios"] = [
            {**entry, "scenario_id": f"{entry['scenario_id']}-zh",
             "file": f"{entry['sample_id']}-zh.json"}
            for entry in index["scenarios"]
            if f"{entry['sample_id']}-zh.json" in translated_names
        ]
        (args.out / "index.json").write_text(
            json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 完成：{len(scenarios)} 场景，翻译调用 {total_calls} 次 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
