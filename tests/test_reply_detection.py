# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""主动 @ 的回应判定：只认「对 Bot 说话」，不认「在群里说过话」。

守的是 design_docs/bug_report/bug_report_2026_8_31#1.md §5.1：
回应检测原先读 ``last_spoke_ts``（该用户最后一次发任意消息）。但被追问的人本
来就是从「近期活跃用户」里选出来的，随后必然还会在群里说话，于是判定在活跃群
里几乎恒为真——``consecutive_no_reply`` 一直被清零，``PROACTIVE_MAX_NO_REPLY``
的自动退避从未触发。这个缺陷不报错，只表现为「对不想聊的人也一直追问」。

改判后新增的风险是反向的：纯文本接话（不 @、不回复）会被算作未回应，攒满上限
后该用户会被永久排除——``consecutive_no_reply`` 没有任何按时间的自然衰减。因此
AT_MENTION 入库路径会调用 ``reset_no_reply`` 自愈。两个方向都必须有断言，
只测一侧的话，把判定写死成恒真或恒假都能通过其中一半。
"""

import pytest

import memory.proactive_target as pt
from memory import proactive_state
from memory.proactive import ProactiveController
from memory.proactive_target import can_at_user

# ── 1. 控制器：两个时间戳必须分开 ──────────────────────────


def test_plain_message_does_not_count_as_addressing_bot():
    """在群里说话不等于回应 Bot——这正是原缺陷的判定依据。"""
    ctrl = ProactiveController()
    ctrl.record_message(1, 1001)

    assert ctrl.last_spoke_ts(1, 1001) is not None, "活跃度统计仍要算上这条"
    assert ctrl.last_tome_ts(1, 1001) is None, "但它不构成「回应了 Bot」"


def test_record_tome_marks_addressing_bot():
    """@ / 回复 Bot 之后，回应判定才成立。"""
    ctrl = ProactiveController()
    asked_at = 0.0

    assert ctrl.last_tome_ts(1, 1001) is None
    ctrl.record_tome(1, 1001)
    last = ctrl.last_tome_ts(1, 1001)
    assert last is not None and last > asked_at


def test_tome_is_per_user_and_per_group():
    """时间戳按群和用户隔离，不得串台。"""
    ctrl = ProactiveController()
    ctrl.record_tome(1, 1001)

    assert ctrl.last_tome_ts(1, 1002) is None
    assert ctrl.last_tome_ts(2, 1001) is None


def test_tome_before_asking_is_not_a_reply():
    """提问之前的那次 @ 不算回应（判定必须是时间戳比较，不是「有没有过」）。"""
    import time

    ctrl = ProactiveController()
    ctrl.record_tome(1, 1001)
    asked_at = time.monotonic() + 1.0

    last = ctrl.last_tome_ts(1, 1001)
    assert last is not None
    assert not (last > asked_at)


# ── 2. 退避的自愈阀门 ──────────────────────────────────


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "reply.db"
    monkeypatch.setattr(proactive_state, "DB_PATH", path)
    monkeypatch.setattr(pt, "DB_PATH", path)
    return path


def test_reset_no_reply_zeroes_counter(db):
    """「对 Bot 说话」即解除已累计的无回应。"""
    proactive_state.record_at(1, 1001)
    proactive_state.record_reply_result(1, 1001, replied=False)
    assert proactive_state.get_state(1, 1001)["consecutive_no_reply"] == 1

    proactive_state.reset_no_reply(1, 1001)
    assert proactive_state.get_state(1, 1001)["consecutive_no_reply"] == 0


def test_reset_no_reply_does_not_touch_other_users(db):
    """反向断言：归零只作用于该用户，不得顺手清掉别人的计数。"""
    proactive_state.record_at(1, 1001)
    proactive_state.record_at(1, 1002)
    proactive_state.record_reply_result(1, 1001, replied=False)
    proactive_state.record_reply_result(1, 1002, replied=False)

    proactive_state.reset_no_reply(1, 1001)

    assert proactive_state.get_state(1, 1001)["consecutive_no_reply"] == 0
    assert proactive_state.get_state(1, 1002)["consecutive_no_reply"] == 1


def test_reset_no_reply_on_unknown_user_is_noop(db):
    """从未被 @ 过的用户没有行，归零不得建行也不得抛错。"""
    proactive_state.reset_no_reply(1, 9999)
    assert proactive_state.get_state(1, 9999)["consecutive_no_reply"] == 0


def test_counter_still_accumulates_after_reset(db):
    """反向断言：归零之后计数照常重新累计，退避机制不能被自愈阀门废掉。"""
    proactive_state.record_at(1, 1001)
    proactive_state.record_reply_result(1, 1001, replied=False)
    proactive_state.reset_no_reply(1, 1001)
    proactive_state.record_reply_result(1, 1001, replied=False)

    assert proactive_state.get_state(1, 1001)["consecutive_no_reply"] == 1


# ── 3. 串到闸门：退避可触发，也可自愈 ────────────────────


def test_backoff_triggers_then_heals(db, monkeypatch):
    """攒满上限后被排除，一次「对 Bot 说话」后重新可问。

    上限取 config 的 PROACTIVE_MAX_NO_REPLY 而非写死 2——写死的话调低配置会
    让这条用例变成空跑。冷却与配额在此不参与判定：把 24h 发言数固定为 0 使
    配额为 BASE，并只 record_at 一次，避免与退避断言混在一起。
    """
    monkeypatch.setattr(pt, "count_user_messages_24h", lambda g, u: 0)
    monkeypatch.setattr(pt, "PROACTIVE_AT_USER_COOLDOWN", 0)

    proactive_state.record_at(1, 1001)
    for _ in range(pt.PROACTIVE_MAX_NO_REPLY):
        proactive_state.record_reply_result(1, 1001, replied=False)

    ok, reason = can_at_user(1, 1001)
    assert ok is False
    assert "退避" in reason

    proactive_state.reset_no_reply(1, 1001)
    ok, reason = can_at_user(1, 1001)
    assert ok is True, f"自愈失败：{reason}"
