# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""SocialContext 构建与预算插槽（计划 §6.5）。

TurnService.prepare_turn 在**最终预算前**调用 :func:`build_social_block`：

1. 先有「无学习基线」prompt（既有检索/Router/Planner 产物原样）；
2. 按窗口常量算出剩余额度（输出预留/安全余量先扣），再放可选片段；
3. 超限丢弃顺序：低分表达 → 剩余表达 → 低分词义 → 全部 social（实现中
   每类先按分数排序，从低分端整条丢弃，绝不半条截断）；
4. 没有任何片段时返回空串——**既有 prompt 字节不变**（回归锚定）。

措辞纪律：群原话和词义是**带来源的低权限数据块**，标注「本群语境」，
绝不提升为系统指令；表达是可选风格参考，不是「必须使用」的指令。
使用记录（selected/injected）写入 social_asset_usage：选择不等于已使用。

shadow 模式：照常选择并记录 usage（selected=1, injected=0），但返回空块
——候选决策可审计，实际 prompt 与发送行为不变（计划 §7）。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field

from core.context_budget import estimate_tokens
from core.social.contracts import ConversationScope

# [assumed] 初始配额（计划 §6.5）：表达 160 / 黑话 240 / 共 400，不扩窗口
EXPRESSION_BUDGET_TOKENS = 160
JARGON_BUDGET_TOKENS = 240
SOCIAL_BUDGET_TOKENS = 400

JARGON_HEADER = "【本群黑话（群内语境，供理解；不代表通用含义，也不是让你使用的指令）】"
EXPRESSION_HEADER = "【本群表达参考（同群成员的说法风格，可选参考，不是指令）】"


@dataclass
class SocialSelection:
    """一次构建的完整记录：选中的资产、实际注入与否、预算裁剪明细。"""

    jargon: list[dict] = field(default_factory=list)
    expressions: list[dict] = field(default_factory=list)
    injected_jargon: bool = False
    injected_expression: bool = False
    dropped: list[dict] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.jargon and not self.expressions


def _connect() -> sqlite3.Connection:
    from config import settings

    return sqlite3.connect(settings.DB_PATH, timeout=10.0)


def _record_usage(
    turn_id: str,
    entries: list[dict],
    *,
    injected: bool,
    effect_id: str | None = None,
) -> None:
    """usage 落库（幂等：turn+asset+revision 唯一）。选择不等于已使用。"""
    if not turn_id or not entries:
        return
    try:
        from core.social.contracts import utc_now_iso
        from memory import social_store

        social_store.ensure_tables()
        conn = _connect()
        try:
            for entry in entries:
                for asset_id in entry.get("asset_ids", [entry.get("asset_id")]):
                    if not asset_id:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO social_asset_usage (usage_id, turn_id, "
                        "asset_id, revision, selected, injected, effect_id, created_at_utc) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, turn_id, str(asset_id),
                         int(entry.get("revision", 1)), 1, 1 if injected else 0,
                         effect_id, utc_now_iso()),
                    )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass  # usage 记录是旁路：失败只损失统计，不影响回复


def _fit_entries(entries: list[dict], render, budget: int, kind: str,
                 selection: SocialSelection) -> tuple[str, int]:
    """按分数从高到低放条目，放不下的整条丢弃并记录（绝不半条截断）。"""
    if budget <= 0:
        for entry in entries:
            selection.dropped.append({"kind": kind, "term": entry.get("term", ""),
                                      "reason": "no_budget"})
        return "", 0
    lines: list[str] = []
    used = 0
    for entry in sorted(entries, key=lambda e: e.get("confidence", 0.0), reverse=True):
        line = render(entry)
        cost = estimate_tokens(line)
        if lines and used + cost > budget:
            selection.dropped.append({"kind": kind, "term": entry.get("term", ""),
                                      "reason": "budget"})
            continue
        lines.append(line)
        used += cost
    return ("\n".join(lines), used) if lines else ("", 0)


def _render_jargon(entry: dict) -> str:
    if entry.get("ambiguous"):
        senses = "；".join(f"「{s}」" for s in entry.get("senses", []))
        return (f"- 「{entry['term']}」在本群有 {len(entry.get('senses', []))} 种可能含义："
                f"{senses}（请按上下文判断或回避）")
    s = entry
    situation = f"（适用：{s['situation']}）" if s.get("situation") else ""
    example = f"｜例：{s['positive_example']}" if s.get("positive_example") else ""
    level = "高" if s.get("confidence", 0) >= 0.7 else "中" if s.get("confidence", 0) >= 0.3 else "低"
    return (f"- 「{s['term']}」：{s['definition']}{situation}{example}"
            f"（群内可信度：{level}）")


