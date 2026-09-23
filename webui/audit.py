# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""WebUI 写操作审计（方案 §9.5）。

所有非幂等写操作（配置、插件、MCP、知识库、定时任务、系统操作）落
``LOG_DIR/webui_audit.jsonl``：谁、从哪来（jwt/desktop）、动了什么、结果。
与调度子系统自身的 audit_log() 是**双层审计**：本层回答「谁在面板上动了
什么」，那层回答「这次受控变更的业务语义」。

失败静默（``_append`` 全程吞异常）：审计是记账，不能反过来让业务操作
失败——与 usage_sink 同一取向。detail 只允许调用方给**脱敏后的**摘要，
本模块不做请求体快照（避免密码/密钥经此处落盘）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import config.settings as settings


def record(
    *,
    request,  # starlette Request，为避免测试期构造负担只按鸭子类型取值
    username: str,
    via: str,
    action: str,
    result: str = "ok",
    detail: dict | None = None,
) -> None:
    """追加一条审计。action 建议形如 ``auth.setup`` / ``config.update``。"""
    entry = {
        "ts": time.time(),
        "username": username,
        "via": via,
        "action": action,
        "result": result,
        "method": request.method,
        "path": request.url.path,
        "client": request.client.host if request.client else None,
    }
    if detail:
        entry["detail"] = detail
    _append(entry)


def _append(entry: dict) -> None:
    try:
        log_dir = Path(settings.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "webui_audit.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return
