# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Capability Registry：能力与其实现方式的注册表。

核心思想（方案第 9 节）：

> 插件不是能力，插件只是能力的实现方式。

分层（方案第 11 节）：

```
Capability Domain  →  Capability  →  Provider  →  Tool
information           weather.query   AstrBot 天气插件   get_forecast()
```

这一层存在的意义是**解耦**：Stella 只知道「需要查天气」，不知道装的是哪个天气插件；
换插件时只改 Provider，任务生成侧与 Router 都不用动。反过来说，Registry 是唯一
知道「能力 ↔ 工具」对应关系的地方，别处不许自己拼这层映射。

注册表是**模块级单例**（``registry``），与 ``astrbot_compat.registry.star_handlers_registry``
和 ``astrbot_compat.llm.tool.llm_tools`` 同理：放在类里或函数里会让不同 import 路径
（``capability.registry`` vs ``import capability`` 后取属性）各拿到一份，注册表分裂后
表现为「插件明明装了但路由不到」，极难定位。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Provider 实现方式。本轮只实现 astrbot_tool，其余是留好的口子（方案第 20 节：
# 未来支持 MCP / API / Native Tool）。不提前实现是刻意的——没有真实调用方时
# 抽象一定是错的。
KIND_ASTRBOT_TOOL = "astrbot_tool"
KIND_MCP = "mcp"
KIND_API = "api"
KIND_NATIVE = "native"

# 自动派生能力的 id 前缀：没有被任何显式声明认领的插件工具会落到 ``tool.<工具名>``。
AUTO_CAPABILITY_PREFIX = "tool."


@dataclass
class CapabilityProvider:
    """一个能力的具体实现方式。

    属性:
        provider_id: provider 唯一标识（同一能力下不重复）；
        capability_id: 所属能力 id；
        kind: 实现类型，见 KIND_* 常量；
        tool_name: ``astrbot_tool`` 时为 ``llm_tools`` 里的工具名；
        priority: 越大越优先。同一能力有多个 provider 时的选择依据；
        enabled: 人工开关。关闭的 provider 永不参与选择；
        source: 注册来源（``config`` / ``auto``），用于「显式声明优先」的归属判定；
        failures: 连续失败次数。达到阈值后进入退避（见 ``available``）；
        disabled_until: 退避到期的时间戳（``time.time()`` 纪元秒）。0 表示未退避。
    """

    provider_id: str
    capability_id: str
    kind: str = KIND_ASTRBOT_TOOL
    tool_name: str = ""
    priority: int = 0
    enabled: bool = True
    source: str = "config"
    failures: int = 0
    disabled_until: float = 0.0

    def available(self, now: float | None = None) -> bool:
        """当前是否可用：人工未关闭，且不在失败退避窗口内。"""
        if not self.enabled:
            return False
        if self.disabled_until <= 0.0:
            return True
        return (now if now is not None else time.time()) >= self.disabled_until

    def mark_success(self) -> None:
        """记一次成功：清零失败计数并解除退避。

        清零而不是递减：一次成功说明服务恢复了，没有理由继续记着之前的失败。
        """
        self.failures = 0
        self.disabled_until = 0.0

    def mark_failure(
        self,
        threshold: int,
        recover_seconds: float,
        now: float | None = None,
    ) -> bool:
        """记一次失败；达到阈值则进入退避。返回本次是否触发了退避。

        ``threshold <= 0`` 表示不退避（只累计计数，供诊断）。退避是**时间窗**而非
        永久禁用：插件依赖的外部 API 抖动是常态，永久禁用会让一次网络波动
        永久关掉一个能力，而这不报错、只表现为「这个功能后来就不好使了」。
        """
        self.failures += 1
        if threshold <= 0 or self.failures < threshold:
            return False
        self.disabled_until = (now if now is not None else time.time()) + max(
            recover_seconds, 0.0,
        )
        return True

    def __repr__(self) -> str:
        if not self.enabled:
            state = " disabled"
        elif not self.available():
            state = f" backoff(failures={self.failures})"
        else:
            state = ""
        return f"Provider({self.provider_id} kind={self.kind} tool={self.tool_name}{state})"


