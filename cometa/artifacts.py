# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""产物收集与 manifest（方案 §6.12）。

- 产物进入 ``STELLA_HOME/cometa/artifacts/<task_id>/``，保存 SHA-256、
  长度与 MIME；
- 只接受**该任务工作区内**的允许文件：拒绝路径穿越、越界链接和未授权
  敏感文件（tests/cometa/test_artifacts.py 的拒绝矩阵）；
- 完整最终答复也作为产物保存（``final_text.md``）——完整文本不进聊天
  上下文，只传有界摘要与引用；
- 文件先写临时名再原子改名；发布结果 manifest 与 final notification 同
  事务（store.finish_task），文件写成功但事务失败的孤立产物由延迟清理
  回收；已发布但文件缺失必须显示 unavailable。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .models import ArtifactAvailability, ArtifactRef, new_id

_LOGGER = logging.getLogger("cometa.artifacts")

FINAL_TEXT_NAME = "final_text.md"
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9._\- ]{1,120}$")
# 结果文件/产物目录的硬上限（config.limits 可再收紧）
DEFAULT_ARTIFACT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_TOTAL_MAX_BYTES = 100 * 1024 * 1024


class ArtifactError(RuntimeError):
    """产物收集被拒绝（越界/超限/缺失）。"""


@dataclass(slots=True)
class CollectedArtifact:
    """已落库的产物（相对存储键是 finish_task 的 manifest 条目来源）。"""

    artifact_id: str
    display_name: str
    relative_storage_key: str
    sha256: str
    size: int
    mime: str


