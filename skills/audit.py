# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skills/Sandbox 审计：结构化事件流，敏感值一律脱敏。

plan §6.5：为发现、选择、加载、策略拒绝、沙盒启动、超时、输出截断和
产物清理记录结构化 audit event；**敏感参数、环境变量值、Skill 正文和
API key 必须脱敏**。plan §6.3：原始 stdout/stderr 留在沙盒审计存储——
所以审计 JSONL 是唯一允许携带（截断后的）原始输出的地方，主链路永远
只拿有界摘要。

写失败（磁盘满/目录不可写）不抛异常：审计是旁路，它挂了不能拖垮聊天；
丢事件计数进 ``AuditLog.dropped``，供状态 API 暴露「审计不完整」这一事实。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

# 键名命中即脱敏（不区分大小写）。宁可多杀不可漏放：审计里永远不需要
# 明文的密钥/环境/正文。
_REDACT_KEYS = frozenset(
    {
        "env",
        "environ",
        "environment",
        "api_key",
        "apikey",
        "token",
        "secret",
        "password",
        "authorization",
        "cookie",
        "skill_body",
        "body",
        "code",
        "command",  # 动作参数逐字进审计有注入回放风险，只记长度与哈希
    }
)
# 单个字段值的上限：审计是排查用的，不是数据备份。
_MAX_FIELD_CHARS = 2000
_MAX_LINE_BYTES = 64 * 1024


def redact(fields: dict[str, Any]) -> dict[str, Any]:
    """按键名脱敏并截断；返回新的 dict，不改调用方数据。"""
    safe: dict[str, Any] = {}
    for key, value in fields.items():
        if str(key).lower() in _REDACT_KEYS:
            safe[str(key)] = f"<redacted len={len(str(value))}>"
            continue
        text = value if isinstance(value, (int, float, bool)) else str(value)
        if isinstance(text, str) and len(text) > _MAX_FIELD_CHARS:
            text = text[:_MAX_FIELD_CHARS] + "…<truncated>"
        safe[str(key)] = text
    return safe


class AuditLog:
    """追加式 JSONL 审计日志。``emit`` 永不抛异常、永不阻塞主链路。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self.emitted = 0
        self.dropped = 0

    @property
    def path(self) -> Path:
        return self._path

    def emit(
        self, event: str, *, invocation_id: str = "", skill: str = "", **fields: Any
    ) -> None:
        """写一条事件。任何失败都只增加 ``dropped`` 计数。"""
        record = {
            "ts": round(time.time(), 3),
            "event": str(event)[:64],
            "invocation_id": str(invocation_id)[:64],
            "skill": str(skill)[:64],
            **redact(fields),
        }
        try:
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            if len(line.encode("utf-8")) > _MAX_LINE_BYTES:
                record["fields"] = "<oversized>"
                line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self.emitted += 1
        except Exception:
            with self._lock:
                self.dropped += 1

    def read_recent(self, limit: int = 50) -> list[dict]:
        """读最近 N 条（状态/诊断用）；文件不存在或损坏行被跳过。"""
        if not self._path.is_file():
            return []
        lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        out: list[dict] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


_default: AuditLog | None = None


def audit() -> AuditLog:
    """进程级审计单例（LOG_DIR/skills_audit.jsonl）。惰性创建，永不失败。"""
    global _default
    if _default is None:
        try:
            from config import LOG_DIR

            path = Path(LOG_DIR) / "skills_audit.jsonl"
        except Exception:
            path = Path("skills_audit.jsonl")
        _default = AuditLog(path)
    return _default


def reset_audit() -> None:
    """测试用：清掉单例，让下一个用例重新按当前配置创建。"""
    global _default
    _default = None
