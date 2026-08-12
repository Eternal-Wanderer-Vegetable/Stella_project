# scripts/probe_consolidation.py
# SPDX-License-Identifier: AGPL-3.0
"""整合器（Consolidator）探针：对真实消息窗口跑生产整合路径，观察 LLM 行为。

读 ``windows_raw.json``（由 ``scripts/sample_windows.py`` 产出，含真实群聊内容），
对每个窗口调用与生产完全一致的链路：
    format_consolidation_prompt()（同一份 prompt 模板）
    → LMStudioBackend.generate()（同一配置的本地模型）
    → MemoryConsolidator._parse_json()（同一份容错解析）
    → memory.policy.validate_candidate()（同一份 Gate 3 审核）

只做观察，不写库、不推进 checkpoint。输出：
- ``consolidation_probe.md``：人类可读，每窗口三段（窗口原文 / LLM 原始输出 / 解析并验证后的候选）
- ``consolidation_probe.json``：机器可读，供后续 A4 runner 复用

用法（项目根目录，LM Studio 已加载整合模型）：
    python scripts/probe_consolidation.py --limit 20
    python scripts/probe_consolidation.py --window-index 3
    python scripts/probe_consolidation.py --window-index 3 --repeat 3   # 稳定性观察
    python scripts/probe_consolidation.py --repeat 3 --temperature 0.1  # 对比采样温度

说明：
- 探针的窗口是独立片段，没有历史短期摘要，因此 ``current_summary`` 一律填
  "（无）"（对应生产中新群的初始状态）。
- 发送者白名单只影响落库（本脚本不落库），但会标注候选归属是否在本窗口发送者
  集合内，供观察归属错误。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

# 允许直接 `python scripts/probe_consolidation.py` 运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (
    CONSOLIDATION_LM_STUDIO_BASE_URL,
    CONSOLIDATION_LM_STUDIO_MODEL,
    CONSOLIDATION_LM_STUDIO_TEMPERATURE,
    CONSOLIDATION_LOCAL_MAX_TOKENS,
)
from core.llm.lm_studio import LMStudioBackend
from memory.consolidation_prompt import format_consolidation_prompt
from memory.consolidator import MemoryConsolidator
from memory.policy import validate_candidate

DEFAULT_INPUT = Path("windows_raw.json")
OUT_MD = Path("consolidation_probe.md")
OUT_JSON = Path("consolidation_probe.json")
POSITIVE_FIXTURE = Path("memory/benchmark/_fixtures/consolidation_positive.json")


def read_windows(path: Path) -> list[list[dict]]:
    """读采样窗口：样本脚本产出的是 [{user, content, ts}] 列表的列表。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return [w for w in data if isinstance(w, list)]


def format_messages(window: list[dict]) -> str:
    """按生产格式拼消息文本（与 MemoryConsolidator._fetch_next_messages 同格式）。
    支持 source_kind 字段：AT_MENTION 时标注 [对Bot说]。
    """
    from config import MEMORY_SOURCE_KIND_ENABLED
    lines = []
    for i, m in enumerate(window, start=1):
        uid = (m.get("user") or "").strip()
        content = (m.get("content") or "").strip()
        source_kind = m.get("source_kind", "PASSIVE")
        if MEMORY_SOURCE_KIND_ENABLED and source_kind == "AT_MENTION":
            lines.append(f"消息ID({i}) 用户({uid}) [对Bot说]: {content}")
        else:
            lines.append(f"消息ID({i}) 用户({uid}): {content}")
    return "\n".join(lines)


def window_senders(window: list[dict]) -> list[str]:
    """窗口内出现过的发送者（去重保序），用于候选归属白名单检查。"""
    return list(dict.fromkeys(str(m.get("user") or "").strip() for m in window if (m.get("user") or "").strip()))


def _normalize_candidate(consolidator: MemoryConsolidator, raw: dict) -> dict | None:
    """把一条 LLM 输出候选规范化 + 过 validate_candidate，复刻生产 _write_memory_candidates 的清洗。"""
    uid = consolidator._normalize_user_id(str(raw.get("user_id", "")))
    if not uid:
        return None
    content = (raw.get("content", "") or "").strip()
    if not content:
        return None
    validated = validate_candidate({
        "type": (raw.get("type") or "FACT"),
        "content": content,
        "usage_tags": raw.get("usage_tags"),
        "visibility": raw.get("visibility"),
        "behavior_rule": raw.get("behavior_rule"),
        "confidence": raw.get("confidence"),
        "importance": raw.get("importance"),
    })
    return {
        "user_id": uid,
        "type": (validated.get("type") or "FACT").strip().upper(),
        "content": (validated.get("content") or "").strip(),
        "usage_tags": validated.get("usage_tags") or [],
        "visibility": validated.get("visibility") or "OPEN",
        "confidence": validated.get("confidence"),
        "importance": validated.get("importance"),
        "behavior_rule": validated.get("behavior_rule") or "",
    }


