# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBotConfig（兼容 AstrBot 插件配置）。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot_compat.config")


class AstrBotConfig(dict):
    """AstrBot 插件配置（dict 子类，支持 config[\"key\"] 与 config.key）。"""

    def __init__(
        self,
        plugin_dir_name: str,
        schema: dict | None = None,
        default: dict | None = None,  # noqa: ARG002  # 兼容上游签名，保留
    ) -> None:
        super().__init__()
        self._plugin_dir_name = plugin_dir_name
        self._schema = schema or {}
        # 上游命名：{plugin_dir_name}_config.json 位于 ASTRBOT_PLUGIN_CONFIG_DIR
        try:
            from config.settings import ASTRBOT_PLUGIN_CONFIG_DIR

            cfg_dir = ASTRBOT_PLUGIN_CONFIG_DIR
        except Exception:
            cfg_dir = Path(__file__).resolve().parent.parent / "data" / "config"
        self._path = cfg_dir / f"{plugin_dir_name}_config.json"
        # 先用 schema 填默认值
        self._apply_defaults()
        # 再读磁盘覆盖
        self._load()

    def _apply_defaults(self) -> None:
        for key, spec in (self._schema or {}).items():
            if not isinstance(spec, dict):
                continue
            if key in self:
                continue
            if "default" in spec:
                self[key] = spec["default"]
                continue
            t = spec.get("type", "string")
            if t in ("string", "text", "editor"):
                self[key] = ""
            elif t == "int":
                self[key] = 0
            elif t == "float":
                self[key] = 0.0
            elif t == "bool":
                self[key] = False
            elif t == "list":
                self[key] = []
            elif t == "object":
                # 带 items 时递归一层（简单处理：items 的默认值）
                items = spec.get("items")
                if isinstance(items, dict):
                    obj: dict[str, Any] = {}
                    for ik, iv in items.items():
                        if isinstance(iv, dict) and "default" in iv:
                            obj[ik] = iv["default"]
                    self[key] = obj
                else:
                    self[key] = {}
            else:
                self[key] = ""

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"[astrbot_compat] 配置文件读取失败 {self._path}: {e}")
            # 坏文件 rename 为 .bak，绝不阻死插件加载（with_suffix 对多点名反直觉，用字符串拼接）
            try:
                bak = self._path.with_name(self._path.name + ".bak")
                self._path.rename(bak)
                logger.warning(f"[astrbot_compat] 已将坏配置文件重命名为 {bak}")
            except Exception:
                pass
            return
        if isinstance(data, dict):
            self.update(data)

    def save_config(self, replace_config: dict | None = None) -> None:
        if replace_config is not None:
            self.clear()
            self.update(replace_config)
        # 原子写：先 .tmp 再 replace（with_suffix 对多点名反直觉，用字符串拼接）
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(dict(self), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.error(f"[astrbot_compat] 配置保存失败 {self._path}: {e}")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            self[name] = value


def load_conf_schema(plugin_dir: Path) -> dict:
    """读取 _conf_schema.json，失败返回 {}。"""
    schema_path = plugin_dir / "_conf_schema.json"
    if not schema_path.exists():
        return {}
    try:
        with schema_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        logger.warning(f"[astrbot_compat] _conf_schema.json 非 dict: {schema_path}")
        return {}
    except Exception as e:
        logger.warning(f"[astrbot_compat] _conf_schema.json 读取失败 {schema_path}: {e}")
        return {}
