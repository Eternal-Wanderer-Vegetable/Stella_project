# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa：跨轮次外部 Agent 任务运行层（design_docs/Cometa 外部 Agent 任务运行层实施方案 v1.0）。

Stella 按需委派 Codex 等外部 Agent：聊天入口提交任务 → SQLite 受理回执 →
独立 worker 进程认领并驱动后端 → 归一事件与结果落库 → 通知投递回原请求者。

依赖方向（方案 §3.2，不得反向）::

    入口/能力层 → cometa.service → store/policy
    worker → executor → backend

内核纪律：

- **不 import ai_gateway / ChatContext / 聊天人格**——内核对聊天零依赖；
- **不 import nonebot**——独立 worker（``python -m cometa.worker``）与 Bot 进程
  共用同一套模块；日志用 stdlib logging（Bot 进程里由日志初始化接管输出）；
- 所有持久 DTO 带 ``schema_version``；任务/attempt 用 UUID，短 ID 只供人读；
- 内核不碰平台（QQ/WebUI），投递只经由注入的 Sender 协议。

本包 ``import`` 无任何运行时副作用：不建目录、不连库、不读配置文件。
"""

from __future__ import annotations

__all__: list[str] = []
