# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""能力清单：把注册表的状态变成「人能看懂」与「机器能读」两种形态。

三个 surface 共用本模块：群里问「你能做什么」、``python -m deploy capabilities``、
状态接口 ``GET /stella/status`` 的 ``capabilities`` 块。**同一份数据源**是刻意的——
三处各遍历一遍注册表必然漂移，而漂移的表现是「CLI 说这条可路由、群里说不可路由」，
到那时用户没有任何办法判断哪一个在说谎。

两种形态的区别只在**要不要自由文本**：

- ``snapshot()``：纯结构化字段（id / domain / source / 是否可路由 / 工具名 /
  工具是否真的存在 / 退避状态 / examples 条数）。它会经状态接口出到回环端口，而
  ``tests/test_status_api.py`` 钉住了「响应体不含凭据与群聊内容」——``description``
  与 ``examples`` 原文是唯一可能夹带 URL 与密钥的字段，不放进去就不必为它加一道守卫。
  原文在本机 TOML 里，要看直接读那三层文件（``offline_declarations()``）。
- ``chat_overview()``：给人看的文本，带描述。来源层、provider 健康度、未声明工具的
  具体名单属排查信息，**只给管理员**；普通群友能看到可路由能力清单与未声明工具的**条数**。

注册表是**进程内**的模块级单例，别的进程拿不到，所以 ``deploy capabilities`` 只能走
状态接口；Bot 没运行时退到 ``offline_declarations()`` 读磁盘上的声明——那份数据回答不了
「到底可不可路由」（要看工具存不存在、插件加载成不成功、自动派生那层有没有把工具占走），
渲染方必须说清这一点。
"""

from __future__ import annotations

import contextlib
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from capability.registry import (
    KIND_ASTRBOT_TOOL,
    SOURCE_AUTO,
    SOURCE_CONFIG,
    SOURCE_PLUGIN,
    Capability,
    CapabilityProvider,
    CapabilityRegistry,
)
from capability.registry import registry as _default_registry

# 快照结构版本。GUI 与 CLI 按它判断字段布局：加字段不必动它，改/删字段要 +1。
SNAPSHOT_VERSION = 1

# provider 指向的工具在 ``llm_tools`` 里的真实状态。``unknown`` 与 ``missing`` 必须分开：
# 「工具不存在」会把人引到插件目录去找问题，而「读不到工具注册表」的原因在别处。
TOOL_OK = "ok"
TOOL_INACTIVE = "inactive"  # 存在但 active=False —— Comes 视同缺失（见 comes/executor.py）
TOOL_MISSING = "missing"  # 工具注册表里没有这个名字
TOOL_UNKNOWN = "unknown"  # 读不到工具注册表，或 provider 不是 astrbot_tool

# 域名 → 中文标签。缺的域直接显示原名，不猜也不报错：域名由声明文件名决定，
# 用户完全可以建一个我们没预料到的域。
DOMAIN_LABELS = {
    "information": "资讯查询",
    "entertainment": "娱乐",
    "memory": "记忆",
    "plugin": "插件工具",
}

SOURCE_LABELS = {
    SOURCE_CONFIG: "配置声明",
    SOURCE_PLUGIN: "插件自带",
    SOURCE_AUTO: "自动派生",
    "": "未标注",
}

# 群里触发能力查询的说法。刻意只收**问功能**的句式，不收「帮我查天气」这类真实请求
# ——后者要交给正常对话链路。
QUERY_KEYWORDS = (
    "你能做什么",
    "你能做些什么",
    "你会做什么",
    "你能干什么",
    "你会干什么",
    "你会什么",
    "有什么功能",
    "有哪些功能",
    "功能列表",
    "能力列表",
    "有什么本事",
    "会哪些技能",
    "会什么技能",
)

# 既有语义域的展示顺序；``plugin`` 与未知域排在其后（前者是装上来的，后者是用户自建的）。
_DOMAIN_ORDER = ("information", "entertainment", "memory")

_CHAT_DESC_MAX = 40  # 单条能力描述的截断长度
_CHAT_MAX_ITEMS = 40  # 群内最多列几条能力
_CHAT_MAX_COMMANDS = 10  # 群内最多列几条指令
_CHAT_MAX_TOOLS = 12  # 管理员那行最多点名几个工具


def is_query_text(text: str, *, toggle_keywords: Sequence[str] = ()) -> bool:
    """这句话是不是一次能力查询。命中 ``toggle_keywords`` 时**一律返回 False**。

    互斥判定放在这里而不是靠「两张词表刚好不重叠」：能力查询与主动发言开关在
    ``ai_gateway.py`` 里同优先级、且都是 ``block=True``，而 NoneBot 会把同优先级的
    matcher 一起跑。一句「恢复一下，你能做什么」会同时命中两者，其中一个**会改群设置**。
    机械互斥是可验证的，「词表不重叠」不是——加词的人不会去查另一张表。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if any(k and k in stripped for k in toggle_keywords):
        return False
    return any(k in stripped for k in QUERY_KEYWORDS)


