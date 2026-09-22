# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill 选择器：从 catalog 的 metadata 里挑出本轮的有限候选。

边界纪律（plan §6.2）：

* 只消费**名称与描述**——候选阶段绝不读正文、scripts 或 references
  （渐进披露：命中后才由 loader 加载正文）。
* 确定性匹配先行：技能名 token 命中即入候选，score 拉满。中文没有词
  边界，从描述里「猜关键词」会产生碰到什么都命中的噪声词
  （capability/registry.py 的 Capability.keywords 同一教训），所以
  确定性层只认名字，不猜词。
* 可选 embedding 层复用 ``memory.embeddings.EmbeddingService``，但缓存
  与 Router 原型缓存**物理隔离**（selector 私有 dict），且键含 catalog
  版本：目录一变，旧原型向量整体失效，不会拿旧目录的向量配新目录。
* 无命中、超时、embedding 失败都返回**空候选**——选择器失败的最坏
  后果是「这轮没有技能可用」，绝不能变成异常击穿主链路。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from pathlib import Path
from typing import Any

from skills.catalog import SkillCatalog
from skills.model import SkillCandidate, SkillManifest

# 选择阶段的整体预算（秒）：embedding 往返也要压在这个窗内，超时按空候选降级。
_SELECT_TIMEOUT_SECONDS = 5.0
# embedding 相似度入候选的门槛。Router 语义匹配用的同一量级；低于它的
# 相似度只会制造「什么都能沾一点」的候选。
_SIMILARITY_THRESHOLD = 0.5
_NAME_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,}")


def _name_tokens(name: str) -> list[str]:
    """把技能名拆成可匹配 token：``doc-lookup`` → ["doc-lookup", "doc", "lookup"]。"""
    tokens = [name.lower()]
    tokens.extend(t for t in re.split(r"[._-]", name.lower()) if len(t) >= 3)
    return tokens


def _latin_terms(text: str) -> list[str]:
    """提取描述里的拉丁词（≥3 字符）：配置键、文件后缀这类术语。"""
    return _NAME_TOKEN_RE.findall(text.lower())


def _deterministic_score(manifest: SkillManifest, message: str) -> tuple[float, str]:
    """确定性匹配：名字 token 或描述术语在消息里出现。返回 (score, 理由)。"""
    lowered = message.lower()
    for token in _name_tokens(manifest.name):
        if token in lowered:
            return 1.0, f"name:{token}"
    for term in _latin_terms(manifest.description):
        if len(term) >= 3 and term in lowered:
            return 0.8, f"term:{term}"
    return 0.0, ""


def _cosine(a: list[float], b: list[float]) -> float:
    """向量夹角相似度（本地实现，避免 selector 依赖 memory 的内部函数集）。"""
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if not norm_a or not norm_b:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (norm_a * norm_b)


class SkillSelector:
    """catalog 快照上的候选挑选器。``select`` 永不抛异常、永不读正文。"""

    def __init__(
        self,
        catalog: SkillCatalog,
        *,
        max_candidates: int,
        description_max_chars: int,
        embedding: Any | None = None,
        embedding_enabled: bool = False,
    ) -> None:
        self._catalog = catalog
        self._max_candidates = max(0, max_candidates)
        self._description_max_chars = description_max_chars
        self._embedding = embedding
        self._embedding_enabled = embedding_enabled
        # 与 Router 原型缓存物理隔离的私有缓存；键含 catalog 版本。
        self._vector_cache: dict[str, list[float] | None] = {}

    @classmethod
    def from_settings(cls, catalog: SkillCatalog) -> SkillSelector:
        """按 settings 构造；embedding 服务仅在开关打开时创建。"""
        from config import settings

        embedding = None
        if settings.SKILLS_EMBEDDING_ENABLED:
            from memory.embeddings import EmbeddingService

            # 传私有 cache dict：不写进 memory 的模块级 _CACHE（命名空间隔离）。
            embedding = EmbeddingService(
                base_url=settings.MEMORY_EMBEDDING_BASE_URL,
                model=settings.MEMORY_EMBEDDING_MODEL,
                timeout=settings.MEMORY_EMBEDDING_TIMEOUT,
            )
        return cls(
            catalog,
            max_candidates=int(settings.SKILLS_MAX_CANDIDATES),
            description_max_chars=1024,
            embedding=embedding,
            embedding_enabled=bool(settings.SKILLS_EMBEDDING_ENABLED),
        )

    # ---------- 向量 ----------

    def _cache_key(self, catalog_version: str, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        model = getattr(self._embedding, "model", "") or ""
        dim = getattr(self._embedding, "dim", 0)
        # plan §6.2 的键形态：skills:<catalog_version>:<model>:<dim>:<sha256>
        return f"skills:{catalog_version}:{model}:{dim}:{digest}"

    async def _prototype_vector(
        self, catalog_version: str, text: str
    ) -> list[float] | None:
        """取一段原型的向量；缓存未命中才请求服务，失败返回 None。"""
        if self._embedding is None:
            return None
        key = self._cache_key(catalog_version, text)
        if key in self._vector_cache:
            return self._vector_cache[key]
        try:
            vector = await self._embedding.embed(text)
        except Exception:
            vector = None
        self._vector_cache[key] = vector
        return vector

    # ---------- 主入口 ----------

    async def select(
        self,
        message: str,
        *,
        workspace_dir: Path | None = None,
    ) -> list[SkillCandidate]:
        """挑选本轮候选。失败路径全部收拢为「空候选」。"""
        try:
            return await asyncio.wait_for(
                self._select_inner(message, workspace_dir),
                timeout=_SELECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return []
        except Exception:
            return []

    async def _select_inner(
        self, message: str, workspace_dir: Path | None
    ) -> list[SkillCandidate]:
        snapshot = (
            self._catalog.snapshot_with_workspace(workspace_dir)
            if workspace_dir is not None
            else self._catalog.snapshot
        )
        manifests = snapshot.manifests()
        if not manifests or self._max_candidates <= 0:
            return []

        scored: dict[str, tuple[float, str, SkillManifest]] = {}
        for manifest in manifests:
            score, reason = _deterministic_score(manifest, message)
            if score > 0.0:
                scored[manifest.name] = (score, reason, manifest)

        if self._embedding_enabled and self._embedding is not None:
            message_vector = await self._prototype_vector(snapshot.version, message)
            if message_vector:
                for manifest in manifests:
                    if manifest.name in scored:
                        continue
                    prototype = f"{manifest.name}: {manifest.description}"
                    vector = await self._prototype_vector(snapshot.version, prototype)
                    if not vector:
                        continue
                    similarity = _cosine(message_vector, vector)
                    if similarity >= _SIMILARITY_THRESHOLD:
                        scored[manifest.name] = (
                            similarity,
                            f"embedding:{similarity:.2f}",
                            manifest,
                        )

        ranked = sorted(
            scored.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[: self._max_candidates]
        return [
            manifest.candidate(score=score, reason=reason)
            for _name, (score, reason, manifest) in ranked
        ]