def audit_candidate(cand: dict, window: list[dict]) -> list[str]:
    """审计一条候选是否可能是编造的，返回问题标签列表（空=通过）。

    捕获层放宽后，合格标准从「空输出率」换成「编造率」：条数多不再是缺陷，
    但候选必须有出处、归属必须正确。这里做机器可查的部分——
    「内容是否确实来自该用户的发言」仍需人工判断。
    """
    problems: list[str] = []
    if not cand["in_senders"]:
        problems.append("归属不在窗口发送者内")

    # 内容里的关键词元是否在该用户的发言中出现过（弱检查：只查数字与英文词，
    # 如型号/年份/技术名——中文改写幅度大，词面比对会误报）
    import re

    own_text = " ".join(
        (m.get("content") or "") for m in window if str(m.get("user") or "") == cand["user_id"]
    ).lower()
    tokens = set(re.findall(r"[a-zA-Z0-9]{2,}", (cand["content"] or "").lower()))
    missing = [t for t in tokens if t not in own_text]
    if missing:
        problems.append(f"内容含该用户未提过的词元 {missing}")

    return problems


async def run_window(consolidator: MemoryConsolidator, backend: LMStudioBackend, window: list[dict]) -> dict:
    """跑单个窗口的生产整合链路，返回结构化探针结果。"""
    messages = format_messages(window)
    senders = window_senders(window)
    prompt = format_consolidation_prompt("（无）", messages)

    raw = await backend.generate(prompt)
    parsed = consolidator._parse_json(raw)
    candidates = []
    if parsed is not None:
        raw_cands = parsed.get("memory_candidates") or []
        for rc in raw_cands:
            c = _normalize_candidate(consolidator, rc)
            if c is None:
                continue
            c["in_senders"] = c["user_id"] in senders
            c["audit"] = audit_candidate(c, window)
            candidates.append(c)

    return {
        "prompt_messages": messages,
        "senders": senders,
        "raw_output": raw,
        "parsed_ok": parsed is not None,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


async def run_positive(
    consolidator: MemoryConsolidator,
    backend: LMStudioBackend,
    fixture_path: Path,
    repeat: int = 1,
    print_prompt: bool = False,
) -> int:
    """跑正例回归基准，返回退出码（0=通过）。

    repeat > 1 时重复跑并按「最差一次」判定，同时报告逐条稳定命中情况
    （temperature 非 0 时单次运行不构成测量）。
    print_prompt=True 时只打印将要发送的 prompt 并退出、不调用 LLM，
    用于离线比对 format_messages 是否被来源标记污染。
    """
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    cases = data if isinstance(data, list) else [data]

    if print_prompt:
        for case in cases:
            print(f"===== {case['id']} =====")
            print(format_consolidation_prompt("（无）", format_messages(case["messages"])))
        return 0

    all_results: list[tuple[str, list[int], int]] = []
    dumps: list[str] = []
    for case in cases:
        window = case["messages"]
        expects = case["expect"]
        expect_count = case.get("expect_count") or len(expects)

        print(f"── 用例 {case['id']}", file=sys.stderr)

        runs: list[tuple[list[dict | None], list[dict]]] = []
        runs_raw: list[tuple[str, bool]] = []
        for i in range(max(1, repeat)):
            r = await run_window(consolidator, backend, window)
            got = r["candidates"]

            hits: list[dict | None] = []
            for exp in expects:
                hit = next(
                    (c for c in got
                     if c["user_id"] == exp["user_id"]
                     and all(k in c["content"] for k in exp["content_contains"])),
                    None,
                )
                hits.append(hit)

            matched = [h for h in hits if h is not None]
            # extras 只列「没被任何 expect 命中的」候选，避免把已命中项重复报成额外候选
            extras = [c for c in got if all(c is not h for h in matched)]
            runs.append((hits, extras))
            runs_raw.append((r["raw_output"], r["parsed_ok"]))

            raw_len = len(r["raw_output"] or "")
            parse_flag = "✓" if r["parsed_ok"] else "✗ JSON解析失败"
            print(f"── 第 {i + 1}/{max(1, repeat)} 次：命中 {len(matched)}/{expect_count}"
                  f"（候选 {r['candidate_count']} 条，解析 {parse_flag}，原始输出 {raw_len} 字符）",
                  file=sys.stderr)
            for exp, hit in zip(expects, hits, strict=False):
                if hit is not None:
                    print(f"  ✅ user={exp['user_id']} type={hit['type']} 「{hit['content']}」", file=sys.stderr)
                else:
                    print(f"  ❌ 未命中 user={exp['user_id']} 需含 {exp['content_contains']}", file=sys.stderr)
                    # 期望词出现在原始输出里（通常在 short_term.recent_exchanges）但没进候选
                    # → 模型读到了信息、主动判定不值得长期记忆（prompt 规则过严），
                    #   而不是没注意到。两者的修法完全不同。
                    raw_all = " ".join(r["raw_output"] if isinstance(r["raw_output"], list) else [r["raw_output"] or ""])
                    if all(k in raw_all for k in exp["content_contains"]):
                        print("     ↳ 该信息出现在原始输出中但未进候选（模型主动弃掉，非未察觉）",
                              file=sys.stderr)
            if extras:
                print(f"  ⚠️ 另有 {len(extras)} 条额外候选（不判失败，但请人工确认不是过度生成）", file=sys.stderr)
                for c in extras:
                    print(f"     user={c['user_id']} type={c['type']} 「{c['content']}」", file=sys.stderr)

        per_run = [sum(1 for h in hits if h is not None) for hits, _ in runs]
        all_results.append((case["id"], per_run, expect_count))
        print(f"── 用例汇总 {case['id']}：各次命中 {per_run}（判定取最差 {min(per_run)}/{expect_count}）",
              file=sys.stderr)
        for idx, exp in enumerate(expects):
            n = sum(1 for hits, _ in runs if hits[idx] is not None)
            flag = "稳定" if n == len(runs) else ("从未" if n == 0 else "不稳定")
            print(f"  {flag} {n}/{len(runs)} user={exp['user_id']} 需含 {exp['content_contains']}", file=sys.stderr)

        # 原始输出落盘，便于人工看截断发生在哪（fixture 是合成数据，无隐私问题）
        dumps.append("\n\n".join(
            f"## {case['id']} 第 {i + 1} 次（解析 {'✓' if runs_raw[i][1] else '✗'}，{len(runs_raw[i][0] or '')} 字符）\n"
            f"```json\n{(runs_raw[i][0] or '').strip()}\n```"
            for i in range(len(runs_raw))
        ))

    out_positive = Path("consolidation_positive_probe.md")
    out_positive.write_text("\n\n".join(dumps), encoding="utf-8")

    print("── 总汇总", file=sys.stderr)
    for cid, per_run, expect_count in all_results:
        print(f"  {'✅' if min(per_run) == expect_count else '❌'} {cid}: 各次命中 {per_run}/{expect_count}",
              file=sys.stderr)
    return 0 if all(min(p) == c for _, p, c in all_results) else 1


def candidate_key(c: dict) -> tuple:
    """候选集合成员身份：归属 + 类型 + 内容（重复运行间做交集/并集用）。"""
    return (c["user_id"], c["type"], c["content"])


def theme_key(c: dict) -> tuple:
    """主题身份：只看归属 + 类型（内容措辞不同视为同一主题）。
    区分“同一主题换措辞”与“每次抽出完全不同的东西”。
    """
    return (c["user_id"], c["type"])


def jaccard_of(runs: list[set]) -> tuple[int, int, float]:
    union = set().union(*runs) if runs else set()
    inter = set.intersection(*runs) if runs else set()
    ratio = round(len(inter) / len(union), 3) if union else 1.0
    return len(inter), len(union), ratio


def stability_of(repeats: list[dict]) -> dict:
    """同窗口多次运行的主题稳定性：交集/并集。
    同时给出「主题身份」（归属+类型）与「逐字内容」两个层面的比值：
    主题稳定但措辞漂移 → 主题比高、逐字比低，是同一主题的复述而非不稳定。
    返回 (主题交集, 主题并集, 主题比, 逐字比, 各次条数, 《出现于哪几次》逐条明细)。"""
    per_run = [set(candidate_key(c) for c in r["candidates"]) for r in repeats]
    per_theme = [set(theme_key(c) for c in r["candidates"]) for r in repeats]
    counts: Counter = Counter()
    for s in per_run:
        counts.update(s)
    union = set(counts)
    inter = {k for k in union if counts[k] == len(repeats)}
    ratio = round(len(inter) / len(union), 3) if union else 1.0
    theme_inter, theme_union, theme_ratio = jaccard_of(per_theme)
    return {
        "verbatim_intersection": sorted(inter),
        "verbatim_ratio": ratio,
        "theme_intersection_size": theme_inter,
        "theme_union_size": theme_union,
        "theme_ratio": theme_ratio,
        "per_run_counts": [len(s) for s in per_run],
        "detail": {" / ".join(k): f"{c}/{len(repeats)}" for k, c in sorted(counts.items())},
    }


# ── 输出 ────────────────────────────────────────────────

def print_summary(results: list[dict], repeat: int) -> None:
    """多窗口汇总：总候选/平均、空输出率、候选数分布。"""
    if not results:
        return
    # 多窗口用各自第一次运行的候选数（与候选展示口径一致）
    counts = [r["candidate_count"] for r in results]
    n = len(counts)
    total = sum(counts)
    avg = round(total / n, 2) if n else 0.0
    empty = sum(1 for c in counts if c == 0)
    empty_pct = round(empty / n * 100, 1) if n else 0.0
    dist = {k: counts.count(k) for k in sorted(set(counts))}
    dist_str = "  ".join(f"{k}条:{v}" for k, v in dist.items()) or "（无）"
    print(f"── 汇总（{n} 个窗口，重复 {repeat} 次）", file=sys.stderr)
    print(f"窗口 {n} 个，总候选 {total} 条，平均 {avg} 条/窗口", file=sys.stderr)
    flagged = sum(1 for r in results for c in r["candidates"] if c.get("audit"))
    total_cands = sum(r["candidate_count"] for r in results)
    rate = round(flagged / total_cands * 100, 1) if total_cands else 0.0
    print(f"审计可疑候选：{flagged}/{total_cands}（{rate}%）— 目标 ≈ 0%", file=sys.stderr)
    print(f"空输出窗口：{empty} 个（{empty_pct}%）— 捕获层放宽后此项下降属预期，非缺陷", file=sys.stderr)
    parse_failed = sum(1 for r in results if not r["parsed_ok"])
    print(f"JSON 解析失败：{parse_failed} 个（这些窗口的 0 候选是缺陷，不是正确的空输出）", file=sys.stderr)
    print(f"候选数分布：{dist_str}", file=sys.stderr)


def render_window_text(window: list[dict]) -> str:
    """窗口原文：前 5 条 + 后 5 条，中间省略。"""
    if len(window) <= 10:
        rows = window
    else:
        rows = window[:5] + [{"user": "…", "content": f"（中间省略 {len(window) - 10} 条）", "ts": ""}] + window[-5:]
    return "\n".join(f"用户({m.get('user')}) {m.get('ts', '')}: {m.get('content')}" for m in rows)


def render_candidates(c: list[dict], window: list[dict]) -> list[str]:
    lines = []
    for cand in c:
        tag = "" if cand["in_senders"] else " ⚠️归属不在窗口发送者内"
        line = (
            f"- user={cand['user_id']} type={cand['type']} "
            f"usage={cand['usage_tags']} vis={cand['visibility']} "
            f"conf={cand['confidence']}{tag}\n  「{cand['content']}」"
            + (f"\n  behavior_rule={cand['behavior_rule']}" if cand["behavior_rule"] else "")
        )
        audit = cand.get("audit") or audit_candidate(cand, window)
        if audit:
            line += "\n  ⚠️ 审计: " + "；".join(audit)
        lines.append(line)
    return lines


def render_markdown(windows: list[list[dict]], results: list[dict], repeat: int) -> str:
    md = [
        "# Consolidation Probe（真实数据，禁止入库）",
        "",
        f"- 窗口数：{len(windows)}，重复次数：{repeat}",
        f"- 路径：`scripts/probe_consolidation.py`（生产链路：同一 prompt 模板 / 同一解析 / 同 validate_candidate）",
        "- ⚠️ 本文件含真实群聊内容，仅供本地人工检查，禁止提交。",
        "",
    ]
    for idx, (w, r) in enumerate(zip(windows, results, strict=False)):
        md.append(f"## 窗口 {idx}（{len(w)} 条）")
        md.append("### 窗口原文（前 5 / 后 5）")
        md.append("```")
        md.append(render_window_text(w))
        md.append("```")
        md.append("### LLM 原始输出")
        raw_outputs = r["raw_output"] if isinstance(r["raw_output"], list) else [r["raw_output"]]
        if len(raw_outputs) > 1:
            for i, ro in enumerate(raw_outputs):
                md.append(f"（第 {i + 1} 次）")
                md.append("```")
                md.append((ro or "").strip() or "（空回复）")
                md.append("```")
        else:
            md.append("```")
            md.append((raw_outputs[0] or "").strip() or "（空回复）")
            md.append("```")
        if repeat > 1:
            st = r.get("stability") or {}
            md.append(f"### 稳定性（{repeat} 次）")
            md.append(
                f"主题（归属+类型）交集/并集 = {st.get('theme_intersection_size')}/{st.get('theme_union_size')} "
                f"→ {st.get('theme_ratio')}；逐字内容比 = {st.get('verbatim_ratio')}"
            )
            md.append(f"每次条数 {st.get('per_run_counts')}")
        md.append("### 解析并过 validate_candidate 后的候选")
        md.append(f"候选 {r['candidate_count']} 条，JSON 解析 {'✓' if r['parsed_ok'] else '✗'}")
        lines = render_candidates(r["candidates"], w) if r["candidates"] else ["（无候选）"]
        md.extend(lines)
        md.append("")
        md.append("---")
        md.append("")
    return "\n".join(md)


# ── CLI ────────────────────────────────────────────────

async def _amain() -> None:
    ap = argparse.ArgumentParser(description="整合器探针：对真实窗口跑生产整合链路")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="windows_raw.json 路径")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个窗口（0=全部）")
    ap.add_argument("--window-index", type=int, default=None, help="只重跑某个窗口")
    ap.add_argument("--repeat", type=int, default=1, help="同一窗口重复次数（稳定性观察，默认 1）")
    ap.add_argument("--temperature", type=float, default=None, help="覆盖采样温度（默认用配置值）")
    ap.add_argument("--positive", action="store_true",
                    help="跑正例回归基准（memory/benchmark/_fixtures/consolidation_positive.json），未达标非零退出")
    ap.add_argument("--positive-fixture", type=Path, default=POSITIVE_FIXTURE)
    ap.add_argument("--print-prompt", action="store_true",
                    help="只打印将发送的 prompt 并退出，不调 LLM（比对格式化是否被来源标记污染）")
    a = ap.parse_args()

    # 复用生产后端构造参数，temperature 可被探针显式覆盖（不改生产代码）
    backend = LMStudioBackend(
        base_url=CONSOLIDATION_LM_STUDIO_BASE_URL,
        model=CONSOLIDATION_LM_STUDIO_MODEL,
        max_tokens=CONSOLIDATION_LOCAL_MAX_TOKENS,
        temperature=a.temperature if a.temperature is not None else CONSOLIDATION_LM_STUDIO_TEMPERATURE,
    )
    consolidator = MemoryConsolidator()

    # 必须在 windows_raw.json 存在性检查之前短路：正例回归不依赖采样窗口
    if a.positive:
        sys.exit(await run_positive(consolidator, backend, a.positive_fixture,
                                    repeat=a.repeat, print_prompt=a.print_prompt))

    if not a.input.exists():
        sys.exit(f"❌ 找不到 {a.input}，请先运行 scripts/sample_windows.py")
    windows = read_windows(a.input)
    if not windows:
        sys.exit("❌ windows_raw.json 为空")

    if a.window_index is not None:
        if not 0 <= a.window_index < len(windows):
            sys.exit(f"❌ --window-index {a.window_index} 越界：窗口范围是 0~{len(windows) - 1}")
        indices = [a.window_index]
    else:
        indices = list(range(len(windows)))
        if a.limit:
            indices = indices[: a.limit]

    results: list[dict] = []
    for idx in indices:
        w = windows[idx]
        print(f"── 窗口 {idx}（{len(w)} 条），重复 {a.repeat} 次", file=sys.stderr)
        if a.repeat > 1:
            repeats = [await run_window(consolidator, backend, w) for _ in range(a.repeat)]
            base = dict(repeats[0])
            base["stability"] = stability_of(repeats)
            base["raw_output"] = [r["raw_output"] for r in repeats]
            base["candidates"] = repeats[0]["candidates"]
            results.append(base)
        else:
            results.append(await run_window(consolidator, backend, w))

    sorted_pairs = sorted(zip(indices, results), key=lambda p: p[0])
    md = render_markdown(windows, [r for _, r in sorted_pairs], a.repeat)
    print_summary([r for _, r in sorted_pairs], a.repeat)
    OUT_MD.write_text(md, encoding="utf-8")
    OUT_JSON.write_text(json.dumps(
        {"windows": [{i: json.dumps(windows[i], ensure_ascii=False)} for i, _ in sorted_pairs],
         "results": [r for _, r in sorted_pairs]},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    print(f"✅ 已写入 {OUT_MD} 与 {OUT_JSON}")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()