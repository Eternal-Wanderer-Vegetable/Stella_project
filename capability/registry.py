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
from collections.abc import Callable
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

# 注册来源。声明分三层（用户 > 出厂 > 插件自带），自动派生垫底；层间归属靠
# ``claimed_by`` 的先到先得判定，来源标记只用于诊断展示与 ``deploy plugin-check``。
SOURCE_CONFIG = "config"  # config/capabilities/*.toml（用户数据目录或程序目录）
SOURCE_PLUGIN = "plugin"  # 插件自带的 <插件目录>/capability.toml
SOURCE_AUTO = "auto"  # 未被任何声明认领的插件工具，启动时自动派生


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
        source: 注册来源，见 SOURCE_* 常量，用于「显式声明优先」的归属判定与诊断；
        failures: 连续失败次数。达到阈值后进入退避（见 ``available``）；
        disabled_until: 退避到期的时间戳（``time.time()`` 纪元秒）。0 表示未退避。
    """

    provider_id: str
    capability_id: str
    kind: str = KIND_ASTRBOT_TOOL
    tool_name: str = ""
    priority: int = 0
    enabled: bool = True
    source: str = SOURCE_CONFIG
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
            理由见 ``capability/adapters/astrbot.py``；
        source: 注册来源，见 SOURCE_* 常量。**只用于诊断展示与校验**，不参与任何
            路由逻辑——层间优先级由 ``claimed_by`` 的先到先得决定，不看这个字段。
    """

    id: str
    domain: str = ""
    description: str = ""
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    providers: list[CapabilityProvider] = field(default_factory=list)
    route_enabled: bool = True
    source: str = ""

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
        # 「这个工具此刻真的在吗」探针。见 ``set_tool_probe``：None = 不校验。
        self._tool_probe: Callable[[str], bool] | None = None

    def set_tool_probe(self, probe: Callable[[str], bool] | None) -> None:
        """装上（或用 ``None`` 卸掉）「工具此刻真的在吗」探针，供 ``routable`` 查询。

        为什么这件事必须由**调用方注入**而不是注册表自己去查：注册表不许 import
        ``astrbot_compat``（它是 Provider 的一种实现方式，不是能力层的依赖），而更要紧
        的是「工具不在」这件事在不同进程里的**含义不同**：

        * Bot 进程里，工具不在就是不在——声明指向的插件没装（或工具名拼错），路由到
          它只会换来 Comes 的一句失败。这种能力必须从候选集里消失，否则出厂自带的
          声明会在一个插件都没装的部署上被答成「我能做这 5 件事」（bug_report_2026_9_2#1）。
        * ``deploy plugin-scaffold`` 与 ``python -m capability.router.benchmark`` 是独立
          进程，插件根本没加载，``llm_tools`` 必然是空的。它们量的是**声明本身**的路由
          质量（见 ``capability/router/benchmark.py`` 模块 docstring），按「工具不在」把
          声明全滤掉的话，这两个工具会一起变成空跑。

        两者靠「探针装没装」区分，而不是靠工具注册表是不是空的——空注册表在这两种
        场合里长得一模一样。所以：**只有 Bot 进程装探针**（见
        ``capability.adapters.astrbot.install_tool_probe``），离线进程不装、行为不变。

        探针在**查询时**才被调用，因此插件热重载后不用重装：判定跟着 ``llm_tools``
        的当前内容走，不会留下一份装配时的快照（快照的表现是「重载完了清单还是旧的」）。

        探针**不许抛异常**。装不上（读不到 ``llm_tools``）时就别装，那是安装点的事——
        在这里兜底只会把「探针坏了」和「工具确实不在」混成同一个结论。
        """
        if probe is self._tool_probe:
            return
        self._tool_probe = probe
        # 探针一装/一卸，``routable()`` 的答案就变了，Router 的原型缓存必须跟着失效
        self._version += 1

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
        # source 同理保留先到的那个：它记录的是「这条能力是谁定义的」，而先到
        # 的那一层按定义就是优先级最高的那一层。
        existing.source = existing.source or capability.source
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
        """清空注册表（测试与热重载用）。

        **不动探针**：它是进程级接线（谁在跑这份注册表），不是注册表的内容。热重载
        会清掉能力再重装，顺手卸掉探针的话，重载后所有声明都会重新变成「可路由」。
        """
        self._capabilities.clear()
        self._claimed_tools.clear()
        self._version += 1

    def unregister(self, capability_id: str) -> bool:
        """摘掉一个能力并释放它认领过的工具。返回它原本是否存在。

        热重载**必须**走这里，不许自己 pop ``_capabilities``：归属表不一起清的话，
        工具会永远被一个已不存在的能力认领着，而 ``_claim`` 是先到先得，于是重载后
        插件重新注册的声明**抢不到自己的工具**——这不报错，只表现为「重载完就路由不到了」。

        按 owner 反查而不是遍历 ``capability.providers``：provider 可能是事后经
        ``add_provider`` 挂上的，两处不一定同步，归属表才是判定归属的那一份。
        """
        capability = self._capabilities.pop(capability_id, None)
        if capability is None:
            return False
        for tool_name, owner in list(self._claimed_tools.items()):
            if owner == capability_id:
                del self._claimed_tools[tool_name]
        self._version += 1
        return True

    def release_tool(self, tool_name: str) -> bool:
        """释放单个工具的归属，让后续注册能重新认领它。返回它原本是否被认领着。"""
        if self._claimed_tools.pop(tool_name, None) is None:
            return False
        self._version += 1
        return True

    # ---------- 查询 ----------

    def get(self, capability_id: str) -> Capability | None:
        return self._capabilities.get(capability_id)

    def all(self) -> list[Capability]:
        """全部能力，按 id 排序（保证遍历确定性，便于测试与日志比对）。"""
        return sorted(self._capabilities.values(), key=lambda c: c.id)

    def ids(self) -> list[str]:
        return sorted(self._capabilities)

    def _tool_live(self, provider: CapabilityProvider) -> bool:
        """provider 指向的实现此刻是否真的存在。没装探针时一律为 True。

        判据与 ``capability/comes/executor.py`` 的 ``resolve_tools`` **必须逐条对齐**：
        非 ``astrbot_tool`` 的 kind 本轮不支持，工具查不到或 ``active=False`` 都算不在。
        对不齐的表现是「路由挑中了它，Comes 立刻回一句『工具全部不可用』」——用户看到
        的是 Stella 答非所问，而日志里两边各自都觉得自己没错。
        """
        probe = self._tool_probe
        if probe is None:
            return True
        if provider.kind != KIND_ASTRBOT_TOOL or not provider.tool_name:
            return False
        return probe(provider.tool_name)

    def live_providers(self, capability: Capability) -> list[CapabilityProvider]:
        """既可用、又确实落到一个存在实现上的 provider（priority 降序）。

        与 ``Capability.enabled_providers`` 的差别只有探针那一层：后者是纯数据判断
        （人工开关 + 退避窗），够不着「工具在不在」这种进程状态。
        """
        return [p for p in capability.enabled_providers() if self._tool_live(p)]

    def routable(self) -> list[Capability]:
        """可被路由的能力：``route_enabled`` 且至少有一个**能真的跑起来的** provider，
        且有原型语料。

        没有 provider 的能力路由到了也执行不了（Comes 会直接 failed），
        提前排除掉可以少一次无用的 27B 往返。「跑不起来」不止是人工关闭和退避——
        声明指向的工具压根没装也算（判据见 ``_tool_live``，只在装了探针的进程里生效）。
        少了这一条，一个插件都没装的部署会把出厂自带的声明当成自己的能力报出去
        （bug_report_2026_9_2#1），而且那 5 条原型还会挤在真能力旁边参与语义竞争。

        ``route_enabled=False`` 的能力被排除在**所有**路由级别之外（L0 关键词、
        L1 语义、L2 兜底），因为三者都以本方法为候选集来源。这是「声明优先」策略的
        唯一执行点：未声明的插件工具不参与能力竞争。
        """
        return [
            c
            for c in self.all()
            if c.route_enabled and self.live_providers(c) and c.prototype_texts()
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
    "SOURCE_AUTO",
    "SOURCE_CONFIG",
    "SOURCE_PLUGIN",
    "Capability",
    "CapabilityProvider",
    "CapabilityRegistry",
    "registry",
]