@dataclass
class Capability:
    """一项能力。

    属性:
        id: 能力 id，形如 ``weather.query``；
        domain: 能力域（``information`` / ``entertainment`` …），取自声明文件名；
        description: 能力描述，进 Router 的原型语料；
        examples: 典型用户说法。**Router 的 Level 1 语义匹配主要靠它**——
            工具描述是写给「看着全部工具做选择」的决策器的指令句（"当用户询问 X 时调用"），
            与用户的**问句**不同构；只靠它做语义匹配，同域工具之间几乎没有区分度；
        keywords: 触发本能力的**确定性关键词**，供 Router 的 Level 0 字面匹配。
            只认显式声明，不从 examples 里猜——中文没有词边界，从「会不会下雨」
            切出来的候选里既有「下雨」也有「不会」，后者会命中几乎任何句子。
            Level 0 的职责是「处理高置信度请求」，猜出来的词达不到这个标准；
        input_schema: 输入契约（可选，给 Comes 做槽位提示）；
        providers: 实现方式列表；
        route_enabled: 是否参与 Router 的能力选择。``False`` 时能力照常注册、
            照常可被显式指定执行，但不进 ``routable()``，因此不参与 Level 0/1/2 的
            任何竞争。自动派生的能力按 ``ROUTER_ROUTE_AUTO_CAPABILITIES`` 落到这里，
            理由见 ``capability/adapters/astrbot.py``。
    """

    id: str
    domain: str = ""
    description: str = ""
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    providers: list[CapabilityProvider] = field(default_factory=list)
    route_enabled: bool = True

    @property
    def is_auto(self) -> bool:
        """是否为自动派生的能力（未被显式声明认领的插件工具）。"""
        return self.id.startswith(AUTO_CAPABILITY_PREFIX)

    def prototype_texts(self) -> list[str]:
        """供 Router 编码原型向量的语料：examples 优先，无 examples 时退到描述。

        两者都拿进来而不是只取 examples：一个只写了 description 的能力
        （自动派生的都是这样）也必须能被语义路由命中，否则零配置场景全废。
        """
        texts = [t.strip() for t in self.examples if t and t.strip()]
        desc = (self.description or "").strip()
        if desc:
            texts.append(desc)
        return texts

    def enabled_providers(self) -> list[CapabilityProvider]:
        """当前可用的 provider，按 priority 降序。同 priority 时保持登记顺序（稳定排序）。

        「可用」含健康度：处于失败退避窗口内的 provider 会被暂时排除
        （见 ``CapabilityProvider.available``）。
        """
        return sorted(
            (p for p in self.providers if p.available()),
            key=lambda p: p.priority,
            reverse=True,
        )

    def __repr__(self) -> str:
        return (
            f"Capability({self.id} domain={self.domain} "
            f"examples={len(self.examples)} providers={[p.tool_name for p in self.providers]}"
            f"{'' if self.route_enabled else ' 不参与路由'})"
        )


