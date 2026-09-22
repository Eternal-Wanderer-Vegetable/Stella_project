# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""用户可管理的 Cron / 主动 Agent 调度子系统（仅覆盖报告第 4 项）。

分层的单一职责（对应 docs/plans/2026-09-22-gitnexus-plan-user-cron-agent.md §6）：

- :mod:`.models` —— 枚举与数据类（Task / Run / AuditEntry）与 UTC 时间助手；
- :mod:`.migrations` —— 独立 SQLite 库（``STELLA_HOME/scheduling/tasks.db``）的
  schema 版本迁移；失败抛 :class:`.migrations.MigrationError`，调用方必须停用
  worker 而不是带病运行；
- :mod:`.store` —— 任务/运行/配额/租约/审计的事务性存取（幂等插入、修订门闩、
  租约恢复、每日配额）；
- :mod:`.cron` —— 五字段 APScheduler 3.x 兼容方言的解析、校验与 next-fire 预览；
- :mod:`.service` —— 生命周期操作（create/list/show/edit/pause/resume/cancel/
  run-now/history）与权限、群边界、审计；
- :mod:`.context` —— 有界只读上下文；调度专用的严格门控在新函数
  ``memory.proactive_gate.can_speak_for_scheduled``（复用主动发言安全闸，
  仅豁免新消息启发式，策略读失败一律拒绝）；
- :mod:`.agent` —— 有界 Agent 运行器（时间/轮数/工具数/输出上限 + 显式允许清单）；
- :mod:`.delivery` —— 投递状态机（ready → sending → sent / delivery_unknown）；
- :mod:`.runtime` —— 租约 worker（认领到期运行、群锁串行、重启恢复、优雅停止）；
- :mod:`.commands` —— 群内任务指令的解析（在既有 priority=1 分类器之前的互斥层）。

v1 边界刻意收窄：仅群任务（私聊目标拒绝）、真实绑定为目标群、无任意插件/技能
执行、无 @all 扇出、不承诺 QQ 投递 exactly-once（进程可在平台调用后、回执落库前
死掉，此时记 ``delivery_unknown``，只允许人工重试）。
"""
