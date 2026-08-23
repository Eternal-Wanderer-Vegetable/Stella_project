# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Star 基类与 StarTools。"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from .context import Context
from .exceptions import StellaCompatNotSupported, StellaCompatUnsupportedAttribute

logger = logging.getLogger("astrbot_compat.base")


def _plugin_data_root() -> Path:
    try:
        from config.settings import ASTRBOT_PLUGIN_DATA_DIR

        return ASTRBOT_PLUGIN_DATA_DIR
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "plugin_data"


def _resolve_plugin_dir_name(mod_name: str) -> str | None:
    """由模块路径推断插件的数据目录名。

    优先取 metadata 声明的 name（上游安装时目录名即 name），否则退回
    `data.plugins.<dir>` 里的目录名。
    """
    if not mod_name:
        return None
    from .registry import star_map

    meta = star_map.get(mod_name)
    if meta is None:
        # handler 可能定义在插件包的子模块里，按包前缀再找一次
        for path, m in star_map.items():
            package = path.rpartition(".")[0]
            if package and mod_name.startswith(package + "."):
                meta = m
                break
    if meta is not None:
        name = meta.name or meta.root_dir_name
        if name:
            return name
    if mod_name.startswith("data.plugins."):
        parts = mod_name.split(".")
        if len(parts) >= 3 and parts[2]:
            return parts[2]
    return None


class CommandTokens:
    """`parse_commands` 的返回值。"""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.len = 0

    def get(self, idx: int) -> str | None:
        if idx >= self.len:
            return None
        return self.tokens[idx].strip()


class CommandParserMixin:
    """上游 `astrbot.core.utils.command_parser.CommandParserMixin`。"""

    def parse_commands(self, message: str) -> CommandTokens:
        cmd_tokens = CommandTokens()
        cmd_tokens.tokens = re.split(r"\s+", message)
        cmd_tokens.len = len(cmd_tokens.tokens)
        return cmd_tokens

    def regex_match(self, message: str, command: str) -> bool:
        return re.search(command, message, re.MULTILINE) is not None


class PluginKVStoreMixin:
    """插件级 KV 存储。落盘在插件自己的 data 目录下 `kv.json`。"""

    def _kv_path(self) -> Path:
        return StarTools.get_data_dir(self._resolve_plugin_dir()) / "kv.json"

    def _resolve_plugin_dir(self) -> str:
        return _resolve_plugin_dir_name(getattr(self.__class__, "__module__", "")) or "_unknown"

    def _read_kv(self) -> dict[str, Any]:
        p = self._kv_path()
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_kv(self, data: dict[str, Any]) -> None:
        p = self._kv_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    async def put_kv_data(self, key: str, value: Any) -> None:
        self._kv_store[key] = value
        try:
            data = self._read_kv()
            data[key] = value
            self._write_kv(data)
        except OSError as e:
            logger.warning(f"[astrbot_compat] KV 写入失败 {key}: {e}")

    async def get_kv_data(self, key: str, default: Any = None) -> Any:
        if key in self._kv_store:
            return self._kv_store[key]
        data = self._read_kv()
        if key in data:
            self._kv_store[key] = data[key]
            return data[key]
        return default

    async def delete_kv_data(self, key: str) -> None:
        self._kv_store.pop(key, None)
        try:
            data = self._read_kv()
            if key in data:
                data.pop(key, None)
                self._write_kv(data)
        except OSError as e:
            logger.warning(f"[astrbot_compat] KV 删除失败 {key}: {e}")


