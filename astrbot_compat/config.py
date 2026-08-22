# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBotConfig（兼容 AstrBot 插件配置）。"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot_compat.config")

# 与上游 DEFAULT_VALUE_MAP 一致
DEFAULT_VALUE_MAP: dict[str, Any] = {
    "int": 0,
    "float": 0.0,
    "bool": False,
    "string": "",
    "text": "",
    "list": [],
    "file": [],
    "object": {},
    "template_list": [],
    "dict": {},
}


def _plugin_config_dir() -> Path:
    try:
        from config.settings import ASTRBOT_PLUGIN_CONFIG_DIR

        return ASTRBOT_PLUGIN_CONFIG_DIR
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "config"


def schema_to_default(schema: dict) -> dict:
    """把 `_conf_schema.json` 展开成默认配置，`object` 递归到底。"""
    conf: dict[str, Any] = {}

    def _parse(node: dict, out: dict) -> None:
        for k, v in node.items():
            if not isinstance(v, dict):
                continue
            typ = v.get("type", "string")
            if typ == "object":
                items = v.get("items")
                child: dict[str, Any] = {}
                if isinstance(items, dict):
                    _parse(items, child)
                # 显式 default 覆盖递归结果
                default = v.get("default")
                out[k] = dict(default) if isinstance(default, dict) else child
                continue
            if "default" in v:
                out[k] = v["default"]
                continue
            if typ not in DEFAULT_VALUE_MAP:
                logger.warning(
                    f"[astrbot_compat] 未知配置类型 {typ!r}（键 {k}），按空字符串处理",
                )
                out[k] = ""
                continue
            fallback = DEFAULT_VALUE_MAP[typ]
            # list/dict 是可变对象，必须每次新建，否则多个键共享同一实例
            out[k] = type(fallback)(fallback) if isinstance(fallback, (list, dict)) else fallback

    _parse(schema, conf)
    return conf


def _merge_defaults(defaults: dict, conf: dict) -> dict:
    """把磁盘配置合并到默认值上，缺失的键补默认值（递归）。"""
    merged: dict[str, Any] = {}
    for key, default_val in defaults.items():
        if key not in conf or conf[key] is None:
            merged[key] = default_val
        elif isinstance(default_val, dict) and isinstance(conf[key], dict):
            merged[key] = _merge_defaults(default_val, conf[key])
        else:
            merged[key] = conf[key]
    # 保留磁盘上 schema 未声明的键，避免用户手写的配置被吃掉
    for key, val in conf.items():
        if key not in merged:
            merged[key] = val
    return merged


class AstrBotConfig(dict):
    """AstrBot 插件配置（dict 子类，支持 `config["key"]` 与 `config.key`）。"""

    def __init__(
        self,
        plugin_dir_name: str = "",
        schema: dict | None = None,
        default: dict | None = None,
    ) -> None:
        super().__init__()
        self._plugin_dir_name = plugin_dir_name
        self._schema = schema or {}
        # 第一个参数既可以是插件目录名，也可以是完整的配置文件路径（上游签名）
        name = str(plugin_dir_name)
        if name.endswith(".json") or "/" in name or "\\" in name:
            self._path = Path(name)
        else:
            self._path = _plugin_config_dir() / f"{name}_config.json"

        defaults = schema_to_default(self._schema) if self._schema else dict(default or {})
        self.update(defaults)
        self._load(defaults)

    def _load(self, defaults: dict) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            logger.error(f"[astrbot_compat] 配置文件读取失败 {self._path}: {e}")
            # 坏文件 rename 为 .bak，绝不阻死插件加载
            # （with_suffix 对多点文件名反直觉，这里用字符串拼接）
            with contextlib.suppress(OSError):
                bak = self._path.with_name(self._path.name + ".bak")
                self._path.rename(bak)
                logger.warning(f"[astrbot_compat] 已将坏配置文件重命名为 {bak}")
            return
        if isinstance(data, dict):
            self.clear()
            self.update(_merge_defaults(defaults, data) if defaults else data)

    def save_config(self, replace_config: dict | None = None) -> None:
        if replace_config is not None:
            self.clear()
            self.update(replace_config)
        # 原子写：先 .tmp 再 replace
        # （with_suffix 对多点文件名反直觉，这里用字符串拼接）
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            tmp.write_text(
                json.dumps(dict(self), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as e:
            logger.error(f"[astrbot_compat] 配置保存失败 {self._path}: {e}")
            with contextlib.suppress(OSError):
                if tmp.exists():
                    tmp.unlink()

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

    def __delattr__(self, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
        else:
            self.pop(name, None)


def load_conf_schema(plugin_dir: Path) -> dict:
    """读取 `_conf_schema.json`，失败返回 `{}`。"""
    schema_path = plugin_dir / "_conf_schema.json"
    if not schema_path.exists():
        return {}
    try:
        data = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        logger.warning(f"[astrbot_compat] _conf_schema.json 读取失败 {schema_path}: {e}")
        return {}
    if isinstance(data, dict):
        return data
    logger.warning(f"[astrbot_compat] _conf_schema.json 非 dict: {schema_path}")
    return {}
