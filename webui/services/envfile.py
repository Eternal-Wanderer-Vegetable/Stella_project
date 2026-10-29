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

import hashlib
import re
import threading
from pathlib import Path

from webui.responses import ApiError

_WRITE_LOCK = threading.RLock()


def env_file() -> Path:
    # Keep legacy settings lazy: importing this leaf service must not initialize
    # config.settings before a management process has selected its revision.
    from config.settings import STELLA_HOME

    return Path(STELLA_HOME) / ".env"


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


def read_snapshot() -> tuple[bytes, str]:
    """Read the current dotenv bytes and their compare token under the write lock."""
    path = env_file()
    with _WRITE_LOCK:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = b""
        except OSError as exc:
            raise ApiError("无法读取配置文件", status_code=409,
                           data={"code": "config_source_unavailable"}) from exc
    return raw, _digest(raw)


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
    updates: dict[str, str],
    *,
    remove: set[str] | None = None,
    expected_digest: str | None = None,
    dedupe_keys: set[str] | None = None,
) -> dict:
    """增量写回 .env（原子）。返回 {written, removed}。

    - 普通值按 ``KEY=value`` 原样写入（数组用 JSON 字面量，如 ONEBOT_WS_URLS）；
      需要 dotenv 转义的调用方可传入已编码的单行值。
    - ``remove`` 中的键整行删除——继承键「留空即继承」靠删除而不是写空串。
    - ``expected_digest`` 为可选的文件级 CAS；同进程的所有 envfile 写入共享锁。
    - ``dedupe_keys`` 仅对指定更新键移除重复的生效赋值行。
    """
    all_keys = [*updates.keys(), *(remove or set()), *(dedupe_keys or set())]
    _reject_stale_keys(all_keys)
    for key in all_keys:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ApiError(f"非法配置键名: {key}")

    path = env_file()
    with _WRITE_LOCK:
        try:
            before = path.read_bytes() if path.exists() else b""
            text = before.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise ApiError("配置文件无法读取或不是 UTF-8", status_code=409,
                           data={"code": "config_source_invalid"}) from exc
        before_digest = _digest(before)
        if expected_digest is not None and expected_digest != before_digest:
            raise _revision_conflict(before_digest)

        written: list[str] = []
        for key, value in updates.items():
            pattern = re.compile(rf"(?m)^\s*#?\s*{re.escape(key)}\s*=.*$")
            replacement = f"{key}={value}"
            if pattern.search(text):
                text = pattern.sub(replacement.replace("\\", "\\\\"), text, count=1)
            else:
                if text and not text.endswith("\n"):
                    text += "\n"
                text += replacement + "\n"
            written.append(key)

        for key in dedupe_keys or ():
            if key not in updates:
                continue
            active = re.compile(rf"^\s*{re.escape(key)}\s*=")
            seen = False
            kept: list[str] = []
            for line in text.splitlines(keepends=True):
                if active.match(line):
                    if seen:
                        continue
                    seen = True
                kept.append(line)
            text = "".join(kept)

        removed: list[str] = []
        for key in remove or ():
            pattern = re.compile(rf"(?m)^\s*#?\s*{re.escape(key)}\s*=.*$\n?", re.MULTILINE)
            if pattern.search(text):
                text = pattern.sub("", text, count=1)
                removed.append(key)

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        if expected_digest is not None:
            try:
                current = path.read_bytes() if path.exists() else b""
            except OSError as exc:
                tmp.unlink(missing_ok=True)
                raise _revision_conflict(None) from exc
            if _digest(current) != before_digest:
                tmp.unlink(missing_ok=True)
                raise _revision_conflict(_digest(current))
        tmp.replace(path)
        return {"written": written, "removed": removed}


def _digest(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _revision_conflict(current_digest: str | None) -> ApiError:
    return ApiError(
        "配置已在其他位置修改，请刷新后重试",
        status_code=409,
        data={"code": "revision_conflict", "current_revision": current_digest},
    )