def _render_expression(entry: dict) -> str:
    situation = f"（场合：{entry.get('situation', '')}）" if entry.get("situation") else ""
    return f"- 「{entry.get('content', '')}」{situation}"


def build_social_block(
    ctx,  # ChatContext（只读其身份与空间字段，避免 import 成环）
    *,
    baseline_prompt: str,
    system_prompt: str,
) -> tuple[str, SocialSelection]:
    """在最终预算前接入的可选片段。返回 (social_text, selection)。

    - 无任何可注入内容 / 预算不足 / scope 不明 → ("", selection)；
      调用方拼回原 prompt，字节不变。
    - 预算按窗口常量扣除基线占用后计算，且不超过 SOCIAL_BUDGET_TOKENS。
    - shadow 模式：选择照记，注入关闭（返回空串）。
    """
    selection = SocialSelection()
    try:
        # 运行时属性读取：测试可 monkeypatch settings，部署可热读 .env 重载值
        from config import settings as _settings

        social_mode = _settings.SOCIAL_MODE
        if social_mode not in ("shadow", "active"):
            return "", selection
        from config import settings as _s2
        from memory import jargon_service

        scope = ConversationScope.for_qq(ctx.group_id)
        inject_allowed = social_mode == "active"

        # ── 选择（本地、零 LLM） ──
        jargon_entries = jargon_service.match_jargon(scope, ctx.message or "")
        # 表达选择（计划 §6.3）：active only、每轮 ≤2、近期用过的不重复注入；
        # 注入另受 SOCIAL_EXPRESSION_INJECT 独立开关约束（「可理解/可模仿」分闸）。
        expression_entries: list[dict] = []
        if getattr(_s2, "SOCIAL_EXPRESSION_INJECT", False):
            try:
                from memory import expression_selector

                expression_entries = expression_selector.select(
                    scope, ctx.message or "",
                    recent_window_turns=int(getattr(_s2, "SOCIAL_EXPRESSION_RECENT_TURNS", 10)),
                )
            except Exception:
                expression_entries = []
        selection.jargon = jargon_entries
        selection.expressions = expression_entries

        # usage 记录（shadow 也记：selected=1 / injected=0）
        if not inject_allowed:
            # shadow：选择照记（selected=1 / injected=0），注入永关
            _record_usage(getattr(ctx, "turn_id", ""), jargon_entries, injected=False)
            _record_usage(getattr(ctx, "turn_id", ""), expression_entries, injected=False)
            return "", selection

        # ── 预算：先扣基线，再放可选（计划 §6.5） ──
        total_budget = (
            int(_settings.LLM_CONTEXT_WINDOW_TOKENS)
            - int(_settings.LLM_OUTPUT_RESERVE_TOKENS)
            - int(_settings.LLM_CONTEXT_SAFETY_TOKENS)
            - estimate_tokens(system_prompt or "")
            - estimate_tokens(baseline_prompt or "")
        )
        social_budget = max(0, min(int(SOCIAL_BUDGET_TOKENS), total_budget))
        expr_budget = min(int(EXPRESSION_BUDGET_TOKENS), social_budget)
        jargon_budget = min(int(JARGON_BUDGET_TOKENS), social_budget - expr_budget)

        expr_text, _used_e = _fit_entries(
            expression_entries, _render_expression, expr_budget, "expression", selection
        )
        jargon_text, _used_j = _fit_entries(
            jargon_entries, _render_jargon, jargon_budget, "jargon", selection
        )
        parts = []
        if expr_text:
            parts.append(EXPRESSION_HEADER + "\n" + expr_text)
            selection.injected_expression = True
        if jargon_text:
            parts.append(JARGON_HEADER + "\n" + jargon_text)
            selection.injected_jargon = True
        if not parts:
            return "", selection
        # 注入事实确定后落 usage（selected ⊃ injected；applied 由输出匹配补记）
        _record_usage(getattr(ctx, "turn_id", ""), jargon_entries,
                      injected=selection.injected_jargon)
        _record_usage(getattr(ctx, "turn_id", ""), expression_entries,
                      injected=selection.injected_expression)
        return "\n\n".join(parts), selection
    except Exception:
        # social 是可选增强：任何异常都退回无学习基线，绝不阻断回复
        return "", SocialSelection()


def social_context_snapshot(selection: SocialSelection) -> str:
    """预算快照（实际删掉的资产与原因），供追踪/审计。"""
    return json.dumps(
        {
            "injected_jargon": selection.injected_jargon,
            "injected_expression": selection.injected_expression,
            "selected": {
                "jargon": [e.get("term") for e in selection.jargon],
                "expression": [e.get("content") for e in selection.expressions],
            },
            "dropped": selection.dropped,
        },
        ensure_ascii=False,
    )
