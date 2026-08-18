# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""优雅停止等待逻辑的单元测试。

用假任务（asyncio.sleep）验证：会等 pending_tasks 收尾、超时后放弃、
reply_tasks 被取消。真实启停信号依赖平台，不在此测试。
"""

from __future__ import annotations

import asyncio

from core.shutdown import wait_for_tasks


def _run(coro) -> None:
    """在临时事件循环里跑完异步协程（不依赖 pytest-asyncio）。"""
    asyncio.run(coro)


def test_waits_for_pending_tasks():
    replies: set[asyncio.Task] = set()
    done_flags: list[bool] = []

    async def _work() -> None:
        await asyncio.sleep(0.01)
        done_flags.append(True)

    async def _scenario() -> None:
        pending = [asyncio.create_task(_work()) for _ in range(3)]
        await wait_for_tasks(replies, pending, grace_seconds=5.0)
        assert all(t.done() for t in pending)

    _run(_scenario())
    assert done_flags == [True, True, True]


def test_cancels_reply_tasks():
    replies: set[asyncio.Task] = set()

    async def _long_sleep() -> None:
        await asyncio.sleep(60)

    async def _scenario() -> None:
        for _ in range(2):
            t = asyncio.create_task(_long_sleep())
            replies.add(t)
            t.add_done_callback(replies.discard)
        await wait_for_tasks(replies, [], grace_seconds=0.1)

    _run(_scenario())
    assert all(t.cancelled() for t in replies)
    assert replies == set()


def test_timeout_gives_up():
    replies: set[asyncio.Task] = set()

    async def _never_ends() -> None:
        await asyncio.sleep(60)

    async def _scenario() -> None:
        task = asyncio.create_task(_never_ends())
        await wait_for_tasks(replies, [task], grace_seconds=0.05)
        assert not task.done()
        task.cancel()

    _run(_scenario())


def test_no_pending_returns_immediately():
    replies: set[asyncio.Task] = set()
    _run(wait_for_tasks(replies, [], grace_seconds=0.1))
    assert replies == set()
