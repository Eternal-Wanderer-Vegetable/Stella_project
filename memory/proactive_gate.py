# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动发言的统一准入闸门（Proactive Gate）。

背景：主动发言的判定条件已有六项（总开关、分路开关、运行时静音、睡眠时段、
醒来缓冲、冷却与新消息门槛），原先散落在 proactive_speak_job /
_proactive_at_user / should_speak 三处。每加一个条件就要改三个调用点，必然漏。

本模块提供唯一入口 ``can_speak()``，所有主动路径只问它。返回值带原因字符串，
便于排查「为什么这次没说话」。

**不影响被动路径**：@ 回复不经过本模块。睡眠或静音期间被 @ 照常回复——
用户主动叫它却不回应看起来像掉线，且 AT_MENTION 是当前唯一的记忆来源，
睡眠期不回复等于每天损失数小时的记忆采集。
"""
from __future__ import annotations

import time
from datetime import datetime
from datetime import time as dtime

from nonebot import logger

from config import (
    PROACTIVE_AT_ENABLED,
    PROACTIVE_ENABLED,
    PROACTIVE_RUNTIME_TOGGLE_ENABLED,
    PROACTIVE_SLEEP_ENABLED,
    PROACTIVE_SLEEP_END,
    PROACTIVE_SLEEP_START,
    PROACTIVE_WAKEUP_GRACE_SECONDS,
)
from memory.proactive import get_proactive
from memory.proactive_state import get_runtime_state

# 睡眠时段的兜底默认值（配置格式非法时使用）
_DEFAULT_SLEEP_START = dtime(23, 30)
_DEFAULT_SLEEP_END = dtime(7, 30)

# group_id -> 苏醒时刻（monotonic）。进程内状态，用于醒来缓冲。
_wakeup_at: dict[int, float] = {}
# group_id -> 上一次判定的睡眠状态。用于检测睡眠↔苏醒跃变（播报与缓冲的触发点）。
_last_sleeping: dict[int, bool] = {}


def _parse_hhmm(text: str, default: dtime) -> dtime:
    """解析 HH:MM；失败时返回默认值。

    配置笔误不应让睡眠功能整体失效（那会让 Bot 通宵说话），因此回退而非抛错。
    """
    try:
        hour, minute = str(text).strip().split(":")
        return dtime(int(hour), int(minute))
    except (ValueError, TypeError, AttributeError):
        logger.warning(f"⚠️ [Gate] 睡眠时间格式非法: {text!r}，使用默认值 {default}")
        return default


def is_sleeping(now: datetime | None = None) -> bool:
    """当前是否处于睡眠时段。

    用**本地时间**：它描述的是人类作息，与数据库时间戳（UTC）无关。
    支持跨午夜区间（如 23:30 → 07:30）。start == end 视为不睡眠。
    """
    if not PROACTIVE_SLEEP_ENABLED:
        return False
    now = now or datetime.now()
    start = _parse_hhmm(PROACTIVE_SLEEP_START, _DEFAULT_SLEEP_START)
    end = _parse_hhmm(PROACTIVE_SLEEP_END, _DEFAULT_SLEEP_END)
    if start == end:
        return False
    current = now.time()
    if start < end:
        return start <= current < end
    # 跨午夜：当前时间晚于起点，或早于终点
    return current >= start or current < end


def note_sleep_transition(group_id: int, sleeping: bool) -> str | None:
    """记录睡眠状态跃变，返回跃变类型（``"sleep"`` / ``"wakeup"``）或 None。

    首次调用（进程刚启动）**不视为跃变**——否则每次重启都会播报一次。
    苏醒跃变时记录时刻，供醒来缓冲使用。
    """
    previous = _last_sleeping.get(group_id)
    _last_sleeping[group_id] = sleeping
    if previous is None or previous == sleeping:
        return None
    if sleeping:
        return "sleep"
    _wakeup_at[group_id] = time.monotonic()
    return "wakeup"


def in_wakeup_grace(group_id: int) -> bool:
    """是否处于醒来缓冲期内。

    苏醒后不立刻恢复主动发言：积压一夜的活跃度统计会让它一睁眼就连发几句。
    """
    woke = _wakeup_at.get(group_id)
    if woke is None:
        return False
    return (time.monotonic() - woke) < PROACTIVE_WAKEUP_GRACE_SECONDS


def is_muted(group_id: int) -> bool:
    """该群是否被管理员运行时静音（持久化状态，重启后仍生效）。"""
    if not PROACTIVE_RUNTIME_TOGGLE_ENABLED:
        return False
    return bool(get_runtime_state(group_id)["proactive_muted"])


def can_speak(group_id: int, kind: str) -> tuple[bool, str]:
    """主动发言的统一准入判定。

    :param group_id: 群号
    :param kind: ``"at"``（主动 @ 某位用户）或 ``"join"``（话题插话）
    :return: ``(是否允许, 原因说明)``

    检查顺序由粗到细，先短路的条件开销更低（静音需要查库，放在纯内存判断之后
    会更省，但它是用户显式设置的意图，优先级应当高于时段与冷却）：

        总开关 → 分路开关 → 运行时静音 → 睡眠时段 → 醒来缓冲
        → 群级冷却 → 新消息门槛

    注意：话题插话的**概率掷骰不在此处**——那是 join 路径独有的，
    由调用方在 gate 通过后自行掷骰（主动 @ 不掷骰，它有配额与冷却约束）。
    """
    if not PROACTIVE_ENABLED:
        return False, "主动发言总开关已关闭"

    if kind == "at" and not PROACTIVE_AT_ENABLED:
        return False, "主动 @ 已关闭"

    if is_muted(group_id):
        return False, "管理员已临时关闭本群主动发言"

    if is_sleeping():
        return False, f"睡眠时段（{PROACTIVE_SLEEP_START}–{PROACTIVE_SLEEP_END}）"

    if in_wakeup_grace(group_id):
        return False, f"醒来缓冲期（{PROACTIVE_WAKEUP_GRACE_SECONDS:.0f}s 内不主动发言）"

    proactive = get_proactive()
    if proactive.in_cooldown(group_id):
        return False, "群级冷却中"

    if not proactive.has_enough_new_messages(group_id):
        return False, f"距上次发言仅 {proactive.messages_since_spoke(group_id)} 条新消息"

    return True, "允许"


def reset_state() -> None:
    """清空进程内状态（供测试使用）。"""
    _wakeup_at.clear()
    _last_sleeping.clear()
