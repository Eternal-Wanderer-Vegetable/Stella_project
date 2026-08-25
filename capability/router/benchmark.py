# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Router Benchmark（方案第 19 节 Phase 4）。

回答一个问题：**能不能把 ``ROUTER_GATE_MEMORY`` 打开？**

门控默认关闭，因为 Router 误判 ``memory=False`` 会让 Stella 当轮悄悄丢失长期记忆
（静默退化，见 config/settings.py 的注释）。要打开它就得先量出误判率——
这个模块就是那把尺子。

## 两类指标，代价完全不对称

| 错误 | 后果 | 严重度 |
|-|-|-|
| ``memory`` 假阴（该读记忆却判不读） | Stella 突然不记得你了，不报错 | **高**，门控的唯一风险 |
| ``memory`` 假阳（不该读却读了） | 多一次检索，浪费一点延迟 | 低 |
| ``tool`` 假阳（不该调却调了） | 凭空调工具，可能改变外部状态 | **高** |
| ``tool`` 假阴（该调却没调） | 用户再问一遍 | 低 |

所以报告分别给出四个数，**不合成单一准确率**——合成会把高代价错误藏在平均值里。

## 用法

```bash
python -m capability.router.benchmark              # 内置用例 + benchmark/*.json
python -m capability.router.benchmark --rules-only # 只测 Level 0（不需要 embedding 服务）
python -m capability.router.benchmark --cases my.json
```

用例文件是 JSON 数组，每项 ``{"message": ..., "memory": bool, "tool": bool,
"capability": "可选，期望命中的能力 id"}``。