class ArtifactCollector:
    def __init__(self, artifacts_root: Path, *, max_bytes: int = DEFAULT_ARTIFACT_MAX_BYTES,
                 total_max_bytes: int = DEFAULT_TOTAL_MAX_BYTES):
        self._root = Path(artifacts_root)
        self._max_bytes = max_bytes
        self._total_max_bytes = total_max_bytes

    def task_dir(self, task_id: str) -> Path:
        return self._root / task_id

    # ── 校验 ─────────────────────────────────────────────
    def _validate_source(self, source: Path, workspace_path: Path) -> Path:
        """源文件必须真实存在于工作区内：拒绝穿越、越界 symlink/junction。"""
        source = Path(source)
        workspace_path = Path(workspace_path)
        if not source.is_absolute():
            source = workspace_path / source
        resolved = source.resolve()
        scope = workspace_path.resolve()
        if os.path.commonpath([str(resolved), str(scope)]) != str(scope):
            raise ArtifactError(f"产物路径越出工作区: {source}")
        if resolved.is_symlink() or (resolved.exists() and resolved.is_symlink()):
            raise ArtifactError(f"产物不允许是链接: {source}")
        # 父目录中的链接同样不允许（junction/symlink 目录逃逸）
        for parent in resolved.parents:
            if parent == scope:
                break
            if parent.is_symlink():
                raise ArtifactError(f"产物路径含链接目录: {source}")
        if not resolved.is_file():
            raise ArtifactError(f"产物不是常规文件: {source}")
        size = resolved.stat().st_size
        if size > self._max_bytes:
            raise ArtifactError(
                f"产物超过单文件上限 {self._max_bytes} 字节: {source}（{size}）"
            )
        return resolved

    # ── 收集 ─────────────────────────────────────────────
    def collect(
        self,
        task_id: str,
        source: Path | str,
        *,
        workspace_path: Path | str,
        display_name: str | None = None,
    ) -> CollectedArtifact:
        """把工作区内文件复制进产物目录（原子写 + 哈希）。"""
        resolved = self._validate_source(Path(source), Path(workspace_path))
        size = resolved.stat().st_size
        total_dir = self.task_dir(task_id)
        if total_dir.exists():
            existing = sum(p.stat().st_size for p in total_dir.rglob("*") if p.is_file())
            if existing + size > self._total_max_bytes:
                raise ArtifactError(
                    f"任务产物总量超过上限 {self._total_max_bytes} 字节"
                )
        name = (display_name or resolved.name).strip()
        if not _ARTIFACT_NAME_RE.match(name):
            raise ArtifactError(f"产物展示名不合法: {name!r}")
        artifact_id = new_id()
        total_dir.mkdir(parents=True, exist_ok=True)
        storage_key = f"{artifact_id[:8]}-{name}"
        target = total_dir / storage_key
        tmp_target = total_dir / f".tmp-{artifact_id}"
        try:
            shutil.copy2(resolved, tmp_target)
            tmp_target.replace(target)  # 原子归档
        finally:
            if tmp_target.exists():
                tmp_target.unlink(missing_ok=True)
        sha256 = _sha256_of(target)
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        return CollectedArtifact(
            artifact_id=artifact_id,
            display_name=name,
            relative_storage_key=storage_key,
            sha256=sha256,
            size=size,
            mime=mime,
        )

    def save_final_text(self, task_id: str, text: str) -> str:
        """保存完整最终答复，返回 storage_key（final_text_ref）。"""
        text = text or ""
        if len(text.encode("utf-8")) > self._max_bytes:
            raise ArtifactError("最终答复超过单文件上限")
        total_dir = self.task_dir(task_id)
        total_dir.mkdir(parents=True, exist_ok=True)
        target = total_dir / FINAL_TEXT_NAME
        tmp = total_dir / f".tmp-final-{new_id()[:6]}"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
        return FINAL_TEXT_NAME

    def read_final_text(self, task_id: str) -> str:
        target = self.task_dir(task_id) / FINAL_TEXT_NAME
        if not target.is_file():
            return ""
        return target.read_text(encoding="utf-8")

    def artifact_path(self, task_id: str, relative_storage_key: str) -> Path:
        """解析存储键为绝对路径。**只按 manifest 键取**，不接受任意 path 参数
        （§6.12：WebUI 下载服务端解析 manifest）。"""
        if "/" in relative_storage_key or "\\" in relative_storage_key or ".." in relative_storage_key:
            raise ArtifactError(f"存储键不合法: {relative_storage_key!r}")
        path = (self.task_dir(task_id) / relative_storage_key).resolve()
        scope = self.task_dir(task_id).resolve()
        if os.path.commonpath([str(path), str(scope)]) != str(scope):
            raise ArtifactError(f"存储键越界: {relative_storage_key!r}")
        return path

    def verify_availability(self, task_id: str, storage_key: str) -> ArtifactAvailability:
        """已发布但文件缺失必须显示 unavailable（§6.12 第 5 步）。"""
        try:
            path = self.artifact_path(task_id, storage_key)
        except ArtifactError:
            return ArtifactAvailability.UNAVAILABLE
        return (
            ArtifactAvailability.AVAILABLE if path.is_file() else ArtifactAvailability.UNAVAILABLE
        )

    def collect_manifest(
        self,
        task_id: str,
        collected: list[CollectedArtifact],
        *,
        manifest_ref: str = "manifest.json",
    ) -> str:
        """写 manifest 并返回引用键。manifest 与 results 同事务落库（引用键），
        文件本身先行写好——顺序符合「先写临时文件并校验/原子归档 → 同事务
        发布 manifest」（§6.3 事务边界 4）。"""
        import json

        payload = {
            "schema_version": 1,
            "task_id": task_id,
            "artifacts": [
                {
                    "artifact_id": c.artifact_id,
                    "display_name": c.display_name,
                    "relative_storage_key": c.relative_storage_key,
                    "sha256": c.sha256,
                    "size": c.size,
                    "mime": c.mime,
                }
                for c in collected
            ],
        }
        total_dir = self.task_dir(task_id)
        total_dir.mkdir(parents=True, exist_ok=True)
        target = total_dir / manifest_ref
        tmp = total_dir / f".tmp-{manifest_ref}"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        return manifest_ref


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_refs_from_manifest(manifest: dict) -> list[ArtifactRef]:
    """manifest → ArtifactRef 列表（service/webui 展示用）。"""
    refs = []
    for item in manifest.get("artifacts", []):
        refs.append(
            ArtifactRef(
                artifact_id=str(item.get("artifact_id", "")),
                display_name=str(item.get("display_name", "")),
                relative_storage_key=str(item.get("relative_storage_key", "")),
                sha256=str(item.get("sha256", "")),
                size=int(item.get("size", 0)),
                mime=str(item.get("mime", "")),
            )
        )
    return refs


__all__ = [
    "FINAL_TEXT_NAME",
    "ArtifactCollector",
    "ArtifactError",
    "CollectedArtifact",
    "artifact_refs_from_manifest",
]
