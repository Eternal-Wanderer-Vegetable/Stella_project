# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Aoede：主动参与子系统（2026-11-03 计划 §3）。

Aoede 负责「是否、何时、对谁开口」：机会/时机/预算/一次性求证调度。
它通过 ``stella_contracts.aoede`` 定义的中立端口访问 Mneme（记忆子系统），
不直接读写候选表，也不拥有记忆晋升规则。

布局（计划 §3.1）：

- ``aoede.controller``      —— 活跃度、近期发言与临时 skip 状态（原 memory.proactive）
- ``aoede.gate``            —— 主动硬门禁 can_speak（原 memory.proactive_gate）
- ``aoede.storage.legacy_state`` —— 旧 quota/mute/announce 持久状态（原 memory.proactive_state）
- ``aoede.verification.target``  —— 主动 @ 选人编排（原 memory.proactive_target）
- ``aoede.prompts``         —— 主动表达、SKIP、服务端问题变体（原 memory.proactive_prompt）
- ``aoede.contract``        —— 主动验证合同编排（原 memory.proactive_contract）
- ``aoede.participation``   —— 参与评分决策层（原 memory.participation）
- ``aoede.host``            —— 宿主注入面（bot/发送/观测/引擎适配）
- ``aoede.service``         —— 主动插话编排（原 ai_gateway 主动区）
- ``aoede.verification.service`` —— 主动 @ 编排（原 ai_gateway ``_proactive_at_user`` 区）

本包不依赖 ``memory.*`` 兼容层；``memory.*`` 是指向本包的显式别名。
"""

from __future__ import annotations

__all__ = [
    "contract",
    "controller",
    "gate",
    "host",
    "participation",
    "prompts",
    "service",
    "storage",
    "verification",
]
