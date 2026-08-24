# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Level 1：Embedding 语义路由（方案第 8 节）。

```
User Message → Embedding → Capability Prototype Matching → Capability Scores
```

复用 ``memory/embeddings.py`` 的 ``EmbeddingService``：它已经具备缓存
（``model:dim:sha256``）、L2 归一化、经 chat 闸门串行、以及**任何一步失败都返回
None 让调用方降级**的契约。这里不另建客户端。

**原型向量 = 该能力全部 prototype_texts 编码后的均值（再归一化）**。
取均值而不是逐条取最大：examples 是同一意图的不同说法，均值代表这个意图的中心，
对个别写得不好的 example 更稳健；逐条取最大会让一条跑偏的 example 把整个能力
的召回拉歪。

原型向量按注册表版本号缓存。装了新插件（注册表变更 → version 自增）时缓存自动失效，
否则新能力永远匹配不上——这个退化不报错，只是「插件装了但用不了」。
"""

from __future__ import annotations

import math
from typing import Any

from capability.registry import CapabilityRegistry
from capability.registry import registry as _default_registry
from capability.router.types import LEVEL_SEMANTIC, CapabilityHit, Route

# 原型向量缓存：{capability_id: 归一化后的均值向量}，与 _cached_version 配对使用
_prototype_cache: dict[str, list[float]] = {}
_cached_version: int | None = None
_cached_model: str = ""


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``。

    ``config/__init__.py`` 是 ``from .settings import *``，名字在 import 时就绑死了，
    测试里 monkeypatch ``config.settings.X`` 改不动 ``config.X``（见
    astrbot_compat/llm/manager.py 的同款注释）。
    """
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


def _mean_vector(vectors: list[list[float]]) -> list[float] | None:
    """求均值并 L2 归一化。维度不一致的向量直接丢弃（换过模型的脏缓存）。"""
    usable = [v for v in vectors if v]
    if not usable:
        return None
    dim = len(usable[0])
    usable = [v for v in usable if len(v) == dim]
    if not usable:
        return None
    total = [0.0] * dim
    for vec in usable:
        for i, value in enumerate(vec):
            total[i] += value
    mean = [value / len(usable) for value in total]
    norm = math.sqrt(sum(v * v for v in mean))
    if norm == 0.0:
        return None
    return [v / norm for v in mean]


def reset_prototype_cache() -> None:
    """清空原型缓存（测试与热重载用）。"""
    global _cached_version, _cached_model
    _prototype_cache.clear()
    _cached_version = None
    _cached_model = ""


def _get_service():
    """构造 EmbeddingService。复用 MEMORY_EMBEDDING_* 配置——同一个本地 embedding 实例。"""
    from memory.embeddings import EmbeddingService

    s = _settings()
    return EmbeddingService(
        base_url=s.MEMORY_EMBEDDING_BASE_URL,
        model=s.MEMORY_EMBEDDING_MODEL,
        timeout=s.MEMORY_EMBEDDING_TIMEOUT,
    )


async def build_prototypes(
    target: CapabilityRegistry | None = None,
    service=None,
) -> dict[str, list[float]]:
    """构建（或复用缓存的）各能力原型向量。

    编码失败的能力**不进结果**——它只是这一次匹配不上，不该把整个路由拖垮。
    """
    global _cached_version, _cached_model
    reg = target if target is not None else _default_registry
    svc = service if service is not None else _get_service()
    model = getattr(svc, "model", "") or ""

    # 注册表未变且模型未换 → 直接复用
    if _cached_version == reg.version and _cached_model == model and _prototype_cache:
        return _prototype_cache

    prototypes: dict[str, list[float]] = {}
    for capability in reg.routable():
        vectors: list[list[float]] = []
        for text in capability.prototype_texts():
            vec = await svc.embed(text)
            if vec:
                vectors.append(vec)
        proto = _mean_vector(vectors)
        if proto is not None:
            prototypes[capability.id] = proto

    _prototype_cache.clear()
    _prototype_cache.update(prototypes)
    _cached_version = reg.version
    _cached_model = model
    return _prototype_cache


async def score_capabilities(
    message: str,
    target: CapabilityRegistry | None = None,
    service=None,
) -> list[CapabilityHit] | None:
    """给每个能力打分（余弦相似度），按分数降序返回。

    返回 None 表示**语义层不可用**（消息编码失败 / 没有任何可用原型），
    与「打了分但都很低」（返回空列表或低分列表）是两种不同情形：
    前者要降级，后者是有效结论「不需要工具」。
    """
    from memory.embeddings import cosine_similarity

    text = (message or "").strip()
    if not text:
        return None

    reg = target if target is not None else _default_registry
    if not reg.routable():
        return None

    svc = service if service is not None else _get_service()
    prototypes = await build_prototypes(reg, svc)
    if not prototypes:
        return None

    query = await svc.embed(text)
    if not query:
        return None

    hits = [
        CapabilityHit(capability_id=cid, score=cosine_similarity(query, proto))
        for cid, proto in prototypes.items()
    ]
    # 同分时按 id 排序，保证结果确定（便于测试与 benchmark 比对）
    hits.sort(key=lambda h: (-h.score, h.capability_id))
    return hits


async def route_semantic(
    message: str,
    *,
    target: CapabilityRegistry | None = None,
    service=None,
    memory: bool = True,
) -> Route | None:
    """Level 1 判定。返回 None 表示语义层不可用，应交给 Level 2 / 降级。

    参数:
        memory: Level 0 传下来的记忆判定。语义层不改它——是否需要读记忆由规则与
            默认值决定，embedding 相似度衡量的是「像不像某个工具能力」，
            对「要不要回忆」没有区分力。
    """
    s = _settings()
    hits = await score_capabilities(message, target, service)
    if hits is None:
        return None

    top = hits[0].score if hits else 0.0

    # 最高分没过 tool 置信线 → 这是一个有效结论：不需要工具。
    # 是否进 Level 2 由级联层按 ROUTER_UNCERTAIN_FLOOR 决定，这里只如实报告。
    if top < s.ROUTER_TOOL_THRESHOLD:
        return Route(
            chat=True,
            memory=memory,
            tool=False,
            capabilities=[h for h in hits if h.score >= s.ROUTER_SEMANTIC_THRESHOLD],
            top_score=top,
            level=LEVEL_SEMANTIC,
            reason=f"最高分 {top:.2f} 未达工具置信线 {s.ROUTER_TOOL_THRESHOLD:.2f}",
        )

    selected = [h for h in hits if h.score >= s.ROUTER_SEMANTIC_THRESHOLD][
        : max(s.ROUTER_MAX_CAPABILITIES, 1)
    ]
    return Route(
        chat=True,
        memory=memory,
        tool=True,
        capabilities=selected,
        top_score=top,
        level=LEVEL_SEMANTIC,
        reason=f"语义命中 {[repr(h) for h in selected]}",
    )


__all__ = [
    "build_prototypes",
    "reset_prototype_cache",
    "route_semantic",
    "score_capabilities",
]
