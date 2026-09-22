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
    summary = report.get("summary", {}) if isinstance(report, dict) else {}
    ok = bool(summary) and not summary.get("blocking", False) and summary.get("error", 0) == 0
    return {"ok": ok, "report": report, "summary": summary, "exit_code": proc.returncode}
