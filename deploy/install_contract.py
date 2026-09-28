# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""安装契约：结果语义、退出码映射与随包负载模式声明。

这是 NSIS 钩子（installer-hooks.nsh）、离线装载辅助（nsis_bootstrap_helper）、
deploy CLI（``python -m deploy bootstrap install``）与 GUI（python.rs）之间的
**单一事实来源**：安装「成功」不再只是「进程退出码 0」，而是明确的
outcome 终态——``ready``、``reboot_required``、``failed``、``cancelled``、
``interrupted``、``repair_required`` 之一，并与退出码/JSON 字段有稳定映射。

随包负载模式（``payload_mode``）也在这里声明：OneClick 安装树根的
``.stella-payload-mode`` 文件由 ``build_release_package.py --stage-resources``
写出。安装侧据此判断变体，而**不是**靠「offline/MANIFEST.json 是否存在」
猜测——声明为 offline 却缺清单是构建缺陷，必须硬失败，绝不能静默降级成
online 让用户首启时才发现装了一半。
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

INSTALL_CONTRACT_VERSION = 1

#: 随包负载模式声明文件（安装树根；内容为 "online" 或 "offline"）。
PAYLOAD_MODE_FILENAME = ".stella-payload-mode"
#: release 元数据文件（安装树根；由构建期写入，安装/诊断侧只读）。
RELEASE_METADATA_FILENAME = ".stella-release-metadata.json"

PAYLOAD_MODE_ONLINE = "online"
PAYLOAD_MODE_OFFLINE = "offline"
PAYLOAD_MODES = (PAYLOAD_MODE_ONLINE, PAYLOAD_MODE_OFFLINE)


class InstallOutcome(str, Enum):
    """安装终态。``failed`` 之外的每个值都携带独立的恢复语义。"""

    READY = "ready"
    REBOOT_REQUIRED = "reboot_required"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    REPAIR_REQUIRED = "repair_required"


#: outcome → 进程退出码的稳定映射。
#: 消费方：deploy CLI（``python -m deploy bootstrap install``）、
#: NSIS 离线装载辅助（非零即 Abort，但详情区展示具体码）、CI 安装验收。
#: ``0`` 之外的任何值都不代表「安装完成」。
OUTCOME_EXIT_CODES: dict[InstallOutcome, int] = {
    InstallOutcome.READY: 0,
    InstallOutcome.FAILED: 1,
    InstallOutcome.REBOOT_REQUIRED: 3,
    InstallOutcome.CANCELLED: 4,
    InstallOutcome.INTERRUPTED: 5,
    InstallOutcome.REPAIR_REQUIRED: 6,
}

#: CLI 参数/调用方式错误（不属于安装 outcome；沿用历史值 2）。
EXIT_USAGE = 2


def exit_code_for(outcome: InstallOutcome) -> int:
    return OUTCOME_EXIT_CODES[outcome]


def write_payload_mode(install_root: Path, mode: str) -> Path:
    """构建期写出负载模式声明。mode 必须是受支持值。"""
    if mode not in PAYLOAD_MODES:
        raise ValueError(f"未知 payload_mode：{mode}")
    path = Path(install_root) / PAYLOAD_MODE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode + "\n", encoding="utf-8")
    return path


def read_payload_mode(install_root: Path) -> str | None:
    """读负载模式声明；缺失或非法时返回 None（旧包兼容）。"""
    path = Path(install_root) / PAYLOAD_MODE_FILENAME
    try:
        mode = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return None
    return mode if mode in PAYLOAD_MODES else None


def write_release_metadata(install_root: Path, metadata: dict) -> Path:
    """构建期写出 release 元数据（安装/诊断侧据此核对身份与指纹）。"""
    path = Path(install_root) / RELEASE_METADATA_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def read_release_metadata(install_root: Path) -> dict | None:
    """读 release 元数据；缺失或损坏返回 None（旧包兼容，诊断侧自行提示）。"""
    path = Path(install_root) / RELEASE_METADATA_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "EXIT_USAGE",
    "INSTALL_CONTRACT_VERSION",
    "OUTCOME_EXIT_CODES",
    "PAYLOAD_MODES",
    "PAYLOAD_MODE_FILENAME",
    "PAYLOAD_MODE_OFFLINE",
    "PAYLOAD_MODE_ONLINE",
    "RELEASE_METADATA_FILENAME",
    "InstallOutcome",
    "exit_code_for",
    "read_payload_mode",
    "read_release_metadata",
    "write_payload_mode",
    "write_release_metadata",
]
