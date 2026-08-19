# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor / init / start / status / stop 子命令的入口。

用法：python -m deploy doctor [--json]
      python -m deploy init [--answers PATH] [--force] [--dry-run]
      python -m deploy start [--force] [--detach]
      python -m deploy status [--json]
      python -m deploy stop
"""

from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path

from config import PROJECT_ROOT

from . import checks, probe, process, report
from .init_wizard import (
    load_answers,
    print_next_steps,
    render_env,
    run_interactive,
    save_answers,
    validate_answers,
)


def _cmd_doctor(args: argparse.Namespace) -> int:
    snapshot = probe.collect()
    results = checks.run_all(snapshot)
    if args.json:
        print(report.to_json(results))
    else:
        print(report.to_terminal(results))
    return 1 if report.has_blocking(results) else 0


def _cmd_init(args: argparse.Namespace) -> int:
    env_path = PROJECT_ROOT / ".env"
    template_path = PROJECT_ROOT / ".env.example"

    if env_path.exists() and not args.force:
        print(f"{env_path} 已存在。确认覆盖请加 --force（会先备份为 .env.bak）。")
        return 1
    if not template_path.exists():
        print(f"缺少模板 {template_path}，无法生成 .env。")
        return 1

    answers = load_answers(Path(args.answers)) if args.answers else run_interactive()

    problems = validate_answers(answers)
    if problems:
        print("配置有误：")
        for p in problems:
            print(f"  - {p}")
        return 1

    rendered = render_env(answers, template_path.read_text(encoding="utf-8"))

    if args.dry_run:
        print(rendered)
        return 0

    if env_path.exists():
        backup = PROJECT_ROOT / ".env.bak"
        env_path.replace(backup)
        print(f"已备份原配置到 {backup}")
        print("注意：向导只管理 5 个必答项，其余保持模板默认值。")
        print("若你此前手工调过阈值类配置（如 PROACTIVE_* / MEMORY_*），请从 .env.bak 里对照恢复。")
    env_path.write_text(rendered, encoding="utf-8")
    print(f"已写入 {env_path}")

    if not args.answers:
        answers_path = PROJECT_ROOT / "deploy.answers.toml"
        save_answers(answers, answers_path)
        print(f"应答已保存到 {answers_path}（下次可用 --answers 跳过提问）")

    # 必须用子进程跑 doctor，不能在本进程内调 probe.collect()：
    # config/settings.py 在 import 时执行 load_dotenv()，而本模块顶部就
    # from config import PROJECT_ROOT——.env 尚不存在时 config 已被导入，
    # 全部常量冻结为默认值（空）。向导写出 .env 后，同一进程里读到的仍是
    # 那批空值，于是 doctor 谎报「ALLOWED_GROUPS 为空」「未配置模型 ID」
    # （2026-08-18 实测：首次配置后必现，第二次启动就消失）。
    # 重新 import 也救不了——各模块都是 from config import X，已绑定旧值。
    # 新进程是唯一能保证「读到刚写入的 .env」的方式。
    print()
    print("正在检查环境（数据库相关项会在首次启动后才就绪）...")
    print()
    subprocess.run(
        [sys.executable, "-m", "deploy", "doctor"],
        cwd=str(PROJECT_ROOT),
        check=False,   # doctor 退出码 1 表示「有阻塞问题」，不代表 init 失败
    )

    print_next_steps(answers)
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
    if args.detach:
        return process.start_detached()
    bot_path = PROJECT_ROOT / "bot.py"
    if not bot_path.exists():
        print(f"缺少入口 {bot_path}，无法启动。")
        return 1
    print(f"启动 Stella：{sys.executable} bot.py")
    return subprocess.call([sys.executable, str(bot_path)])


def _fmt_secs(value: float | None) -> str:
    """秒数 → 可读字符串；None 显示为「—」。

    dict.get(key, 0) 的默认值只在**键不存在**时生效，而 link_status() 里
    connected_seconds / last_event_seconds_ago 在未连接时是显式的 None——
    键存在、值为 None，默认值不会生效，直接进 :.0f 会 TypeError
    （2026-08-19 实测：未连 NapCat 时 status 必崩）。
    """
    if value is None:
        return "—"
    if value < 60:
        return f"{value:.0f} 秒"
    if value < 3600:
        return f"{value / 60:.0f} 分钟"
    return f"{value / 3600:.1f} 小时"


def _cmd_status(args: argparse.Namespace) -> int:
    data = process.status()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        if data["alive"]:
            pid_txt = f"（PID {data['pid']}）" if data.get("pid") else ""
            print(f"Stella 正在运行{pid_txt}。")
            if not data.get("api_reachable"):
                # PID 文件说活着但接口不可达：仍在启动中，或状态接口被关闭
                print("  状态接口不可达 —— 可能仍在启动，或 STELLA_STATUS_API_ENABLED=false。")
            elif not data.get("pid_file_present"):
                # 接口可达但无 PID 文件：不是 deploy start --detach 启动的
                print("  未找到 PID 文件 —— 该进程可能是手工启动的（deploy stop 无法停止它）。")
            link = data.get("link")
            if link:
                if not link.get("enabled"):
                    print("  链路监测已关闭（LINK_MONITOR_ENABLED=false）。")
                elif link.get("connected"):
                    print(
                        f"  链路：{'健康' if link.get('healthy') else '异常'}"
                        f"（QQ {link.get('bot_self_id') or '?'}，"
                        f"已连接 {_fmt_secs(link.get('connected_seconds'))}，"
                        f"最近事件 {_fmt_secs(link.get('last_event_seconds_ago'))}前）"
                    )
                else:
                    # 进程活着但协议端没连上来：最常见的是 NapCat 未启动或未登录
                    print("  链路：协议端未连接 —— 检查 NapCat 是否运行并已登录。")
            sched = data.get("scheduler") or {}
            for name, s in sched.items():
                if s.get("waiting"):
                    print(f"  资源 {name}：排队 {s['waiting']} 个"
                          f"（持有者 {s.get('holder') or '—'}）")
        else:
            print("Stella 未在运行。")
        if data["recent_log"]:
            recent = data["recent_log"]
            print(f"最近日志 [{recent.get('level', '?')}] {recent.get('message', '')[:120]}")
        print("提示：link/scheduler 来自 Bot 进程内的状态接口，接口不可达时无法显示。")
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    return 0 if process.stop() else 1


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

    p_init = sub.add_parser("init", help="交互式生成 .env（基于 .env.example）")
    p_init.add_argument(
        "--answers", help="从 TOML 应答文件读取答案（跳过提问）"
    )
    p_init.add_argument(
        "--force", action="store_true", help="覆盖已存在的 .env（先备份为 .env.bak）"
    )
    p_init.add_argument(
        "--dry-run", action="store_true", help="只打印生成的 .env，不落盘"
    )
    p_init.set_defaults(func=_cmd_init)

    p_start = sub.add_parser("start", help="启动（先跑 doctor）")
    p_start.add_argument("--force", action="store_true", help="忽略阻塞问题继续启动")
    p_start.add_argument("--detach", action="store_true", help="后台启动并写 PID 文件")
    p_start.set_defaults(func=_cmd_start)

    p_status = sub.add_parser("status", help="查看进程状态")
    p_status.add_argument("--json", action="store_true", help="输出 JSON（供 GUI 使用）")
    p_status.set_defaults(func=_cmd_status)

    p_stop = sub.add_parser("stop", help="优雅停止（等后台任务收尾后强杀）")
    p_stop.set_defaults(func=_cmd_stop)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
