# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill catalog：四层合并、原子快照、按插件局部刷新。

边界纪律（plan §6.1/§3）：

* catalog 只持有 **metadata**（manifest 不含正文文本），合并优先级固定
  ``workspace > user > plugin > builtin``，同层冲突按确定性路径排序。
* 快照**原子替换**：``snapshot`` 整体换引用，进行中的请求继续持有旧
  快照读完这一轮——不存在「读到一半的目录」。刷新失败保留上一版，
  错误进 ``status()`` 供诊断（plan §6.5）。
* 插件重载只刷新该插件的来源（``refresh_plugin``），不整层重建——
  重载一个插件不该让其他插件的技能目录重新扫一遍。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from skills.discovery import scan_layer, scan_plugins
from skills.model import SkillManifest, SkillSource


@dataclass(frozen=True)
class SkillSnapshot:
    """一次合并结果的不可变视图。``by_name`` 视为只读（快照语义）。"""

    by_name: dict[str, SkillManifest]
    version: str
    quarantined: tuple[str, ...] = ()
    built_at: float = 0.0

    def get(self, name: str) -> SkillManifest | None:
        return self.by_name.get(name)

    def manifests(self) -> list[SkillManifest]:
        """确定性顺序的全部 manifest：层优先级降序，同层按名称排序。"""
        return sorted(
            self.by_name.values(),
            key=lambda m: (-m.priority, m.name, str(m.root)),
        )

    def candidates_metadata(self) -> list[dict]:
        """给状态 API 的 metadata 摘要：名称/描述/来源，无路径无正文。"""
        return [
            {
                "name": m.name,
                "description": m.description,
                "source": m.source.value,
                "trust": m.trust.value,
                "version": m.version,
            }
            for m in self.manifests()
        ]


@dataclass
class _WorkspaceCache:
    """workspace 层的轻缓存：目录内容没变（mtime 摘要相同）就不重扫。"""

    key: str = ""
    mtimes: str = ""
    manifests: tuple[SkillManifest, ...] = ()
    quarantined: tuple[str, ...] = ()


def _merge(
    layers: dict[SkillSource, tuple[SkillManifest, ...]],
    quarantined: tuple[str, ...],
) -> SkillSnapshot:
    """按固定优先级合并各层；同层同名时路径排序后的**后者**生效（确定性）。"""
    by_name: dict[str, SkillManifest] = {}
    for source in (
        SkillSource.BUILTIN,
        SkillSource.PLUGIN,
        SkillSource.USER,
        SkillSource.WORKSPACE,
    ):
        for manifest in layers.get(source, ()):
            by_name[manifest.name] = manifest  # 高优先级层后写入，直接覆盖
    digest = hashlib.sha256(
        "\n".join(
            f"{name}:{m.content_digest}" for name, m in sorted(by_name.items())
        ).encode("utf-8")
    ).hexdigest()[:16]
    return SkillSnapshot(
        by_name=by_name,
        version=digest,
        quarantined=tuple(quarantined[-256:]),  # 诊断记录有界，防重载风暴撑爆内存
        built_at=time.time(),
    )


