# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Stella 版 Context（兼容 AstrBot 插件 API）。"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from .exceptions import StellaCompatNotSupported, StellaCompatUnsupportedAttribute

_MODEL_DEPENDENT_PLUGINS: set[str] = set()
logger = logging.getLogger("astrbot_compat.context")


def _caller_module(depth: int) -> str:
    """登记方所在的模块路径（`data.plugins.foo.main` 这种）。取不到时返回空串。

    热重载要能只取消**被重载的那个插件**起的后台任务，所以任务必须带归属；而
    ``register_task(task, desc)`` 的签名是上游 API，不能加参数让插件自己报家门
    （那样每个插件都得改代码，超集承诺就没了）。所以从调用栈上取——插件调用
    ``self.context.register_task(...)`` 时，上一帧的 ``__name__`` 就是插件模块。

    取不到只意味着这个任务归属未知：它照常被全量 ``cancel_tasks()`` 收走，
    只是不会被单插件重载收走。这是安全的降级方向（宁可漏取消也不错杀别人的任务）。
    """
    try:
        frame = sys._getframe(depth)
    except (ValueError, AttributeError):  # pragma: no cover - 非 CPython 或栈太浅
        return ""
    return str(frame.f_globals.get("__name__") or "")


def _owned_by(module: str, owner: str) -> bool:
    """``module`` 是否属于 ``owner`` 这个包。空 owner 表示「全部」。"""
    if not owner:
        return True
    return module == owner or module.startswith(f"{owner}.")


