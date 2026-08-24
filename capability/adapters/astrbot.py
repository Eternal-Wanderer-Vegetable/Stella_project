# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""AstrBot 插件 → Capability 的适配（方案第 13 节）。

```
AstrBot Plugin → Adapter → Capability Registry → Comes
```

插件必须被映射为 Capability，这样：

- Stella 不依赖 AstrBot；
- Comes 不依赖插件名称；
- 插件生态可替换。

## 两条注册通路

**显式声明**（``config/capabilities/*.toml``，见 ``capability/loader.py``）：
把若干工具归入一个语义能力，带中文 ``examples`` 与 ``keywords``。路由质量最好。

**自动派生**（本模块）：扫 ``llm_tools``，把**没有被任何显式声明认领**的活跃工具
注册成 ``tool.<工具名>``。零配置——装上插件就能被路由到。

两者的归属判定靠 ``registry.claimed_by()``：声明的注册一定早于自动派生
（后者要等插件加载完），而 ``_claim`` 是先到先得，所以「先到」天然等于「显式优先」。

## 自动派生能力的先天局限

工具描述大多是英文短句（``"get weather forecast for a city"``），而用户说中文。
自动派生的能力只有这一句英文做原型语料，Level 1 的跨语言语义匹配准确率明显低于
中文 examples；且它没有 ``keywords``，拿不到 Level 0 的零延迟通路。

这个局限是**刻意不去补**的：从英文描述machine-generate中文 examples 需要调模型，
而生成质量无法验证，错的 examples 比没有 examples 更糟（会把不相关的请求吸进来）。
需要好的路由质量就写 TOML——这是一次性的几行配置。
"""

from __future__ import annotations

from typing import Any

from capability.registry import (
    AUTO_CAPABILITY_PREFIX,
    KIND_ASTRBOT_TOOL,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry


def _logger():
    from nonebot import logger

    return logger


def auto_capability_id(tool_name: str) -> str:
    """自动派生能力的 id：``tool.<工具名>``。"""
    return f"{AUTO_CAPABILITY_PREFIX}{tool_name}"


def _build_auto_capability(tool: Any) -> Capability:
    """把一个 FunctionTool 包成一个单 provider 的能力。"""
    cap_id = auto_capability_id(tool.name)
    description = (getattr(tool, "description", "") or "").strip() or tool.name
    return Capability(
        id=cap_id,
        domain="plugin",
        description=description,
        # examples 留空：能填的只有 description，而 prototype_texts() 已经会带上它。
        # 把描述复制一份进 examples 只会让它在原型均值里被计两次，无谓地加权。
        examples=[],
        keywords=[],
        input_schema=getattr(tool, "parameters", None) or {},
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#{tool.name}",
                capability_id=cap_id,
                kind=KIND_ASTRBOT_TOOL,
                tool_name=tool.name,
                source="auto",
            ),
        ],
    )


def sync_astrbot_tools(
    target: CapabilityRegistry | None = None,
    tool_manager=None,
) -> dict[str, int]:
    """把 ``llm_tools`` 里的活跃工具同步进能力注册表。

    返回 ``{"derived": 新派生的能力数, "claimed": 已被声明认领而跳过的工具数,
    "skipped": 未激活而跳过的工具数}``。

    幂等：重复调用不会重复注册（``registry.register`` 是合并语义，
    ``add_provider`` 按 provider_id 去重）。插件热加载后可以再调一次。
    """
    reg = target if target is not None else _default_registry
    manager = tool_manager
    if manager is None:
        from astrbot_compat.llm.tool import llm_tools

        manager = llm_tools

    stats = {"derived": 0, "claimed": 0, "skipped": 0}
    for tool in list(getattr(manager, "tools", []) or []):
        name = getattr(tool, "name", "") or ""
        if not name:
            continue
        if not getattr(tool, "active", True):
            stats["skipped"] += 1
            continue
        # 已被显式声明认领 → 不派生（显式优先）
        owner = reg.claimed_by(name)
        if owner is not None and owner != auto_capability_id(name):
            stats["claimed"] += 1
            continue
        before = len(reg)
        reg.register(_build_auto_capability(tool))
        if len(reg) > before:
            stats["derived"] += 1

    if stats["derived"] or stats["claimed"]:
        _logger().info(
            f"🧩 [Capability] 插件工具同步完成：自动派生 {stats['derived']} 项，"
            f"已由声明认领 {stats['claimed']} 项，未激活跳过 {stats['skipped']} 项",
        )
    return stats


def bootstrap(target: CapabilityRegistry | None = None) -> dict[str, int]:
    """启动期一次性装配：先读声明文件，再自动派生剩余工具。

    **顺序不可交换**：声明必须先注册，才能通过 ``claimed_by`` 抢下工具归属。
    反过来的话自动派生会先把每个工具都占成 ``tool.<name>``，显式声明再想认领
    同一个工具就抢不到了（``_claim`` 先到先得），于是精心写的中文 examples
    永远不会被用到——而这不报错，只表现为「路由准确率没提升」。
    """
    from capability.loader import load_capabilities

    declared = load_capabilities(target=target)
    stats = sync_astrbot_tools(target)
    stats["declared"] = declared
    return stats


__all__ = ["auto_capability_id", "bootstrap", "sync_astrbot_tools"]
