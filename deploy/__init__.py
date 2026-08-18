# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""部署与自检工具（``python -m deploy``）。

**检查逻辑全部在 Python 侧，GUI 只是渲染器**：doctor 输出结构化 JSON，桌面安装器
（Tauri）调用它并渲染。这样检查逻辑能被 pytest 覆盖、在终端可直接跑、将来 Web 前端
复用同一接口、GUI 换框架时逻辑不用重写。

三层划分：``probe`` 采集（有副作用，逻辑简单）→ ``checks`` 判断（纯函数，逻辑复杂）
→ ``report`` 渲染。测试重点压在 ``checks``。
"""
