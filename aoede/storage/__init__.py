# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Aoede 持久状态子包。

``legacy_state`` 保有旧 quota/mute/announce 表（schema23 的
proactive/participation DDL 兼容区，计划 §6.1 第 3 条）；新状态表的真正
领域归属在第二阶段（S2）随 scoped repository 落地。
"""
