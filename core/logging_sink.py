# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""结构化 JSON 日志（供 GUI / Web 前端消费）。

这份 JSON 日志是**给程序读的**（GUI / 将来的 Web 前端），不是给人读的。
人看 ``logs/stella_thought_logs.md`` 与终端输出。

为什么不让 GUI 直接捕获 stdout：loguru 的彩色转义码需要剥离，多行异常栈
需要重组，按级别过滤需要解析文本格式——这些在 GUI 侧做既脆弱又要跨语言
重复实现。写一份结构化的反而更省：GUI tail 文件、按行解析 JSON 即可。

为什么不用 ``serialize=True``：loguru 的原生序列化字段太多（含 ``elapsed``
/ ``exception`` / ``extra`` 等嵌套结构），GUI 解析成本高。这里用手工挑选
字段的 ``format`` 函数，只输出 GUI 需要的四个字段，并截断超长消息。

实现细节：sink 必须用**文件路径**而非 callable——loguru 的 ``rotation`` /
``retention`` 只对文件 sink 生效（callable sink 上会被忽略并告警）。用文件
路径 + 自定义 ``format`` 函数，既拿到原生轮转，又拿到手工字段。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from config import (
    STELLA_JSON_LOG_ENABLED,
    STELLA_JSON_LOG_MAX_MESSAGE,
    STELLA_JSON_LOG_PATH,
)

try:
    from nonebot import logger
except Exception:  # pragma: no cover - 纯逻辑测试环境也允许 import 本模块
    from loguru import logger  # type: ignore[no-redef]


def make_json_formatter(max_message: int = STELLA_JSON_LOG_MAX_MESSAGE) -> Callable[[Any], str]:
    """构造 JSON 行格式化器，供 ``logger.add(format=...)`` 使用。

    每个 loguru record 输出一行 JSON：``ts``（ISO8601）/ ``level`` / ``module`` /
    ``message``。消息超过 ``max_message`` 字符时截断并加 ``truncated: true`` 标记
    （prompt 全文动辄数千字符，进结构化日志只会让文件暴涨且对 GUI 无用）。
    """
    def _fmt(record: Any) -> str:
        text = record["message"]
        truncated = False
        if len(text) > max_message:
            text = text[:max_message]
            truncated = True
        payload: dict[str, Any] = {
            "ts": record["time"].isoformat(),
            "level": record["level"].name,
            "module": record["name"],
            "message": text,
        }
        if truncated:
            payload["truncated"] = True
        line = json.dumps(payload, ensure_ascii=False)
        # loguru 会对动态 format 的返回值再跑一次 str.format_map（_handler.py:161），
        # 因此把 JSON 的花括号全部转义成 {{ }}，让 format_map 还原成单个花括号，
        # 最终写盘仍是合法 JSON。不转义会触发 KeyError '"ts"' 之类。
        return line.replace("{", "{{").replace("}", "}}") + "\n"

    return _fmt


def setup_json_sink(enqueue: bool = True) -> None:
    """注册 JSON Lines 日志 sink（Bot 入口调用一次）。

    路径 / 开关 / 截断长度均来自配置（``STELLA_JSON_LOG_*``）。开关关闭时
    静默跳过；目录创建失败只告警不中断启动——结构化日志是加分项，不是必需品。
    """
    if not STELLA_JSON_LOG_ENABLED:
        return
    try:
        path = STELLA_JSON_LOG_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"[JSON 日志] 创建目录失败，跳过结构化日志: {e}")
        return
    logger.add(
        str(path),
        format=make_json_formatter(),
        rotation="10 MB",
        retention=5,
        encoding="utf-8",
        enqueue=enqueue,
    )
    logger.debug(f"[JSON 日志] 已启用: {path}")
