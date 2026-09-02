# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor / init / start / status / stop / migrate 等子命令的入口。

用法：python -m deploy doctor [--json]
      python -m deploy init [--answers PATH] [--force] [--dry-run]
      python -m deploy start [--force] [--detach]
      python -m deploy status [--json]
      python -m deploy stop
      python -m deploy migrate [--from 旧目录] [--dry-run] [--fresh-runtime]
      python -m deploy space-merge --from space_1,space_2 --to casual [--dry-run]
      python -m deploy plugin-check <插件目录> [--json]
      python -m deploy plugin-scaffold <插件目录> [--endpoint 槽] [--force] [--dry-run] [--measure]
      python -m deploy capabilities [--json]
      python -m deploy manifest [--write]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from config import PROJECT_ROOT, STELLA_HOME, STELLA_HOME_SOURCE, home

from . import checks, env_merge, env_schema, migrate, probe, process, report
from .init_wizard import (
    load_answers,
    managed_keys,
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
        print(report.to_json(results, snapshot))
    else:
        print(report.to_terminal(results, snapshot))
    return 1 if report.has_blocking(results) else 0


def _cmd_init(args: argparse.Namespace) -> int:
    # 用户数据目录此刻才真正需要存在（import config 时刻意不创建，避免副作用）
    resolved = home.resolve(PROJECT_ROOT, create=True)
    env_path = resolved.path / ".env"
    template_path = PROJECT_ROOT / ".env.example"
    if resolved.path != PROJECT_ROOT:
        print(f"用户数据目录：{resolved.path}（{resolved.source}）")

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

    # 覆盖已有配置时，把旧文件里的其它键合并回来。2026-08-27 之前这里只写向导管理的
    # 5 个键，然后提示「请从 .env.bak 里对照恢复」——那等于让用户人工比对两个 27KB
    # 的文件。向导答案优先（用户刚答过），其余键沿用旧值，废弃键顺手清掉。
    merge_report = None
    if env_path.exists():
        rendered, merge_report = env_merge.merge_env(
            env_path.read_text(encoding="utf-8"),
            rendered,
            schema_keys=env_merge.settings_keys(PROJECT_ROOT / "config" / "settings.py"),
            prefer_template=managed_keys(answers),
        )

    if args.dry_run:
        print(rendered)
        if merge_report:
            print()
            print(merge_report.to_markdown())
        return 0

    if env_path.exists():
        backup = env_path.parent / ".env.bak"
        shutil.copy2(env_path, backup)
        print(f"已备份原配置到 {backup}")
    env_path.write_text(rendered, encoding="utf-8")
    print(f"已写入 {env_path}")
    if merge_report:
        print()
        print(merge_report.to_markdown())

    if not args.answers:
        answers_path = env_path.parent / "deploy.answers.toml"
        save_answers(answers, answers_path)
        print(f"应答已保存到 {answers_path}（下次可用 --answers 跳过提问）")

    # 必须用子进程跑 doctor，不能在本进程内调 probe.collect()：
    # config/settings.py 在 import 时执行 load_dotenv()，而本模块顶部就
    # from config import PROJECT_ROOT, STELLA_HOME, STELLA_HOME_SOURCE, home——.env 尚不存在时 config 已被导入，
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


def _print_usage(usage: dict | None) -> None:
    """把今日用量摘成三行以内。

    只打计数与比率——这份数据来自 ``usage_snapshot()``，本来就不含 prompt 与凭据。
    缓存命中率单独占一行：它是验证前缀缓存到底有没有生效的唯一手段，
    数字一直是 0 就说明 prompt 前缀被什么东西破坏了。
    """
    if not usage:
        return
    if usage.get("accounting") is False:
        print("  用量记账：已关闭（LLM_USAGE_ACCOUNTING=false）。")
        return
    totals = usage.get("totals") or {}
    used = usage.get("used_tokens") or 0
    budget = usage.get("budget") or 0
    quota = f"{used}/{budget} token" if budget > 0 else f"{used} token（预算不限）"
    print(
        f"  今日用量：{quota}，调用 {totals.get('calls', 0)} 次"
        f"（失败 {totals.get('failures', 0)}，截断 {totals.get('truncated', 0)}）"
    )
    print(f"  缓存命中率：{(totals.get('cache_hit_rate') or 0.0) * 100:.1f}%")
    paused = usage.get("paused_roles") or []
    if paused:
        print(f"  已因预算暂停的角色：{'、'.join(paused)}（动作={usage.get('action')}）")
    degraded = [
        role
        for role, st in (usage.get("fallback_states") or {}).items()
        if st.get("degraded")
    ]
    if degraded:
        print(f"  正在降级中的角色：{'、'.join(degraded)} —— 主端点故障，走的是降级端点。")


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
            _print_usage(data.get("usage"))
        else:
            print("Stella 未在运行。")
        if data["recent_log"]:
            recent = data["recent_log"]
            print(f"最近日志 [{recent.get('level', '?')}] {recent.get('message', '')[:120]}")
        print(
            "提示：link/scheduler/usage 来自 Bot 进程内的状态接口，接口不可达时无法显示；"
            "能力清单见 python -m deploy capabilities。"
        )
    return 0


def _cmd_stop(args: argparse.Namespace) -> int:
    return 0 if process.stop() else 1


def _cmd_config_schema(args: argparse.Namespace) -> int:
    data = env_schema.build_schema(PROJECT_ROOT / "config" / "settings.py")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """从旧版本安装目录导入用户数据并升级数据库。"""
    source = Path(args.source).expanduser() if args.source else None
    # 预演不该创建任何东西；真正导入时才把用户数据目录建出来
    resolved = home.resolve(PROJECT_ROOT, create=not args.dry_run)
    result = migrate.run(
        PROJECT_ROOT,
        source,
        data_root=resolved.path,
        dry_run=args.dry_run,
        reuse_runtime=not args.fresh_runtime,
    )
    print(result.to_markdown())
    if not args.dry_run and not result.error:
        path = migrate.write_report(resolved.path, result)
        print()
        print(f"报告已写入 {path}")
    return 0 if result.ok else 1


def _cmd_paths(args: argparse.Namespace) -> int:
    """输出解析后的关键路径（供 GUI 与排查使用）。

    GUI 不自己判断用户数据目录在哪：判据只有 ``config/home.py`` 一份，两处各写一遍
    必然漂移（一边读旧目录、一边写新目录，用户会看到「保存了但没生效」）。
    """
    from config import DB_PATH, LOG_DIR, STELLA_JSON_LOG_PATH

    if args.env_file:
        # start.bat 用它判断「配置过了没有」——路径判据同样只能有一份
        print(STELLA_HOME / ".env")
        return 0
    data = {
        "version": 1,
        "project_root": str(PROJECT_ROOT),
        "stella_home": str(STELLA_HOME),
        "stella_home_source": STELLA_HOME_SOURCE,
        "env_file": str(STELLA_HOME / ".env"),
        "env_template": str(PROJECT_ROOT / ".env.example"),
        "answers_file": str(STELLA_HOME / "deploy.answers.toml"),
        "spaces_dir": str(STELLA_HOME / "config" / "spaces"),
        "prompts_dir": str(STELLA_HOME / "system_prompts"),
        "shipped_prompts_dir": str(PROJECT_ROOT / "system_prompts"),
        "db_path": str(DB_PATH),
        "log_dir": str(LOG_DIR),
        "json_log_path": str(STELLA_JSON_LOG_PATH),
        "pointer_file": str(home.pointer_path()),
    }
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _cmd_space_merge(args: argparse.Namespace) -> int:
    """把若干空间合并成一个（替代过去要用户手搓的那串 UPDATE）。"""
    from memory import space_merge

    sources = [s.strip() for s in args.source.replace("，", ",").split(",") if s.strip()]
    if not sources:
        print("--from 至少要给一个空间名。")
        return 1
    result = space_merge.merge_spaces(sources, args.to, dry_run=args.dry_run)
    print(result.to_markdown())
    return 0 if not result.error else 1


def _cmd_plugin_check(args: argparse.Namespace) -> int:
    """按插件接入规范校验一个插件目录。

    延迟 import：本命令要拉起 ``capability`` 与 ``astrbot_compat``（后者会装 shim），
    而 ``doctor`` / ``status`` 这些常用命令没有理由为它付这份 import 成本。
    """
    from . import plugin_check

    plugin_dir = Path(args.plugin_dir).expanduser()
    if not plugin_dir.is_dir():
        print(f"{plugin_dir} 不是一个目录。")
        return 1
    facts = plugin_check.collect(plugin_dir)
    results = plugin_check.run_all(facts)
    if args.json:
        print(plugin_check.to_json(facts, results))
    else:
        print(plugin_check.to_terminal(facts, results))
    return 1 if report.has_blocking(results) else 0


def _cmd_plugin_scaffold(args: argparse.Namespace) -> int:
    """给一个插件生成 ``capability.toml.draft``，并用真实 embedding 打一份量化报告。

    延迟 import 的理由同 ``_cmd_plugin_check``，只是更重一层：这条命令还要拉起
    ``core.llm`` 与 ``memory.embeddings``。
    """
    from . import plugin_scaffold

    return plugin_scaffold.run(
        args.plugin_dir,
        endpoint=args.endpoint,
        force=args.force,
        dry_run=args.dry_run,
        measure_only=args.measure,
    )


def _cmd_capabilities(args: argparse.Namespace) -> int:
    """列出 Stella 当前具备哪些能力、哪些装了却不生效。

    退出码恒为 0：这是一条查询命令，「没有可路由的能力」是一种合法状态（新装的
    实例就是这样），拿它当失败会让 CI 与 GUI 把正常情况当故障。
    """
    from . import capability_view

    view = capability_view.collect()
    print(capability_view.to_json(view) if args.json else capability_view.to_terminal(view))
    return 0


def _cmd_manifest(args: argparse.Namespace) -> int:
    """生成发布包清单（release CI 用；升级时据此判断用户是否改过自带文件）。"""
    from . import manifest

    if args.write:
        path = manifest.write_manifest(PROJECT_ROOT)
        print(f"已写入 {path}")
        return 0
    print(json.dumps(manifest.build_manifest(PROJECT_ROOT), ensure_ascii=False, indent=2))
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

    p_schema = sub.add_parser("config-schema", help="输出 settings.py 的配置 schema（供 GUI 使用）")
    p_schema.add_argument("--json", action="store_true", help="兼容 GUI 调用")
    p_schema.set_defaults(func=_cmd_config_schema)

    p_migrate = sub.add_parser("migrate", help="从旧版本目录导入用户数据并升级数据库")
    p_migrate.add_argument(
        "--from", dest="source", help="旧版本安装目录（省略则自动探测）"
    )
    p_migrate.add_argument(
        "--dry-run", action="store_true", help="只预演并出报告，不写入任何文件"
    )
    p_migrate.add_argument(
        "--fresh-runtime",
        action="store_true",
        help="不复用旧目录的 runtime（默认复用，省一次约 100MB 的下载）",
    )
    p_migrate.add_argument(
        "--keep-runtime",
        action="store_true",
        help="显式要求复用旧 runtime（默认行为，保留此开关便于脚本自文档）",
    )
    p_migrate.set_defaults(func=_cmd_migrate)

    p_merge = sub.add_parser("space-merge", help="把若干共享空间合并为一个（含记忆与画像）")
    p_merge.add_argument("--from", dest="source", required=True, help="源空间名，逗号分隔")
    p_merge.add_argument("--to", required=True, help="目标空间名")
    p_merge.add_argument("--dry-run", action="store_true", help="只预演，不写入")
    p_merge.set_defaults(func=_cmd_space_merge)

    p_plugin_check = sub.add_parser(
        "plugin-check", help="按插件接入规范校验一个插件目录（会执行该插件代码）"
    )
    p_plugin_check.add_argument("plugin_dir", help="插件目录（含 main.py 的那一层）")
    p_plugin_check.add_argument("--json", action="store_true", help="输出 JSON（供 GUI 使用）")
    p_plugin_check.set_defaults(func=_cmd_plugin_check)

    p_scaffold = sub.add_parser(
        "plugin-scaffold",
        help="给插件生成 capability.toml.draft 并量化（会执行该插件代码）",
    )
    p_scaffold.add_argument("plugin_dir", help="插件目录（含 main.py 的那一层）")
    p_scaffold.add_argument(
        "--endpoint",
        default="",
        help="指定生成用的端点槽（LOCAL / ONLINE_CHAT / ONLINE_MEMORY / EXTRA），"
        "默认走 EXTRACT 角色绑定的那个",
    )
    p_scaffold.add_argument("--force", action="store_true", help="覆盖已存在的草稿")
    p_scaffold.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    p_scaffold.add_argument(
        "--measure",
        action="store_true",
        help="只量化已有声明（不调模型、不写文件）",
    )
    p_scaffold.set_defaults(func=_cmd_plugin_scaffold)

    p_caps = sub.add_parser(
        "capabilities", help="列出当前能力清单（哪些能被聊天触发、哪些不能及原因）"
    )
    p_caps.add_argument("--json", action="store_true", help="输出 JSON（供 GUI 使用）")
    p_caps.set_defaults(func=_cmd_capabilities)

    p_manifest = sub.add_parser("manifest", help="生成发布包清单（.stella-manifest.json）")
    p_manifest.add_argument("--write", action="store_true", help="写入文件而非打印")
    p_manifest.set_defaults(func=_cmd_manifest)

    p_paths = sub.add_parser("paths", help="输出解析后的路径（程序目录 / 用户数据目录等）")
    p_paths.add_argument("--json", action="store_true", help="兼容 GUI 调用（默认就是 JSON）")
    p_paths.add_argument(
        "--env-file", action="store_true", help="只打印 .env 的完整路径（供 start.bat 判断）"
    )
    p_paths.set_defaults(func=_cmd_paths)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
