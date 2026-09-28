# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""随包离线负载的清单（MANIFEST.json）读取、结构校验与逐文件验证。

清单覆盖负载内**所有**运行所需文件（Python 运行时 zip、get-pip、依赖
wheels、catalog 组件、python-zip.sha256），记录相对路径、SHA-256、大小与
用途；清单不包含自身摘要（外层 release metadata/签名负责绑定清单）。

``files`` 保持 v1 的扁平 ``{相对路径: sha256}`` 结构——GUI 侧 python.rs 的
``offline_manifest_hash`` 只读它，扩展字段全部另起键名，旧消费者不受影响。

安全边界：清单里的路径是不可信输入。校验拒绝绝对路径、``..``、盘符、
ADS（冒号）、大小写冲突与重复项；验证失败区分 ``payload_missing`` 与
``payload_corrupt``，让「包不完整」和「包被改坏」可分别定位。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MANIFEST_FILENAME = "MANIFEST.json"
MANIFEST_SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)

_PURPOSE_KEYS = ("runtime", "pip-bootstrap", "dependency", "component", "metadata")


class PayloadError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_manifest(payload_dir: Path) -> dict[str, Any]:
    path = Path(payload_dir) / MANIFEST_FILENAME
    if not path.is_file():
        raise PayloadError("payload_missing", f"离线负载缺少清单：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PayloadError("payload_corrupt", f"离线清单不是有效 JSON：{path}") from exc
    if not isinstance(payload, dict):
        raise PayloadError("payload_corrupt", "离线清单必须是 JSON 对象")
    if payload.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise PayloadError(
            "payload_corrupt",
            f"离线清单 schema 版本不受支持：{payload.get('schema_version')}",
        )
    return payload


def _validate_entry_name(name: str) -> None:
    """清单条目名是不可信输入：拒绝一切越界形态。"""
    if not name or not isinstance(name, str):
        raise PayloadError("payload_corrupt", "清单条目名为空或非法")
    normalized = name.replace("\\", "/")
    if normalized != name:
        # 统一用 / 分隔；出现 \\ 视为构造可疑
        raise PayloadError("payload_corrupt", f"清单条目含反斜杠：{name}")
    path = Path(normalized)
    if path.is_absolute() or normalized.startswith("/"):
        raise PayloadError("payload_corrupt", f"清单条目是绝对路径：{name}")
    if ".." in path.parts:
        raise PayloadError("payload_corrupt", f"清单条目含 ..：{name}")
    if len(normalized) > 1 and normalized[1] == ":":
        raise PayloadError("payload_corrupt", f"清单条目含盘符：{name}")
    if ":" in normalized:
        # NTFS 备用数据流（ADS）
        raise PayloadError("payload_corrupt", f"清单条目含冒号（ADS）：{name}")
    if normalized.endswith("/"):
        raise PayloadError("payload_corrupt", f"清单条目指向目录：{name}")


def validate_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    """校验清单结构；返回归一化的 files 映射（相对路径 → sha256）。

    拒绝绝对路径 / .. / 盘符 / ADS / 重复项 / 大小写冲突（NTFS 不区分
    大小写，Wheels/ 与 wheels/ 同名会在解压/复制时互相覆盖）。
    """
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise PayloadError("payload_corrupt", "离线清单缺少 files 映射")
    seen_lower: dict[str, str] = {}
    normalized: dict[str, str] = {}
    for name, digest in files.items():
        _validate_entry_name(str(name))
        text = str(digest or "").strip().lower()
        if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
            raise PayloadError("payload_corrupt", f"清单条目 {name} 的 SHA-256 非法")
        key = str(name)
        lowered = key.lower()
        if lowered in seen_lower and seen_lower[lowered] != key:
            raise PayloadError(
                "payload_corrupt",
                f"清单条目大小写冲突：{key} 与 {seen_lower[lowered]}",
            )
        seen_lower[lowered] = key
        if key in normalized:
            raise PayloadError("payload_corrupt", f"清单条目重复：{key}")
        normalized[key] = text
    return normalized


def verify_payload(payload_dir: Path, manifest: dict[str, Any] | None = None) -> None:
    """逐文件验证负载：存在性 + 大小 + SHA-256，任一不满足即具名失败。

    在「安装使用负载之前」调用（NSIS helper 的 pip 步骤前、GUI 消费离线
    仓前）；不在状态轮询里反复调用——几 GB 的负载每次全量哈希是浪费。
    """
    payload_dir = Path(payload_dir)
    if manifest is None:
        manifest = read_manifest(payload_dir)
    files = validate_manifest(manifest)
    sizes = manifest.get("sizes") if isinstance(manifest.get("sizes"), dict) else {}
    for name, expected in files.items():
        path = payload_dir / name
        if not path.is_file():
            raise PayloadError(
                "payload_missing",
                f"离线负载缺少 {name}（期望 SHA-256 {expected}）——安装包不完整",
            )
        if sizes and name in sizes:
            try:
                actual_size = path.stat().st_size
            except OSError as exc:
                raise PayloadError(
                    "payload_corrupt", f"无法读取离线文件 {name}：{exc}"
                ) from exc
            if actual_size != int(sizes[name]):
                raise PayloadError(
                    "payload_corrupt",
                    f"离线文件 {name} 大小不匹配：期望 {sizes[name]}，实际 {actual_size}",
                )
        actual = sha256_file(path)
        if actual != expected:
            raise PayloadError(
                "payload_corrupt",
                f"离线文件 {name} 校验失败：期望 {expected}，实际 {actual}",
            )


def build_manifest(
    payload_dir: Path,
    files: dict[str, str],
    *,
    python_version: str | None = None,
    browser_revision: str | None = None,
) -> dict[str, Any]:
    """构建期生成 v2 清单（payload 构建脚本调用）。

    ``files`` 映射负载内相对路径 → 用途标签（runtime / pip-bootstrap /
    dependency / component / metadata）；相对路径、SHA-256 与大小由磁盘
    实际内容统计，不由调用方声明。清单本身不进 files：外层 release
    metadata 负责绑定清单摘要。
    """
    purposes = ("runtime", "pip-bootstrap", "dependency", "component", "metadata")
    entries: dict[str, str] = {}
    sizes: dict[str, int] = {}
    hashes: dict[str, str] = {}
    for name, purpose in files.items():
        _validate_entry_name(name)
        if purpose not in purposes:
            raise PayloadError("payload_corrupt", f"未知用途标签：{purpose}")
        path = payload_dir / name
        if not path.is_file():
            raise PayloadError("payload_missing", f"清单登记的文件不存在：{name}")
        entries[name] = purpose
        sizes[name] = path.stat().st_size
        hashes[name] = sha256_file(path)
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "files": hashes,
        "sizes": sizes,
        "purposes": entries,
    }
    if python_version:
        manifest["python_version"] = python_version
    if browser_revision:
        manifest["browser_revision"] = browser_revision
    return manifest


__all__ = [
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    "PayloadError",
    "build_manifest",
    "read_manifest",
    "sha256_file",
    "validate_manifest",
    "verify_payload",
]
