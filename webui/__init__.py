# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""WebUI（v2 控制面）后端包。

浏览器与桌面壳共用的管理面板 API（``/api/v1/*``）与前端静态托管，挂在
NoneBot 已有的 ASGI app 上（同 ``/stella/status`` 的先例，**不新增端口**）。
入口：``webui.mount.setup_webui()``（bot.py 在所有启动钩子注册之后调用，
保证挂载的 ``/`` catch-all 排在 OneBot WS 与状态路由之后）。

与 v1 状态接口（只读、回环、无凭据）的本质区别：本层带写操作，因此
每个路由都必须鉴权——唯一豁免是 auth 路由里的公开端点（setup-status /
setup / login / desktop-session），它们自身就是鉴权的入口。

设计契约见 design_docs/Stella GUI v2 与 WebUI 建设方案 v1.0.md（§7 API 表、
§9 安全设计）；配置键见 config/settings.py 的「WebUI 面板」节。
"""
