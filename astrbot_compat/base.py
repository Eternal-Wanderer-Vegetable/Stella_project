# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Star 基类与 StarTools。"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from .context import Context

from .exceptions import StellaCompatNotSupported


class Star:
    """AstrBot 插件基类（Stella 兼容实现）。"""

    name: str = ""
    author: str = ""
    plugin_id: str = ""
    version: str = ""
    desc: str = ""

    def __init__(self, context: Context, config: Any | None = None) -> None:
        self.context = context
        self.config = config
        # KV 简易内存存储（插件常用 get_data/set_data 语义）
        self._kv_store: dict[str, Any] = {}
        # 上游做日志容错：有插件把 logger 定义成只读 property
        try:
            self.logger = logging.getLogger(self.__class__.__module__)
        except AttributeError:
            pass

    async def initialize(self) -> None:
        pass

    async def terminate(self) -> None:
        pass

    def _get_plugin_dir(self) -> str:
        mod = getattr(self.__class__, "__module__", "")
        if mod.startswith("data.plugins."):
            parts = mod.split(".")
            if len(parts) >= 3 and parts[2]:
                return parts[2]
        return "_unknown"

    # --- KV 简易实现（内存 + 持久化） ---
    def get_data(self, key: str, default: Any | None = None) -> Any:
        return self._kv_store.get(key, default)

    def set_data(self, key: str, value: Any) -> None:
        self._kv_store[key] = value

    def save_data(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    async def put_kv_data(self, key: str, value: Any) -> None:
        self._kv_store[key] = value
        try:
            p = StarTools.get_data_dir(self._get_plugin_dir()) / "kv.json"
            data: dict[str, Any] = {}
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if not isinstance(data, dict):
                        data = {}
                except Exception:
                    data = {}
            data[key] = value
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    async def get_kv_data(self, key: str, default: Any | None = None) -> Any:
        if key in self._kv_store:
            return self._kv_store[key]
        try:
            p = StarTools.get_data_dir(self._get_plugin_dir()) / "kv.json"
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and key in data:
                    self._kv_store[key] = data[key]
                    return data[key]
        except Exception:
            pass
        return default

    async def delete_kv_data(self, key: str) -> None:
        self._kv_store.pop(key, None)
        try:
            p = StarTools.get_data_dir(self._get_plugin_dir()) / "kv.json"
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
                if isinstance(data, dict) and key in data:
                    data.pop(key, None)
                    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # --- 渲染方法（暂不支持，转可识别异常） ---
    def html_render(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported("Star.html_render")

    def text_to_image(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported("Star.text_to_image")

    def t2i(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        raise StellaCompatNotSupported("Star.t2i")

    def __init_subclass__(cls, **kwargs) -> None:  # type: ignore[override]
        super().__init_subclass__(**kwargs)
        # 此时还读不到 metadata.yaml，只能建占位 StarMetadata
        from .registry import StarMetadata, star_handlers_registry, star_map, star_registry

        module_path = cls.__module__
        if module_path in star_map:
            existing = star_map[module_path]
            existing.star_cls_type = cls
            # 类体内的装饰器先执行，__init_subclass__ 后执行；
            # 此时装饰器已把 handler 注册到 star_handlers_registry，
            # 需回填到 StarMetadata。
            existing.star_handler_full_names = [
                h.handler_full_name
                for h in star_handlers_registry.get_handlers_by_module_name(module_path)
            ]
        else:
            md = StarMetadata(
                name="",
                author="",
                desc="",
                version="",
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
    def __getattr__(cls, name: str):  # type: ignore[override]
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        raise StellaCompatNotSupported(f"StarTools.{name}")


class StarTools(metaclass=_StarToolsMeta):
    """插件工具集（仅 get_data_dir 本步可用，其余抛 NotSupported）。"""

    _context = None

    @classmethod
    def initialize(cls, context) -> None:  # type: ignore[no-untyped-def]
        cls._context = context

    @classmethod
    def get_data_dir(cls, plugin_name: str | None = None) -> Path:
        """获取插件数据目录。

        上游靠 sys._getframe 回溯调用栈，从 module 字面量 data.plugins.<dir> 取目录名。
        """
        # 解析 ASTRBOT_PLUGIN_DATA_DIR（插件运行时数据，不与源码同目录）
        try:
            from config.settings import ASTRBOT_PLUGIN_DATA_DIR

            base = ASTRBOT_PLUGIN_DATA_DIR
        except Exception:
            base = Path(__file__).resolve().parent.parent / "data" / "plugin_data"

        dir_name: str | None = None
        if plugin_name:
            dir_name = plugin_name
        else:
            try:
                frame = sys._getframe(1)
                mod_name: str = frame.f_globals.get("__name__", "")
                if mod_name.startswith("data.plugins."):
                    parts = mod_name.split(".")
                    if len(parts) >= 3 and parts[2]:
                        dir_name = parts[2]
            except (ValueError, AttributeError):
                dir_name = None

        if not dir_name:
            logging.getLogger(__name__).warning(
                "StarTools.get_data_dir: 无法从调用栈推断插件目录，回退到 _unknown"
            )
            dir_name = "_unknown"

        p = base / dir_name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @classmethod
    def get_db(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise StellaCompatNotSupported("StarTools.get_db")

    @classmethod
    def get_event_queue(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise StellaCompatNotSupported("StarTools.get_event_queue")

    @classmethod
    def get_config(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise StellaCompatNotSupported("StarTools.get_config")

    @classmethod
    def register_web_api(cls, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise StellaCompatNotSupported("StarTools.register_web_api")


__all__ = ["Star", "StarTools", "Context"]
