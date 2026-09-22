# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""日志 history + SSE live 测试。

SSE 生成器用 asyncio 直接驱动（pytest-asyncio auto 模式）：写文件 → 取帧
→ 断言帧 id（字节偏移）与 JSON 载荷 → 断点续传（从中间偏移重启）→ 心跳。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import config.settings as settings
from webui.services import logs as logs_service

USER = {"username": "admin", "password": "correct horse battery"}


@pytest.fixture
def log_file(isolated_home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = isolated_home / "logs" / "stella.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "STELLA_JSON_LOG_PATH", path)
    return path


def _auth_header(client: TestClient) -> dict:
    resp = client.post("/api/v1/auth/setup", json=USER)
    return {"Authorization": f"Bearer {resp.json()['data']['token']}"}


def test_history_tail_and_level(client: TestClient, log_file: Path):
    lines = [
        {"ts": "t1", "level": "INFO", "module": "a", "message": "one"},
        {"ts": "t2", "level": "ERROR", "module": "b", "message": "two"},
        {"ts": "t3", "level": "INFO", "module": "a", "message": "three"},
    ]
    log_file.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n",
        encoding="utf-8",
    )
    headers = _auth_header(client)
    resp = client.get("/api/v1/logs/history", params={"tail": 2}, headers=headers)
    data = resp.json()["data"]
    assert [i["message"] for i in data["items"]] == ["two", "three"]  # 旧→新
    resp = client.get(
        "/api/v1/logs/history", params={"tail": 10, "level": "error"}, headers=headers
    )
    data = resp.json()["data"]
    assert [i["message"] for i in data["items"]] == ["two"]


def test_history_missing_file_degrades(client: TestClient, log_file: Path):
    headers = _auth_header(client)
    resp = client.get("/api/v1/logs/history", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["data"]["items"] == []


async def test_live_stream_frames_and_resume(log_file: Path):
    log_file.write_text(
        json.dumps({"ts": "t1", "level": "INFO", "message": "one"}) + "\n",
        encoding="utf-8",
    )
    gen = logs_service.live(0)
    # 不发帧时只出心跳：先消费一帧前先追加一行，保证第一帧是数据
    task = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.6)  # 让 poller 先看到文件
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "t2", "level": "ERROR", "message": "boom"}) + "\n")
    frame = await asyncio.wait_for(task, timeout=5)
    assert frame.startswith("id: ")
    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert payload["message"] == "one"

    # 断点续传：从第一帧的偏移重启，boom（先追加）与 again 依次补发，不丢不重
    offset = int(frame.split("\n", 1)[0].removeprefix("id: "))
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "t3", "level": "INFO", "message": "again"}) + "\n")
    gen2 = logs_service.live(offset)
    frame2 = await asyncio.wait_for(gen2.__anext__(), timeout=5)
    payload2 = json.loads(frame2.split("data: ", 1)[1].strip())
    assert payload2["message"] == "boom"
    frame3 = await asyncio.wait_for(gen2.__anext__(), timeout=5)
    payload3 = json.loads(frame3.split("data: ", 1)[1].strip())
    assert payload3["message"] == "again"

    gen.aclose()
    await gen2.aclose()


async def test_live_level_filter(log_file: Path):
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps({"ts": "t1", "level": "INFO", "message": "noise"}) + "\n"
            + json.dumps({"ts": "t2", "level": "ERROR", "message": "wanted"}) + "\n"
        )
    gen = logs_service.live(0, level="error")
    frame = await asyncio.wait_for(gen.__anext__(), timeout=5)
    assert "wanted" in frame
    assert "noise" not in frame
    await gen.aclose()