# ---------- 结构化快照 ----------


def _tool_states(tool_manager: Any = None) -> dict[str, bool] | None:
    """工具名 → 是否激活。取不到工具注册表时返回 ``None``（表示「未知」而非「空」）。

    区分 ``None`` 与空字典是必要的：空字典会把每个 provider 都标成「工具不存在」，
    而那句话在插件确实没装时是对的、在 ``astrbot_compat`` 根本没起来时是**谎报**。
    """
    manager = tool_manager
    if manager is None:
        try:
            from astrbot_compat.llm.tool import llm_tools

            manager = llm_tools
        except Exception:
            return None
    tools = getattr(manager, "tools", None)
    if tools is None:
        return None
    states: dict[str, bool] = {}
    try:
        listed = list(tools)
    except Exception:
        return None
    for tool in listed:
        name = str(getattr(tool, "name", "") or "")
        if name:
            states[name] = bool(getattr(tool, "active", True))
    return states


def _tool_state(tool_name: str, states: dict[str, bool] | None) -> str:
    if states is None:
        return TOOL_UNKNOWN
    if tool_name not in states:
        return TOOL_MISSING
    return TOOL_OK if states[tool_name] else TOOL_INACTIVE


def _provider_item(
    provider: CapabilityProvider,
    states: dict[str, bool] | None,
    now: float,
) -> dict[str, Any]:
    """一个 provider 的结构化状态。**不含任何自由文本**（见模块 docstring）。"""
    state = (
        _tool_state(provider.tool_name, states)
        if provider.kind == KIND_ASTRBOT_TOOL
        else TOOL_UNKNOWN
    )
    remaining = 0
    if provider.disabled_until > 0.0:
        remaining = int(max(0.0, provider.disabled_until - now))
    return {
        "tool": provider.tool_name,
        "kind": provider.kind,
        "source": provider.source,
        "priority": provider.priority,
        "enabled": provider.enabled,
        "available": provider.available(now),
        "failures": provider.failures,
        "backoff_seconds": remaining,
        "tool_state": state,
    }


def snapshot(
    *,
    target: CapabilityRegistry | None = None,
    tool_manager: Any = None,
    now: float | None = None,
) -> dict[str, Any]:
    """注册表的结构化快照，可直接进 JSON 响应体。

    ``routable`` 逐条取自 ``registry.routable()`` 而不是自己重算 ``route_enabled and
    providers``：Router 三级都以那个方法为候选集来源，判据只能有一份，否则这份清单会
    在最关键的一个字段上说谎（「明明显示可路由却从来不被调用」正是它要回答的问题）。
    """
    reg = target if target is not None else _default_registry
    stamp = time.time() if now is None else now
    states = _tool_states(tool_manager)
    routable_ids = {c.id for c in reg.routable()}

    items: list[dict[str, Any]] = []
    missing_tools: list[str] = []
    for cap in reg.all():
        providers = [_provider_item(p, states, stamp) for p in cap.providers]
        items.append(
            {
                "id": cap.id,
                "domain": cap.domain,
                "source": cap.source,
                "route_enabled": cap.route_enabled,
                "routable": cap.id in routable_ids,
                "auto": cap.is_auto,
                "examples": len(cap.examples),
                "keywords": len(cap.keywords),
                "providers": providers,
            },
        )
        # 声明里指向不存在的工具是静默失效的头号原因。只看声明层：自动派生那层是从
        # 工具反推出来的，不可能指向不存在的工具，把它算进来只会多出一堆噪音。
        if not cap.is_auto:
            missing_tools.extend(
                str(p["tool"])
                for p in providers
                if p["tool_state"] == TOOL_MISSING and p["tool"]
            )

    auto_items = [i for i in items if i["auto"]]
    return {
        "version": SNAPSHOT_VERSION,
        # 注册表版本号：Router 的原型缓存按它失效，排查「改了声明没生效」时要对照
        "registry_version": reg.version,
        "total": len(items),
        "routable": sum(1 for i in items if i["routable"]),
        "declared": sum(1 for i in items if not i["auto"]),
        "auto": len(auto_items),
        # 未声明且确实不可路由的工具数——这就是「装了插件却从来不被调用」的那批
        "auto_unrouted": sum(1 for i in auto_items if not i["routable"]),
        "tools_known": states is not None,
        "items": items,
        # 指令名是标识符而非自由文本，与工具名同级，所以可以进响应体。收进来是因为
        # 「你能做什么」只答能力、不答指令，对装了一堆 @command 的群就是**误导**。
        "commands": _command_names(),
        "missing_tools": sorted(set(missing_tools)),
    }


