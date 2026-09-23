# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""系统操作：重启与 doctor（方案 §4 D7）。

重启 = 写停止哨兵（``core/stop_signal.request_stop``），Bot 的 watcher
轮询到后优雅退出；谁来重启分两种形态——桌面壳（持有 GUI_OWNS_BOT 语义，
检测到退出自动重启）与无壳形态（提示手动 `stella restart`）。桌面壳
场景的判定：注入了 STELLA_DESKTOP_SESSION_SECRET 即视为壳在管。

doctor：子进程跑 ``python -m deploy doctor --json``，与 CLI 完全同源，
避免在 webui 进程里重跑探测逻辑。超时 60s；失败返回错误文本。
"""

from __future__ import annotations

import asyncio
import sys

from webui import security


def restart() -> dict:
    from core import stop_signal

    stop_signal.request_stop(reason="webui restart")
    mode = "desktop" if security.desktop_session_secret() else "manual"
    return {"ok": True, "restart_mode": mode}


async def run_doctor() -> dict:
    """子进程跑 ``python -m deploy doctor --json``，与 CLI 完全同源。

    退出码语义：**存在未通过检查项时非零**（deploy 侧的约定）——这不等于
    「doctor 没跑成」。报告 JSON 无论退出码如何都照常打印，所以这里先解析
    stdout 再看退出码；``ok`` 取自报告自身的 summary（error=0 且不 blocking），
    而不是退出码。解析失败（真异常）才降级为错误文本。
    """
    import json

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "deploy", "doctor", "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "doctor 超时（120s）", "output": ""}
    text = out.decode("utf-8", errors="replace")
    try:
        report = json.loads(text)
    except ValueError:
        return {
            "ok": False,
            "error": f"doctor 退出码 {proc.returncode}，且输出不是 JSON",
            "output": text[-4000:],
        }
    _reframe_port_item(report)
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    ok = bool(summary) and not summary.get("blocking", False) and summary.get("error", 0) == 0
    return {"ok": ok, "report": report, "summary": summary, "exit_code": proc.returncode}


def _reframe_port_item(report: dict) -> None:
    """Bot 进程内运行时，重释「反向 WS 端口被占」检查项（用户实测误报）。

    deploy 侧该检查的语义是**启动前**验证：端口被占且无法确认占用者是自己
    → error。它的「确认自己」依赖两条证据——状态接口探活（0.8s 超时，启动
    繁忙期可能错过）与 deploy 的 PID 文件（``python bot.py`` 直启时根本不
    写）——而 WebUI 恰恰运行在 Bot 进程内：本服务能响应请求本身就证明端口
    是自己占的。因此 webui 报告里的 onebot_port error/warn 项一律改写为
    「本进程正常占用」，并重算 summary。独立模式（无宿主注入）不改写。
    """
    from webui import status_source

    link_connected = False
    try:
        payload = status_source.collect_status()
        link = payload.get("link") or {}
        link_connected = bool(payload.get("pid")) and bool(link.get("connected"))
    except Exception:
        link_connected = False

    items = report.get("items")
    if not isinstance(items, list):
        return
    for item in items:
        if item.get("id") != "onebot_port":
            continue
        if item.get("level") not in ("error", "warn"):
            continue
        if link_connected:
            item["level"] = "ok"
            item["title"] = "反向 WS 端口由当前 Bot 占用（正常）"
            item["detail"] = (
                "端口正被本进程监听且 NapCat 已连接——doctor 的端口检查面向"
                "「启动前」场景，运行中看到这条是预期状态。"
            )
            item.pop("fix_hint", None)
        else:
            item["level"] = "warn"
            item["title"] = "反向 WS 端口被占用，但 NapCat 尚未连接"
            item["detail"] = (
                "端口被占用且未确认占用者。若这是刚启动的 Bot 自身，NapCat "
                "连上后重跑自检即转为正常。"
            )
        _recount_summary(report)


def _recount_summary(report: dict) -> None:
    """按 items 重算 summary（改写单项级别后计数与 blocking 必须同步）。"""
    items = report.get("items") or []
    summary = report.get("summary") or {}
    counts = {"ok": 0, "warn": 0, "error": 0}
    for item in items:
        level = item.get("level", "ok")
        counts[level] = counts.get(level, 0) + 1
    summary["ok"] = counts["ok"]
    summary["warn"] = counts["warn"]
    summary["error"] = counts["error"]
    summary["total"] = len(items)
    summary["blocking"] = counts["error"] > 0
