# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""插件与能力清单只读取数（方案 §6.5.1 的 M1 只读部分）。

数据三路合并：astrbot_compat 注册表（插件元数据与激活态）、loader 的失败
清单、capability.inventory 的能力声明快照（工具/可路由/退避）。全部是
结构化字段——inventory 的脱敏契约（无 description/examples 原文）由其
自身保证，webui 不伸手进去挖。
"""

from __future__ import annotations


def plugin_inventory() -> dict:
    plugins: list[dict] = []
    try:
        from astrbot_compat import registry as compat_registry

        for md in compat_registry.star_registry:
            plugins.append(
                {
                    "plugin_id": md.plugin_id,
                    "name": md.name,
                    "display_name": md.display_name,
                    "author": md.author,
                    "desc": md.desc,
                    "version": md.version,
                    "repo": md.repo,
                    "root_dir_name": md.root_dir_name,
                    "reserved": md.reserved,
                    "activated": md.activated,
                    "handlers": len(md.star_handler_full_names),
                }
            )
    except Exception:
        plugins = []
    failed: dict = {}
    try:
        from astrbot_compat.loader import get_failed_plugins

        failed = get_failed_plugins()
    except Exception:
        failed = {}
    capabilities = None
    try:
        from capability.inventory import snapshot

        capabilities = snapshot()
    except Exception:
        capabilities = None
    return {"plugins": plugins, "failed": failed, "capabilities": capabilities}
