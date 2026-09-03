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

## 四层注册通路

| 序 | 层 | 位置 | 由谁决定 |
|---|---|---|---|
| 1 | 用户声明 | ``STELLA_HOME/config/capabilities/*.toml`` | 部署者 |
| 2 | 出厂声明 | ``PROJECT_ROOT/config/capabilities/*.toml`` | 本项目 |
| 3 | 插件自带声明 | ``<插件目录>/capability.toml`` | 插件作者 |
| 4 | 自动派生（本模块） | 扫 ``llm_tools`` 取未被认领的工具 | 无人 |

前三层是**显式声明**（见 ``capability/loader.py``）：把若干工具归入一个语义能力，
带中文 ``examples`` 与 ``keywords``，路由质量最好。第四层是本模块的兜底：把没有被任何
声明认领的活跃工具注册成 ``tool.<工具名>``，装上插件就在注册表里有个位置。

四层的归属判定统一靠 ``registry.claimed_by()`` 的**先到先得**：装配序（``bootstrap``）
从高优先层往低走，而 ``_claim`` 只认第一个来的，所以「先到」天然等于「高优先层胜出」。

## 自动派生能力的先天局限

工具描述是写给**决策器**的指令句（``"当用户询问今天更新什么动画时调用"``）——AstrBot 的
模型是「把全部工具 schema 塞给一个大模型让它选」，这种写法对那个用途是最优的。
但 Router 拿它当**语义原型**去和用户的**问句**算余弦，两种用途要求的文本形态不同：
前者是「什么时候该用我」，后者是「用户会怎么问」。后果是同一语域的几个工具彼此
几乎没有区分度（2026-08-24 实测：5 个 ACG 工具对一句「主管，这是？」给出
0.44/0.41/0.39/0.39/0.39）。

所以自动派生的能力**默认不参与路由**（``ROUTER_ROUTE_AUTO_CAPABILITIES=false``）：
照常注册、照常可被显式指定执行，但 ``route_enabled=False``，不进 ``registry.routable()``。
要让一个工具能被聊天触发，就给它写一份声明——几行 TOML 的一次性成本，
换掉的是「工具假阳」这一类高代价错误（见 config/settings.py 该配置项的注释）。

**这个局限不在运行期用生成去补。** 启动时调模型把 examples 直接灌进内存里的原型向量，
那份语料没有人过目、没有基准、也不留痕，错的 examples 比没有 examples 更糟（会把不相关的
请求吸进来）。**离线**生成是支持的：``deploy plugin-scaffold`` 产出的是磁盘上一份
``capability.toml.draft``，带 ``reviewed = false``，人审改成 ``true`` 才会被载入，
且生成时就打印同域分离度与负样本余量。区别不在「生成」，在于**有没有一道人审闸门和一份
可复算的指标**。详见 ``docs/plugin-spec.md``。
"""

from __future__ import annotations

from typing import Any

from capability.registry import (
    AUTO_CAPABILITY_PREFIX,
    KIND_ASTRBOT_TOOL,
    SOURCE_AUTO,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry


def _settings() -> Any:
    """读 config.settings 的属性而不是 ``from config import X``（见 router/semantic.py）。"""
    from config import settings

    return settings


def _logger():
    from nonebot import logger

    return logger


def auto_capability_id(tool_name: str) -> str:
    """自动派生能力的 id：``tool.<工具名>``。"""
    return f"{AUTO_CAPABILITY_PREFIX}{tool_name}"


def install_tool_probe(target: CapabilityRegistry | None = None) -> bool:
    """让注册表能查「声明指向的工具此刻在不在」。返回是否装上。

    **只有 Bot 进程该调这个，而且要在 ``bootstrap()`` 之前调**（顺序决定了
    ``bootstrap`` 回的 ``routable`` 统计是不是真话——那行日志正是部署者排查
    「怎么一个插件都没装还说有 5 项能力」时第一个看的东西）。理由与「为什么不是
    注册表自己去查」都在 ``CapabilityRegistry.set_tool_probe`` 的 docstring 里。

    **不放进 ``bootstrap()``**：``capability/router/benchmark.py`` 与
    ``deploy/plugin_scaffold.py`` 也走 ``bootstrap()``，它们在没加载插件的独立进程里
    量声明本身的路由质量，装上探针会让它们一起变成空跑。

    读不到 ``llm_tools`` 时**不装**（返回 False）而不是装一个永远说「不在」的探针：
    那等于把「兼容层没起来」误报成「你的插件都没装」，而后者会把人送去翻插件目录。
    """
    try:
        from astrbot_compat.llm.tool import llm_tools
    except Exception as exc:  # 兼容层没起来（理论上不该发生）
        _logger().warning(f"🧩 [Capability] 工具存活探针未装上（读不到 llm_tools）：{exc}")
        return False

    def _live(tool_name: str) -> bool:
        """判据与 comes/executor.resolve_tools 逐字一致：查得到且 active。"""
        tool = llm_tools.get_tool(tool_name)
        return tool is not None and bool(getattr(tool, "active", True))

    reg = target if target is not None else _default_registry
    reg.set_tool_probe(_live)
    return True


def _build_auto_capability(tool: Any, route_enabled: bool) -> Capability:
    """把一个 FunctionTool 包成一个单 provider 的能力。

    ``route_enabled`` 由 ``ROUTER_ROUTE_AUTO_CAPABILITIES`` 决定，见模块 docstring。
    """
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
        route_enabled=route_enabled,
        source=SOURCE_AUTO,
        providers=[
            CapabilityProvider(
                provider_id=f"{cap_id}#{tool.name}",
                capability_id=cap_id,
                kind=KIND_ASTRBOT_TOOL,
                tool_name=tool.name,
                source=SOURCE_AUTO,
            ),
        ],
    )


def sync_astrbot_tools(
    target: CapabilityRegistry | None = None,
    tool_manager=None,
    route_enabled: bool | None = None,
) -> dict[str, int]:
    """把 ``llm_tools`` 里的活跃工具同步进能力注册表。

    参数:
        target: 目标注册表，缺省用模块级单例；
        tool_manager: 工具注册表（测试注入点），缺省用 ``llm_tools``；
        route_enabled: 派生出的能力是否参与路由。缺省读
            ``ROUTER_ROUTE_AUTO_CAPABILITIES``（默认 False，声明优先）。

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
    if route_enabled is None:
        route_enabled = bool(_settings().ROUTER_ROUTE_AUTO_CAPABILITIES)

    stats = {"derived": 0, "claimed": 0, "skipped": 0}
    unrouted: list[str] = []
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
        reg.register(_build_auto_capability(tool, route_enabled))
        if len(reg) > before:
            stats["derived"] += 1
            if not route_enabled:
                unrouted.append(name)

    if stats["derived"] or stats["claimed"]:
        _logger().info(
            f"🧩 [Capability] 插件工具同步完成：自动派生 {stats['derived']} 项，"
            f"已由声明认领 {stats['claimed']} 项，未激活跳过 {stats['skipped']} 项",
        )
    # 未声明的工具不参与路由是**刻意的**，但绝不能是无声的：不点名的话，
    # 现象是「插件装了、日志也说派生成功了、可就是从来不被调用」，极难定位。
    if unrouted:
        _logger().warning(
            f"🧩 [Capability] 以下 {len(unrouted)} 个工具没有能力声明，"
            f"不参与语义路由（聊天中不会被触发）: {unrouted}。"
            f"要启用请任选一条：在 config/capabilities/<域名>.toml 里为它写一条 "
            f"[[capability]]；或在插件目录里放一份 capability.toml"
            f"（``python -m deploy plugin-check <插件目录>`` 会告诉你缺哪条，"
            f"格式见 docs/plugin-spec.md）；或设 ROUTER_ROUTE_AUTO_CAPABILITIES=true "
            f"恢复旧行为",
        )
    return stats


def bootstrap(target: CapabilityRegistry | None = None) -> dict[str, int]:
    """启动期一次性装配：三层声明从高到低，最后自动派生剩余工具。

    **顺序不可交换**（层内层间都一样）：高优先层必须先注册，才能通过 ``claimed_by``
    抢下工具归属。反过来的话低层会先把工具占住——自动派生尤其霸道，它会把每个工具都
    占成 ``tool.<name>``，显式声明再想认领同一个工具就抢不到了（``_claim`` 先到先得），
    于是精心写的中文 examples 永远不会被用到——而这不报错，只表现为「路由准确率没提升」。

    返回的统计里 ``routable`` 是**真正会参与路由竞争的能力数**——这个数才决定
    Router 的行为；``declared`` / ``plugin_declared`` / ``derived`` 只说明注册表里有什么。
    ``declared`` 含插件层，``plugin_declared`` 是其中来自插件自带声明的部分（单独列出来是
    因为它回答的是「谁决定了 Bot 会调什么」，与用户自己写的那些不是一回事）。
    """
    from capability.loader import load_declaration_tiers

    tiers = load_declaration_tiers(target)
    stats = sync_astrbot_tools(target)
    stats["declared"] = tiers["declared"]
    stats["plugin_declared"] = tiers["plugin"]
    reg = target if target is not None else _default_registry
    stats["routable"] = len(reg.routable())
    return stats


__all__ = [
    "auto_capability_id",
    "bootstrap",
    "install_tool_probe",
    "sync_astrbot_tools",
]
