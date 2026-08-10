# scripts/build_embedding_fixture.py
# SPDX-License-Identifier: AGPL-3.0
"""构建 embedding 语义分 fixture，供 ``memory.benchmark --embedding-fixture`` 用。

扫描所有 benchmark 用例的 ``input`` 与 ``memories[*].content``，去重后批量编码为
向量并写入 ``memory/benchmark/_fixtures/embeddings_<model>.json``。之后跑 benchmark
只需从 fixture 查向量（按文本 sha256 索引），**不发 HTTP**，保证 CI 可复现。

编码约定（与 memory/embeddings.py 一致）：
- query 与 content 一律裸文本，不加 ``Instruct:`` 前缀；
- 维度固定 1024（LM Studio 忽略 ``dimensions``，不做 MRL）；
- 用 float16 + base64 打包（约 400KB，直接存 JSON 约 1.8MB）。

用法（项目根目录，LM Studio 已加载 embedding 模型）：
    python scripts/build_embedding_fixture.py
    python scripts/build_embedding_fixture.py --model text-embedding-qwen3-embedding-0.6b --out path.json
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from pathlib import Path

import httpx
import numpy as np

from memory.benchmark import load_cases

DEFAULT_MODEL = "text-embedding-qwen3-embedding-0.6b"
DEFAULT_BASE = "http://127.0.0.1:1234"
FIXTURE_DIR = Path(__file__).resolve().parent.parent / "memory" / "benchmark" / "_fixtures"


def collect_texts(cases: list[dict]) -> list[str]:
    """去重收集所有用例的 input 与记忆 content（保序）。"""
    seen: set[str] = set()
    texts: list[str] = []
    for c in cases:
        for text in [c.get("input"), *(m.get("content") for m in (c.get("memories") or {}).values())]:
            t = (text or "").strip()
            if t and t not in seen:
                seen.add(t)
                texts.append(t)
    return texts


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_batch(texts: list[str], model: str, base: str) -> dict[str, str]:
    """把一批文本编码为 float16 + base64 向量（key=sha256(text)）。"""
    r = httpx.post(
        f"{base.rstrip('/')}/v1/embeddings",
        json={"model": model, "input": texts},
        timeout=300,
        trust_env=False,
    )
    if r.status_code != 200:
        sys.exit(f"❌ HTTP {r.status_code}: {r.text[:400]}")
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    out: dict[str, str] = {}
    for d, text in zip(data, texts, strict=False):
        v = np.asarray(d["embedding"], dtype=np.float32)
        if v.ndim != 1 or v.size == 0:
            sys.exit("❌ embedding 返回为空")
        # 归一化后转 float16 打包
        v = v / np.linalg.norm(v) if np.linalg.norm(v) > 0 else v
        out[digest(text)] = base64.b64encode(v.astype(np.float16).tobytes()).decode("ascii")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL, help="embedding 模型 ID")
    ap.add_argument("--base", default=DEFAULT_BASE, help="LM Studio 服务地址")
    ap.add_argument("--out", default=None, help="输出路径（缺省 memory/benchmark/_fixtures/…）")
    a = ap.parse_args()

    cases = load_cases()
    texts = collect_texts(cases)
    print(f"用例 {len(cases)} 条，去重文本 {len(texts)} 段，正在编码…")
    data = embed_batch(texts, a.model, a.base)

    fixture = {
        "model": a.model,
        "dim": 1024,
        "dtype": "float16",
        "normalized": True,
        "keys": sorted(data),
        "data": data,
    }
    if a.out:
        out_path = Path(a.out)
    else:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        safe = a.model.replace("/", "-").replace(":", "_")
        out_path = FIXTURE_DIR / f"embeddings_{safe}.json"
    out_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    print(f"✅ 已写入 {out_path}（{len(data)} 条向量，约 {out_path.stat().st_size // 1024} KB）")


if __name__ == "__main__":
    main()
