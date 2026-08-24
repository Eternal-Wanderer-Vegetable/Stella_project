# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""能力声明文件加载：``config/capabilities/*.toml`` → Capability Registry。

读法照 ``config/spaces.py`` 的惯例：``tomllib``（Py3.10 回退 ``tomli``），
**文件名即 domain**，单个文件解析失败只跳过该文件不中断其余加载。

文件格式：

```toml
# config/capabilities/information.toml
[[capability]]
id = "weather.query"
description = "查询天气信息"
examples = ["明天天气怎么样", "会不会下雨", "东京温度多少"]
keywords = ["天气", "气温", "下雨", "降雨"]        # Level 0 字面匹配，只认显式声明
providers = ["get_weather", "weather_forecast"]   # llm_tools 里的工具名

[[capability]]
id = "web.search"
description = "联网搜索"
examples = ["搜一下", "帮我查查"]
providers = [{ tool = "bing_search", priority = 10 }, { tool = "google_search" }]
```

``providers`` 两种写法都收：字符串（工具名）或表（可带 ``priority`` / ``kind``）。
字符串形式覆盖绝大多数场景，表形式留给「同一能力有多个实现要排优先级」的情况。

``examples`` 与 ``keywords`` 服务于**不同**的路由级别，不要混用：
``examples`` 是 Level 1 的语义原型语料（写自然句子），``keywords`` 是 Level 0 的
确定性字面词（写名词，且绝不从 examples 里猜——理由见 ``router/rules.py``）。

**声明文件是可选的**：目录不存在时一切照常，能力全靠 ``adapters/astrbot.py`` 自动派生。
写 TOML 的收益在路由质量上——中文 ``examples`` 让 Level 1 语义匹配显著变准，
``keywords`` 让高频请求走零延迟的 Level 0。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底（pyproject requires-python >=3.10）
    import tomli as tomllib

from capability.registry import (
    KIND_ASTRBOT_TOOL,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry


def _logger():
    """延迟取 nonebot logger：本模块要能在没起 NoneBot 的单测里直接用。

    与 config/spaces.py 内 ``from nonebot import logger`` 写在函数里同理。
    """
    from nonebot import logger

    return logger


def _parse_provider(
    raw: Any,
    capability_id: str,
    index: int,
) -> CapabilityProvider | None:
    """把 providers 列表里的一项解析成 CapabilityProvider；非法项返回 None。"""
    if isinstance(raw, str):
        tool_name = raw.strip()
        if not tool_name:
            return None
        return CapabilityProvider(
            provider_id=f"{capability_id}#{tool_name}",
            capability_id=capability_id,
            kind=KIND_ASTRBOT_TOOL,
            tool_name=tool_name,
            source="config",
        )
    if isinstance(raw, dict):
        tool_name = str(raw.get("tool") or raw.get("tool_name") or "").strip()
        kind = str(raw.get("kind") or KIND_ASTRBOT_TOOL).strip() or KIND_ASTRBOT_TOOL
        # astrbot_tool 没有工具名就无从执行；其它 kind 本轮不实现，也一并要求标识
        if not tool_name:
            return None
        try:
            priority = int(raw.get("priority", 0) or 0)
        except (TypeError, ValueError):
            priority = 0
        return CapabilityProvider(
            provider_id=str(raw.get("id") or f"{capability_id}#{tool_name}"),
            capability_id=capability_id,
            kind=kind,
            tool_name=tool_name,
            priority=priority,
            source="config",
        )
    _logger().warning(
        f"⚠️ [Capability] {capability_id} 的第 {index + 1} 个 provider 既不是工具名也不是表，已跳过",
    )
    return None


def _parse_capability(raw: Any, domain: str) -> Capability | None:
    """把一个 ``[[capability]]`` 表解析成 Capability；缺 id 时返回 None。"""
    if not isinstance(raw, dict):
        _logger().warning(f"⚠️ [Capability] {domain} 中存在非表项，已跳过")
        return None
    cap_id = str(raw.get("id") or "").strip()
    if not cap_id:
        _logger().warning(f"⚠️ [Capability] {domain} 中有能力缺少 id，已跳过")
        return None

    examples_raw = raw.get("examples") or []
    examples = (
        [str(e).strip() for e in examples_raw if str(e).strip()]
        if isinstance(examples_raw, list)
        else []
    )
    keywords_raw = raw.get("keywords") or []
    keywords = (
        [str(k).strip() for k in keywords_raw if str(k).strip()]
        if isinstance(keywords_raw, list)
        else []
    )
    schema = raw.get("input_schema")

    capability = Capability(
        id=cap_id,
        domain=str(raw.get("domain") or domain),
        description=str(raw.get("description") or "").strip(),
        examples=examples,
        keywords=keywords,
        input_schema=schema if isinstance(schema, dict) else {},
    )

    providers_raw = raw.get("providers") or []
    if not isinstance(providers_raw, list):
        _logger().warning(f"⚠️ [Capability] {cap_id} 的 providers 不是列表，已忽略")
        providers_raw = []
    for i, item in enumerate(providers_raw):
        provider = _parse_provider(item, cap_id, i)
        if provider is not None:
            capability.providers.append(provider)
    return capability


def load_capability_file(path: Path, target: CapabilityRegistry | None = None) -> int:
    """载入单个声明文件，返回成功注册的能力数。解析失败返回 0（只记日志）。"""
    reg = target if target is not None else _default_registry
    domain = path.stem
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        _logger().error(f"⚠️ [Capability] 解析 {path.name} 失败，跳过该文件: {e}")
        return 0

    entries = data.get("capability")
    if entries is None:
        _logger().warning(f"⚠️ [Capability] {path.name} 缺少 [[capability]] 段，跳过该文件")
        return 0
    # 允许单个 [capability] 表（TOML 里写成非数组），省掉一类容易犯的格式错
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        _logger().warning(f"⚠️ [Capability] {path.name} 的 capability 段格式非法，跳过该文件")
        return 0

    count = 0
    for raw in entries:
        capability = _parse_capability(raw, domain)
        if capability is None:
            continue
        reg.register(capability)
        count += 1
    return count


def load_capabilities(
    directory: Path | None = None,
    target: CapabilityRegistry | None = None,
) -> int:
    """扫描声明目录并全部载入，返回注册的能力总数。

    参数:
        directory: 声明目录，缺省为 ``config/capabilities``；
        target: 目标注册表，缺省为模块级单例。

    目录不存在或无 ``.toml`` 时正常返回 0——声明文件是可选的（见模块 docstring）。
    排序遍历保证多文件间的注册顺序确定。
    """
    if directory is None:
        from config import PROJECT_ROOT

        directory = PROJECT_ROOT / "config" / "capabilities"
    if not directory.is_dir():
        return 0

    total = 0
    for path in sorted(directory.glob("*.toml")):
        total += load_capability_file(path, target)
    if total:
        _logger().info(f"🧩 [Capability] 已载入 {total} 项声明能力（{directory.name}/）")
    return total


__all__ = ["load_capabilities", "load_capability_file"]