**跑全链路（不加 --rules-only）时，能力注册表决定结果。** ``_main`` 里的
``bootstrap()`` 只读得到 ``config/capabilities/*.toml``——独立进程里插件没加载，
``llm_tools`` 是空的，所以自动派生为 0。这正好是标定阈值想要的条件：
量的是**声明**的路由质量，不受装了哪些插件影响。

``--rules-only`` 下所有靠 Level 1 的工具用例都会记成「工具假阴」——那是如实的
（Level 0 本来就判不了它们），且属低代价错误，不影响退出码。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capability.registry import CapabilityRegistry

# 内置用例集：与 capability/router/benchmark/ 下的 JSON 分开放，
# 保证「没有任何外部文件也能跑一遍」。
CASES_DIR = Path(__file__).parent / "benchmark"


@dataclass
class Case:
    """一条用例。``capability`` 为空表示不检查具体命中哪个能力。"""

    message: str
    memory: bool
    tool: bool
    capability: str = ""
    note: str = ""


@dataclass
class Outcome:
    """一条用例的判定结果。"""

    case: Case
    memory: bool
    tool: bool
    capabilities: list[str]
    level: str
    reason: str

    @property
    def memory_ok(self) -> bool:
        return self.memory == self.case.memory

    @property
    def tool_ok(self) -> bool:
        return self.tool == self.case.tool

    @property
    def capability_ok(self) -> bool:
        """期望的能力是否在命中列表里；未指定期望时视为通过。"""
        if not self.case.capability:
            return True
        return self.case.capability in self.capabilities


@dataclass
class Report:
    """汇总报告。四类错误分开计数，刻意不合成单一准确率。"""

    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def memory_false_negative(self) -> list[Outcome]:
        """该读记忆却判不读——门控的唯一风险，也是最该盯的数。"""
        return [o for o in self.outcomes if o.case.memory and not o.memory]

    @property
    def memory_false_positive(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.case.memory and o.memory]

    @property
    def tool_false_positive(self) -> list[Outcome]:
        """不该调工具却调了——可能改变外部状态。"""
        return [o for o in self.outcomes if not o.case.tool and o.tool]

    @property
    def tool_false_negative(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.case.tool and not o.tool]

    @property
    def capability_misses(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.case.tool and o.tool and not o.capability_ok]

    @property
    def gate_safe(self) -> bool:
        """能否打开 ROUTER_GATE_MEMORY：记忆假阴必须为 0。

        用 0 而不是「足够低」：这类错误无声、且用户能直接感觉到人格断裂，
        没有可接受的非零比例。
        """
        return not self.memory_false_negative

    def by_level(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for o in self.outcomes:
            counts[o.level] = counts.get(o.level, 0) + 1
        return counts

    def render(self) -> str:
        lines = [
            f"用例总数: {self.total}",
            f"判定级别分布: {self.by_level()}",
            "",
            f"记忆假阴（该读却不读，高代价）: {len(self.memory_false_negative)}",
            f"记忆假阳（不该读却读了，低代价）: {len(self.memory_false_positive)}",
            f"工具假阳（不该调却调了，高代价）: {len(self.tool_false_positive)}",
            f"工具假阴（该调却没调，低代价）: {len(self.tool_false_negative)}",
            f"能力选错（tool 判对但选错能力）: {len(self.capability_misses)}",
            "",
            f"ROUTER_GATE_MEMORY 可否打开: {'可以' if self.gate_safe else '不可以'}",
        ]
        for label, group in (
            ("记忆假阴", self.memory_false_negative),
            ("工具假阳", self.tool_false_positive),
            ("能力选错", self.capability_misses),
        ):
            if not group:
                continue
            lines.append("")
            lines.append(f"— {label}明细 —")
            for o in group:
                lines.append(
                    f"  {o.case.message!r} → memory={o.memory} tool={o.tool} "
                    f"caps={o.capabilities} via {o.level}（{o.reason}）",
                )
        return "\n".join(lines)


def load_cases(path: Path | None = None) -> list[Case]:
    """载入用例。

    - 传 ``path``：只用这个文件（调用方明确想跑自己那一组）；
    - 不传：内置用例集 **加上** ``benchmark/*.json`` 里的全部用例。

    内置集是**规则表的回归地板**（记忆信号、寒暄整句匹配、切词坏词护栏），
    它必须始终参与。这里用「合并」而不是「有外部文件就用外部文件」：
    后者会让「加一个领域用例文件」这个动作静默地把地板整个撤掉——
    表现是 benchmark 依然通过，但已经不再检查规则表了。
    """
    if path is not None:
        return _parse_cases(json.loads(path.read_text(encoding="utf-8")))

    cases: list[Case] = list(BUILTIN_CASES)
    if CASES_DIR.is_dir():
        for file in sorted(CASES_DIR.glob("*.json")):
            try:
                cases.extend(_parse_cases(json.loads(file.read_text(encoding="utf-8"))))
            except Exception as e:
                # 单个用例文件坏掉不该中断整轮（照 config/spaces.py 的容错惯例）
                print(f"跳过 {file.name}: {e}")
    return cases


def _parse_cases(raw: Any) -> list[Case]:
    if not isinstance(raw, list):
        raise ValueError("用例文件应为 JSON 数组")
    out: list[Case] = []
    for item in raw:
        if not isinstance(item, dict) or "message" not in item:
            continue
        out.append(
            Case(
                message=str(item["message"]),
                memory=bool(item.get("memory", True)),
                tool=bool(item.get("tool", False)),
                capability=str(item.get("capability") or ""),
                note=str(item.get("note") or ""),
            ),
        )
    return out


async def run(
    cases: list[Case] | None = None,
    *,
    target: CapabilityRegistry | None = None,
    embedding_service=None,
    rules_only: bool = False,
) -> Report:
    """跑一轮 benchmark。

    参数:
        rules_only: 只跑 Level 0。不需要 embedding 服务，适合 CI 与离线回归。
    """
    from capability.router import route
    from capability.router.rules import apply_rules
    from capability.router.types import LEVEL_RULE, default_route

    items = cases if cases is not None else load_cases()
    report = Report()
    for case in items:
        if rules_only:
            ruled = apply_rules(case.message, target)
            result = ruled if ruled is not None else default_route("规则未命中", level=LEVEL_RULE)
        else:
            result = await route(
                case.message,
                target=target,
                embedding_service=embedding_service,
            )
        report.outcomes.append(
            Outcome(
                case=case,
                memory=result.memory,
                tool=result.tool,
                capabilities=list(result.capability_ids),
                level=result.level,
                reason=result.reason,
            ),
        )
    return report


# ============================================================
# 内置用例集
# ============================================================
# 覆盖三类：明确要回忆、明确要查询、纯闲聊。刻意包含几条**陷阱用例**——
# 它们是评审这套规则时最容易出错的地方，注释里说明了陷阱在哪。
BUILTIN_CASES: tuple[Case, ...] = (
    # ---- 明确要回忆 ----
    Case("你还记得我之前说的旅行计划吗", memory=True, tool=False),
    Case("我跟你说过我在学日语", memory=True, tool=False),
    Case("上次聊的那个游戏叫什么", memory=True, tool=False),
    Case("你忘了我不吃香菜吗", memory=True, tool=False),
    # ---- 纯寒暄：不需要记忆 ----
    Case("在吗？", memory=False, tool=False),
    Case("早上好", memory=False, tool=False),
    Case("晚安", memory=False, tool=False),
    Case("哈哈哈哈", memory=False, tool=False),
    # ---- 陷阱：寒暄开头但有实质内容，必须仍读记忆 ----
    Case(
        "你好，还记得我的旅行计划吗",
        memory=True,
        tool=False,
        note="整句匹配的护栏：不能因为以「你好」开头就判成寒暄",
    ),
    Case(
        "在吗，帮我查一下东京天气",
        memory=True,
        tool=True,
        note="寒暄词 + 工具意图：不能被寒暄规则短路掉工具判定",
    ),
    # ---- 普通闲聊：读记忆、不调工具 ----
    Case("今天心情不太好", memory=True, tool=False),
    Case("这个游戏怎么样", memory=True, tool=False, note="「怎么样」不该把它吸进任何能力"),
    Case("我不会用这个软件", memory=True, tool=False, note="「不会」不该命中天气类能力"),
    Case("你觉得我该换工作吗", memory=True, tool=False),
)


def _main() -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="Router benchmark")
    parser.add_argument("--cases", type=Path, default=None, help="用例 JSON 路径")
    parser.add_argument(
        "--rules-only",
        action="store_true",
        help="只测 Level 0（不需要 embedding 服务）",
    )
    args = parser.parse_args()

    from capability.adapters.astrbot import bootstrap

    bootstrap()
    cases = load_cases(args.cases)
    report = asyncio.run(run(cases, rules_only=args.rules_only))
    print(report.render())
    return 0 if report.gate_safe else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["BUILTIN_CASES", "Case", "Outcome", "Report", "load_cases", "run"]
