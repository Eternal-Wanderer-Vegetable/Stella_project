# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Router 的输出类型。

方案第 7 节：Router 输出的是 **multi-label** 判断，不是单选。
「你还记得我说的旅行计划吗？帮我查一下东京天气」同时需要 chat + memory + tool，
把它归到某一类就必然丢掉另外两项。

刻意做成纯数据、无行为：``Route`` 会被写进 ``ChatContext.route`` 供 log_thought /
memory.trace 落盘，任何行为都可能在序列化时炸掉。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 路由判定级别（写进 Route.level，用于日志与 benchmark 归因）
LEVEL_RULE = "rule"          # Level 0：关键词规则
LEVEL_SEMANTIC = "semantic"  # Level 1：Embedding 语义
LEVEL_FALLBACK = "fallback"  # Level 2：更强模型兜底
LEVEL_DEFAULT = "default"    # 降级：路由不可用/被关闭/异常
LEVEL_DISABLED = "disabled"  # 总开关关闭


@dataclass
class CapabilityHit:
    """一次命中：能力 id + 置信分。

    ``score`` 的语义随级别不同：规则级是 1.0（命中即确定），语义级是余弦相似度，
    兜底级是模型给的置信度。跨级别比较分数没有意义，只在同一级别内排序。
    """

    capability_id: str
    score: float = 0.0

    def __repr__(self) -> str:
        return f"{self.capability_id}={self.score:.2f}"


@dataclass
class Route:
    """一次路由判定的完整结论。

    属性:
        chat: 是否需要 Stella 出面回复。**默认 True**——Stella 是唯一对用户说话的模块，
            任何请求最终都要有人回话，没有「只执行不回复」的路径；
        memory: 是否需要读取长期记忆。默认 True 是保守取值，见 ROUTER_GATE_MEMORY 的注释；
        tool: 是否需要调用工具。默认 False——凭空调工具的代价高于漏调；
        capabilities: 命中的能力（按 score 降序），只在 tool=True 时有意义。
            **注意它已被 ROUTER_SEMANTIC_THRESHOLD 过滤过**，不代表全部候选；
        top_score: 过滤**之前**的最高分。必须单独记录：级联层要用它判断是否落在
            Level 2 的不确定带，而 ``capabilities`` 是按 ROUTER_SEMANTIC_THRESHOLD
            过滤后的结果——从它推最高分，会让 (UNCERTAIN_FLOOR, SEMANTIC_THRESHOLD)
            区间内的分数一律读成 0，Level 2 的触发区间被无声地缩窄；
        level: 由哪一级给出结论（见 LEVEL_* 常量）；
        reason: 人话解释，写进日志用于排查「为什么这次没调工具」；
        elapsed: 判定耗时（秒）。
    """

    chat: bool = True
    memory: bool = True
    tool: bool = False
    capabilities: list[CapabilityHit] = field(default_factory=list)
    top_score: float = 0.0
    level: str = LEVEL_DEFAULT
    reason: str = ""
    elapsed: float = 0.0

    @property
    def capability_ids(self) -> list[str]:
        return [hit.capability_id for hit in self.capabilities]

    def to_dict(self) -> dict:
        """扁平快照，供 log_thought / memory.trace 落盘。

        不用 ``dataclasses.asdict``：它会把 CapabilityHit 展成嵌套 dict，
        日志里读起来远不如 ``["weather.query=0.82"]`` 直观。
        """
        return {
            "chat": self.chat,
            "memory": self.memory,
            "tool": self.tool,
            "capabilities": [repr(h) for h in self.capabilities],
            "top_score": round(self.top_score, 3),
            "level": self.level,
            "reason": self.reason,
            "elapsed": round(self.elapsed, 3),
        }

    def __repr__(self) -> str:
        labels = [
            name
            for name, on in (("chat", self.chat), ("memory", self.memory), ("tool", self.tool))
            if on
        ]
        caps = f" {self.capability_ids}" if self.capabilities else ""
        return f"Route({'+'.join(labels)}{caps} via {self.level})"


def default_route(reason: str = "", level: str = LEVEL_DEFAULT) -> Route:
    """降级路由：照常聊天、照常读记忆、不调工具。

    这是所有失败路径的统一归宿（embedding 不可用 / 注册表为空 / 超时 / 异常）。
    保守方向是刻意的：漏调一次工具用户最多再问一遍，凭空调一次工具则可能真的
    发出一条消息或改变外部状态。
    """
    return Route(chat=True, memory=True, tool=False, level=level, reason=reason)


__all__ = [
    "LEVEL_DEFAULT",
    "LEVEL_DISABLED",
    "LEVEL_FALLBACK",
    "LEVEL_RULE",
    "LEVEL_SEMANTIC",
    "CapabilityHit",
    "Route",
    "default_route",
]
