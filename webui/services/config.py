# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""配置页取数与写回（方案 §6.6 / §7.3）。

schema 来自 ``deploy/env_schema.build_schema``（AST 提取，与 v1 高级页同
一条管线），进程内缓存一次——settings.py 不变则 schema 不变。
读取时把当前 .env 原文值合进每个字段（``current_value``）；敏感键只给
``has_value`` 不回显内容（脱敏红线，测试钉死）。写回走 envfile：继承键
空串=删除该键（留空即继承）；敏感键空串=不修改；choice/数值类型在服务
端校验。settings.py 是 import 期冻结，写完必须重启才生效——所有写接口
统一返回 ``restart_required: true``。
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import config.settings as settings
from webui.responses import ApiError
from webui.services import envfile


@functools.lru_cache(maxsize=1)
def schema() -> dict[str, Any]:
    """配置 schema（缓存；settings.py 在运行期不变）。

    注意用 ``settings.__file__`` 定位真实 settings.py，而不是
    ``settings.PROJECT_ROOT``——测试会把 PROJECT_ROOT monkeypatch 到临时
    目录，跟着走就找不到 schema 源文件了（实测踩过）。
    """
    from deploy.env_schema import build_schema

    settings_path = Path(settings.__file__).resolve().parent / "settings.py"
    return build_schema(settings_path)


# NoneBot/适配器直读环境变量、不经 settings._env 的连接键——build_schema
# 看不见它们，但它们是 .env 里真实存在且用户必须能改的配置。
_EXTRA_FIELDS = [
    {"key": "HOST", "type": "str", "default": "0.0.0.0",
     "comment": "Bot 监听地址（reverse 模式；NapCat 异机时 0.0.0.0）"},
    {"key": "PORT", "type": "int", "default": "8080", "comment": "Bot 监听端口"},
    {"key": "ONEBOT_WS_URLS", "type": "str", "default": "",
     "comment": "正向 WS 上游地址（JSON 数组；forward 模式用）"},
    {"key": "ONEBOT_ACCESS_TOKEN", "type": "str", "default": "",
     "comment": "OneBot WS 鉴权 token（须与 NapCat 一致）", "extra_sensitive": True},
]


def _fields() -> list[dict]:
    fields = schema().get("fields") if isinstance(schema(), dict) else None
    if fields is None:
        # build_schema 的返回既可能是 {"fields": [...]} 也可能直接是列表，
        # 两种都兼容，别赌形状。
        fields = schema() if isinstance(schema(), list) else []
    known = {f["key"] for f in fields}
    return [*fields, *[e for e in _EXTRA_FIELDS if e["key"] not in known]]


def _is_sensitive(key: str) -> bool:
    if key == "ONEBOT_ACCESS_TOKEN":
        return True
    try:
        from deploy import env_keys

        return bool(env_keys.is_sensitive(key))
    except Exception:
        return key.endswith(("KEY", "TOKEN", "PASSWORD", "SECRET"))


def current() -> dict:
    raw = envfile.read_values()
    fields = []
    for f in _fields():
        key = f["key"]
        sensitive = _is_sensitive(key)
        value = raw.get(key)
        item = {
            "key": key,
            "type": f.get("type"),
            "default": f.get("default"),
            "choices": f.get("choices") or f.get("options"),
            "comment": f.get("comment") or f.get("description"),
            "inherits": f.get("inherits"),
            "sensitive": sensitive,
            "present": key in raw,
            "current_value": None if sensitive else value,
            "has_value": bool(value),
        }
        fields.append(item)
    return {"fields": fields, "env_file": str(envfile.env_file())}


def _scalar_to_str(value: Any) -> str:
    """JSON 标量 → .env 行值。开关发的是 JSON 布尔值，pydantic 的
    dict[str, str] 会拒绝 bool——前端 ConfigForm 的开关必须有这条通路
    （否则「格式不正确」，用户实测阻塞了 DB_CLEANUP 两个开关）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def update(values: dict[str, Any]) -> dict:
    """增量写回。返回 {written, removed, restart_required}。"""
    valid = {f["key"]: f for f in _fields()}
    remove: set[str] = set()
    apply_updates: dict[str, str] = {}
    for key, raw_value in (values or {}).items():
        if key not in valid:
            raise ApiError(f"未知配置键: {key}")
        field = valid[key]
        value = _scalar_to_str(raw_value)
        sensitive = _is_sensitive(key)
        if sensitive and value == "":
            continue  # 敏感键空串 = 不修改
        if field.get("inherits") and value == "":
            remove.add(key)  # 继承键清空 = 删除，让继承链生效
            continue
        if field.get("choices") and value not in field["choices"]:
            raise ApiError(f"{key} 的合法取值: {', '.join(map(str, field['choices']))}")
        if field.get("type") == "bool":
            if value.lower() not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                raise ApiError(f"{key} 需要布尔值（true/false）")
            value = value.lower()
        elif field.get("type") in ("int", "float"):
            try:
                float(value)
            except (TypeError, ValueError):
                raise ApiError(f"{key} 需要数字") from None
        apply_updates[key] = value
    report = envfile.write_values(apply_updates, remove=remove)
    return {**report, "restart_required": True}
