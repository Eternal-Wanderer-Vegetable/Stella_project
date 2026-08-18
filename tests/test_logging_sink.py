# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""结构化 JSON 日志 sink 的单元测试。

只测格式函数与 sink 注册（同步 enqueue=False，避免后台线程写文件造成时序抖动）：
每行必须是合法 JSON、字段完整、超长消息被截断且带 ``truncated`` 标记。
"""

from __future__ import annotations

import json

from core.logging_sink import make_json_formatter, setup_json_sink

try:
    from nonebot import logger
except Exception:  # pragma: no cover
    from loguru import logger  # type: ignore[no-redef]


def test_json_lines_parse_and_fields_complete(tmp_path):
    path = tmp_path / "stella.jsonl"
    logger.add(str(path), format=make_json_formatter(max_message=500), encoding="utf-8")
    try:
        logger.info("hello 世界")
        logger.error("something failed")
        logger.warning("middle")
    finally:
        logger.remove()

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 3
    for ln in lines:
        obj = json.loads(ln)
        assert {"ts", "level", "module", "message"} <= set(obj.keys())
        assert "truncated" not in obj
    levels = {json.loads(ln)["level"] for ln in lines}
    assert levels == {"INFO", "ERROR", "WARNING"}
    assert any(json.loads(ln)["message"] == "hello 世界" for ln in lines)


def test_long_message_truncated_with_marker(tmp_path):
    path = tmp_path / "stella.jsonl"
    logger.add(str(path), format=make_json_formatter(max_message=20), encoding="utf-8")
    try:
        logger.warning("x" * 80)
    finally:
        logger.remove()

    obj = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[0])
    assert obj["truncated"] is True
    assert len(obj["message"]) == 20
    assert obj["message"] == "x" * 20


def test_short_message_not_truncated(tmp_path):
    path = tmp_path / "stella.jsonl"
    logger.add(str(path), format=make_json_formatter(max_message=20), encoding="utf-8")
    try:
        logger.warning("short")
    finally:
        logger.remove()

    obj = json.loads(path.read_text(encoding="utf-8").strip())
    assert "truncated" not in obj
    assert obj["message"] == "short"


def test_setup_json_sink_writes_file(monkeypatch, tmp_path):
    from core import logging_sink

    monkeypatch.setattr(logging_sink, "STELLA_JSON_LOG_ENABLED", True)
    monkeypatch.setattr(logging_sink, "STELLA_JSON_LOG_PATH", tmp_path / "stella.jsonl")
    monkeypatch.setattr(logging_sink, "STELLA_JSON_LOG_MAX_MESSAGE", 500)
    setup_json_sink(enqueue=False)
    try:
        logger.warning("via setup")
    finally:
        logger.remove()

    obj = json.loads(
        (tmp_path / "stella.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert obj["message"] == "via setup"


def test_setup_json_sink_disabled_does_nothing(monkeypatch, tmp_path, capsys):
    from core import logging_sink

    monkeypatch.setattr(logging_sink, "STELLA_JSON_LOG_ENABLED", False)
    setup_json_sink(enqueue=False)
    assert not list(tmp_path.iterdir())


def test_make_json_formatter_requires_callable():
    fmt = make_json_formatter(max_message=10)
    assert callable(fmt)
