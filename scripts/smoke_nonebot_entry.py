#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""受控 NoneBot 入口 smoke（计划 §8.3/§13.14 M6 硬件项）。

真 `bot.py` 直启 + 真 OneBot v11 反向 WS 通道注入合成群消息，验证
「入口 → gateway → 观测 root」全链路。隔离边界：

- ``STELLA_HOME`` 指向临时目录（数据根完全隔离，绝不触碰生产数据）；
- 临时 home 内预置 ``.env``（PORT=18101）：bot.py 的接管自查
  （``deploy.process.replace_running``）读该 .env 探活——启动早期 18101
  无监听 → 无运行实例 → no-op，**不会**触碰用户在 8080 的真实实例；
- ``PROACTIVE_ENABLED=false`` 关主动发言定时器；不配置模型后端
  （轮次走 no_backend 兜底路径——本 smoke 验证入口与观测事实，
  不验证生成质量）；
- mock NapCat：连接反向 WS（``/onebot/v11/ws``）注入 lifecycle + 群消息
  事件，并收集 Bot 下发的 action（send_group_msg 等）作为投递通道证据。

输出 ``--output`` JSON：入口存活、root 事实（message_traces/flow_events/
integrity）、WS action 回执、接管自查 no-op 证据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SMOKE_PORT = 18101
WS_URL = f"ws://127.0.0.1:{SMOKE_PORT}/onebot/v11/ws"
STATUS_URL = f"http://127.0.0.1:{SMOKE_PORT}/stella/status"


def _wait_status(timeout: float = 90.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=2.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            pass
        time.sleep(1.0)
    return None


def _trace_facts(home: Path) -> dict:
    db = home / "turn_trace.db"
    if not db.exists():
        return {"db_exists": False}
    conn = sqlite3.connect(db)
    try:
        traces = conn.execute(
            "SELECT trace_id, root_kind, status, integrity, outcome, "
            "process_instance_id FROM message_traces ORDER BY started_utc"
        ).fetchall()
        events = conn.execute(
            "SELECT trace_id, node_id, kind, status FROM flow_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return {
        "db_exists": True,
        "traces": [
            {"trace_id": t[0], "root_kind": t[1], "status": t[2],
             "integrity": t[3], "outcome": t[4]}
            for t in traces
        ],
        "event_count": len(events),
        "nodes": sorted({e[1] for e in events})[:12],
    }


async def _ws_phase(results: dict, run_seconds: float = 25.0) -> None:
    import websockets

    async with websockets.connect(
        WS_URL, max_size=2**22,
        additional_headers={"X-Self-ID": "10000"},
    ) as ws:
        results["ws_connected"] = True
        now = int(time.time())
        # NapCat 握手：lifecycle connect
        await ws.send(json.dumps({
            "time": now, "self_id": 10000, "post_type": "meta_event",
            "meta_event_type": "lifecycle", "sub_type": "connect",
        }))
        # 合成群消息（@Stella 形态走 qq_chat 主链）
        await ws.send(json.dumps({
            "time": now, "self_id": 10000, "post_type": "message",
            "message_type": "group", "sub_type": "normal",
            "message_id": 55, "user_id": 2001, "group_id": 777,
            "message": [{"type": "text", "data": {"text": "Stella 你在吗"}}],
            "raw_message": "Stella 你在吗",
            "font": 0,
            "sender": {"user_id": 2001, "nickname": "smoke", "card": "",
                       "role": "member"},
        }))
        # 收 Bot 下发的 action（send_group_msg 等）＝投递通道证据
        deadline = time.monotonic() + run_seconds
        try:
            while time.monotonic() < deadline:
                frame = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(frame)
                if data.get("post_type") == "meta_event":
                    continue
                results.setdefault("actions", []).append({
                    "action": data.get("action"),
                    "echo": data.get("echo"),
                    "params_preview": str(data.get("params", {}))[:160],
                })
        except (asyncio.TimeoutError, TimeoutError):
            pass
        # 心跳保持到窗口结束，让 gateway 的后台链路走完
        remaining = deadline - time.monotonic()
        if remaining > 0:
            await asyncio.sleep(remaining)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--keep-home", action="store_true")
    args = parser.parse_args()

    home = Path(tempfile.mkdtemp(prefix="stella-smoke-"))
    (home / ".env").write_text(
        f"HOST=127.0.0.1\nPORT={SMOKE_PORT}\n", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "STELLA_HOME": str(home),
        "HOST": "127.0.0.1",
        "PORT": str(SMOKE_PORT),
        "PROACTIVE_ENABLED": "false",
        "PYTHONUNBUFFERED": "1",
    })
    log_path = home / "bot_stdout.log"
    results: dict = {"home": str(home), "ws_url": WS_URL}

    with open(log_path, "w", encoding="utf-8", newline="") as log:
        proc = subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "bot.py")],
            cwd=str(PROJECT_ROOT), env=env, stdout=log, stderr=log,
        )
        try:
            status = _wait_status()
            if status is None:
                results["verdict"] = "FAIL"
                results["error"] = "status API 未在 90s 内就绪（启动失败或过慢）"
            else:
                results["status_api"] = {
                    "alive": True,
                    "pid_matches": status.get("pid") == proc.pid,
                }
                try:
                    asyncio.run(_ws_phase(results))
                except Exception as exc:
                    results["ws_error"] = f"{type(exc).__name__}: {exc}"

            # 给 writer/后台链路落库的时间，再读观测事实
            time.sleep(6.0)
            results["trace_facts"] = _trace_facts(home)

            takeover_lines = 0
            if log_path.exists():
                takeover_lines = sum(
                    1 for line in log_path.read_text(encoding="utf-8",
                                                     errors="replace").splitlines()
                    if "发现运行中的 Stella 实例" in line)
            results["takeover_touched_user_instance"] = takeover_lines > 0
            ok = (
                results.get("ws_connected")
                and results.get("trace_facts", {}).get("db_exists")
                and any(t.get("root_kind") in ("qq_passive", "qq_chat")
                        for t in results.get("trace_facts", {}).get("traces", []))
                and not results.get("takeover_touched_user_instance")
            )
            results["verdict"] = "PASS" if ok else "FAIL"
        finally:
            # 只杀本 smoke 自己的子进程（进程树），绝不碰其它进程
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True)
            else:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            results["child_returncode"] = proc.returncode
        if args.keep_home:
            print(f"home kept: {home}")
        else:
            log_tail = ""
            if log_path.exists():
                log_tail = log_path.read_text(encoding="utf-8",
                                              errors="replace")[-2000:]
            results["log_tail"] = log_tail
            shutil.rmtree(home, ignore_errors=True)

    payload = json.dumps(results, ensure_ascii=False, indent=1, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        print(f"report written: {args.output}")
    print(payload)
    return 0 if results["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
