# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Stella 版 Context（兼容 AstrBot 插件 API）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .exceptions import StellaCompatNotSupported

_MODEL_DEPENDENT_PLUGINS: set[str] = set()
logger = logging.getLogger("astrbot_compat.context")


class Context:
    """AstrBot 插件上下文（Stella 兼容实现）。"""

    def __init__(self) -> None:
        self._config: dict = {}
        self._registered_web_apis: list = []
        self.provider_manager = None
        self.platform_manager = None

    # --- 必须真实实现的方法 ---

    def get_registered_star(self, star_name: str) -> Any | None:
        from .registry import star_registry

        for md in star_registry:
            if not md.activated:
                continue
            if md.name == star_name:
                return md
        return None

    def get_all_stars(self) -> list[Any]:
        from .registry import star_registry

        return [md for md in star_registry if md.activated]

    def get_config(self) -> dict:
        return self._config

    def get_db(self) -> Any:
        raise StellaCompatNotSupported("Context.get_db")

    def get_event_queue(self) -> Any:
        raise StellaCompatNotSupported("Context.get_event_queue")

    def register_commands(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        logger.debug("[astrbot_compat] Context.register_commands 已废弃，仅作兼容")

    def register_provider(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        logger.warning("[astrbot_compat] Context.register_provider 暂不支持，仅作兼容")

    def register_platform_adapter(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        logger.warning("[astrbot_compat] Context.register_platform_adapter 暂不支持，仅作兼容")

    def activate_llm_tool(self, name: str) -> bool:  # noqa: ARG002
        logger.debug(f"[astrbot_compat] Context.activate_llm_tool({name}) -> False")
        return False

    def deactivate_llm_tool(self, name: str) -> bool:  # noqa: ARG002
        logger.debug(f"[astrbot_compat] Context.deactivate_llm_tool({name}) -> False")
        return False

    async def activate_llm_tool_async(self, name: str) -> bool:  # noqa: ARG002
        logger.debug(f"[astrbot_compat] Context.activate_llm_tool_async({name}) -> False")
        return False

    async def deactivate_llm_tool_async(self, name: str) -> bool:  # noqa: ARG002
        logger.debug(f"[astrbot_compat] Context.deactivate_llm_tool_async({name}) -> False")
        return False

    async def send_message(self, session: str, message_chain: Any) -> bool:  # noqa: ARG002
        logger.warning("[astrbot_compat] Context.send_message 尚未接入 OneBot，返回 False")
        # TODO(step3): 接入 OneBot 发送
        return False


# LLM 相关：必须存在但不实现（用循环批量挂，避免闭包坑）
_LLM_METHODS = (
    "llm_generate",
    "tool_loop_agent",
    "get_using_provider",
    "get_using_provider_async",
    "get_all_providers",
    "get_provider_by_id",
    "get_using_tts_provider",
    "get_using_stt_provider",
    "get_llm_tool_manager",
)

# 注意：_LLM_PROPS 用 property 实现，hasattr(ctx, "conversation_manager") 会因
# property getter 抛 StellaCompatNotSupported 而被 hasattr 捕获返回 False（优雅降级），
# 而直接访问 ctx.conversation_manager 则会抛 StellaCompatNotSupported（可被分流处理）。
_LLM_PROPS = (
    "persona_manager",
    "conversation_manager",
    "kb_manager",
    "subagent_orchestrator",
    "knowledge_db_manager",
)


def _make_unsupported(api: str) -> Any:
    def _m(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported(api)

    _m.__name__ = api.rsplit(".", 1)[-1]
    return _m


for _name in _LLM_METHODS:
    setattr(Context, _name, _make_unsupported(f"Context.{_name}"))


def _make_unsupported_prop(api: str) -> property:
    def _get(self: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported(api)

    return property(_get)


for _pname in _LLM_PROPS:
    setattr(Context, _pname, _make_unsupported_prop(f"Context.{_pname}"))


_context_singleton: Context | None = None


def get_context() -> Context:
    global _context_singleton
    if _context_singleton is None:
        _context_singleton = Context()
    return _context_singleton
