# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""发布包清单 ``.stella-manifest.json``：路径 → sha256。

用途只有一个，但很关键：升级时判断**用户有没有改过发布包自带的文件**。
``system_prompts/default.md``、``config/capabilities/*.toml`` 这些文件既是「发布包内容」
又是「用户可能改的配置」。没有原始哈希就只能二选一：一律用新版（覆盖用户改的人格），
或一律保留旧版（用户永远拿不到新默认值）。两个都不对。

有了清单就能精确判断：命中原始哈希 = 用户没动过 → 用新版；不命中 = 用户改过 →
保留他的文件，把新版另存为 ``*.new`` 并在报告里点出来。

清单由 release CI 生成（``python -m deploy manifest --write``），随包发布。
没有清单的旧版本（≤3.0.0）退化为「一律保留旧文件」。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

MANIFEST_NAME = ".stella-manifest.json"
# 只登记「发布包自带、且用户可能会改」的文件。全量登记没有意义：代码文件本就该被新版覆盖。
MANIFEST_TARGETS = (
    "system_prompts/*.md",
    "config/capabilities/*.toml",
    "memory/SYSTEM.md",
    ".env.example",
)


def file_sha256(path: Path) -> str:
    """文件内容的 sha256（十六进制）。按块读，避免大文件占内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path) -> dict[str, str]:
    """扫描 ``MANIFEST_TARGETS``，返回「相对路径（正斜杠） → sha256」。"""
    entries: dict[str, str] = {}
    for pattern in MANIFEST_TARGETS:
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                entries[path.relative_to(root).as_posix()] = file_sha256(path)
    return entries


def write_manifest(root: Path) -> Path:
    """把清单写到 ``root/.stella-manifest.json``（稳定排序，便于 diff）。"""
    target = root / MANIFEST_NAME
    payload = {"version": 1, "files": build_manifest(root)}
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def load_manifest(root: Path) -> dict[str, str]:
    """读取某个安装目录的清单；不存在或损坏时返回空 dict（退化为「保留旧文件」）。"""
    path = root / MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    files = data.get("files")
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}


def is_pristine(root: Path, relative: str, manifest: dict[str, str] | None = None) -> bool:
    """该文件是否与它所属发布包的原始内容一致（即用户没改过）。

    没有清单记录时返回 False——**宁可保留用户的文件**：把用户写了几小时的人格
    覆盖掉是不可逆的，而多留一个 ``*.new`` 只是有点吵。
    """
    entries = manifest if manifest is not None else load_manifest(root)
    expected = entries.get(relative)
    if not expected:
        return False
    path = root / relative
    if not path.is_file():
        return False
    return file_sha256(path) == expected
