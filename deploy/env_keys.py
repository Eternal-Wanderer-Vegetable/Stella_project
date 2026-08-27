# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``.env`` 键的生命周期登记表：废弃、改名、敏感。

**全项目关于「这个键还算不算数」的单一真相源**：`deploy doctor` 的废弃提示、
升级时的 `.env` 合并器、将来 GUI 的配置页都从这里读。散落两份必然对不上——
一处删了、另一处还在提示，用户会收到互相矛盾的建议。

判据只有一条：**代码是否还在读它**。只要 `config/settings.py` 不再读某个键，它就
必须登记在这里，否则用户的 `.env` 里会留着一行完全不生效的配置，而他以为改了。
"""

from __future__ import annotations

# 已废弃的键 → 废弃原因（会写进升级报告，所以要写成人话）
DEPRECATED: dict[str, str] = {
    "NAPCAT_SHELL_PATH": "启动流程已与 NapCat 完全分离，Bot 只连现成的 OneBot 端点",
    "NAPCAT_AUTO_START": "同上：不再由 Stella 拉起 NapCat",
    "NAPCAT_QQ_ACCOUNT": "同上：登录由 NapCat 自己完成（需人工扫码）",
    "NAPCAT_QQ_PASSWORD": "同上，且明文密码本不该出现在配置文件里",
    "NAPCAT_QQ_PASSWORD_MD5": "同上",
    "NAPCAT_LAUNCH_LOG_PATH": "同上：不再有 NapCat 启动日志",
    "NAPCAT_SHOW_WINDOW": "同上",
    "MEMORY_COMPRESS_LOG_FILENAME": (
        "2026-08-25 日志统一到 LOG_DIR 后改为完整路径 MEMORY_COMPRESS_LOG_PATH；"
        "语义从「文件名」变成「完整路径」，旧值不能直接沿用"
    ),
}

# 已废弃的键前缀 → 原因
DEPRECATED_PREFIXES: dict[str, str] = {
    "NAPCAT_WATCHDOG_": "NapCat 看护逻辑已移除",
}

# 改名且**值可以直接沿用**的键（旧名 → 新名）。
# 语义也变了的不要放这里（如 MEMORY_COMPRESS_LOG_FILENAME），那种只能提示重填。
RENAMED: dict[str, str] = {}

# 敏感键：报告里只说「已沿用」，绝不打印值。
# 发布包的日志与报告都可能被贴进 issue，凭据一旦泄露无法收回。
SENSITIVE: frozenset[str] = frozenset(
    {
        "ONEBOT_ACCESS_TOKEN",
        "NAPCAT_QQ_PASSWORD",
        "NAPCAT_QQ_PASSWORD_MD5",
        "LM_STUDIO_API_KEY",
        "OPENAI_API_KEY",
    }
)


def deprecation_reason(key: str) -> str | None:
    """键是否已废弃；是则返回原因，否则 None。"""
    if key in DEPRECATED:
        return DEPRECATED[key]
    for prefix, reason in DEPRECATED_PREFIXES.items():
        if key.startswith(prefix):
            return reason
    return None


def is_sensitive(key: str) -> bool:
    """是否敏感键（报告与日志里不打印其值）。"""
    upper = key.upper()
    return upper in SENSITIVE or any(
        marker in upper for marker in ("TOKEN", "PASSWORD", "SECRET", "API_KEY")
    )
