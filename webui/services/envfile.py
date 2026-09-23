# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
""".env 增量读写（方案 §4 D6：配置仍以 .env 为唯一存储）。

写语义沿用 deploy/init_wizard.render_env 的既有契约：逐行扫描，匹配
``^\\s*#?\\s*KEY\\s*=`` 的行整行替换（顺带取消注释），只替换第一处；
模板里没有的键追加到文件末尾。写盘学 core/stop_signal：tmp + replace
原子落盘。

键卫生：DEPRECATED/RENAMED 键拒绝写入（deploy/env_keys 登记表是唯一
事实源），避免复活旧键造成「改了没反应」。

读语义：直接复用 deploy/env_merge.parse_env（键 → 右侧原文）。
"""

from __future__ import annotations

import re
from pathlib import Path

import config.settings as settings
from webui.responses import ApiError


def env_file() -> Path:
    return Path(settings.STELLA_HOME) / ".env"


def read_values() -> dict[str, str]:
    """当前 .env 的键 → 右侧原文（沿用 env_merge.parse_env 语义）。"""
    from deploy.env_merge import parse_env

    path = env_file()
    if not path.exists():
        return {}
    try:
        return parse_env(path.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _reject_stale_keys(keys: list[str]) -> None:
    """拒绝废弃/被取代键（读 env_keys 登记表；无该模块时跳过防护）。"""
    try:
        from deploy import env_keys
    except Exception:
        return
    for key in keys:
        reason = env_keys.deprecation_reason(key) or env_keys.superseded_by(key)
        if reason:
            raise ApiError(f"配置键 {key} 已废弃：{reason}")


def write_values(
    updates: dict[str, str], *, remove: set[str] | None = None
) -> dict:
    """增量写回 .env（原子）。返回 {written, removed}。

    - 值一律 ``KEY=value`` 无引号（与 parse_env 读取契约一致；数组用 JSON
      字面量，如 ONEBOT_WS_URLS）。
    - ``remove`` 中的键整行删除——继承键「留空即继承」靠删除而不是写空串。
    """
    _reject_stale_keys([*updates.keys(), *(remove or set())])
    path = env_file()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    written: list[str] = []
    for key, value in updates.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ApiError(f"非法配置键名: {key}")
        pattern = re.compile(rf"(?m)^\s*#?\s*{re.escape(key)}\s*=.*$")
        replacement = f"{key}={value}"
        if pattern.search(text):
            text = pattern.sub(replacement.replace("\\", "\\\\"), text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += replacement + "\n"
        written.append(key)
    removed: list[str] = []
    for key in remove or ():
        pattern = re.compile(rf"(?m)^\s*#?\s*{re.escape(key)}\s*=.*$\n?", re.MULTILINE)
        if pattern.search(text):
            text = pattern.sub("", text, count=1)
            removed.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return {"written": written, "removed": removed}
