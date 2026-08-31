# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""主动 @ 流程中可独立验证的部分（不启动 NoneBot）。

ai_gateway 的发送链路依赖 OneBot 运行时，这里只覆盖记账与退避的正确性——
它们决定「会不会重复骚扰同一个人」，是这套机制最需要护栏的地方。
"""

import pytest

from memory.proactive import ProactiveController
from memory.proactive_state import get_state, record_at, record_reply_result


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "proactive.db"
    path.touch()
    monkeypatch.setattr("memory.proactive_state.DB_PATH", path)
    monkeypatch.setattr("memory.schema.DB_PATH", path)
    return path


def test_record_at_counts_and_persists(db):
    """发出即计数，且落库后可跨实例读取。"""
    record_at(1, 1001, topic="最近在玩什么游戏")
    state = get_state(1, 1001)
    assert state["at_count_today"] == 1
    assert state["last_asked_topic"] == "最近在玩什么游戏"
    assert state["last_at_at"] is not None

    record_at(1, 1001, topic="平时喜欢吃什么")
    assert get_state(1, 1001)["at_count_today"] == 2


def test_no_reply_accumulates_then_resets(db):
    """连续无回应累计，一次回应即归零（退避可恢复）。"""
    record_at(1, 1001)
    record_reply_result(1, 1001, replied=False)
    assert get_state(1, 1001)["consecutive_no_reply"] == 1

    record_reply_result(1, 1001, replied=False)
    assert get_state(1, 1001)["consecutive_no_reply"] == 2

    record_reply_result(1, 1001, replied=True)
    assert get_state(1, 1001)["consecutive_no_reply"] == 0


def test_quota_is_per_user(db):
    """配额按用户独立，不互相影响。"""
    record_at(1, 1001)
    record_at(1, 1001)
    record_at(1, 1002)
    assert get_state(1, 1001)["at_count_today"] == 2
    assert get_state(1, 1002)["at_count_today"] == 1


def test_last_spoke_ts_tracks_any_message():
    """last_spoke_ts 记的是「发过任意消息」，不是「回应了 Bot」。

    回应检测已改用 last_tome_ts（见 tests/test_reply_detection.py）：这里只保留
    活跃度时间戳本身的语义断言，免得再有人把它当成回应判据。
    """
    # 用独立实例，不污染全局单例（真实 monotonic 值会干扰其他用例的假时钟）
    proactive = ProactiveController()

    assert proactive.last_spoke_ts(1, 1001) is None

    proactive.record_message(1, 1001)
    assert proactive.last_spoke_ts(1, 1001) > 0.0
    # 反向断言：发言不得被记成「对 Bot 说话」
    assert proactive.last_tome_ts(1, 1001) is None
