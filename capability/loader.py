# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""能力声明文件加载：TOML 声明 → Capability Registry。

读法照 ``config/spaces.py`` 的惯例：``tomllib``（Py3.10 回退 ``tomli``），
**文件名即 domain**，单个文件解析失败只跳过该文件不中断其余加载。

## 三层声明

声明有三个来源，优先级 **用户 > 出厂 > 插件自带**，垫底的是
``adapters/astrbot.py`` 的自动派生：

| 序 | 层 | 位置 | source |
|---|---|---|---|
| 1 | 用户 | ``STELLA_HOME/config/capabilities/*.toml`` | ``config`` |
| 2 | 出厂 | ``PROJECT_ROOT/config/capabilities/*.toml`` | ``config`` |
| 3 | 插件自带 | ``<插件目录>/capability.toml`` | ``plugin`` |

层间归属靠 ``registry.claimed_by()`` 的**先到先得**判定（与自动派生同一个惯例）：
低优先层的能力若其 id 已存在、或任一 provider 的工具已被别的能力认领，**整条跳过**。
整条跳而不是跳单个 provider——半条能力的 examples/keywords 与 providers 不再自洽，
比缺一条更糟。装配入口是 ``load_declaration_tiers()``。

> 两个目录以前是**二选一**（用户目录存在就完全不读出厂目录）。那是个隐坑：用户目录里
> 只要出现一个文件，随发布包出厂、带实测标定的 ``entertainment.toml`` 就全部失效，
> 而这不报错、只表现为路由变差。现在改成按层合并 + 按认领跳过，用户的覆盖仍然逐条生效。

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

**声明不是可选的加分项**（``ROUTER_ROUTE_AUTO_CAPABILITIES=false`` 起，即默认）：
没有声明的插件工具照常注册、仍可被显式执行，但**不参与语义路由**，聊天里不会被触发。
写声明的收益在路由质量上——中文 ``examples`` 让 Level 1 语义匹配显著变准，
``keywords`` 让高频请求走零延迟的 Level 0。完整规范见 ``docs/plugin-spec.md``。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底（pyproject requires-python >=3.10）
    import tomli as tomllib

from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_CONFIG,
    SOURCE_PLUGIN,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry

# 插件自带声明的固定文件名。``plugin-scaffold`` 生成的草稿叫 ``capability.toml.draft``，
# 文件名不匹配所以天然不会被载入——这是 reviewed 闸门之外的第一道。
PLUGIN_DECL_FILENAME = "capability.toml"
# 草稿名放在这里而不是 ``plugin_scaffold``：产出方（scaffold）与检查方（plugin-check）
# 都要认这个名字，各写一个字面量的话改名时必然漏一处，而漏的表现是「校验说没草稿、
# 实际有一份没人审的躺在那」。加载器自己不读它，只负责定义它叫什么。
PLUGIN_DECL_DRAFT_FILENAME = "capability.toml.draft"
# 插件自带声明里没写 domain 时的缺省域。与自动派生那层同名，语义也一样：
# 「这条能力来自插件，没归进任何既有语义域」。
PLUGIN_DECL_DOMAIN = "plugin"


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
    source: str = SOURCE_CONFIG,
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
            source=source,
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
            source=source,
        )
    _logger().warning(
        f"⚠️ [Capability] {capability_id} 的第 {index + 1} 个 provider 既不是工具名也不是表，已跳过",
    )
    return None


def _parse_capability(raw: Any, domain: str, source: str = SOURCE_CONFIG) -> Capability | None:
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
        source=source,
    )

    providers_raw = raw.get("providers") or []
    if not isinstance(providers_raw, list):
        _logger().warning(f"⚠️ [Capability] {cap_id} 的 providers 不是列表，已忽略")
        providers_raw = []
    for i, item in enumerate(providers_raw):
        provider = _parse_provider(item, cap_id, i, source)
        if provider is not None:
            capability.providers.append(provider)
    return capability


def _shadowed_by(reg: CapabilityRegistry, capability: Capability) -> str:
    """这条能力是否已被更高优先层拿下。返回顶掉它的能力 id，没被顶掉返回空串。

    两条判据缺一不可：
    - **同 id 已注册**：涵盖没有 provider 的能力（那种没有工具可供认领判定）；
    - **任一 provider 的工具已被别的能力认领**：涵盖「换了个 id 声明同一个工具」，
      这是用户覆盖插件声明的常见写法（用户未必知道插件把它叫什么 id）。
    """
    if reg.get(capability.id) is not None:
        return capability.id
    for provider in capability.providers:
        if provider.kind != KIND_ASTRBOT_TOOL or not provider.tool_name:
            continue
        owner = reg.claimed_by(provider.tool_name)
        if owner:
            return owner
    return ""


class ParsedDeclaration(NamedTuple):
    """一份声明文件的解析结果，**不含任何注册动作**。

    ``error`` 非空表示整份文件不可用（TOML 语法错、缺 ``[[capability]]`` 段等）；
    ``reviewed`` 为 ``None`` 表示键缺省（视为已审，见 ``load_capability_file``）。
    """

    capabilities: list[Capability]
    reviewed: bool | None
    error: str


def parse_declaration(
    path: Path,
    *,
    source: str = SOURCE_CONFIG,
    domain: str | None = None,
) -> ParsedDeclaration:
    """解析一份声明文件但不注册，供校验器与加载器共用。

    ``deploy plugin-check`` 必须走这里而不是自己再解析一遍 TOML：两套解析必然漂移，
    而漂移的表现是「校验说没问题、运行期却少一条能力」——校验器一旦不可信就没有意义了。

    参数:
        path: 声明文件；
        source: 落到 ``Capability.source`` 与各 provider 的来源标记；
        domain: 缺省的 domain（能力自己写了 ``domain`` 键时以它为准）。
            传 ``None`` 时取文件名——那是 ``config/capabilities/<域名>.toml``
            的惯例；插件自带的那份文件名固定叫 ``capability.toml``，取文件名会得到
            一个叫「capability」的假域，所以调用方要显式给（见 ``load_plugin_capabilities``）。
    """
    dom = path.stem if domain is None else domain
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except Exception as e:
        return ParsedDeclaration([], None, f"TOML 解析失败: {e}")

    reviewed = data.get("reviewed")
    if not isinstance(reviewed, bool):
        reviewed = None

    entries = data.get("capability")
    if entries is None:
        return ParsedDeclaration([], reviewed, "缺少 [[capability]] 段")
    # 允许单个 [capability] 表（TOML 里写成非数组），省掉一类容易犯的格式错
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return ParsedDeclaration([], reviewed, "capability 段格式非法（既不是数组也不是表）")

    capabilities: list[Capability] = []
    for raw in entries:
        capability = _parse_capability(raw, dom, source)
        if capability is not None:
            capabilities.append(capability)
    return ParsedDeclaration(capabilities, reviewed, "")


def load_capability_file(
    path: Path,
    target: CapabilityRegistry | None = None,
    *,
    source: str = SOURCE_CONFIG,
    skip_claimed: bool = False,
    require_reviewed: bool = False,
    domain: str | None = None,
) -> int:
    """载入单个声明文件，返回成功注册的能力数。解析失败返回 0（只记日志）。

    参数:
        path: 声明文件；
        target: 目标注册表，缺省为模块级单例；
        source: 落到 ``Capability.source`` 与各 provider 的来源标记；
        skip_claimed: 低优先层用。为真时已被更高层拿下的能力**整条跳过**
            （判据见 ``_shadowed_by``），并记一条 INFO 说明被谁顶掉了；
        require_reviewed: 插件层用。为真时顶层键 ``reviewed = false`` 的文件整份不载入；
        domain: 缺省 domain，透传给 ``parse_declaration``。
    """
    reg = target if target is not None else _default_registry
    parsed = parse_declaration(path, source=source, domain=domain)
    if parsed.error:
        _logger().error(f"⚠️ [Capability] {path.name} 不可用，跳过该文件: {parsed.error}")
        return 0

    # reviewed 闸门：只拦**显式**写了 false 的（``plugin-scaffold`` 生成的草稿就是这样）。
    # 键缺省视为已审——手写声明的插件作者是在直接编写而不是审阅草稿，要求他多写一行
    # ``reviewed = true`` 只会造出一类新的静默失效（写了声明却不生效且不知道为什么）。
    if require_reviewed and parsed.reviewed is False:
        _logger().warning(
            f"⚠️ [Capability] {path} 标记为 reviewed = false，整份未载入。"
            f"这是 plugin-scaffold 生成的草稿——人工核对 examples 与 keywords 后"
            f"把该键改为 true 才会生效（理由见 docs/plugin-spec.md）",
        )
        return 0

    count = 0
    for capability in parsed.capabilities:
        if skip_claimed:
            owner = _shadowed_by(reg, capability)
            if owner:
                _logger().info(
                    f"🧩 [Capability] {path.name} 的 {capability.id} 已由更高优先层的 "
                    f"{owner} 认领，本条跳过（优先级：用户 > 出厂 > 插件自带）",
                )
                continue
        reg.register(capability)
        count += 1
    return count


def load_capabilities(
    directory: Path | None = None,
    target: CapabilityRegistry | None = None,
    *,
    source: str = SOURCE_CONFIG,
    skip_claimed: bool = False,
) -> int:
    """扫描声明目录并全部载入，返回注册的能力总数。

    参数:
        directory: 声明目录。缺省时按 **用户层 → 出厂层** 两层依次载入
            （见 ``_config_declaration_dirs``），而不是二选一；
        target: 目标注册表，缺省为模块级单例；
        source: 来源标记，透传给 ``load_capability_file``；
        skip_claimed: 是否跳过已被更高层认领的能力，透传给 ``load_capability_file``。
            只在显式传 ``directory`` 时有意义；缺省的两层模式各层自带取值。

    目录不存在或无 ``.toml`` 时正常返回 0。排序遍历保证多文件间的注册顺序确定。
    """
    if directory is None:
        total = 0
        # 第一层（用户）不跳过任何东西；其后的层（出厂）跳过已被更高层认领的
        for index, tier_dir in enumerate(_config_declaration_dirs()):
            total += load_capabilities(
                tier_dir,
                target,
                source=source,
                skip_claimed=index > 0,
            )
        return total

    if not directory.is_dir():
        return 0

    total = 0
    for path in sorted(directory.glob("*.toml")):
        total += load_capability_file(
            path,
            target,
            source=source,
            skip_claimed=skip_claimed,
        )
    if total:
        # 打完整路径而不是 directory.name：两层的目录名都叫 capabilities，
        # 只打名字的话日志里看不出这批声明来自用户目录还是出厂目录。
        _logger().info(f"🧩 [Capability] 已载入 {total} 项声明能力（{directory}）")
    return total


def _config_declaration_dirs() -> list[Path]:
    """声明目录的两层：用户数据目录优先，程序目录（出厂）垫在后面。

    以前这里是**二选一**（用户目录存在就完全不读出厂目录），那让「用户目录里出现任意
    一个文件」等价于「丢掉全部出厂声明」——包括随发布包出厂、带实测标定的
    ``entertainment.toml``。而这不报错，只表现为路由质量下降。

    现在两层都读，出厂层按认领跳过：用户的覆盖仍然逐条生效（同 id 或同工具的那条
    由用户那份胜出），没被覆盖的出厂声明照旧可用。升级时新出厂默认值也能到达。

    两者 ``resolve()`` 相同时（开发机、自包含布局）只返回一个，别把同一批读两遍。
    """
    from config import PROJECT_ROOT, STELLA_HOME

    dirs: list[Path] = []
    seen: set[Path] = set()
    for base in (STELLA_HOME, PROJECT_ROOT):
        path = base / "config" / "capabilities"
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            continue
        seen.add(key)
        dirs.append(path)
    return dirs


def _plugin_declaration_paths() -> list[tuple[str, Path]]:
    """已加载插件的 ``capability.toml`` 路径，返回 ``[(插件名, 路径), ...]``。

    **只看已成功加载的插件**（``star_registry``），不扫插件目录。import 失败的插件
    没有登记任何工具，载入它的声明会造出「provider 指向不存在工具」的能力——而
    ``routable()`` 只查 enabled/backoff、不查工具是否存在，于是那条能力会照常参与
    路由竞争、抢走 ``ROUTER_CAPABILITY_MARGIN`` 的间距，最后必然在 Comes 里 failed。

    插件目录由模块的 ``__file__`` 反推而不是拼 ``ASTRBOT_PLUGINS_DIR``：目录名不合法
    或插件目录被配置到项目外时，插件是按文件路径挂载的，拼出来的路径不一定对。
    """
    from astrbot_compat.registry import star_registry

    found: list[tuple[str, Path]] = []
    for md in list(star_registry):
        if not md.activated or md.star_cls is None:
            continue
        main_file = getattr(md.module, "__file__", None)
        if not main_file:
            continue
        try:
            path = Path(main_file).resolve().parent / PLUGIN_DECL_FILENAME
        except OSError:
            continue
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        found.append((md.root_dir_name or md.name or md.plugin_id, path))
    found.sort(key=lambda item: item[0])
    return found


def load_plugin_capabilities(target: CapabilityRegistry | None = None) -> int:
    """载入插件自带的 ``<插件目录>/capability.toml``，返回注册的能力数。

    这是三层里**优先级最低**的一层：已被用户层或出厂层认领的能力整条跳过。
    受 ``ASTRBOT_PLUGIN_CAPABILITIES_ENABLED`` 控制（默认开）——插件自带声明意味着
    插件作者决定自己的工具能在聊天里被自动调用，而这件事以前需要用户手写 TOML 才成立，
    所以留一个能把这份授权收回的开关。
    """
    try:
        from config.settings import ASTRBOT_PLUGIN_CAPABILITIES_ENABLED

        enabled = ASTRBOT_PLUGIN_CAPABILITIES_ENABLED
    except Exception:
        enabled = True
    if not enabled:
        _logger().info(
            "🧩 [Capability] ASTRBOT_PLUGIN_CAPABILITIES_ENABLED=false，跳过插件自带声明",
        )
        return 0

    total = 0
    loaded: list[str] = []
    for plugin_name, path in _plugin_declaration_paths():
        count = load_capability_file(
            path,
            target,
            source=SOURCE_PLUGIN,
            skip_claimed=True,
            require_reviewed=True,
            # 文件名固定叫 capability.toml，取文件名会得到一个叫「capability」的假域，
            # 而 domain 会露在能力查询的分组里、也是同域分离度的分组依据。
            # 「plugin」与自动派生那层用的是同一个域名；插件想归到别的语义域就在
            # 自己那条 [[capability]] 里显式写 domain（规范里要求写）。
            domain=PLUGIN_DECL_DOMAIN,
        )
        if count:
            total += count
            loaded.append(f"{plugin_name}({count})")
    # 点名而不是只报总数：「这条能力是插件自己声明的」是用户唯一能察觉
    # 「谁决定了 Bot 会调什么」的地方。
    if loaded:
        _logger().info(f"🧩 [Capability] 插件自带声明已载入 {total} 项：{', '.join(loaded)}")
    return total


def load_declaration_tiers(target: CapabilityRegistry | None = None) -> dict[str, int]:
    """按 **用户 > 出厂 > 插件自带** 三层载入全部声明，返回各层计数。

    **层序不可交换**：高优先层必须先注册，才能通过 ``claimed_by`` 抢下工具归属
    （``_claim`` 是先到先得）。反过来的话低优先层会先占住工具，用户精心写的覆盖
    永远不会被用到——而这不报错，只表现为「改了声明但路由没变」。

    本函数之后还必须跑 ``adapters/astrbot.py::sync_astrbot_tools``（自动派生垫底），
    整条装配序由 ``bootstrap()`` 负责。
    """
    config_count = load_capabilities(target=target)
    plugin_count = load_plugin_capabilities(target=target)
    return {
        "config": config_count,
        "plugin": plugin_count,
        "declared": config_count + plugin_count,
    }


__all__ = [
    "PLUGIN_DECL_DOMAIN",
    "PLUGIN_DECL_DRAFT_FILENAME",
    "PLUGIN_DECL_FILENAME",
    "ParsedDeclaration",
    "load_capabilities",
    "load_capability_file",
    "load_declaration_tiers",
    "load_plugin_capabilities",
    "parse_declaration",
]
