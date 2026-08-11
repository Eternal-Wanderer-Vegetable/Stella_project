# scripts/probe_embedding.py
# SPDX-License-Identifier: AGPL-3.0
"""Qwen3-Embedding 探针：验证模型对 benchmark 真实用例是否具备区分力（不改动生产代码）。

用法（项目根目录，LM Studio 已加载 embedding 模型）：
    python scripts/probe_embedding.py

约定（依据实测，与 memory/embeddings.py 一致）：
- query 与 content 一律裸文本编码，不加 ``Instruct:`` 前缀（无前缀正/噪音中位差 0.124
  优于加前缀 0.110；最差间隔 −0.109 也优于 −0.145）；
- 维度固定 1024，不做 MRL 降维（LM Studio 忽略 ``dimensions`` 参数）。

输出：每用例正样本最低/噪音最高 cosine 的“间隔”，以及全局噪音/正样本分布，
供 MEMORY_EMBEDDING_CONTEXTUAL_MIN 定阈值用。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许直接 `python scripts/probe_embedding.py` 运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import numpy as np

from memory.benchmark import load_cases

BASE = "http://127.0.0.1:1234"
MODEL = "text-embedding-qwen3-embedding-0.6b"


def embed(texts: list[str]) -> list[np.ndarray]:
    """批量取向量并做 L2 归一化（LM Studio 不保证归一化）。"""
    payload: dict = {"model": MODEL, "input": texts}
    r = httpx.post(f"{BASE}/v1/embeddings", json=payload,
                   timeout=120, trust_env=False)   # trust_env=False 绕过本机代理
    if r.status_code != 200:
        sys.exit(f"❌ HTTP {r.status_code}: {r.text[:400]}")
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    out = []
    for d in data:
        v = np.asarray(d["embedding"], dtype=np.float32)
        n = np.linalg.norm(v)
        out.append(v / n if n > 0 else v)
    return out


def label_of(mid: str, case: dict) -> str:
    if mid in (case.get("expected_memory") or []):
        return "期望"
    if mid in (case.get("expected_behavior_memory") or []):
        return "行为"
    if mid in (case.get("forbidden_memory") or []):
        return "禁止"
    return "噪音"


def run() -> None:
    cases = [c for c in load_cases() if c.get("input") and c.get("memories")]
    print("=" * 68)
    print("Qwen3-Embedding 探针（裸文本，无指令前缀，维度 1024）")
    print(f"用例 {len(cases)} 条")
    print("=" * 68 + "\n")

    # 探测维度与归一化状态（用未归一化的原始返回值看范数）
    raw = httpx.post(f"{BASE}/v1/embeddings",
                     json={"model": MODEL, "input": ["维度探测"]},
                     timeout=60, trust_env=False).json()["data"][0]["embedding"]
    rv = np.asarray(raw, dtype=np.float32)
    print(f"原始维度 = {len(rv)}   原始 L2 范数 = {np.linalg.norm(rv):.4f}")
    print("（范数≠1.0 ⇒ embeddings.py 的 cosine 必须自己除模长）\n")

    margins: list[tuple[str, float]] = []
    noise_scores: list[float] = []
    positive_scores: list[float] = []

    for case in cases:
        cid = case.get("id", "?")
        mems = case["memories"]
        mids = sorted(mems)
        contents = [(mems[m].get("content") or "") for m in mids]

        qv = embed([case["input"]])[0]
        mvs = embed(contents)

        rows = []
        for mid, mv in zip(mids, mvs, strict=False):
            s = float(qv @ mv)          # 已归一化 ⇒ 点积即 cosine
            lab = label_of(mid, case)
            rows.append((s, mid, lab))
            if lab in ("期望", "行为"):
                positive_scores.append(s)
            elif lab == "噪音":
                noise_scores.append(s)
        rows.sort(reverse=True)

        pos = [s for s, _, lab in rows if lab in ("期望", "行为")]
        noi = [s for s, _, lab in rows if lab == "噪音"]

        print(f"── {cid}   query={case['input']!r}")
        for s, mid, lab in rows:
            mark = {"期望": "✓", "行为": "◆", "禁止": "✗", "噪音": " "}[lab]
            txt = (mems[mid].get("content") or "")[:28]
            print(f"   {s:+.4f} {mark} [{lab}] {mid:<16} {txt}")
        if pos and noi:
            m = min(pos) - max(noi)
            margins.append((cid, m))
            flag = "✅" if m > 0 else "❌"
            print(f"   {flag} 正样本最低 {min(pos):+.4f} / 噪音最高 {max(noi):+.4f} → 间隔 {m:+.4f}")
        else:
            print("   （无正/噪音对照，跳过间隔计算）")
        print()

    # ── 汇总 ──
    print("=" * 68)
    if margins:
        vals = np.array([m for _, m in margins])
        worst_id, worst = min(margins, key=lambda x: x[1])
        print(f"每用例间隔：正 {int((vals > 0).sum())}/{len(vals)} 条   "
              f"最差 {worst:+.4f}（{worst_id}）   中位 {np.median(vals):+.4f}")
    if noise_scores and positive_scores:
        a, p = np.array(noise_scores), np.array(positive_scores)
        print(f"\n噪音 cosine : 中位 {np.median(a):.3f}  p90 {np.percentile(a, 90):.3f}  "
              f"p95 {np.percentile(a, 95):.3f}  max {a.max():.3f}")
        print(f"正样本 cosine: 中位 {np.median(p):.3f}  p10 {np.percentile(p, 10):.3f}  "
              f"min {p.min():.3f}")
        print(f"\n→ MEMORY_EMBEDDING_CONTEXTUAL_MIN 建议 ≈ {np.percentile(a, 95):.2f}")
        overlap = np.percentile(a, 95) - np.percentile(p, 10)
        print(f"→ 全局重叠量 = 噪音p95 − 正样本p10 = {overlap:+.3f}"
              f"（≤0 表示两类基本分开）")
    print("=" * 68)


if __name__ == "__main__":
    run()
