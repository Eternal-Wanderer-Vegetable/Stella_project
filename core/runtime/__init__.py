# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Stella 自有运行时的 Python 稳定边界（计划修订 v2，原 §6.2/§6.4）。

已落地：``turn_service``（prepare/generate/finalize 领域阶段）、
``facade``（唯一入口 owner、epoch fence、独立运行记录、legacy/native 切换）。
原 Node 桥/线协议已随计划修订 v2 移除（Cortico 降级为设计参考）。
"""
