# SPDX-License-Identifier: AGPL-3.0
# 一次性分析：P4 未见数据验证集（8 段 1,682 题）与 production 基线逐题配对对比。
# 用法：python E:/stella/runs/memory-eval/analyze_p4.py
import json
import statistics
from pathlib import Path

RUN = Path("E:/stella/runs/memory-eval/p4-validation")
BASE = Path("E:/stella/runs/memory-eval/locomo-full-qa")
SEEN = {26, 30}
NAMES = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop", 5: "adversarial"}


def load(root):
    out = {}
    for f in Path(root).glob("locomo-conv-*/qa_results.jsonl"):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                out[r["qid"]] = r
    return out


def stats(rows, name):
    graded = [r for r in rows if r.get("verdict") in ("correct", "incorrect", "unparseable")]
    hits = sum(1 for r in graded if r["verdict"] == "correct")
    ans = [r for r in graded if r.get("gold_answer")]
    ah = sum(1 for r in ans if r["verdict"] == "correct")
    adv = [r for r in graded if not r.get("gold_answer")]
    ab = sum(1 for r in adv if r["verdict"] == "correct")
    ev = sum(
        1
        for r in ans
        if any(f"gold-{x}" in (r.get("retrieved_ids") or []) for x in r.get("evidence_dia_ids") or [])
    )
    gated = sum(1 for r in graded if (r.get("sufficiency") or "").startswith(("INSUFFICIENT",)))
    suff = {}
    for r in graded:
        s = r.get("sufficiency") or "?"
        suff[s] = suff.get(s, 0) + 1
    return {
        "cell": name,
        "n": len(graded),
        "overall": round(hits / len(graded) * 100, 1),
        "answerable": round(ah / len(ans) * 100, 1),
        "answerable_hits": ah,
        "abstain": round(ab / len(adv) * 100, 1),
        "ev_any": round(ev / len(ans) * 100, 1),
        "gated_insufficient": gated,
        "sufficiency": suff,
    }


p4_rows = list(load(RUN).values())
base = load(BASE)

print("== P4 未见验证集（8 段）改进栈全组合 vs production 基线 ==")
print(json.dumps(stats(p4_rows, "P4 stack"), ensure_ascii=False, indent=1))
base_seen = [r for q, r in base.items() if int(q.split("-")[1]) in SEEN]
base_unseen = [r for q, r in base.items() if int(q.split("-")[1]) not in SEEN]
print(json.dumps(stats(base_unseen, "production(unseen)"), ensure_ascii=False, indent=1))

# 分类别（unseen）
bycat = {}
for r in p4_rows:
    if r.get("verdict") not in ("correct", "incorrect", "unparseable"):
        continue
    c = NAMES[int(r["category"])]
    bycat.setdefault(c, [0, 0])
    bycat[c][0] += r["verdict"] == "correct"
    bycat[c][1] += 1
print("P4 stack 分类:", {c: f"{h}/{n} ({round(h/n*100,1)}%)" for c, (h, n) in sorted(bycat.items())})

# 基线同题配对（unseen 交集）
p4 = load(RUN)
common = [q for q in p4 if q in base and int(q.split("-")[1]) not in SEEN]
flips_up = sum(1 for q in common if p4[q]["verdict"] == "correct" and base[q]["verdict"] != "correct")
flips_down = sum(1 for q in common if base[q]["verdict"] == "correct" and p4[q]["verdict"] != "correct")
p4h = sum(1 for q in common if p4[q]["verdict"] == "correct")
bh = sum(1 for q in common if base[q]["verdict"] == "correct")
print(f"\n配对子集 n={len(common)}: stack {p4h} 对 vs baseline {bh} 对（{flips_up} 升 / {flips_down} 降）")

# 预算（T3 表示在 unseen 上的占用）
ptok = [r.get("answer_prompt_tokens") or 0 for r in p4_rows if r.get("verdict")]
lat = sorted(r.get("answer_latency_seconds") or 0 for r in p4_rows if r.get("verdict"))
if ptok:
    print(
        f"预算: prompt_tok mean={statistics.mean(ptok):.0f} p95={sorted(ptok)[int(len(ptok)*0.95)]}"
        f" | latency p50={lat[len(lat)//2]:.1f}s p95={lat[int(len(lat)*0.95)]:.1f}s"
    )
