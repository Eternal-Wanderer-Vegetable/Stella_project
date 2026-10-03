#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""隔离验证执行器 CLI（计划 §6.7.2 / M5，Dashboard 适配的唯一执行入口）。

固定参数 schema（无生产默认路径——workdir/dataset 必填，数据集路径必须已
存在，绝不回退生产记忆库）::

    python scripts/run_flow_evaluation.py \\
        --mode isolated_pipeline \\
        --dataset <dataset_dir> \\
        --workdir <workdir> \\
        [--snapshot <snapshot_dir>] \\
        [--seed 42] \\
        [--budget-max-calls 100] \\
        [--budget-timeout 600] \\
        [--json]

- ``--json``：把 ExperimentReport 以机器可读 JSON 打到 stdout；
- 退出码：0=completed，3=partial（预算/超时被截断），1=failed/参数非法。

worker 子命令（内部参数，由 ``core.evaluation.runner`` 以子进程方式调用，
实现 isolated_pipeline / model_validation 的进程级隔离）::

    python scripts/run_flow_evaluation.py --worker --worker-config <json_path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 允许直接 `python scripts/run_flow_evaluation.py` 运行：把项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.evaluation.runner import (
    MODES,
    ExperimentConfig,
    run_experiment,
    run_worker,
)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_flow_evaluation",
        description="隔离验证执行器：dataset 回放 / 决策重算 / 隔离 pipeline / 模型验证",
    )
    # --mode/--dataset/--workdir 的 required 校验在 main() 手工完成：
    # worker 子命令复用同一 CLI，但不需要这三者，argparse 会提前拦掉 worker。
    parser.add_argument(
        "--mode", choices=list(MODES), default=None, help="实验模式（四选一；普通模式必填）"
    )
    parser.add_argument(
        "--dataset", default=None,
        help="数据集目录（manifest.json + messages.jsonl；普通模式必填且必须已存在）",
    )
    parser.add_argument(
        "--workdir", default=None,
        help="实验工作目录（全部状态强制留在其下；普通模式必填；无生产默认路径）",
    )
    parser.add_argument("--snapshot", default=None, help="可选快照目录（backup API 沙箱快照）")
    parser.add_argument("--seed", type=int, default=None, help="随机种子（记录进报告）")
    parser.add_argument(
        "--budget-max-calls", type=int, default=None,
        help="模型调用预算上限；超限停止并把未执行样本标 dropped",
    )
    parser.add_argument(
        "--budget-timeout", type=float, default=None,
        help="墙钟预算（秒）；超时杀 worker 并保存 partial 报告",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 报告")
    # worker 内部参数：由 core.evaluation.runner 子进程调用
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--worker-config", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.worker:
        return _run_worker(args)

    # 普通模式必填项（无生产默认路径：缺了就拒绝，绝不回退）
    missing = [
        name for name, value in
        (("--mode", args.mode), ("--dataset", args.dataset), ("--workdir", args.workdir))
        if not value
    ]
    if missing:
        print(f"[evaluation] 缺少必填参数: {', '.join(missing)}", file=sys.stderr)
        return EXIT_FAILED
    dataset = Path(args.dataset).resolve()
    if not dataset.is_dir():
        print(f"[evaluation] 数据集目录不存在: {dataset}", file=sys.stderr)
        return EXIT_FAILED
    workdir = Path(args.workdir).resolve()
    snapshot = Path(args.snapshot).resolve() if args.snapshot else None
    if args.snapshot and not snapshot.is_dir():
        print(f"[evaluation] 快照目录不存在: {snapshot}", file=sys.stderr)
        return EXIT_FAILED

    config = ExperimentConfig(
        mode=args.mode,
        dataset_dir=dataset,
        workdir=workdir,
        snapshot_dir=snapshot,
        seed=args.seed,
        budget_max_calls=args.budget_max_calls,
        budget_timeout=args.budget_timeout,
    )
    try:
        report = run_experiment(config)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[evaluation] 实验失败: {exc}", file=sys.stderr)
        return EXIT_FAILED

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        stability = report.stability
        print(
            f"[evaluation] mode={report.mode} status={report.status}"
            f" samples={stability.valid}/{stability.total}"
            f" coverage={stability.coverage:.2%}"
            f" digest={report.semantic_digest()[:12]}"
        )
        for dimension in stability.dimensions:
            print(f"  - {dimension.name}: {dimension.status.value} {dimension.detail}")
        print(f"  report: {Path(report.workdir) / 'artifacts' / 'report.json'}")

    return EXIT_OK if report.status == "completed" else EXIT_PARTIAL


def _run_worker(args: argparse.Namespace) -> int:
    """worker 子命令：加载配置 JSON → 子进程内执行 pipeline → 落盘报告。"""
    if not args.worker_config:
        print("[evaluation] --worker 需要 --worker-config <json_path>", file=sys.stderr)
        return EXIT_FAILED
    cfg_path = Path(args.worker_config)
    if not cfg_path.is_file():
        print(f"[evaluation] worker 配置不存在: {cfg_path}", file=sys.stderr)
        return EXIT_FAILED
    config_dict = json.loads(cfg_path.read_text(encoding="utf-8"))
    try:
        report_dict = run_worker(config_dict)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"[evaluation] worker 执行失败: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(
        f"[evaluation][worker] status={report_dict['status']}"
        f" samples={len(report_dict['samples'])}",
        file=sys.stderr,
    )
    return EXIT_OK if report_dict["status"] == "completed" else EXIT_PARTIAL


if __name__ == "__main__":
    raise SystemExit(main())
