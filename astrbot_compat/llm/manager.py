# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""ProviderManager：持有 Stella 的唯一 provider（对齐上游的多 provider 形状）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .provider import Provider, StellaChatProvider
from .tool import llm_tools

logger = logging.getLogger("astrbot_compat.llm.manager")

# Stella 只有一个模型后端，固定用这个 id
STELLA_PROVIDER_ID = "stella"


@dataclass(frozen=True)
class ModelAvailability:
    """A role-scoped availability snapshot.

    Embeddings intentionally have their own state: disabling generation must not
    make rule/embedding capability routing disappear.
    """

    role: str
    available: bool
    reason: str
    kind: str = "generation"


class ProviderManager:
    """上游的 ProviderManager 支持多实例，Stella 只有一个，形状保留即可。"""

    def __init__(self) -> None:
        self._provider: Provider | None = None
        self.llm_tools = llm_tools
        self.stt_provider_insts: list = []
        self.tts_provider_insts: list = []
        self.embedding_provider_insts: list = []
        self.rerank_provider_insts: list = []

    def _enabled(self) -> bool:
        # 必须读 config.settings 的属性而不是 `from config import X`：
        # config/__init__.py 是 `from .settings import *`，名字在 import 时就绑死了，
        # 测试里 monkeypatch config.settings.X 改不动 config.X。
        try:
            from config import settings

            return settings.ASTRBOT_LLM_ENABLED
        except Exception:
            return True

    def availability(self, role: str = "plugin") -> ModelAvailability:
        """Return a cheap, side-effect-free availability diagnosis."""
        normalized = (role or "plugin").strip().lower()
        if normalized == "embedding":
            try:
                from config import settings

                enabled = bool(settings.MEMORY_EMBEDDING_ENABLED)
                base_url = str(settings.MEMORY_EMBEDDING_BASE_URL or "").strip()
                model = str(settings.MEMORY_EMBEDDING_MODEL or "").strip()
            except Exception as exc:
                return ModelAvailability(
                    normalized,
                    False,
                    f"embedding 配置不可读: {exc}",
                    kind="embedding",
                )
            if not enabled:
                return ModelAvailability(normalized, False, "embedding 未启用", kind="embedding")
            if not base_url or not model:
                return ModelAvailability(
                    normalized,
                    False,
                    "embedding 缺少服务地址或模型名",
                    kind="embedding",
                )
            return ModelAvailability(normalized, True, "embedding 配置可用", kind="embedding")

        if not self._enabled():
            return ModelAvailability(normalized, False, "生成模型未启用")
        return ModelAvailability(normalized, True, "生成模型已启用")

    @property
    def provider(self) -> Provider | None:
        if not self._enabled():
            return None
        if self._provider is None:
            self._provider = StellaChatProvider()
        return self._provider

    @property
    def provider_insts(self) -> list[Provider]:
        p = self.provider
        return [p] if p is not None else []

    @property
    def inst_map(self) -> dict[str, Provider]:
        p = self.provider
        return {STELLA_PROVIDER_ID: p} if p is not None else {}

    @property
    def curr_provider_inst(self) -> Provider | None:
        return self.provider

    async def get_provider_by_id(self, provider_id: str) -> Provider | None:
        _ = provider_id
        return self.provider

    def reset(self) -> None:
        """丢弃缓存的 provider，下次访问按当前配置重建（测试用）。"""
        self._provider = None


_manager: ProviderManager | None = None


def get_provider_manager() -> ProviderManager:
    global _manager
    if _manager is None:
        _manager = ProviderManager()
    return _manager


def reset_provider_manager() -> None:
    """仅供单测：清掉单例，避免用例之间共享 provider 配置。"""
    global _manager
    _manager = None


__all__ = [
    "ModelAvailability",
    "STELLA_PROVIDER_ID",
    "ProviderManager",
    "get_provider_manager",
    "reset_provider_manager",
]
