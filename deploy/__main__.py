# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor / init / start 三个子命令的入口。

用法：python -m deploy doctor [--json]
      python -m deploy init
      python -m deploy start [--force]
"""

from __future__ import annotations

import argparse
import contextlib
import sys

from . import checks, probe, report


def _cmd_doctor(args: argparse.Namespace) -> int:
    snapshot = probe.collect()
    results = checks.run_all(snapshot)
    if args.json:
        print(report.to_json(results))
    else:
        print(report.to_terminal(results))
    return 1 if report.has_blocking(results) else 0


def _cmd_init(args: argparse.Namespace) -> int:
    print("init 向导将在下一步实现（生成 .env / 初始化数据库）。")
    return 0


def _cmd_start(args: argparse.Namespace) -> int:
    snapshot = probe.collect()
    results = checks.run_all(snapshot)
    if report.has_blocking(results):
        if not args.force:
            print(report.to_terminal(results))
            print("存在阻塞性问题。确认原因后可用 python -m deploy start --force 忽略。")
            return 1
        print("[跳过] 发现阻塞性问题，但 --force 已指定，继续启动。")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 固定 UTF-8：Windows 下 stdout 被重定向（GUI 读管道/PS 管道）时
    # Python 会改用 ANSI 代码页，导致中文变乱码。强制 UTF-8 后
    # 无论管道还是控制台输出都一致，GUI 直接按 UTF-8 解码原始字节即可。
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m deploy",
        description="Stella 部署与自检工具",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="环境自检")
    p_doctor.add_argument("--json", action="store_true", help="输出 JSON（供 GUI 使用）")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_init = sub.add_parser("init", help="初始化配置")
    p_init.set_defaults(func=_cmd_init)

    p_start = sub.add_parser("start", help="启动（先跑 doctor）")
    p_start.add_argument("--force", action="store_true", help="忽略阻塞问题继续启动")
    p_start.set_defaults(func=_cmd_start)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
