# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""记忆语义检索（可选，Embedding）。

通过本地 LM Studio 的 OpenAI 兼容 ``/v1/embeddings`` 接口，把查询与记忆内容编码为
向量并计算余弦相似度，取代 ``memory.policy._semantic_similarity`` 的词面 Jaccard
占位——短中文文本上词面几乎不命中，导致排序缺乏区分力。

编码约定（依据实测，见 scripts/build_embedding_fixture.py 的注释）：
1. **query 与 content 一律裸文本编码，不加 ``Instruct:`` 前缀**。实测 22 个用例，
   不加前缀正/噪音余弦中位差 0.124，优于加前缀的 0.110；最差间隔 −0.109 也优于
   −0.145。Qwen3 官方建议的指令前缀在此场景（短中文群聊检索）不带来收益。
2. **维度固定 1024，不做 MRL 降维**。LM Studio 忽略 ``dimensions`` 参数，且降维
   只省约 20MB 磁盘，不值得。
3. LM Studio 返回的向量已归一化（L2 范数 1.0000），故点积即余弦；但 cosine 实现
   仍保留“除模长”兜底，避免上游改变行为时产生零分错误。

设计原则：
1. **可降级**：任何一步失败（服务不可用 / 无 embedding 模型 / 解析异常）都返回
   ``None``，调用方回退到规则版语义分，绝不让语义检索成为主链路的硬依赖；
2. **缓存**：key 含模型名、维度与文本哈希，避免不同模型/维度互相污染；
3. **纯向量工具与网络分离**：cosine / 归一化是纯函数，可离线单测；
   EmbeddingService 才持有 httpx 客户端与缓存；
4. **与主聊天共享闸门**：默认与主聊天同一 LM Studio 实例，而一次检索要编码
   20+ 条文本（query + 每条候选）；LM Studio 不限并发，不串行会出现间歇性
   变慢且难以定位，因此每次编码经 ``_maybe_gate()`` 走 chat 闸门（tag="embed"）。
   批量编码（``input`` 支持数组，一次请求只抢一次锁）是将来的优化方向。
"""

from __future__ import annotations

import hashlib
import math
from contextlib import asynccontextmanager
from typing import Any

import httpx
from nonebot import logger

# 文本 → 向量 的进程内缓存（键为 “model:dim:sha256(text)”，值为 float 列表或 None）
_CACHE: dict[str, list[float] | None] = {}

# 固定编码维度（LM Studio 下 Qwen3-Embedding 输出 1024，不做 MRL 降维）
EMBEDDING_DIM = 1024


def _cache_key(model: str, dim: int, text: str) -> str:
    """缓存键：模型 + 维度 + 文本哈希，避免跨模型/维度复用错误向量。"""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{model or ''}:{dim}:{digest}"


def normalize(vec: list[float]) -> list[float]:
    """L2 归一化向量；空/全零向量返回原样（避免除零）。"""
    norm = math.sqrt(sum(v * v for v in vec))
    if not vec or norm == 0.0:
        return vec
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度（自动按内部做点积，需维度一致）。

    LM Studio 返回的向量已归一化，此时点积即余弦；这里仍除模长兜底，
    保证上游返回未归一化向量时结果也正确。
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


@asynccontextmanager
async def _maybe_gate():
    """embedding 与某个 chat 端点共用同一 LM Studio 实例时，走那个端点的闸门串行化。

    资源名由 ``MEMORY_EMBEDDING_GATE`` 解析（``auto`` = 找地址相同的本地槽、
    ``<槽名>`` = 指定槽、``none`` = 不排队）；解析结果为空串即不排队，
    例如独立的 embedding 实例。R2 要求 embedding 恒定本地，因此这里永远
    不会排到在线端点上。

    config 与 core.llm 都在函数内延迟 import，保持纯向量工具
    （cosine / normalize）可离线单测。
    """
    from core.llm import acquire, embedding_gate

    resource = embedding_gate()
    if not resource:
        yield
        return
    async with acquire(resource, tag="embed"):
        yield


class EmbeddingService:
    """调用 LM Studio /v1/embeddings 的语义编码服务（带缓存与降级）。"""

    def __init__(
        self,
        base_url: str,
        model: str = "",
        timeout: float = 10.0,
        dim: int = EMBEDDING_DIM,
        cache: dict[str, list[float] | None] | None = None,
    ):
        """参数:
            base_url: LM Studio 服务地址，如 http://127.0.0.1:1234；
            model: 嵌入模型 ID；留空则由服务端默认路由；
            timeout: 单次编码请求超时；
            dim: 预期编码维度（仅用于缓存键，不发给服务端——LM Studio 忽略 dimensions）；
            cache: 可注入的缓存（测试用），缺省用模块级 _CACHE。
        """
        self.api_url = f"{base_url.rstrip('/')}/v1/embeddings"
        self.model = model or ""
        self.timeout = timeout
        self.dim = dim
        self._cache = cache if cache is not None else _CACHE

    async def embed(self, text: str) -> list[float] | None:
        """把一段文本编码为向量；失败返回 None（调用方自行降级）。"""
        text = (text or "").strip()
        if not text:
            return None
        key = _cache_key(self.model, self.dim, text)
        if key in self._cache:
            return self._cache[key]

        payload: dict[str, Any] = {"input": text}
        if self.model:
            payload["model"] = self.model
        try:
            # 网络请求在闸门内（少占锁），向量解析移到闸门外（少占锁时间）
            async with (
                _maybe_gate(),
                httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), trust_env=False) as client,
            ):
                resp = await client.post(self.api_url, json=payload)
                resp.raise_for_status()
                data = resp.json()
            vector = data["data"][0]["embedding"]
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding 返回为空")
            vector = [float(v) for v in vector]
        except Exception as e:
            logger.warning(f"[Embedding] 编码失败（{text[:20]}…）: {e}")
            self._cache[key] = None
            return None

        self._cache[key] = vector
        return vector

    async def similarity(self, query: str, content: str) -> float | None:
        """查询与记忆内容的余弦相似度；任一侧编码失败返回 None。"""
        q = await self.embed(query)
        c = await self.embed(content)
        if q is None or c is None:
            return None
        return cosine_similarity(q, c)

    def clear(self) -> None:
        """清空进程内缓存（测试/热重载用）。"""
        self._cache.clear()
