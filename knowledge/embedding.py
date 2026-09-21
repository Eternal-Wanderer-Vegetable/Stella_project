# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""知识库的向量编码服务（dense 通道的写入侧与查询侧）。

复用 ``memory.embeddings.EmbeddingService``（同一个本地 embedding 实例、
同一把资源闸门、同一套降级语义），只在上面加两层知识库特有的事：

1. **指纹**（plan §6.4）：model / dim / encoder / index_version 四元组。
   库在首次收到向量时锁定指纹（service 层落库）；此后配置里的指纹若与库的
   锁定不一致，dense 通道对该库整体停用并标 ``needs_rebuild``——半新半旧的
   向量空间里做余弦，排序结果是垃圾，宁可降级成纯 BM25。
2. **批量编码回调**：ingest 侧 ``embed_batch``（一次切块 → 一次 BLOB 列表），
   与查询侧 ``embed_query`` 走同一个服务实例。

编码约定与记忆系统一致（裸文本、不加指令前缀；LM Studio 返回已归一化向量，
点积即余弦，``cosine_similarity`` 仍带除模兜底）。
"""

from __future__ import annotations

from typing import Any

from nonebot import logger

from knowledge.store import pack_vector

# 编码约定版本：裸文本编码（与 memory/embeddings 的实测结论一致）。
# 改约定（加前缀、换归一化）必须递增此版本——所有既有向量随之作废。
ENCODER_VERSION = "raw-v1"

# 向量存储格式版本：float32 小端数组（knowledge.store.pack_vector）。
# 改存储格式必须递增此版本并全量重建。
INDEX_VERSION = 1


def _settings() -> Any:
    from config import settings

    return settings


def _embedding_service():
    from memory.embeddings import EmbeddingService

    return EmbeddingService


def resolve_embedding_profile() -> dict[str, Any]:
    """当前配置解析出的 embedding 指纹（服务地址留空 = 继承记忆系统的）。"""
    s = _settings()
    base_url = (getattr(s, "KNOWLEDGE_EMBEDDING_BASE_URL", "") or "").strip()
    model = (getattr(s, "KNOWLEDGE_EMBEDDING_MODEL", "") or "").strip()
    if not base_url or not model:
        base_url = base_url or getattr(s, "MEMORY_EMBEDDING_BASE_URL", "")
        model = model or getattr(s, "MEMORY_EMBEDDING_MODEL", "")
    from memory.embeddings import EMBEDDING_DIM

    return {
        "base_url": base_url,
        "model": model,
        "dim": EMBEDDING_DIM,
        "encoder": ENCODER_VERSION,
        "index_version": INDEX_VERSION,
    }


def fingerprint_matches(kb_profile: dict[str, Any], current: dict[str, Any]) -> bool:
    """库的锁定指纹与当前配置是否一致（base_url 不参与：换地址不换模型不用重建）。"""
    return all(
        kb_profile.get(key) == current.get(key)
        for key in ("model", "dim", "encoder", "index_version")
    )


class KBEmbedder:
    """知识库向量编码器。``available`` 为 False 时一切调用返回空。"""

    def __init__(self):
        self.profile = resolve_embedding_profile()

    @property
    def available(self) -> bool:
        """模型未配置时 dense 通道整体不可用（BM25 仍可用）。"""
        return bool(self.profile["model"])

    def _service(self):
        embedding_service = _embedding_service()
        return embedding_service(
            base_url=self.profile["base_url"],
            model=self.profile["model"],
            dim=self.profile["dim"],
        )

    async def embed_query(self, text: str) -> list[float] | None:
        """查询向量；服务不可用返回 None（检索侧降级 BM25）。"""
        if not self.available:
            return None
        try:
            return await self._service().embed(text)
        except Exception as e:
            logger.warning(f"🧭 [Knowledge] 查询编码失败（dense 降级）: {e}")
            return None

    async def embed_batch(self, texts: list[str]) -> list[bytes | None]:
        """切块文本批量编码 → BLOB 列表（失败的块为 None，ingest 记数）。"""
        if not self.available:
            return [None] * len(texts)
        service = self._service()
        blobs: list[bytes | None] = []
        for text in texts:
            try:
                vec = await service.embed(text)
            except Exception:
                vec = None
            blobs.append(pack_vector(vec) if vec else None)
        return blobs

    def embed_batch_sync(self, texts: list[str]) -> list[bytes | None]:
        """``embed_batch`` 的同步形态——ingest 在工作线程里跑（导入在回复路径
        之外），线程内没有事件循环，这里负责把协程跑完。

        若调用线程本身在事件循环里（管理入口直接在 async 处理器中触发导入的
        场景），退到独立线程执行，避免嵌套循环冲突。
        """
        if not texts:
            return []
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.embed_batch(texts))
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, self.embed_batch(texts)).result()


__all__ = [
    "ENCODER_VERSION",
    "INDEX_VERSION",
    "KBEmbedder",
    "fingerprint_matches",
    "resolve_embedding_profile",
]
