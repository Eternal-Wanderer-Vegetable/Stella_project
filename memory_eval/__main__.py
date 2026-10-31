# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""memory_eval CLI（在仓库根目录运行）。

用法示例：
    # smoke：2 段对话、每类抽 3 题
    python -m memory_eval --data-dir memory/benchmark/_public/locomo/adapted \
        --workdir runs/smoke --stage all --mode hybrid \
        --conversations 2 --qa-sample 3 \
        --llm-base-url http://127.0.0.1:1234/v1 --llm-model qwen/qwen3.8-27b

    # 全量
    python -m memory_eval --workdir runs/full --stage all --mode hybrid --resume

阶段：``--stage ingest``（只摄入）/ ``qa``（只问答，须先摄入）/ ``all``。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m memory_eval",
        description="公开数据集 × 真实记忆链路端到端评测（MBENCH-002）",
    )
    parser.add_argument("--data-dir", type=Path,
                        default=Path("memory/benchmark/_public/locomo/adapted"),
                        help="适配场景目录（scripts/adapt_locomo.py 产出）")
    parser.add_argument("--workdir", type=Path, required=True,
                        help="运行工作目录（隔离 DB/进度/报告都放这里）")
    parser.add_argument("--out", type=Path, default=None, help="报告输出目录（默认 <workdir>/report）")
    parser.add_argument("--stage", choices=("ingest", "qa", "all"), default="all")
    parser.add_argument("--mode", choices=("rule", "embedding", "fts", "hybrid"), default="hybrid",
                        help="检索通道（生产默认形态是 hybrid）")
    parser.add_argument("--pack-mode", choices=("auto", "casual", "tech", "conflict"),
                        default="auto",
                        help="检索用法模式：auto=生产自动分类；conflict=limit10 检索友好对照")
    parser.add_argument("--conversations", type=int, default=0, help="只跑前 N 段（0=全部）")
    parser.add_argument("--qa-sample", type=int, default=0, help="每类别抽样 N 题（0=全量）")
    parser.add_argument("--seed", type=int, default=20261031, help="抽样种子")
    parser.add_argument("--resume", action="store_true", help="复用 workdir 内已完成的进度")
    parser.add_argument("--llm-base-url", default="http://127.0.0.1:1234/v1",
                        help="OpenAI 兼容端点（answer/judge）")
    parser.add_argument("--llm-model", default=None, help="answer/judge 模型 ID（缺省取端点首个）")
    parser.add_argument("--judge-model", default=None, help="独立 judge 模型（缺省与 answer 相同）")
    parser.add_argument("--llm-api-key", default="", help="端点 API key（本地端点通常为空）")
    parser.add_argument("--embedding-base-url", default=None,
                        help="embedding 端点（缺省用 MEMORY_EMBEDDING_BASE_URL）")
    parser.add_argument("--embedding-model", default=None,
                        help="embedding 模型（缺省用 MEMORY_EMBEDDING_MODEL）")
    parser.add_argument("--memory-base-url", default=None,
                        help="整合/提取（ROLE_CONSOLIDATION/EXTRACT）端点；缺省用配置默认槽位。"
                             "评测进程 STELLA_HOME 是隔离的，不读用户 .env")
    parser.add_argument("--memory-model", default=None,
                        help="整合/提取模型 ID（如 qwen/qwen3.8-27b）")
    parser.add_argument("--consolidation", choices=("live", "oracle"), default="live",
                        help="写侧模式：live=生产整合/提取 LLM；oracle=机械抽取合同句型"
                             "（无写侧 LLM，用于 harness 校验与 Oracle 实验）")
    parser.add_argument("--inject-gold", action="store_true",
                        help="Oracle 上界实验：把 QA 证据轮原文直接注入 memories"
                             "（id=gold-*，幂等），测检索+生成上界")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 顺序关键：先设环境（含 MEMORY 槽位覆盖），再把 STELLA_HOME/DB_PATH 指向
    # 隔离目录，最后才允许导入任何 config/memory 模块
    import os

    if args.memory_base_url:
        os.environ["LLM_ENDPOINT_MEMORY_BASE_URL"] = args.memory_base_url
    if args.memory_model:
        os.environ["LLM_ENDPOINT_MEMORY_MODEL"] = args.memory_model
    if not args.resume and args.workdir.exists() and any(args.workdir.iterdir()):
        print(f"❌ 工作目录非空：{args.workdir}（--resume 续跑，或换目录/清空）", file=sys.stderr)
        return 2
    args.workdir.mkdir(parents=True, exist_ok=True)

    # 顺序关键：先把 STELLA_HOME/DB_PATH 指向隔离目录，再导入任何 config/memory 模块
    from memory_eval.isolation import ensure_eval_home

    ensure_eval_home(args.workdir)

    from memory_eval.runner import run

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