class Context:
    """AstrBot 插件上下文（Stella 兼容实现）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        self._config: dict = {}
        self._registered_web_apis: list = []
        # 任务 → 登记它的模块路径。归属标记只为热重载服务：卸载单个插件时要能只掐
        # 掉它自己的后台任务。dict 保序，遍历顺序与登记顺序一致。
        self._tasks: dict[asyncio.Task, str] = {}
        self._provider_manager_override = None
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
        """登记一个后台任务，进程退出时统一取消。

        插件**必须**走这里而不是裸 ``asyncio.create_task(...)``：只有登记过的任务在
        插件卸载与热重载时收得回，裸 task 会残留并继续跑（见 docs/plugin-spec.md §4，
        ``deploy plugin-check`` 第 ⑮ 项会扫这个写法）。
        """
        try:
            t = asyncio.ensure_future(task)
        except (TypeError, RuntimeError) as e:
            logger.warning(f"[astrbot_compat] register_task({desc}) 失败: {e}")
            return
        # depth=1 是本函数自己的帧，depth=2 才是调用方（插件）
        self._tasks[t] = _caller_module(2)
        t.add_done_callback(lambda fut: self._tasks.pop(fut, None))

    def cancel_tasks(self, owner: str = "") -> int:
        """取消已登记的后台任务，返回取消了几个。

        ``owner`` 为插件包路径（``data.plugins.foo``）时只取消该插件登记的任务，
        供热重载使用；缺省的空串表示全部，即进程退出时的老语义。
        """
        cancelled = 0
        for t, module in list(self._tasks.items()):
            if not _owned_by(module, owner):
                continue
            if not t.done():
                t.cancel()
                cancelled += 1
            self._tasks.pop(t, None)
        return cancelled

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
        from .llm.tool import llm_tools

        return llm_tools.activate_llm_tool(name)

    def deactivate_llm_tool(self, name: str) -> bool:
        from .llm.tool import llm_tools

        return llm_tools.deactivate_llm_tool(name)

    async def activate_llm_tool_async(self, name: str) -> bool:
        return self.activate_llm_tool(name)

    async def deactivate_llm_tool_async(self, name: str) -> bool:
        return self.deactivate_llm_tool(name)

    def get_db(self) -> Any:
        raise StellaCompatNotSupported("Context.get_db")

    def get_event_queue(self) -> Any:
        raise StellaCompatNotSupported("Context.get_event_queue")

    # --- LLM ---

    @property
    def provider_manager(self) -> Any:
        # 上游这是普通属性，插件（尤其是测试替身）会直接赋值覆盖，所以尊重覆盖值
        if self._provider_manager_override is not None:
            return self._provider_manager_override
        from .llm.manager import get_provider_manager

        return get_provider_manager()

    @provider_manager.setter
    def provider_manager(self, value: Any) -> None:
        self._provider_manager_override = value

    @property
    def conversation_manager(self) -> Any:
        from .conversation import get_conversation_manager

        return get_conversation_manager()

    @property
    def persona_manager(self) -> Any:
        from .persona import get_persona_manager

        return get_persona_manager()

    def get_llm_tool_manager(self) -> Any:
        from .llm.tool import llm_tools

        return llm_tools

    def get_provider_by_id(self, provider_id: str) -> Any:
        _ = provider_id
        return self.provider_manager.provider

    def get_all_providers(self) -> list[Any]:
        return self.provider_manager.provider_insts

    def get_all_tts_providers(self) -> list[Any]:
        return []

    def get_all_stt_providers(self) -> list[Any]:
        return []

    def get_all_embedding_providers(self) -> list[Any]:
        return []

    def get_using_provider(self, umo: str | None = None) -> Any:
        _ = umo
        return self.provider_manager.provider

    async def get_using_provider_async(self, umo: str | None = None) -> Any:
        return self.get_using_provider(umo)

    def get_using_tts_provider(self, umo: str | None = None) -> Any:
        _ = umo
        return None

    async def get_using_tts_provider_async(self, umo: str | None = None) -> Any:
        _ = umo
        return None

    def get_using_stt_provider(self, umo: str | None = None) -> Any:
        _ = umo
        return None

    async def get_using_stt_provider_async(self, umo: str | None = None) -> Any:
        _ = umo
        return None

    async def get_current_chat_provider_id(self, umo: str) -> str:
        provider = await self.get_using_provider_async(umo)
        if provider is None:
            raise StellaCompatNotSupported("Context.get_current_chat_provider_id（LLM 未启用）")
        return provider.meta().id

    def add_llm_tools(self, *tools: Any) -> None:
        """把插件自建的 FunctionTool 挂进全局工具表。"""
        from .llm.tool import llm_tools

        for tool in tools:
            if tool.handler_module_path is None:
                tool.handler_module_path = getattr(tool.handler, "__module__", None)
            if llm_tools.get_tool(tool.name) is not None:
                llm_tools.remove_tool(tool.name)
            llm_tools.add_tool(tool)
            logger.info(f"[astrbot_compat] 已注册函数工具 {tool.name}")

    async def llm_generate(
        self,
        *,
        chat_provider_id: str = "",
        prompt: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        tools: Any = None,
        system_prompt: str | None = None,
        contexts: list | None = None,
        **kwargs: Any,
    ) -> Any:
        """直接问模型，**不会**自动执行工具调用（与上游一致）。

        要跑工具循环请用 `tool_loop_agent()`。
        """
        provider = self.get_provider_by_id(chat_provider_id)
        if provider is None:
            raise StellaCompatNotSupported("Context.llm_generate（LLM 未启用）")
        return await provider.text_chat(
            prompt=prompt,
            image_urls=image_urls,
            audio_urls=audio_urls,
            func_tool=tools,
            system_prompt=system_prompt,
            contexts=contexts,
            **kwargs,
        )

    async def tool_loop_agent(
        self,
        *,
        event: Any,
        chat_provider_id: str = "",
        prompt: str | None = None,
        image_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        tools: Any = None,
        system_prompt: str | None = None,
        contexts: list | None = None,
        max_steps: int = 30,
        tool_call_timeout: int = 120,
        **kwargs: Any,
    ) -> Any:
        """带工具循环地问模型，返回最终的 LLMResponse。"""
        _ = (audio_urls, kwargs)
        from .llm.agent import run_tool_loop
        from .llm.entities import ProviderRequest

        provider = self.get_provider_by_id(chat_provider_id)
        if provider is None:
            raise StellaCompatNotSupported("Context.tool_loop_agent（LLM 未启用）")
        req = ProviderRequest(
            prompt=prompt,
            session_id=getattr(event, "unified_msg_origin", ""),
            image_urls=list(image_urls or []),
            func_tool=tools,
            contexts=list(contexts or []),
            system_prompt=system_prompt or "",
        )
        return await run_tool_loop(
            provider,
            req,
            event,
            max_steps=max_steps,
            tool_timeout=tool_call_timeout,
        )

    def register_llm_tool(
        self,
        name: str,
        func_args: list,
        desc: str,
        func_obj: Any,
    ) -> None:
        """上游已废弃的旧式注册接口。"""
        from .llm.tool import llm_tools

        llm_tools.add_func(name, func_args, desc, func_obj)

    def unregister_llm_tool(self, name: str) -> None:
        from .llm.tool import llm_tools

        llm_tools.remove_tool(name)


# 仍未实现的能力：必须存在（插件 import 得到）但一碰就抛可识别异常。
# LLM 相关方法已在 Context 类里真实现，不再出现在这里。
_LLM_METHODS: tuple[str, ...] = ()

# 注意：_LLM_PROPS 用 property 实现。hasattr() 只吞 AttributeError，所以这些 getter
# 抛的是 StellaCompatUnsupportedAttribute（同时是 StellaCompatNotSupported 和
# AttributeError）：hasattr(ctx, "conversation_manager") 返回 False（插件特性探测优雅
# 降级），而直接访问 ctx.conversation_manager 仍抛 StellaCompatNotSupported（可分流）。
# conversation_manager / persona_manager 已真实现（见类定义），不在此列。
_LLM_PROPS = (
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