class SkillCatalog:
    """四层技能目录。读路径无锁：整快照换引用，读者各持一致的旧版。"""

    def __init__(
        self,
        *,
        builtin_dir: Path,
        user_dir: Path,
        plugins_dir: Path,
        manifest_max_bytes: int = 262144,
    ) -> None:
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir
        self._plugins_dir = plugins_dir
        self._manifest_max_bytes = manifest_max_bytes
        self._layers: dict[SkillSource, tuple[SkillManifest, ...]] = dict.fromkeys(
            SkillSource, ()
        )
        self._snapshot = _merge(self._layers, ())
        self._last_error = ""
        self._last_refresh_at = 0.0
        self._workspace_cache = _WorkspaceCache()

    @classmethod
    def from_settings(cls) -> SkillCatalog:
        """按 settings 的目录配置构造（延迟 import，避免包级依赖 config）。"""
        from config import settings

        return cls(
            builtin_dir=Path(settings.SKILLS_BUILTIN_DIR),
            user_dir=Path(settings.SKILLS_USER_DIR),
            plugins_dir=Path(settings.ASTRBOT_PLUGINS_DIR),
            manifest_max_bytes=int(settings.SKILLS_MANIFEST_MAX_BYTES),
        )

    # ---------- 刷新 ----------

    def refresh(self) -> bool:
        """全量重扫四层并原子替换快照。失败保留旧快照并记录错误。"""
        try:
            layers: dict[SkillSource, tuple[SkillManifest, ...]] = {}
            quarantined: list[str] = []
            builtin, q = scan_layer(
                self._builtin_dir,
                source=SkillSource.BUILTIN,
                max_bytes=self._manifest_max_bytes,
            )
            layers[SkillSource.BUILTIN] = tuple(builtin)
            quarantined.extend(q)
            plugins, q = scan_plugins(
                self._plugins_dir, max_bytes=self._manifest_max_bytes
            )
            layers[SkillSource.PLUGIN] = tuple(plugins)
            quarantined.extend(q)
            user, q = scan_layer(
                self._user_dir,
                source=SkillSource.USER,
                max_bytes=self._manifest_max_bytes,
            )
            layers[SkillSource.USER] = tuple(user)
            quarantined.extend(q)
        except Exception as e:  # 刷新失败：旧快照继续服务，错误进状态
            self._last_error = f"刷新失败: {e}"
            return False
        self._layers[SkillSource.BUILTIN] = layers[SkillSource.BUILTIN]
        self._layers[SkillSource.PLUGIN] = layers[SkillSource.PLUGIN]
        self._layers[SkillSource.USER] = layers[SkillSource.USER]
        self._workspace_cache = _WorkspaceCache()  # workspace 层缓存随之失效
        self._snapshot = _merge(self._layers, tuple(quarantined))
        self._last_error = ""
        self._last_refresh_at = time.time()
        return True

    def refresh_plugin(self, plugin_dir: Path) -> bool:
        """插件重载后只刷新该插件的技能来源（plan §6.1.2 / §6.5）。

        ``plugin_dir`` 传 ``loader._plugin_dir_of(md)`` 的结果；目录不存在
        （插件被卸载）视为清空该来源。失败保留现状。
        """
        origin = plugin_dir.name
        try:
            found, quarantined = scan_layer(
                plugin_dir / "skills",
                source=SkillSource.PLUGIN,
                max_bytes=self._manifest_max_bytes,
                origin_of=lambda _child: origin,
            )
        except Exception as e:
            self._last_error = f"刷新插件 {origin} 失败: {e}"
            return False
        kept = tuple(m for m in self._layers[SkillSource.PLUGIN] if m.origin != origin)
        self._layers[SkillSource.PLUGIN] = kept + tuple(found)
        self._snapshot = _merge(
            self._layers, tuple(self._snapshot.quarantined) + tuple(quarantined)
        )
        self._last_error = ""
        self._last_refresh_at = time.time()
        return True

    # ---------- 读取 ----------

    @property
    def snapshot(self) -> SkillSnapshot:
        """当前快照（无 workspace 层）。读方持有引用即可，不会被原地改。"""
        return self._snapshot

    def snapshot_with_workspace(self, workspace_dir: Path) -> SkillSnapshot:
        """当前快照 + workspace 层的合并视图（mtime 缓存，未变不重扫）。"""
        try:
            mtimes = self._workspace_mtimes(workspace_dir)
        except OSError:
            return self._snapshot
        key = str(workspace_dir)
        cache = self._workspace_cache
        # key 恒非空（Path 的字符串形态），空技能层的缓存命中也不误判
        if cache.key == key and cache.mtimes == mtimes:
            return self._merge_view(cache)
        try:
            found, quarantined = scan_layer(
                workspace_dir / "skills",
                source=SkillSource.WORKSPACE,
                max_bytes=self._manifest_max_bytes,
            )
        except Exception:
            return self._snapshot
        self._workspace_cache = _WorkspaceCache(
            key=key,
            mtimes=mtimes,
            manifests=tuple(found),
            quarantined=tuple(quarantined),
        )
        return self._merge_view(self._workspace_cache)

    def _merge_view(self, cache: _WorkspaceCache) -> SkillSnapshot:
        layers = dict(self._layers)
        layers[SkillSource.WORKSPACE] = cache.manifests
        return _merge(layers, tuple(self._snapshot.quarantined) + cache.quarantined)

    @staticmethod
    def _workspace_mtimes(workspace_dir: Path) -> str:
        """workspace 层变化探针：各 <name>/SKILL.md 的 mtime 拼接摘要。"""
        root = workspace_dir / "skills"
        if not root.is_dir():
            return ""
        parts: list[str] = []
        for child in sorted(root.iterdir(), key=lambda p: str(p)):
            body = child / "SKILL.md"
            if body.is_file():
                parts.append(f"{child.name}:{int(body.stat().st_mtime)}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()

    # ---------- 状态 ----------

    def status(self) -> dict:
        """给状态 API 的摘要：数量、版本、隔离与最近错误，无正文无路径明细。"""
        counts = {
            source.value: len(self._layers[source])
            for source in (
                SkillSource.BUILTIN,
                SkillSource.PLUGIN,
                SkillSource.USER,
            )
        }
        return {
            "enabled": True,
            "version": self._snapshot.version,
            "total": len(self._snapshot.by_name),
            "layer_counts": counts,
            "quarantined": len(self._snapshot.quarantined),
            "last_error": self._last_error,
            "last_refresh_at": self._last_refresh_at,
        }
