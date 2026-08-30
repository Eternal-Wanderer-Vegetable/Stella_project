# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 的渲染层：把检查结论变成 JSON 或终端文本。

--json 输出面向桌面安装器（Tauri），结构稳定且自描述，GUI 只做渲染。
"""

from __future__ import annotations

import json
import sys

from . import checks
from .models import CheckResult, Snapshot


def to_json(results: list[CheckResult], snapshot: Snapshot | None = None) -> str:
    """序列化为结构化 JSON。id 供 GUI 做图标/本地化映射。

    传了 ``snapshot`` 时额外带一段 ``llm``：那不是「检查结论」而是「事实」——
    GUI 的模型服务面板要照它渲染当前生效的角色→端点→模型，用户才能确认
    自己那一套端点配置真的被读进来了。**只搬 describe() 的输出，因此不含 key 值。**
    """
    doc: dict = {
        "version": 1,
        "summary": _summarize(results),
        "items": [
            {
                "id": r.id,
                "level": r.level,
                "title": r.title,
                "detail": r.detail,
                "fix_hint": r.fix_hint,
            }
            for r in results
        ],
    }
    if snapshot is not None:
        doc["llm"] = _llm_section(snapshot)
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _llm_section(snap: Snapshot) -> dict:
    """端点 / 角色的事实汇总（含探测结果）。没配地址的槽不列，免得四个空卡片。"""
    endpoints = {}
    for slot, ep in snap.llm_endpoints.items():
        if not str(ep.get("base_url") or "").strip():
            continue
        endpoints[slot] = {
            **ep,
            "reachable": snap.llm_endpoint_reachable.get(slot),
            "error": snap.llm_endpoint_error.get(slot, ""),
            "models": snap.llm_endpoint_models.get(slot, []),
        }
    return {
        "endpoints": endpoints,
        "roles": snap.llm_roles,
        "embedding_gate": snap.llm_embedding_gate,
        "embedding_base_url": snap.embedding_base_url,
        # 今日用量与运行期降级状态：同样是「事实」而不是「结论」。
        # 都来自 usage_snapshot() / runtime_state()，只有计数、比率与槽名。
        "usage": snap.llm_usage,
        "fallback_states": snap.llm_fallback_states,
    }


def _summarize(results: list[CheckResult]) -> dict:
    total = checks.total_checks()
    n_error = sum(1 for r in results if r.level == "error")
    n_warn = sum(1 for r in results if r.level == "warn")
    # ok 用「总数 − 有问题的项数」推算。注意两点误差：
    # ① 不适用而跳过的检查（如 embedding 未启用）也算进 ok；
    # ② 单个检查可能产出多条结果（deprecated_env_keys），会让 ok 偏小。
    # 这两点对「让用户知道确实检查过一批项目」的目的无影响，不值得为精确
    # 而让每个检查都返回 ok 结果（那要改全部检查函数）。
    return {
        "ok": max(0, total - n_error - n_warn),
        "warn": n_warn,
        "error": n_error,
        "blocking": has_blocking(results),
        "total": total,
    }


def has_blocking(results: list[CheckResult]) -> bool:
    """是否存在 error 级结论（阻塞启动）。"""
    return any(r.level == "error" for r in results)


_REACHABLE_TEXT = {True: "可达", False: "不可达", None: "未探测"}


def _llm_overview(snap: Snapshot) -> list[str]:
    """「角色 → 端点 → 模型」与端点清单两张小表。拿不到解析结果时返回空列表。"""
    if not snap.llm_roles and not snap.llm_endpoints:
        return []
    lines = ["模型服务", "  角色         端点            模型                     闸门"]
    for role, rb in snap.llm_roles.items():
        slot = str(rb.get("slot") or "") or "（未绑定）"
        model = str(rb.get("model") or "") or "（服务端默认）"
        lines.append(
            f"  {role:<12} {slot:<15} {model:<24} {rb.get('gate') or ''}"
        )
    listed = [
        (slot, ep) for slot, ep in snap.llm_endpoints.items() if ep.get("base_url")
    ]
    if listed:
        lines.append("  端点：")
        for slot, ep in listed:
            reach = _REACHABLE_TEXT.get(snap.llm_endpoint_reachable.get(slot), "未探测")
            key = "有 key" if ep.get("has_api_key") else "无 key"
            lines.append(
                f"    {slot:<13} {ep.get('base_url')}  "
                f"{ep.get('kind')}  {key}  并发 {ep.get('concurrency')}  {reach}"
            )
    gate = snap.llm_embedding_gate or "none"
    lines.append(f"  embedding：{snap.embedding_base_url}（闸门 {gate}，恒定本地）")
    lines += _usage_overview(snap)
    lines.append("")
    return lines


def _usage_overview(snap: Snapshot) -> list[str]:
    """今日用量一行。缓存命中率单独给出——它是验证前缀缓存有没有生效的唯一手段。"""
    usage = snap.llm_usage
    if usage.get("accounting") is not True:
        return []
    totals = usage.get("totals") or {}
    budget = usage.get("budget") or 0
    used = usage.get("used_tokens") or 0
    quota = f"{used}/{budget} token" if budget else f"{used} token（预算不限）"
    rate = (totals.get("cache_hit_rate") or 0.0) * 100
    return [
        f"  今日用量：{quota}，调用 {totals.get('calls', 0)} 次，"
        f"缓存命中率 {rate:.1f}%"
    ]


def to_terminal(results: list[CheckResult], snapshot: Snapshot | None = None) -> str:
    """人类可读文本。颜色用 ANSI，检测不到终端时自动降级。

    传了 ``snapshot`` 时先打一张「角色 → 端点 → 模型」的表。这张表本身不是
    检查结论，但「无缝切换」要能被信任，前提就是用户能一眼看到当前到底在用谁——
    尤其是配了在线端点却忘了改角色绑定时，表里一看就知道请求还在走本地。
    """
    use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    lines: list[str] = []
    if snapshot is not None:
        lines += _llm_overview(snapshot)
    levels = {"error": "错误", "warn": "警告", "ok": "通过"}
    styles = {
        "error": ("31", "1"),
        "warn": ("33", "1"),
        "ok": ("32", ""),
    }
    for r in results:
        code, bold = styles[r.level]
        if use_color:
            label = f"\x1b[{code};{bold}m[{levels[r.level]}]\x1b[0m"
        else:
            label = f"[{levels[r.level]}]"
        lines.append(f"{label} {r.title}")
        if r.detail:
            lines.append(f"    {r.detail}")
        if r.fix_hint:
            lines.append(f"    解决：{r.fix_hint}")
    lines.append("")
    if has_blocking(results):
        lines.append("发现阻塞性问题，请先解决后再启动。")
    else:
        lines.append("未发现阻塞性问题。")
    return "\n".join(lines)