def _command_names(limit: int = 60) -> list[str]:
    """已加载插件登记的指令名（不带唤醒前缀）。

    指令**不是能力**：它们靠 ``ASTRBOT_WAKE_PREFIXES`` 前缀显式触发，不参与语义路由，
    所以不在注册表里。别名不列——一条指令挂 5 个别名对「你能做什么」毫无信息量。
    """
    try:
        from astrbot_compat.filters import CommandFilter, CommandGroupFilter
        from astrbot_compat.registry import EventType, star_handlers_registry
    except Exception:
        return []
    try:
        handlers = star_handlers_registry.get_handlers_by_event_type(
            EventType.AdapterMessageEvent,
        )
    except Exception:
        return []

    names: set[str] = set()
    for md in handlers:
        for handler_filter in getattr(md, "event_filters", None) or []:
            if isinstance(handler_filter, CommandFilter):
                parents = [p for p in (handler_filter.parent_command_names or []) if p]
                base = str(handler_filter.command_name or "")
                if not base:
                    continue
                names.add(f"{parents[0]} {base}" if parents else base)
            elif isinstance(handler_filter, CommandGroupFilter):
                try:
                    complete = handler_filter.get_complete_command_names()
                except Exception:
                    continue
                # 该方法按长度倒序返回「主名 + 全部别名」，取最短的那个当展示名
                if complete:
                    names.add(min(complete, key=len))
    return sorted(names)[:limit]


# ---------- 群内文本 ----------


def _domain_label(domain: str) -> str:
    return DOMAIN_LABELS.get(domain) or domain or "其它"


def _source_label(source: str) -> str:
    label = SOURCE_LABELS.get(source)
    return label if label is not None else (source or "未标注")


def _clip(text: str, limit: int) -> str:
    stripped = (text or "").strip()
    return stripped if len(stripped) <= limit else stripped[: limit - 1] + "…"


def _group_by_domain(items: Sequence[dict[str, Any]]) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(str(item.get("domain") or ""), []).append(dict(item))

    def sort_key(domain: str) -> tuple[int, str]:
        if domain in _DOMAIN_ORDER:
            return (_DOMAIN_ORDER.index(domain), domain)
        return (len(_DOMAIN_ORDER) + (1 if domain == "plugin" else 0), domain)

    return [(domain, groups[domain]) for domain in sorted(groups, key=sort_key)]


def wake_prefix() -> str:
    """指令前缀：取 ``ASTRBOT_WAKE_PREFIXES`` 的第一个，读不到时退到 ``/``。"""
    with contextlib.suppress(Exception):
        from config import ASTRBOT_WAKE_PREFIXES

        for prefix in ASTRBOT_WAKE_PREFIXES or []:
            if prefix:
                return str(prefix)
    return "/"


def _capability_line(
    capability: Capability | None,
    item: dict[str, Any],
    *,
    admin: bool,
) -> str:
    """一条能力在群里显示成什么。普通群友只看到描述，管理员多看到 id 与来源层。"""
    desc = _clip(getattr(capability, "description", "") or "", _CHAT_DESC_MAX)
    cap_id = str(item.get("id") or "")
    if not admin:
        return desc or cap_id
    head = f"{cap_id}（{_source_label(str(item.get('source') or ''))}）"
    tail = f" —— {desc}" if desc else ""
    sick = [p for p in item.get("providers") or [] if not p.get("available")]
    warn = f"［{len(sick)} 个实现不可用］" if sick else ""
    return f"{head}{tail}{warn}"


