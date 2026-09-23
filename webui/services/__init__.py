# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebUI 只读服务层。

M1 面板的取数逻辑：每个模块只做「调既有门面 + 组装响应形状」，绝不复制
业务逻辑；SQLite 一律只读（usage_store 拥有写侧）。取数失败返回降级形状
（空列表 / unavailable 标记），绝不让面板 500。
"""
