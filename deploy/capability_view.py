# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""``python -m deploy capabilities`` 的渲染层：把能力清单打成一张表。

这张表回答的是**今天只能靠翻启动日志才能回答**的那个问题：装了插件、日志说派生
成功了、可它为什么从来不被调用。答案永远是那几条里的一条——没有声明（不可路由）、
声明被更高优先层顶掉了、声明指向的工具名拼错了、provider 正在退避、或者工具被
``active=false`` 停用了。表里每一列都对应其中一条。

**数据源不在本进程**：``capability.registry`` 是模块级单例，``deploy`` 是另一个进程，
读不到。所以走状态接口（``GET /stella/status`` 的 ``capabilities`` 块，回环 only），
判据与渲染都在 ``capability.inventory`` 里，本模块只负责排版——三个 surface 各遍历一遍
注册表必然漂移，而漂移的表现是「CLI 说这条可路由、群里说不可路由」，到那时用户没有
任何办法判断哪一个在说谎。

Bot 没运行时退到 ``inventory.offline_declarations()`` 直接读磁盘上的三层声明。那份
数据**回答不了「到底可不可路由」**（要看工具存不存在、插件加载成不成功、自动派生那层
有没有把工具先占走，全都只有在 Bot 进程里才知道），所以离线分支必须把这句话说出来，
否则用户会拿它去解释「为什么没被调用」，而它恰好不含那个答案。
"""

from __future__ import annotations

import json
import unicodedata
from typing import Any, NamedTuple

from capability.inventory import (
    DOMAIN_LABELS,
    HINT_MISSING_TOOL,
    SOURCE_LABELS,
    TOOL_INACTIVE,
    TOOL_MISSING,
    TOOL_OK,
    TOOL_UNKNOWN,
)
from capability.registry import KIND_ASTRBOT_TOOL

# 工具状态 → 表里显示什么。``unknown`` 与 ``missing`` 必须分开：前者的成因在别处
# （读不到工具注册表），后者会把人引到插件目录去核工具名。
_TOOL_STATE_LABELS = {
    TOOL_OK: "",
    TOOL_INACTIVE: "已停用",
    TOOL_MISSING: "工具不存在",
    TOOL_UNKNOWN: "未知",
}

_TIER_LABELS = {
    "user": "用户层",
    "factory": "出厂层",
    "config": "配置层",
    "plugin": "插件自带",
}


class CapabilityView(NamedTuple):
    """一次查询的结果。``live`` 与 ``offline`` 至多一个非空。"""

    live: dict[str, Any] | None
    offline: dict[str, Any] | None
    api_reachable: bool


def collect() -> CapabilityView:
    """取一份能力清单：优先状态接口，不可达时退到磁盘声明。

    经 ``process.status()`` 而不是直接打 HTTP：HOST/PORT/路径的解析、``0.0.0.0`` →
    ``127.0.0.1`` 的换算、1 秒超时那套判据都在那边，抄一遍必然漂移。
    """
    from . import process

    data = process.status()
    live = data.get("capabilities")
    if isinstance(live, dict):
        return CapabilityView(live=live, offline=None, api_reachable=True)

    # 接口可达但没有 capabilities 块：Bot 是旧版本，或快照取数失败（inventory 那边
    # 整个 try/except 掉了）。两种都不该冒充「Bot 没运行」，但离线声明仍然有用。
    from capability.inventory import offline_declarations

    return CapabilityView(
        live=None,
        offline=offline_declarations(),
        api_reachable=bool(data.get("api_reachable")),
    )


# ---------- 表格排版 ----------


def _width(text: str) -> int:
    """终端显示宽度：东亚宽字符算 2 列。

    ``str.ljust`` 按字符数补空格，而能力 id 是 ASCII、来源标签是中文，混在一列里
    用字符数对齐会错开一半——表格错位比不做表更难读。
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _table(headers: list[str], rows: list[list[str]], *, indent: str = "  ") -> list[str]:
    """等宽表格。空行集合返回空列表（调用方自己决定说什么）。"""
    if not rows:
        return []
    widths = [
        max(_width(headers[i]), *(_width(r[i]) for r in rows)) for i in range(len(headers))
    ]
    out = [
        indent + "  ".join(_pad(h, w) for h, w in zip(headers, widths, strict=True)).rstrip()
    ]
    out.append(indent + "  ".join("-" * w for w in widths))
    out.extend(
        indent + "  ".join(_pad(c, w) for c, w in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )
    return out


def _domain_label(domain: str) -> str:
    return DOMAIN_LABELS.get(domain) or domain or "其它"


def _source_label(source: str) -> str:
    label = SOURCE_LABELS.get(source)
    return label if label is not None else (source or "未标注")


def _provider_cell(provider: dict[str, Any]) -> str:
    """一个 provider 在「实现」列里显示成什么：工具名 + 出问题的原因。

    健康的 provider 只显示工具名——每行都挂一个「正常」标记会把真正出问题的那几行
    淹掉，而这张表的用途正是把它们找出来。
    """
    name = str(provider.get("tool") or provider.get("kind") or "?")
    notes: list[str] = []
    state = str(provider.get("tool_state") or "")
    label = _TOOL_STATE_LABELS.get(state, state)
    if label:
        notes.append(label)
    if not provider.get("enabled"):
        notes.append("已人工关闭")
    backoff = int(provider.get("backoff_seconds") or 0)
    if backoff:
        notes.append(f"退避中 {backoff}s／连续失败 {provider.get('failures', 0)} 次")
    return f"{name}（{'，'.join(notes)}）" if notes else name


def _reason_not_routable(item: dict[str, Any]) -> str:
    """这条为什么不可路由。判据顺序照 ``registry.routable()``，先命中先报。

    ``routable()`` 要求 ``route_enabled``、有能真的跑起来的 provider、有原型语料，
    三者缺一即不进候选集。逐条对上是刻意的：说「不可路由」谁都会，说清缺哪一样才
    省得用户去翻源码。

    「跑得起来」比「可用」严一层：人工没关、不在退避窗，还得那个工具真的在
    （判据见 ``registry._tool_live``）。这一层是**最常命中**的一条——声明指向的插件
    没装、或者工具名拼错了，而两者在表里长得一样，所以要分开报。
    """
    if item.get("auto"):
        return "无能力声明（自动派生）"
    if not item.get("route_enabled"):
        return "声明里 route_enabled = false"
    providers = list(item.get("providers") or [])
    if not providers:
        return "声明没有任何 providers"
    if not any(p.get("enabled") and p.get("available") for p in providers):
        return "所有实现都不可用（已关闭或正在退避）"
    if not any(p.get("tool_state") == TOOL_OK for p in providers):
        # 注意判据都写成「有没有哪个 provider 是 X」而不是「有没有不是 X 的」：
        # tools_known=false 时全部 provider 都是 unknown，那时一条都不该命中——
        # 读不到工具注册表就指着用户说「你的插件没装」是谎报（见 inventory._tool_states）。
        kinds = {str(p.get("kind") or "") for p in providers}
        if KIND_ASTRBOT_TOOL not in kinds:
            return f"实现类型暂不支持（{'、'.join(sorted(k for k in kinds if k))}）"
        if any(p.get("tool_state") == TOOL_MISSING for p in providers):
            return "声明指向的工具不存在（插件没装，或工具名拼错）"
        if any(p.get("tool_state") == TOOL_INACTIVE for p in providers):
            return "声明指向的工具被停用了（active = false）"
    if not item.get("examples") and not item.get("keywords"):
        return "既没有 examples 也没有 keywords（没有原型语料）"
    return "原因未知"


def _live_summary(snap: dict[str, Any]) -> list[str]:
    total = int(snap.get("total") or 0)
    routable = int(snap.get("routable") or 0)
    lines = [
        f"能力注册表：共 {total} 项，其中 {routable} 项可被聊天自动触发"
        f"（声明 {snap.get('declared', 0)} 项、自动派生 {snap.get('auto', 0)} 项）；"
        f"注册表版本 v{snap.get('registry_version', 0)}。",
    ]
    if not snap.get("tools_known", True):
        lines.append(
            "  注意：Bot 那边读不到工具注册表，「工具不存在」这一列本次不可信。",
        )
    return lines


def _live_rows(items: list[dict[str, Any]]) -> tuple[list[list[str]], list[list[str]]]:
    """(可路由的行, 不可路由的行)。分两张表是因为两者要看的列不一样——
    前者看实现健康度，后者看**为什么不可路由**。"""
    routable: list[list[str]] = []
    blocked: list[list[str]] = []
    for item in sorted(items, key=lambda i: str(i.get("id") or "")):
        cap_id = str(item.get("id") or "")
        implementations = "、".join(_provider_cell(p) for p in item.get("providers") or [])
        if item.get("routable"):
            routable.append(
                [
                    cap_id,
                    _domain_label(str(item.get("domain") or "")),
                    _source_label(str(item.get("source") or "")),
                    f"{item.get('examples', 0)}/{item.get('keywords', 0)}",
                    implementations or "—",
                ],
            )
        else:
            blocked.append(
                [
                    cap_id,
                    _domain_label(str(item.get("domain") or "")),
                    _source_label(str(item.get("source") or "")),
                    _reason_not_routable(item),
                    implementations or "—",
                ],
            )
    return routable, blocked


def _live_notes(snap: dict[str, Any]) -> list[str]:
    """表后面的几行说明。每一行都对应一个具体的、可动手修的成因。"""
    from capability.inventory import wake_prefix

    out: list[str] = []
    missing = [str(m) for m in (snap.get("missing_tools") or []) if m]
    if missing:
        out.append(
            f"声明里指向的这些工具不存在：{'、'.join(missing)}"
            f" —— {HINT_MISSING_TOOL}",
        )
    unrouted = int(snap.get("auto_unrouted") or 0)
    if unrouted:
        out.append(
            f"有 {unrouted} 个插件工具没有能力声明，聊天里不会被自动触发。"
            f"给它写一份 capability.toml（放插件根目录或 config/capabilities/）才会参与"
            f"路由，格式见 docs/plugin-spec.md。",
        )
    commands = [str(c) for c in (snap.get("commands") or []) if c]
    if commands:
        prefix = wake_prefix()
        out.append(
            f"指令（{len(commands)} 条，靠 {prefix} 前缀显式触发，不参与语义路由）："
            + " ".join(f"{prefix}{c}" for c in commands),
        )
    return out


def _render_live(snap: dict[str, Any]) -> list[str]:
    lines = _live_summary(snap)
    routable_rows, blocked_rows = _live_rows(list(snap.get("items") or []))

    lines.append("")
    if routable_rows:
        lines.append(f"可被聊天自动触发（{len(routable_rows)}）：")
        lines += _table(
            ["能力 id", "域", "来源", "例句/关键词", "实现"],
            routable_rows,
        )
    else:
        lines.append("没有任何能力可被聊天自动触发。")
    if blocked_rows:
        lines.append("")
        lines.append(f"不参与路由（{len(blocked_rows)}）：")
        lines += _table(["能力 id", "域", "来源", "原因", "实现"], blocked_rows)

    notes = _live_notes(snap)
    if notes:
        lines.append("")
        lines += notes
    return lines


# ---------- 离线（Bot 未运行）----------


def _render_offline(data: dict[str, Any], *, api_reachable: bool) -> list[str]:
    """磁盘上的三层声明。**必须**先说清它回答不了什么。"""
    lines: list[str] = []
    if api_reachable:
        # 接口通了却没有 capabilities 块：Bot 比本 CLI 旧，或那边取快照失败了
        lines.append(
            "状态接口可达，但没有返回能力清单 —— Bot 可能是旧版本。以下是磁盘上的声明：",
        )
    else:
        lines.append("Stella 未在运行（状态接口不可达）。以下是磁盘上的声明：")
    lines.append(
        "  这份清单**只是文件内容**：能不能被聊天自动触发还要看工具是否存在、插件是否"
        "加载成功、有没有被更高优先层顶掉 —— 那些只有 Bot 进程里才知道。启动后再查一次。",
    )

    files = list(data.get("files") or [])
    if not files:
        lines.append("")
        lines.append("没有找到任何 capability.toml。")
    for entry in files:
        tier = str(entry.get("tier") or "")
        lines.append("")
        lines.append(f"[{_TIER_LABELS.get(tier, tier or '?')}] {entry.get('path')}")
        error = entry.get("error")
        if error:
            lines.append(f"  解析失败：{error} —— 该文件整体不会被载入。")
            continue
        if not entry.get("loadable"):
            # 唯一会走到这里的原因是插件层 reviewed = false（见 loader 的闸门）
            lines.append(
                "  reviewed = false —— 生成的草稿未经人审，不会被载入。"
                "核对 examples 与 keywords 后把它改成 true。",
            )
        rows = [
            [
                str(c.get("id") or ""),
                str(c.get("domain") or ""),
                f"{c.get('examples', 0)}/{c.get('keywords', 0)}",
                "、".join(str(t) for t in c.get("tools") or []) or "—",
                str(c.get("description") or ""),
            ]
            for c in entry.get("capabilities") or []
        ]
        if rows:
            lines += _table(
                ["能力 id", "域", "例句/关键词", "工具", "描述"],
                rows,
                indent="    ",
            )
        else:
            lines.append("  文件里没有任何 [[capability]]。")

    drafts = [str(d) for d in (data.get("drafts") or []) if d]
    if drafts:
        lines.append("")
        lines.append(f"待人审的草稿（{len(drafts)} 份，一律不会被载入）：")
        lines.extend(f"  {d}" for d in drafts)
        lines.append(
            "  审完去掉 .draft 后缀并把 reviewed 改成 true。"
            "生成物必须过人审才生效 —— 错的 examples 会把不相关的请求吸进来。",
        )
    return lines


# ---------- 出口 ----------


def to_terminal(view: CapabilityView) -> str:
    if view.live is not None:
        return "\n".join(_render_live(view.live))
    return "\n".join(
        _render_offline(view.offline or {}, api_reachable=view.api_reachable),
    )


def to_json(view: CapabilityView) -> str:
    """结构化输出（供 GUI）。

    ``live`` 就是状态接口那一块原样，**不在这里加工**：GUI 与 CLI 读同一份字段，
    本模块加工过的字段只会让两边看到的东西不一样。``source`` 是 ``live`` 或
    ``offline``，让调用方不必靠「哪个 key 是 null」去猜。
    """
    return json.dumps(
        {
            "version": 1,
            "source": "live" if view.live is not None else "offline",
            "api_reachable": view.api_reachable,
            "capabilities": view.live,
            "declarations": view.offline,
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = ["CapabilityView", "collect", "to_json", "to_terminal"]