def _admin_lines(snap: dict[str, Any]) -> list[str]:
    """只给管理员的排查信息。每条都对应一个「装了却不生效」的具体成因。"""
    items = list(snap.get("items") or [])
    out: list[str] = []

    counts = Counter(str(i.get("source") or "") for i in items)
    # 空注册表时不要留下「共 0 项：；版本 v0」这种半句——它出现的场合恰好是
    # 「装配根本没跑」，那时读日志的人需要的是一句读得通的话
    detail = "、".join(f"{_source_label(src)} {n} 项" for src, n in sorted(counts.items()))
    out.append(
        f"（管理员）注册表共 {snap.get('total', 0)} 项"
        f"{'：' + detail if detail else ''}；"
        f"版本 v{snap.get('registry_version', 0)}。",
    )

    if not snap.get("tools_known", True):
        out.append("（管理员）读不到工具注册表，「工具是否存在」这一列本次不可信。")

    backoff = [
        f"{i.get('id')}#{p.get('tool')}（连续失败 {p.get('failures')} 次，"
        f"约 {p.get('backoff_seconds')} 秒后恢复）"
        for i in items
        for p in i.get("providers") or []
        if p.get("backoff_seconds")
    ]
    if backoff:
        out.append("（管理员）正在退避：" + "；".join(backoff[:5]))

    off = [
        f"{i.get('id')}#{p.get('tool')}"
        for i in items
        for p in i.get("providers") or []
        if not p.get("enabled")
    ]
    if off:
        out.append("（管理员）已人工关闭的实现：" + "、".join(off[:8]))

    inactive = sorted(
        {
            str(p.get("tool") or "")
            for i in items
            for p in i.get("providers") or []
            if p.get("tool_state") == TOOL_INACTIVE and p.get("tool")
        },
    )
    if inactive:
        out.append(
            "（管理员）这些工具被停用了（active=false），对应能力会被跳过："
            + "、".join(inactive[:8]),
        )

    missing = list(snap.get("missing_tools") or [])
    if missing:
        out.append(
            "（管理员）声明里指向的这些工具不存在："
            + "、".join(str(m) for m in missing[:8])
            + " —— 工具名拼错是静默失效的头号原因，对照插件里 @llm_tool 的函数名核一遍",
        )
    return out


def chat_overview(
    *,
    target: CapabilityRegistry | None = None,
    tool_manager: Any = None,
    admin: bool = False,
    data: dict[str, Any] | None = None,
) -> str:
    """群里回复的那段文本。``admin`` 为真时附上排查信息（方案 §3.1 的权限分界）。

    ``data`` 是已算好的 ``snapshot()``（测试与 CLI 用）；不传则现算一份。
    """
    reg = target if target is not None else _default_registry
    snap = snapshot(target=reg, tool_manager=tool_manager) if data is None else data

    lines: list[str] = []
    routable = [i for i in snap.get("items") or [] if i.get("routable")]
    if routable:
        shown = routable[:_CHAT_MAX_ITEMS]
        lines.append(f"我现在能在聊天里自动用上的能力有 {len(routable)} 项：")
        for domain, group in _group_by_domain(shown):
            lines.append(f"【{_domain_label(domain)}】")
            lines.extend(
                f"· {_capability_line(reg.get(str(i.get('id') or '')), i, admin=admin)}"
                for i in group
            )
        if len(routable) > len(shown):
            lines.append(f"（还有 {len(routable) - len(shown)} 项没列出来）")
    else:
        lines.append("我现在没有可以在聊天里自动触发的能力。")

    commands = [str(c) for c in (snap.get("commands") or []) if c]
    if commands:
        prefix = wake_prefix()
        shown_cmds = commands[:_CHAT_MAX_COMMANDS]
        more = f"（共 {len(commands)} 条）" if len(commands) > len(shown_cmds) else ""
        listed = " ".join(f"{prefix}{c}" for c in shown_cmds)
        lines.append(f"也可以直接发指令：{listed}{more}")

    unrouted = int(snap.get("auto_unrouted") or 0)
    if unrouted:
        lines.append(f"另有 {unrouted} 个插件工具没有能力声明，聊天里不会被自动触发。")
        if admin:
            names = sorted(
                {
                    str(p.get("tool") or "")
                    for i in snap.get("items") or []
                    if i.get("auto") and not i.get("routable")
                    for p in i.get("providers") or []
                    if p.get("tool")
                },
            )
            listed = "、".join(names[:_CHAT_MAX_TOOLS])
            more = f" 等 {len(names)} 个" if len(names) > _CHAT_MAX_TOOLS else ""
            lines.append(
                f"（管理员）未声明的工具：{listed}{more}。"
                f"给它写一份 capability.toml 才会参与路由，格式见 docs/plugin-spec.md",
            )

    if admin:
        lines.extend(_admin_lines(snap))
    return "\n".join(lines)


