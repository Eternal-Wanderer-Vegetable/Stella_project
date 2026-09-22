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
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "deploy", "doctor", "--json",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        return {"ok": False, "error": "doctor 超时（90s）", "output": ""}
    text = out.decode("utf-8", errors="replace")
    if proc.returncode == 0 and text.lstrip().startswith(("{", "[")):
        import json

        try:
            return {"ok": True, "report": json.loads(text), "output": ""}
        except ValueError:
            pass
    return {"ok": False, "error": f"doctor 退出码 {proc.returncode}", "output": text[-4000:]}
