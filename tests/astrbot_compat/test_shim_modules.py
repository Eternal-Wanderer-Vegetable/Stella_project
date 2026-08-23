# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""shim 补充模块：astrbot.api.all 通配入口与 astrbot.core.star.filter.* 子模块。"""

from __future__ import annotations

import astrbot.api  # noqa: F401  # 触发 shim 注入（conftest 已 install_shim）


def test_api_all_wildcard_import():
    # 上游官方推荐写法：from astrbot.api.all import *
    from astrbot.api import all as api_all

    assert api_all.__all__
    for name in ("command", "regex", "GreedyStr", "Plain", "Image", "AstrMessageEvent", "Star"):
        assert name in api_all.__all__, name
        assert getattr(api_all, name) is not None


def test_api_all_members_are_canonical_objects():
    from astrbot.api import all as api_all

    import astrbot_compat.components as _c
    import astrbot_compat.filters as _f

    assert api_all.GreedyStr is _f.GreedyStr
    assert api_all.command is _f.command
    assert api_all.Plain is _c.Plain


def test_core_star_filter_command_submodule():
    # 插件惯用写法：from astrbot.core.star.filter.command import GreedyStr
    from astrbot.core.star.filter import command as cmd_mod
    from astrbot.core.star.filter.command import CommandFilter, GreedyStr

    import astrbot_compat.filters as _f

    assert GreedyStr is _f.GreedyStr
    assert CommandFilter is _f.CommandFilter
    assert cmd_mod.command is _f.command


def test_core_star_filter_other_submodules():
    from astrbot.core.star.filter import (
        command,  # noqa: F401
        custom_filter,
        event_message_type,
        permission_type,
        regex,
    )

    import astrbot_compat.filters as _f

    assert regex.regex is _f.regex
    assert permission_type.PermissionType is _f.PermissionType
    assert event_message_type.EventMessageType is _f.EventMessageType
    assert custom_filter.CustomFilter is _f.CustomFilter