class Star(CommandParserMixin, PluginKVStoreMixin):
    """AstrBot 插件基类（Stella 兼容实现）。"""

    name: str = ""
    author: str = ""
    plugin_id: str = ""
    version: str = ""
    desc: str = ""

    def __init__(self, context: Context, config: Any | None = None) -> None:
        self.context = context
        self.config = config
        self._kv_store: dict[str, Any] = {}
        # 上游做日志容错：有插件把 logger 定义成只读 property
        with contextlib.suppress(AttributeError):
            from .registry import star_map

            meta = star_map.get(self.__class__.__module__)
            plugin_name = (meta.name if meta else "") or getattr(self, "name", "")
            self.logger = logging.getLogger(
                f"astrbot_compat.plugin.{plugin_name}"
                if plugin_name
                else self.__class__.__module__,
            )

    async def initialize(self) -> None:
        """插件被激活时调用。"""

    async def terminate(self) -> None:
        """插件被禁用 / 重载时调用。"""

    def _get_context_config(self) -> Any:
        get_config = getattr(self.context, "get_config", None)
        if callable(get_config):
            try:
                return get_config()
            except Exception as e:
                logger.debug(f"[astrbot_compat] get_config() 失败: {e}")
                return None
        return getattr(self.context, "_config", None)

    def _get_plugin_dir(self) -> str:
        return self._resolve_plugin_dir()

    # --- 同步 KV（Stella 扩展，进程内） ---
    def get_data(self, key: str, default: Any | None = None) -> Any:
        return self._kv_store.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self._kv_store[key] = value

    def save_data(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)
        with contextlib.suppress(OSError):
            data = self._read_kv()
            data.update(self._kv_store)
            self._write_kv(data)

    # --- 渲染（依赖浏览器/模板服务，Stella 暂不提供） ---
    async def html_render(
        self,
        tmpl: str,
        data: dict,
        return_url: bool = True,
        options: dict | None = None,
    ) -> str:
        _ = (tmpl, data, return_url, options)
        raise StellaCompatNotSupported("Star.html_render")

    async def text_to_image(self, text: str, return_url: bool = True) -> str:
        _ = (text, return_url)
        raise StellaCompatNotSupported("Star.text_to_image")

    async def t2i(self, *args: Any, **kwargs: Any) -> str:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("Star.t2i")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # 此时还读不到 metadata.yaml，只能建占位 StarMetadata
        from .registry import (
            StarMetadata,
            star_handlers_registry,
            star_map,
            star_registry,
        )

        module_path = cls.__module__
        existing = star_map.get(module_path)
        if existing is not None:
            existing.star_cls_type = cls
            existing.module_path = module_path
            # 类体内的装饰器先执行、__init_subclass__ 后执行，这里回填 handler 名单
            existing.star_handler_full_names = [
                h.handler_full_name
                for h in star_handlers_registry.get_handlers_by_module_name(module_path)
            ]
            return
        md = StarMetadata(
            star_cls_type=cls,
            module_path=module_path,
            star_handler_full_names=[
                h.handler_full_name
                for h in star_handlers_registry.get_handlers_by_module_name(module_path)
            ],
        )
        star_map[module_path] = md
        star_registry.append(md)


class _StarToolsMeta(type):
    def __getattr__(cls, name: str) -> Any:
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise StellaCompatUnsupportedAttribute(f"StarTools.{name}")


class StarTools(metaclass=_StarToolsMeta):
    """插件工具集。平台类能力已实现，LLM 类能力抛 StellaCompatNotSupported。"""

    _context: Context | None = None

    @classmethod
    def initialize(cls, context: Context) -> None:
        cls._context = context

    @classmethod
    async def send_message(cls, session: Any, message_chain: Any) -> bool:
        """按 unified_msg_origin 主动发消息。"""
        if cls._context is None:
            from .context import get_context

            cls._context = get_context()
        return await cls._context.send_message(str(session), message_chain)

    @classmethod
    def get_data_dir(cls, plugin_name: str | None = None) -> Path:
        """获取插件数据目录 `<ASTRBOT_PLUGIN_DATA_DIR>/<插件名>`。

        不传参数时按上游做法回溯调用栈：从模块路径 `data.plugins.<dir>` 定位插件，
        再优先取其 metadata 里声明的 name（上游安装时目录名即 name）。
        """
        base = _plugin_data_root()
        dir_name: str | None = plugin_name or None

        if not dir_name:
            mod_name = ""
            with contextlib.suppress(ValueError, AttributeError):
                mod_name = sys._getframe(1).f_globals.get("__name__", "")
            dir_name = _resolve_plugin_dir_name(mod_name)

        if not dir_name:
            logger.warning(
                "StarTools.get_data_dir: 无法从调用栈推断插件目录，回退到 _unknown",
            )
            dir_name = "_unknown"

        p = base / dir_name
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    @classmethod
    def activate_llm_tool(cls, name: str) -> bool:
        from .llm.tool import llm_tools

        return llm_tools.activate_llm_tool(name)

    @classmethod
    def deactivate_llm_tool(cls, name: str) -> bool:
        from .llm.tool import llm_tools

        return llm_tools.deactivate_llm_tool(name)

    @classmethod
    async def activate_llm_tool_async(cls, name: str) -> bool:
        return cls.activate_llm_tool(name)

    @classmethod
    async def deactivate_llm_tool_async(cls, name: str) -> bool:
        return cls.deactivate_llm_tool(name)

    @classmethod
    def get_db(cls, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("StarTools.get_db")

    @classmethod
    def get_event_queue(cls, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("StarTools.get_event_queue")

    @classmethod
    def get_config(cls, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("StarTools.get_config")

    @classmethod
    def register_web_api(cls, *args: Any, **kwargs: Any) -> Any:
        _ = (args, kwargs)
        raise StellaCompatNotSupported("StarTools.register_web_api")

    @classmethod
    def register_llm_tool(
        cls,
        name: str,
        func_args: list,
        desc: str,
        func_obj: Any,
    ) -> None:
        """上游已废弃的旧式注册接口（与 Context.register_llm_tool 同一张表）。"""
        from .llm.tool import llm_tools

        llm_tools.add_func(name, func_args, desc, func_obj)

    @classmethod
    def unregister_llm_tool(cls, name: str) -> None:
        from .llm.tool import llm_tools

        llm_tools.remove_tool(name)


__all__ = ["CommandParserMixin", "CommandTokens", "Context", "PluginKVStoreMixin", "Star", "StarTools"]
