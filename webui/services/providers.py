# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""提供商（端点槽 × 角色绑定）读写与连通性测试（方案 §6.4）。

配置态直接读写 settings 的 ``LLM_ENDPOINT_*`` / ``LLM_ROLE_*`` 键（写侧
经 envfile 落 .env，重启生效——registry 是 import 期冻结的，这正是
restart_required 的原因）。api_key 永不回显，只报 ``has_api_key``；
写侧空串 = 不修改。连通性测试复用 deploy/probe 的现成探针。
"""

from __future__ import annotations

from typing import Any

import config.settings as settings
from core.llm import registry as llm_registry
from webui.responses import ApiError
from webui.services import envfile

_BASE_FIELDS = ("BASE_URL", "API_KEY", "MODEL", "KIND", "CONCURRENCY", "TIMEOUT")
_ROLE_FIELDS = ("ENDPOINT", "MODEL", "TEMPERATURE", "MAX_TOKENS", "FALLBACK_ENDPOINT")


def _slots() -> list[str]:
    try:
        return list(llm_registry.all_slots())
    except Exception:
        return ["CHAT", "MEMORY", "VISION"]


def _norm_slot(value: str) -> str:
    """旧槽名（LOCAL/EXTRA/...）→ 新槽名；其余原样。委托 registry 单一出处。"""
    try:
        return llm_registry._normalize_slot(value)
    except Exception:
        return value


def endpoints() -> list[dict]:
    items = []
    for slot in _slots():
        def cfg(field: str, *, _slot: str = slot) -> Any:
            return getattr(settings, f"LLM_ENDPOINT_{_slot}_{field}", None)

        base_url = cfg("BASE_URL")
        items.append(
            {
                "slot": slot,
                "base_url": base_url or "",
                "model": cfg("MODEL") or "",
                "kind": cfg("KIND") or "",
                "concurrency": cfg("CONCURRENCY"),
                "timeout": cfg("TIMEOUT"),
                "has_api_key": bool(cfg("API_KEY")),
            }
        )
    return items


def update_endpoints(payload: list[dict]) -> dict:
    valid = set(_slots())
    updates: dict[str, str] = {}
    for item in payload:
        slot = str(item.get("slot", "")).upper()
        # 旧槽名归一后校验：客户端拿着过期缓存里的 LOCAL 保存也不炸
        slot = _norm_slot(slot)
        if slot not in valid:
            raise ApiError(f"未知端点槽: {slot}")
        # 前端传小写字段名，这里统一按大写域匹配
        item_upper = {k.upper(): v for k, v in item.items()}
        for field in _BASE_FIELDS:
            if field not in item_upper:
                continue
            value = str(item_upper[field]).strip()
            if field == "API_KEY" and value == "":
                continue  # 空串 = 不修改
            if field == "CONCURRENCY" and value != "":
                try:
                    int(value)
                except ValueError:
                    raise ApiError(f"{slot}.{field} 需要整数") from None
            if field == "TIMEOUT" and value != "":
                try:
                    float(value)
                except ValueError:
                    raise ApiError(f"{slot}.{field} 需要数字（秒）") from None
            updates[f"LLM_ENDPOINT_{slot}_{field}"] = value
    report = envfile.write_values(updates)
    return {**report, "restart_required": True}


def roles() -> list[dict]:
    items = []
    for role in llm_registry.ROLES:
        upper = role.upper()
        def cfg(field: str, *, _upper: str = upper) -> Any:
            return getattr(settings, f"LLM_ROLE_{_upper}_{field}", None)

        # ENDPOINT 的旧槽名（LOCAL/EXTRA/...）在此归一展示，保存时也会以
        # 新名写回——.env 里的旧值在下次保存后自然完成迁移。
        endpoint = _norm_slot(str(cfg("ENDPOINT") or ""))
        items.append(
            {
                "role": role,
                "endpoint": endpoint,
                "model": cfg("MODEL") or "",
                "temperature": cfg("TEMPERATURE"),
                "max_tokens": cfg("MAX_TOKENS"),
                "fallback_endpoint": _norm_slot(str(cfg("FALLBACK_ENDPOINT") or "")),
            }
        )
    return items


def update_roles(payload: list[dict]) -> dict:
    valid_roles = set(llm_registry.ROLES)
    valid_slots = set(_slots())
    updates: dict[str, str] = {}
    for item in payload:
        role = item.get("role")
        if role not in valid_roles:
            raise ApiError(f"未知角色: {role}")
        upper = role.upper()
        # ``none`` 是合法值（视觉等可选角色显式声明不启用），规范写法小写——
        # 之前的 .upper() 把它变成 NONE 再验槽位，误杀成 400（用户实测）。
        # 旧槽名（LOCAL/EXTRA/...）在此归一为新名：存量 .env 的绑定值
        # 保存一次即完成迁移。
        endpoint = str(item.get("endpoint", "")).strip()
        if endpoint and endpoint.lower() != "none":
            endpoint = _norm_slot(endpoint.upper())
            if endpoint not in valid_slots:
                raise ApiError(
                    f"{role} 的端点槽必须是: {', '.join(sorted(valid_slots))} 或 none"
                )
        if endpoint:
            updates[f"LLM_ROLE_{upper}_ENDPOINT"] = endpoint
        if "model" in item:
            updates[f"LLM_ROLE_{upper}_MODEL"] = str(item.get("model", "")).strip()
        if item.get("temperature") not in (None, ""):
            try:
                float(item["temperature"])
                updates[f"LLM_ROLE_{upper}_TEMPERATURE"] = str(item["temperature"])
            except (TypeError, ValueError):
                raise ApiError(f"{role}.temperature 需要数字") from None
        fallback = str(item.get("fallback_endpoint", "") or "").strip()
        if fallback:
            fallback = _norm_slot(fallback.upper())
            if fallback not in valid_slots:
                raise ApiError(f"{role} 的降级端点槽必须是: {', '.join(sorted(valid_slots))}")
            updates[f"LLM_ROLE_{upper}_FALLBACK_ENDPOINT"] = fallback
    report = envfile.write_values(updates)
    return {**report, "restart_required": True}


async def fetch_models(base_url: str, api_key: str) -> dict:
    """拉取远端 /v1/models（deploy.probe 现成实现；api_key 仅本次请求使用）。"""
    import asyncio

    from deploy.probe import fetch_endpoint_models

    models, err = await asyncio.to_thread(fetch_endpoint_models, base_url, api_key)
    return {"models": models, "error": err}


async def test_endpoint(base_url: str, api_key: str, model: str) -> dict:
    """连通性测试：模型列表 + 一次最小补全（max_tokens=1）。"""
    import asyncio

    from deploy.probe import probe_llama_readiness

    result = await asyncio.to_thread(
        probe_llama_readiness, base_url, model=model, api_key=api_key, timeout=8.0
    )
    return {
        "ok": bool(result.get("ready")),
        "models_reachable": result.get("models_reachable"),
        "chat_reachable": result.get("chat_reachable"),
        "error": result.get("error"),
    }