# ---------- 离线（Bot 未运行）----------


def _plugins_dir() -> Path | None:
    with contextlib.suppress(Exception):
        from config import ASTRBOT_PLUGINS_DIR

        path = Path(ASTRBOT_PLUGINS_DIR)
        if path.is_dir():
            return path
    return None


def _offline_file(tier: str, path: Path, parsed: Any) -> dict[str, Any]:
    """一份磁盘上的声明文件。**含 description 原文**——它只在本机 CLI 里露出，
    不经状态接口，所以不受「响应体不含自由文本」那条约束。
    """
    return {
        "tier": tier,
        "path": str(path),
        "error": parsed.error,
        # 保留 None 让渲染方能区分「显式写了 true」与「没写」：没写视为已审
        # （理由见 loader.load_capability_file），而 reviewed=false 只拦插件层。
        "reviewed": parsed.reviewed,
        "loadable": not parsed.error and (tier != "plugin" or parsed.reviewed is not False),
        "capabilities": [
            {
                "id": c.id,
                "domain": c.domain,
                "description": c.description,
                "examples": len(c.examples),
                "keywords": len(c.keywords),
                "tools": [p.tool_name for p in c.providers if p.tool_name],
            }
            for c in parsed.capabilities
        ],
    }


def offline_declarations() -> dict[str, Any]:
    """不启动 Bot、直接读磁盘上的三层声明，供 ``deploy capabilities`` 在接口不可达时用。

    它回答不了「到底可不可路由」——那要看工具存不存在、插件加载成不成功、自动派生那层
    有没有把工具先占走，全都只有在 Bot 进程里才知道。渲染方**必须**说清这一点，否则
    用户会拿这份清单去解释「为什么没被调用」，而这份清单恰好不包含那个答案。

    与运行期的插件层还有一处**刻意的**差别：这里扫的是插件**目录**，而
    ``loader._plugin_declaration_paths()`` 只看已成功加载的插件。所以 import 失败的
    插件的声明也会出现在这份清单里——正好，那种情况下人要看的就是「文件在，但没加载」。
    """
    from capability.loader import (
        PLUGIN_DECL_DOMAIN,
        PLUGIN_DECL_DRAFT_FILENAME,
        PLUGIN_DECL_FILENAME,
        _config_declaration_dirs,
        parse_declaration,
    )

    files: list[dict[str, Any]] = []
    # 借 loader 的私有函数而不是自己拼两个目录：那份「用户层 + 出厂层、按 resolve 去重」
    # 的判据只能有一处，两处各写一遍必然漂移（CLI 报的层与实际生效的层不一致）。
    dirs = _config_declaration_dirs()
    for index, directory in enumerate(dirs):
        # 只有一层时（开发机 / 自包含布局）它同时是用户层与出厂层，别谎称是其中一层
        if len(dirs) == 1:
            tier = "config"
        elif index == 0:
            tier = "user"
        else:
            tier = "factory"
        try:
            paths = sorted(directory.glob("*.toml")) if directory.is_dir() else []
        except OSError:
            paths = []
        files.extend(_offline_file(tier, p, parse_declaration(p)) for p in paths)

    drafts: list[str] = []
    plugins_dir = _plugins_dir()
    if plugins_dir is not None:
        try:
            children = sorted(p for p in plugins_dir.iterdir() if p.is_dir())
        except OSError:
            children = []
        for child in children:
            decl = child / PLUGIN_DECL_FILENAME
            draft = child / PLUGIN_DECL_DRAFT_FILENAME
            if decl.is_file():
                files.append(
                    _offline_file(
                        "plugin",
                        decl,
                        parse_declaration(
                            decl,
                            source=SOURCE_PLUGIN,
                            domain=PLUGIN_DECL_DOMAIN,
                        ),
                    ),
                )
            if draft.is_file():
                drafts.append(str(draft))

    return {"version": SNAPSHOT_VERSION, "files": files, "drafts": drafts}


__all__ = [
    "DOMAIN_LABELS",
    "QUERY_KEYWORDS",
    "SNAPSHOT_VERSION",
    "SOURCE_LABELS",
    "TOOL_INACTIVE",
    "TOOL_MISSING",
    "TOOL_OK",
    "TOOL_UNKNOWN",
    "chat_overview",
    "is_query_text",
    "offline_declarations",
    "snapshot",
    "wake_prefix",
]
