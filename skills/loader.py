# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill 延迟加载：命中之后才读正文，references/scripts 只给受限索引。

边界纪律（plan §6.1）：

* 启动与选择阶段**只碰 manifest**；本模块只在调用编排明确点名某个
  Skill 时才被触发。
* 正文按字符预算截断后交给 Skill Agent——它是「不可信指令」，不是
  系统配置：不能改变沙盒安全策略，也不进 Stella 的人格 prompt。
* references/ 与 scripts/ 只提供**索引**（相对路径 + 大小）；读取单个
  资源必须走 ``read_resource``，它做路径白名单 + 逐段符号链接检查 +
  大小上限三道校验。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from skills.model import SkillManifest, safe_relative_path

# 索引的防御性上限：正经技能的资源不会超过这些量，超出的部分不进索引。
_MAX_ENTRIES_PER_DIR = 64
_INDEX_DEPTH = 4


@dataclass(frozen=True)
class ResourceEntry:
    """resources/scripts 里的一个条目：POSIX 相对路径 + 字节大小。"""

    path: str
    size: int
    kind: str  # "reference" | "script"


@dataclass(frozen=True)
class LoadedSkill:
    """一次命中后的完整加载产物（orchestrator 的输入）。"""

    manifest: SkillManifest
    body: str
    body_truncated: bool
    references: tuple[ResourceEntry, ...] = ()
    scripts: tuple[ResourceEntry, ...] = ()
    assets_oversize_dropped: tuple[str, ...] = ()

    @property
    def resource_digest(self) -> str:
        """加载视图摘要：正文截断态 + 索引，进审计与调用记录。"""
        payload = "|".join(
            [self.manifest.content_digest, str(self.body_truncated)]
            + [e.path for e in self.references + self.scripts]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _index_dir(
    root: Path, *, kind: str, asset_max_bytes: int
) -> tuple[tuple[ResourceEntry, ...], tuple[str, ...]]:
    """枚举一个资源目录（不读内容）；返回 (条目, 超限被丢弃的路径)。"""
    entries: list[ResourceEntry] = []
    oversize: list[str] = []
    if not root.is_dir() or root.is_symlink():
        return (), ()
    pending = [(root, 0)]
    while pending and len(entries) < _MAX_ENTRIES_PER_DIR:
        current, depth = pending.pop(0)
        if depth > _INDEX_DEPTH:
            continue
        try:
            children = sorted(current.iterdir(), key=lambda p: str(p))
        except OSError:
            continue
        for child in children:
            try:
                if child.is_symlink():
                    continue  # 越界 symlink 是资源目录里最便宜的逃逸通道
                if child.is_dir():
                    pending.append((child, depth + 1))
                    continue
                if child.is_file():
                    size = child.stat().st_size
                    rel = child.relative_to(root.parent)
                    posix = PurePosixPath(*rel.parts).as_posix()
                    if size > asset_max_bytes:
                        oversize.append(posix)
                        continue
                    entries.append(ResourceEntry(path=posix, size=size, kind=kind))
            except OSError:
                continue
    if len(entries) >= _MAX_ENTRIES_PER_DIR:  # 防御性截断，保持确定性
        entries = entries[:_MAX_ENTRIES_PER_DIR]
    return tuple(entries), tuple(oversize)


def load_skill(
    manifest: SkillManifest,
    *,
    body_max_chars: int,
    asset_max_bytes: int,
) -> LoadedSkill:
    """读取 SKILL.md 正文（截断到预算）并建立 references/scripts 索引。

    只在调用编排命中该 Skill 后调用；启动与选择阶段不许走到这里。
    """
    body_path = Path(manifest.root) / "SKILL.md"
    try:
        text = body_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    truncated = len(text) > body_max_chars
    references, ref_oversize = _index_dir(
        Path(manifest.root) / "references",
        kind="reference",
        asset_max_bytes=asset_max_bytes,
    )
    scripts, script_oversize = _index_dir(
        Path(manifest.root) / "scripts",
        kind="script",
        asset_max_bytes=asset_max_bytes,
    )
    return LoadedSkill(
        manifest=manifest,
        body=text[:body_max_chars],
        body_truncated=truncated,
        references=references,
        scripts=scripts,
        assets_oversize_dropped=ref_oversize + script_oversize,
    )


def read_resource(
    manifest: SkillManifest,
    rel_path: str,
    *,
    asset_max_bytes: int,
) -> bytes:
    """按白名单读取技能内的一个资源文件；越界/超限抛 ``ValueError``。

    三道校验（plan §6.1：禁止 ``..``/绝对路径/越界 symlink）：
    1. POSIX 相对路径白名单（``safe_relative_path``）；
    2. 逐段符号链接检查 + resolve 后必须仍在技能根内；
    3. 文件大小不超过单资源上限。
    """
    safe = safe_relative_path(rel_path)
    if safe is None:
        raise ValueError(f"资源路径不合法: {rel_path!r}")
    root = Path(manifest.root).resolve()
    walker = Path(manifest.root)
    for part in safe.parts:
        walker = walker / part
        if walker.is_symlink():
            raise ValueError(f"资源路径包含符号链接: {rel_path!r}")
    target = walker.resolve()
    if not (target == root or target.is_relative_to(root)):
        raise ValueError(f"资源路径越出技能目录: {rel_path!r}")
    if not target.is_file():
        raise ValueError(f"资源不存在或不是普通文件: {rel_path!r}")
    size = target.stat().st_size
    if size > asset_max_bytes:
        raise ValueError(f"资源超过单文件上限 {asset_max_bytes}: {rel_path!r}")
    return target.read_bytes()
