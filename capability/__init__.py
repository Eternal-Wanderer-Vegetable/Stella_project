# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Capability 层：把「聊天能力」「记忆能力」「工具能力」解耦成任务协议通信。

设计见 ``design_docs/Stella 智能机器人架构升级方案：基于 Capability Router 与
Comes 工具执行层的任务调度系统.md`` 与 ``design_docs/Capability Router 与 Comes
落地方案 v1.0.md``。

四个模块的职责边界：

| 模块 | 职责 | 不负责 |
|-|-|-|
| Router | 判断本次请求需要哪些能力 | 记忆写入、工具选择、工具执行、人格回复 |
| Stella | 用户交互、人格表达、最终回复 | 工具执行 |
| Memory | 记忆检索与管理 | 判断是否需要检索（Router 的活） |
| Comes | 工具调用、插件执行 | 理解用户、判断意图、管理人格 |

本包含三块：``registry``（能力注册表）、``router``（三级路由）、``comes``（工具执行）。
子模块一律**延迟导入**：``router.semantic`` 会拉起 ``memory.embeddings``、
``comes.executor`` 会拉起 ``astrbot_compat``，在包入口就 import 会让「只想用协议」的
调用方被迫拖上整条依赖链，也会在测试里造成 import 顺序耦合。

**注册表单例刻意不在这里再导出**，取用一律写 ``from capability.registry import registry``。
在包入口 ``from capability.registry import registry`` 会让包属性 ``capability.registry``
从子模块变成那个单例对象，于是 ``import capability.registry as m`` 拿到的是实例而不是模块
（``import a.b as c`` 会退化成 ``getattr(a, "b")``）。这种遮蔽只在 ``__init__`` 已执行时
才出现，行为随 import 顺序变化，属于最难查的一类问题。
"""

from capability.registry import Capability, CapabilityProvider, CapabilityRegistry

__all__ = [
    "Capability",
    "CapabilityProvider",
    "CapabilityRegistry",
]
