# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Adapter availability rules shared by the control plane and Bot runtime."""

import sys

BLOCKED_ADAPTERS = {
    "nonebot_adapter_walleq": "walleQ",
    "nonebot.adapters.ntchat": "ntchat",
    "nonebot.adapters.mail": "mailSecurityCompatibility",
}

# Temporarily disabled: only OneBot V11 is in use. These adapters' packages are no
# longer installed (nonebot-adapter-villa pins protobuf<5, which carries an unfixed
# advisory), but their integration code in core/transport/adapters stays in place.
# Re-enable one by removing it here and restoring its package in requirements.txt
# and pyproject.toml. Tracked in https://github.com/Eternal-Wanderer-Vegetable/stella_project/issues/134.
TEMPORARILY_DISABLED_ADAPTERS = dict.fromkeys(
    (
        "nonebot.adapters.ding",
        "nonebot.adapters.feishu",
        "nonebot.adapters.telegram",
        "nonebot.adapters.qq",
        "nonebot.adapters.kaiheila",
        "nonebot.adapters.mirai",
        "nonebot.adapters.onebot.v12",
        "nonebot.adapters.console",
        "nonebot.adapters.github",
        "nonebot.adapters.minecraft",
        "nonebot.adapters.bilibili",
        "nonebot.adapters.villa",
        "nonebot.adapters.red",
        "nonebot.adapters.discord",
        "nonebot.adapters.satori",
        "nonebot.adapters.dodo",
        "nonebot.adapters.rocketchat",
        "nonebot.adapters.kritor",
        "nonebot_adapter_tailchat",
        "nonebot.adapters.heybox",
        "nonebot.adapters.wxmp",
        "nonebot.adapters.milky",
        "nonebot.adapters.efchat",
        "nonebot.adapters.vocechat",
        "nonebot.adapters.bilibili_live",
        "nonebot.adapters.yunhu",
        "nonebot.adapters.wxclaw",
        "nonebot.adapters.matrix",
    ),
    "temporarilyDisabled",
)


def unavailable_adapter_reasons() -> dict[str, str]:
    """Return adapters blocked by policy, temporarily disabled, or unsupported here."""
    unavailable = {**TEMPORARILY_DISABLED_ADAPTERS, **BLOCKED_ADAPTERS}
    if sys.version_info < (3, 11) and "nonebot.adapters.heybox" not in unavailable:
        unavailable["nonebot.adapters.heybox"] = "requiresPython311"
    return unavailable