class CapabilityRegistry:
    """能力注册表。

    ``register`` 的合并语义：同 id 重复注册时**不覆盖**已有能力，而是补齐空字段并
    合并 provider。原因是两条注册通路会先后碰到同一个 id——显式声明（启动时读 TOML）
    与自动派生（插件加载后扫 llm_tools）。覆盖会让后跑的那条把前一条的 examples 抹掉，
    路由质量无声下降。
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        # 工具名 → 认领它的能力 id。自动派生时据此跳过已被显式声明认领的工具。
        self._claimed_tools: dict[str, str] = {}
        # 注册表版本号：每次变更自增，供 Router 的原型向量缓存失效
        self._version = 0

    # ---------- 变更 ----------

    def register(self, capability: Capability) -> Capability:
        """登记/合并一个能力，返回注册表内的那一份（可能不是传入的对象）。"""
        existing = self._capabilities.get(capability.id)
        if existing is None:
            self._capabilities[capability.id] = capability
            for provider in capability.providers:
                self._claim(provider)
            self._version += 1
            return capability

        # 合并：已有值优先，空字段用新值补齐
        existing.domain = existing.domain or capability.domain
        existing.description = existing.description or capability.description
        existing.input_schema = existing.input_schema or capability.input_schema
        # route_enabled 取「或」：一旦有任一次注册认为它该参与路由，就参与。
        # 语义是「显式声明优先」——声明（route_enabled=True）碰上自动派生
        # （可能为 False）时，声明赢；而重复同步同一批自动能力时两边都是 False，
        # 结果不变（sync_astrbot_tools 是幂等的）。
        existing.route_enabled = existing.route_enabled or capability.route_enabled
        for example in capability.examples:
            if example not in existing.examples:
                existing.examples.append(example)
        for keyword in capability.keywords:
            if keyword not in existing.keywords:
                existing.keywords.append(keyword)
        for provider in capability.providers:
            self.add_provider(existing.id, provider)
        self._version += 1
        return existing

    def add_provider(self, capability_id: str, provider: CapabilityProvider) -> bool:
        """给能力挂一个 provider。provider_id 已存在时不重复添加，返回是否真的加了。"""
        capability = self._capabilities.get(capability_id)
        if capability is None:
            return False
        provider.capability_id = capability_id
        if any(p.provider_id == provider.provider_id for p in capability.providers):
            return False
        capability.providers.append(provider)
        self._claim(provider)
        self._version += 1
        return True

    def _claim(self, provider: CapabilityProvider) -> None:
        """记录工具归属。已被别的能力认领过的工具不改归属（先到先得）。

        先到先得而不是后来者胜出：加载顺序里显式声明（TOML）一定早于自动派生
        （要等插件加载完），所以「先到」天然等于「显式优先」。
        """
        if provider.kind != KIND_ASTRBOT_TOOL or not provider.tool_name:
            return
        self._claimed_tools.setdefault(provider.tool_name, provider.capability_id)

    def clear(self) -> None:
        """清空注册表（测试与热重载用）。"""
        self._capabilities.clear()
        self._claimed_tools.clear()
        self._version += 1

    # ---------- 查询 ----------

    def get(self, capability_id: str) -> Capability | None:
        return self._capabilities.get(capability_id)

    def all(self) -> list[Capability]:
        """全部能力，按 id 排序（保证遍历确定性，便于测试与日志比对）。"""
        return sorted(self._capabilities.values(), key=lambda c: c.id)

    def ids(self) -> list[str]:
        return sorted(self._capabilities)

    def routable(self) -> list[Capability]:
        """可被路由的能力：``route_enabled`` 且至少有一个可用 provider，且有原型语料。

        没有 provider 的能力路由到了也执行不了（Comes 会直接 failed），
        提前排除掉可以少一次无用的 27B 往返。

        ``route_enabled=False`` 的能力被排除在**所有**路由级别之外（L0 关键词、
        L1 语义、L2 兜底），因为三者都以本方法为候选集来源。这是「声明优先」策略的
        唯一执行点：未声明的插件工具不参与能力竞争。
        """
        return [
            c
            for c in self.all()
            if c.route_enabled and c.enabled_providers() and c.prototype_texts()
        ]

    def find_providers(self, capability_id: str) -> list[CapabilityProvider]:
        """取某能力的可用 provider（按 priority 降序）；能力不存在返回空列表。"""
        capability = self._capabilities.get(capability_id)
        return capability.enabled_providers() if capability else []

    def claimed_by(self, tool_name: str) -> str | None:
        """某工具被哪个能力认领了；未被认领返回 None。"""
        return self._claimed_tools.get(tool_name)

    @property
    def version(self) -> int:
        """注册表版本号，每次变更自增。Router 用它判断原型向量缓存是否过期。"""
        return self._version

    def __len__(self) -> int:
        return len(self._capabilities)

    def __bool__(self) -> bool:
        return bool(self._capabilities)

    def __repr__(self) -> str:
        return f"CapabilityRegistry({len(self)} capabilities, v{self._version})"


# 模块级单例。必须模块级——理由见模块 docstring。
registry = CapabilityRegistry()


__all__ = [
    "AUTO_CAPABILITY_PREFIX",
    "KIND_API",
    "KIND_ASTRBOT_TOOL",
    "KIND_MCP",
    "KIND_NATIVE",
    "Capability",
    "CapabilityProvider",
    "CapabilityRegistry",
    "registry",
]
