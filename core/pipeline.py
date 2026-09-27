# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""聊天主处理管线（兼容门面）。

实现已迁移至 :mod:`core.runtime.turn_service`（迁移计划 M2：prepare/generate/
finalize 三阶段可独立测试）。本模块保留原有公开面——``Pipeline``、钩子类型别名
与 ``_compose_prompt``——供 gateway、extensions 与既有测试继续使用；签名与
行为不变，回退仅需还原本文件。
"""

from __future__ import annotations

from config import MEMORY_V2_ENABLED, PLANNER_MAX_LLM_CALLS_PER_TURN
from core.runtime.turn_service import (
    BUDGET_LIMITED,
    DIRECT,
    GENERATE,
    NO_BACKEND,
    SILENT,
    PostHook,
    PreHook,
    TurnPlan,
    TurnService,
    _compose_prompt,
)

__all__ = [
    "BUDGET_LIMITED",
    "DIRECT",
    "GENERATE",
    "MEMORY_V2_ENABLED",
    "NO_BACKEND",
    "PLANNER_MAX_LLM_CALLS_PER_TURN",
    "SILENT",
    "Pipeline",
    "PostHook",
    "PreHook",
    "TurnPlan",
    "TurnService",
    "_compose_prompt",
]


class Pipeline(TurnService):
    """主处理管线：把"钩子 + LLM 后端"组装成一条可复用的消息处理链路。

    使用方式：
        pipeline = Pipeline(timeout=90.0)
        pipeline.register_pre_hook(...)
        pipeline.register_post_hook(...)
        pipeline.set_llm_backend(backend)
        ctx = await pipeline.run(ctx)

    钩子按优先级（数字越大越先执行）排序；LLM 调用经调度器
    acquire(gate_of(ROLE_CHAT)) 排队——纯本地时那把闸门并发度 1，即串行访问
    共享的本地模型后端。

    阶段语义见 :class:`~core.runtime.turn_service.TurnService`：
    ``prepare_turn``（pre hooks/直回短路/Planner/prompt 组装与预算）→
    ``generate_reply``（闸门 + 单次生成 + 兜底）→ ``finalize_turn``
    （trace 与后置 hooks）。Cortico 迁移后新运行时经同一批阶段服务执行
    （turn_service 是唯一实现，本类只是兼容入口）。
    """
