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

**缓存是逐条落盘的**（每算完一个能力就写进去），不是整轮算完才写。写声明文件之后
原型语料从「每个能力 1 句工具描述」变成「每个能力 4~6 句 examples + 描述」，
首次构建的编码次数涨了约 5 倍；而这次构建就发生在某个用户的请求里、外面套着
``ROUTER_TIMEOUT``。整轮写的话一旦超时就一条都不留，下一条消息从零重来，
表现为「工具连续好几轮都不触发」且不报错。逐条写让进度能跨请求累积。
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from capability.registry import CapabilityRegistry
from capability.registry import registry as _default_registry
from capability.router.types import LEVEL_SEMANTIC, CapabilityHit, Route

# 原型向量缓存：{capability_id: 归一化后的均值向量}，与 _cached_version 配对使用。
# _cached_complete 区分「这一版全算完了」与「算了一部分」——后者要接着算，
# 不能当成结论直接用（会让还没算到的能力永远匹配不上）。
_prototype_cache: dict[str, list[float]] = {}
_cached_version: int | None = None
_cached_model: str = ""
_cached_complete: bool = False

# 启动期预热的时间预算（秒）。预热在后台跑，超时只是少算几个原型（已算的会留下），
# 不影响启动，也不影响首条消息——那时会接着算完。
WARMUP_TIMEOUT = 120.0


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
    global _cached_version, _cached_model, _cached_complete
    _prototype_cache.clear()
    _cached_version = None
    _cached_model = ""
    _cached_complete = False


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

    **逐条写缓存**：每算完一个能力立刻落进 ``_prototype_cache``，所以被
    ``ROUTER_TIMEOUT`` 取消时进度不丢，下一次调用接着算没算完的（理由见模块 docstring）。

    编码失败的能力不进结果，且把本版标记为「未算完」——下次会重试。
    （``EmbeddingService`` 对失败的文本也有缓存，所以重试不会反复打网络。）
    """
    global _cached_version, _cached_model, _cached_complete
    reg = target if target is not None else _default_registry
    svc = service if service is not None else _get_service()
    model = getattr(svc, "model", "") or ""

    # 注册表变更或换了模型 → 整批作废重算
    if _cached_version != reg.version or _cached_model != model:
        _prototype_cache.clear()
        _cached_version = reg.version
        _cached_model = model
        _cached_complete = False

    if _cached_complete:
        return _prototype_cache

    complete = True
    for capability in reg.routable():
        if capability.id in _prototype_cache:
            continue
        vectors: list[list[float]] = []
        for text in capability.prototype_texts():
            vec = await svc.embed(text)
            if vec:
                vectors.append(vec)
        proto = _mean_vector(vectors)
        if proto is None:
            # 这一个这次没算出来（服务不可用/维度不一致），保持「未算完」下次再试
            complete = False
            continue
        _prototype_cache[capability.id] = proto
    _cached_complete = complete
    return _prototype_cache


async def warmup(
    target: CapabilityRegistry | None = None,
    service=None,
    timeout: float | None = None,
) -> int:
    """启动期预热原型向量，返回已缓存的原型数。**绝不抛异常。**

    把首次构建的编码开销从「某个用户的第一条消息」挪到启动期。不预热的话那条消息
    要多等好几秒，而且构建外面套着 ``ROUTER_TIMEOUT``，能力越多越可能超时降级。

    超时/失败都只是少算几个（已算的留在缓存里），首条消息会接着算完。
    """
    budget = WARMUP_TIMEOUT if timeout is None else timeout
    try:
        await asyncio.wait_for(build_prototypes(target, service), timeout=budget)
    # 必须写 asyncio.TimeoutError：Python 3.10 下它与内置 TimeoutError 是两个
    # 不相干的类（3.11 起才合并），写内置的会在 3.10 上漏接。
    except asyncio.TimeoutError:
        _logger().warning(
            f"⚠️ [Router] 原型预热超时（{budget:.0f}s），已算好 {len(_prototype_cache)} 个，"
            f"其余留给首次请求补齐",
        )
    except Exception as e:
        _logger().warning(f"⚠️ [Router] 原型预热失败（不影响启动）: {e}")
    return len(_prototype_cache)


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


def select_hits(hits: list[CapabilityHit], settings: Any) -> list[CapabilityHit]:
    """从打分结果里挑出**真的要执行**的能力。

    两道筛子，顺序无所谓，作用完全不同：

    - ``ROUTER_SEMANTIC_THRESHOLD``（绝对地板）：压掉长尾噪声；
    - ``ROUTER_CAPABILITY_MARGIN``（相对间距）：只保留与最高分差距在容忍范围内的。

    **相对间距是必需的，绝对地板替代不了它。** 2026-08-24 首轮实测里，
    「帮我推荐一些新番」的正确能力得 0.911，而搭车的每日放送/B 站热门得 0.689/0.678——
    搭车分数高于任何一个可用的地板值（地板必须低于正样本下界才不误杀）。
    而每个命中能力都会**各自执行一次**并把结果贴上「真实数据」送进 Stella 的 prompt，
    所以搭车不是浪费一点延迟，是往证据段里塞无关数据。

    间距筛完仍可能剩多个——那是真正的多能力请求（「记得我的旅行计划吗，帮我查东京天气」
    这类两个意图都强的句子），本来就该都执行，最后由 ``ROUTER_MAX_CAPABILITIES`` 兜底封顶。
    """
    if not hits:
        return []
    floor = settings.ROUTER_SEMANTIC_THRESHOLD
    margin = settings.ROUTER_CAPABILITY_MARGIN
    if margin > 0:
        floor = max(floor, hits[0].score - margin)
    selected = [h for h in hits if h.score >= floor]
    return selected[: max(settings.ROUTER_MAX_CAPABILITIES, 1)]


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
            # 不执行时列表纯粹是诊断用（「差多少才会调工具」），所以只过绝对地板、
            # 不做间距裁剪——裁掉了反而看不出第二三名离得有多近。
            capabilities=[h for h in hits if h.score >= s.ROUTER_SEMANTIC_THRESHOLD],
            top_score=top,
            level=LEVEL_SEMANTIC,
            reason=f"最高分 {top:.2f} 未达工具置信线 {s.ROUTER_TOOL_THRESHOLD:.2f}",
        )

    selected = select_hits(hits, s)
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
    "WARMUP_TIMEOUT",
    "build_prototypes",
    "reset_prototype_cache",
    "route_semantic",
    "score_capabilities",
    "select_hits",
    "warmup",
]
