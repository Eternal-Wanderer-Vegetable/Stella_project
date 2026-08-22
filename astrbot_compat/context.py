# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Stella 版 Context（兼容 AstrBot 插件 API）。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .exceptions import StellaCompatNotSupported, StellaCompatUnsupportedAttribute

_MODEL_DEPENDENT_PLUGINS: set[str] = set()
logger = logging.getLogger("astrbot_compat.context")


class Context:
    """AstrBot 插件上下文（Stella 兼容实现）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        self._config: dict = {}
        self._registered_web_apis: list = []
        self._tasks: list[asyncio.Task] = []
        self.provider_manager = None
        self.platform_manager = None

    # --- 插件注册表 ---

    def get_registered_star(self, star_name: str) -> Any | None:
        from .registry import star_registry

        for md in star_registry:
            if md.activated and md.name == star_name:
                return md
        return None

    def get_all_stars(self) -> list[Any]:
        from .registry import star_registry

        return [md for md in star_registry if md.activated]

    def get_config(self, umo: str | None = None) -> dict:
        _ = umo
        return self._config

    # --- 平台能力 ---

    async def send_message(self, session: Any, message_chain: Any) -> bool:
        """按 `platform:MessageType:id` 主动发消息。"""
        try:
            target_type, target_id = self._parse_session(str(session))
            lst = self._normalize(message_chain)
            bot = self._get_bot()
            if bot is None:
                logger.error("[astrbot_compat] Context.send_message 无可用 Bot")
                return False
            return await self._deliver(bot, target_type, target_id, lst)
        except Exception as e:
            logger.error(f"[astrbot_compat] Context.send_message 失败: {e}", exc_info=True)
            return False

    @staticmethod
    def _parse_session(session: str) -> tuple[str, str]:
        parts = session.split(":")
        if len(parts) >= 3:
            return parts[1], parts[-1]
        return "GroupMessage", session

    @staticmethod
    def _normalize(message_chain: Any) -> list:
        from .components import BaseMessageComponent
        from .events import MessageChain

        if isinstance(message_chain, MessageChain):
            return list(message_chain.chain)
        if isinstance(message_chain, list):
            return list(message_chain)
        if isinstance(message_chain, BaseMessageComponent):
            return [message_chain]
        if isinstance(message_chain, str):
            return [message_chain]
        return [str(message_chain)]

    @staticmethod
    def _get_bot() -> Any:
        from nonebot import get_bot, get_bots

        try:
            return get_bot()
        except Exception:
            bots = get_bots()
            return next(iter(bots.values())) if bots else None

    @staticmethod
    async def _deliver(bot: Any, target_type: str, target_id: str, lst: list) -> bool:
        from .components import split_forward_nodes, to_onebot_message

        is_group = target_type != "FriendMessage"
        forwards, rest = split_forward_nodes(lst)
        sent = False
        for nodes in forwards:
            payload = await nodes.to_dict()
            if is_group:
                payload["group_id"] = int(target_id)
                await bot.call_action("send_group_forward_msg", **payload)
            else:
                payload["user_id"] = int(target_id)
                await bot.call_action("send_private_forward_msg", **payload)
            sent = True
        if rest:
            msg = to_onebot_message(rest)
            if msg:
                if is_group:
                    await bot.send_group_msg(group_id=int(target_id), message=msg)
                else:
                    await bot.send_private_msg(user_id=int(target_id), message=msg)
                sent = True
        if not sent:
            logger.debug("[astrbot_compat] Context.send_message 空消息跳过")
        return sent

    def get_platform(self, platform_type: Any) -> Any | None:
        _ = platform_type
        logger.debug("[astrbot_compat] Context.get_platform 暂不支持，返回 None")
        return None

    def get_platform_inst(self, platform_id: str) -> Any | None:
        _ = platform_id
        logger.debug("[astrbot_compat] Context.get_platform_inst 暂不支持，返回 None")
        return None

    def register_task(self, task: Any, desc: str = "") -> None:
        """登记一个后台任务，进程退出时统一取消。"""
        try:
            t = asyncio.ensure_future(task)
        except (TypeError, RuntimeError) as e:
            logger.warning(f"[astrbot_compat] register_task({desc}) 失败: {e}")
            return
        self._tasks.append(t)
        t.add_done_callback(lambda fut: self._tasks.remove(fut) if fut in self._tasks else None)

    def cancel_tasks(self) -> None:
        for t in list(self._tasks):
            if not t.done():
                t.cancel()
        self._tasks.clear()

    # --- 兼容占位 ---

    def register_commands(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        logger.debug("[astrbot_compat] Context.register_commands 已废弃，仅作兼容")

    def register_provider(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        logger.warning("[astrbot_compat] Context.register_provider 暂不支持，仅作兼容")

    def register_platform_adapter(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        logger.warning("[astrbot_compat] Context.register_platform_adapter 暂不支持，仅作兼容")

    def register_web_api(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        logger.warning("[astrbot_compat] Context.register_web_api 暂不支持，仅作兼容")

    def activate_llm_tool(self, name: str) -> bool:
        logger.debug(f"[astrbot_compat] Context.activate_llm_tool({name}) -> False")
        return False

    def deactivate_llm_tool(self, name: str) -> bool:
        logger.debug(f"[astrbot_compat] Context.deactivate_llm_tool({name}) -> False")
        return False

    async def activate_llm_tool_async(self, name: str) -> bool:
        return self.activate_llm_tool(name)

    async def deactivate_llm_tool_async(self, name: str) -> bool:
        return self.deactivate_llm_tool(name)

    def get_db(self) -> Any:
        raise StellaCompatNotSupported("Context.get_db")

    def get_event_queue(self) -> Any:
        raise StellaCompatNotSupported("Context.get_event_queue")


# LLM 相关：必须存在但不实现（用循环批量挂，避免闭包坑）
_LLM_METHODS = (
    "llm_generate",
    "tool_loop_agent",
    "get_current_chat_provider_id",
    "get_using_provider",
    "get_using_provider_async",
    "get_all_providers",
    "get_provider_by_id",
    "get_using_tts_provider",
    "get_using_tts_provider_async",
    "get_using_stt_provider",
    "get_using_stt_provider_async",
    "get_all_tts_providers",
    "get_all_stt_providers",
    "get_all_embedding_providers",
    "get_llm_tool_manager",
    "add_llm_tools",
    "register_llm_tool",
    "unregister_llm_tool",
)

# 注意：_LLM_PROPS 用 property 实现。hasattr() 只吞 AttributeError，所以这些 getter
# 抛的是 StellaCompatUnsupportedAttribute（同时是 StellaCompatNotSupported 和
# AttributeError）：hasattr(ctx, "conversation_manager") 返回 False（插件特性探测优雅
# 降级），而直接访问 ctx.conversation_manager 仍抛 StellaCompatNotSupported（可分流）。
_LLM_PROPS = (
    "persona_manager",
    "conversation_manager",
    "kb_manager",
    "subagent_orchestrator",
    "knowledge_db_manager",
)


def _make_unsupported(api: str) -> Any:
    def _m(self: Any, *args: Any, **kwargs: Any) -> Any:
        _ = (self, args, kwargs)
        raise StellaCompatNotSupported(api)

    _m.__name__ = api.rsplit(".", 1)[-1]
    return _m


def _make_unsupported_prop(api: str) -> property:
    def _get(self: Any) -> Any:
        _ = self
        raise StellaCompatUnsupportedAttribute(api)

    return property(_get)


for _name in _LLM_METHODS:
    setattr(Context, _name, _make_unsupported(f"Context.{_name}"))

for _pname in _LLM_PROPS:
    setattr(Context, _pname, _make_unsupported_prop(f"Context.{_pname}"))


_context_singleton: Context | None = None


def get_context() -> Context:
    global _context_singleton
    if _context_singleton is None:
        _context_singleton = Context()
    return _context_singleton
