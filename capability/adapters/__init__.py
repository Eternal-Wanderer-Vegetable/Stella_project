# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""能力实现方式的适配层。

本轮只有 ``astrbot``（AstrBot 插件工具）。``CapabilityProvider.kind`` 已经留好
MCP / API / native 的口子，但没有真实调用方时抽象一定是错的，所以不提前实现
（方案第 20 节把它们列为「未来支持」）。
"""
