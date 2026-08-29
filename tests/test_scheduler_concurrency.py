# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""core.llm.scheduler 闸门并发度的测试。

改造把闸门从「一把 ``asyncio.Lock``」换成「每个端点槽一个 ``Semaphore(concurrency)``」。
这组用例守两件事：

1. **并发度 1 与改造前的 Lock 逐字等价**——纯本地部署的全部行为都压在这条上；
2. **不同资源互不阻塞**——纯本地下 ``LOCAL``（27B/GPU）与 ``EXTRA``（E4B/CPU）
   要真正并行，这正是改造前 chat / consolidation 两把锁分离的意义。

以及一条安全性质：并发度解析不出来时**一律退回 1**。把未知资源当独占资源，
绝不会因为配置读不到就放开并发——放开的后果是本地模型被并发推理拖慢，
而且表现为「间歇性变慢」，最难定位。
"""

from __future__ import annotations

import asyncio

import pytest

import core.llm.registry as registry
import core.llm.scheduler as scheduler

# 在任何用例替换解析器之前记下调度器上装着的那一个。它应当是 import
# ``core.llm.registry`` 的副作用装上去的——模块导入发生在收集期，早于本文件
# 任何用例运行，所以这个快照是干净的。
_RESOLVER_AT_IMPORT = scheduler._concurrency_resolver


@pytest.fixture(autouse=True)
def _clean_scheduler():
    """逐例重建闸门。

    必须清空：``_resources`` 里的 ``asyncio.Semaphore`` 会绑定到创建它的事件循环，
    跨 ``asyncio.run()`` 复用会抛「bound to a different event loop」。
    退出时把生产用的解析器装回去——它是 import ``core.llm.registry`` 的副作用，
    某个用例替换后不还原，后面的用例就会拿到假并发度。
    """
    scheduler.reset_state()
    yield
    scheduler.reset_state()
    scheduler.set_concurrency_resolver(registry.concurrency_of)


def _with_limits(limits: dict[str, int]) -> None:
    scheduler.set_concurrency_resolver(lambda name: limits.get(name, 1))


async def _peak_concurrent(resource: str, tasks: int) -> int:
    """让 ``tasks`` 个任务同时抢同一把闸门，返回**同时持有**的峰值。

    用「进入后等同一个 Event」而不是 sleep 计时：计时会让用例在慢机器上抖动，
    而这里要断言的是精确的并发上限。
    """
    release = asyncio.Event()
    live = 0
    peak = 0

    async def worker():
        nonlocal live, peak
        async with scheduler.acquire(resource, tag="t"):
            live += 1
            peak = max(peak, live)
            await release.wait()
            live -= 1

    running = [asyncio.create_task(worker()) for _ in range(tasks)]
    # 反复让出控制权，直到所有「能进的」都进来了；每次 sleep(0) 走一轮就绪队列
    for _ in range(50):
        await asyncio.sleep(0)
    release.set()
    await asyncio.gather(*running)
    return peak


# ---------------------------------------------------------------- 并发度语义


def test_limit_one_serializes_like_the_old_lock():
    """并发度 1 = 改造前的 asyncio.Lock。纯本地部署的等价性全压在这一条上。"""
    _with_limits({"LOCAL": 1})
    assert asyncio.run(_peak_concurrent("LOCAL", 4)) == 1


def test_online_limit_admits_exactly_that_many():
    """在线端点放开到 N 就该真的同时进 N 个，多一个都不行。"""
    _with_limits({"ONLINE_CHAT": 3})
    assert asyncio.run(_peak_concurrent("ONLINE_CHAT", 6)) == 3


def test_every_waiter_eventually_gets_in():
    """名额是会归还的：6 个任务全部完成，不能有谁被永久挂住。"""
    _with_limits({"ONLINE_CHAT": 2})
    done: list[int] = []

    async def main():
        async def worker(i: int):
            async with scheduler.acquire("ONLINE_CHAT", tag=f"t{i}"):
                await asyncio.sleep(0)
                done.append(i)

        await asyncio.gather(*(worker(i) for i in range(6)))

    asyncio.run(main())
    assert sorted(done) == [0, 1, 2, 3, 4, 5]


def test_separate_resources_never_block_each_other():
    """纯本地下 LOCAL 与 EXTRA 必须真正并行。

    这是改造前「27B 跑 GPU、E4B 跑 CPU，两把锁彼此不等」的行为；退化成一把闸门
    的话，一次 20~60 秒的整合会把每条回复都堵住。
    """
    _with_limits({"LOCAL": 1, "EXTRA": 1})
    order: list[str] = []

    async def main():
        held_local = asyncio.Event()
        release = asyncio.Event()

        async def local_holder():
            async with scheduler.acquire("LOCAL", tag="reply"):
                order.append("local-in")
                held_local.set()
                await release.wait()
                order.append("local-out")

        async def extra_worker():
            await held_local.wait()  # 确保 LOCAL 正被持有
            async with scheduler.acquire("EXTRA", tag="consolidate"):
                order.append("extra-in")
                order.append("extra-out")
            release.set()

        await asyncio.gather(local_holder(), extra_worker())

    asyncio.run(main())
    # EXTRA 在 LOCAL 仍被持有期间跑完了整个临界区
    assert order == ["local-in", "extra-in", "extra-out", "local-out"]


def test_the_gate_is_released_even_when_the_body_raises():
    """调用失败也必须还名额，否则一次异常就把闸门永久锁死。"""
    _with_limits({"LOCAL": 1})

    async def main():
        with pytest.raises(RuntimeError):
            async with scheduler.acquire("LOCAL", tag="boom"):
                raise RuntimeError("boom")
        # 还能再拿到
        async with scheduler.acquire("LOCAL", tag="after"):
            pass
        return scheduler.snapshot()["LOCAL"]

    stats = asyncio.run(main())
    assert stats["holding"] == 0
    assert stats["waiting"] == 0
    assert stats["acquired"] == 2


# ---------------------------------------------------------------- 解析器语义


def test_no_resolver_means_exclusive():
    """没装解析器时按 1 处理：宁可多串行，也不能因为读不到配置就放开并发。"""
    scheduler.set_concurrency_resolver(None)
    assert asyncio.run(_peak_concurrent("ANYTHING", 3)) == 1


def test_a_broken_resolver_falls_back_to_exclusive():
    """配置坏了不该让闸门失效——退回独占，并留下一条 warning。"""

    def boom(_name):
        raise ValueError("坏配置")

    scheduler.set_concurrency_resolver(boom)
    assert asyncio.run(_peak_concurrent("LOCAL", 3)) == 1


@pytest.mark.parametrize("bad", [0, -1, None, "abc"])
def test_nonsense_limits_fall_back_to_exclusive(bad):
    """0 / 负数 / 非整数一律按 1。Semaphore(0) 会把闸门直接锁死，绝不能放过去。"""
    scheduler.set_concurrency_resolver(lambda _n: bad)
    assert asyncio.run(_peak_concurrent("LOCAL", 3)) == 1


def test_limit_is_fixed_at_first_use():
    """并发度在资源首次使用时定下，改配置要重启（reset_state 会清空）。

    这是刻意的：运行中调整 Semaphore 的容量没有安全做法，而闸门的意义就是
    「此刻最多几个请求打到同一个端点上」——不能有一个模糊的中间态。
    """
    _with_limits({"LOCAL": 1})

    async def main():
        async with scheduler.acquire("LOCAL", tag="warmup"):
            pass
        _with_limits({"LOCAL": 4})
        return await _peak_concurrent("LOCAL", 4)

    assert asyncio.run(main()) == 1
    # 重建之后才生效
    scheduler.reset_state()
    _with_limits({"LOCAL": 4})
    assert asyncio.run(_peak_concurrent("LOCAL", 4)) == 4


# ---------------------------------------------------------------- 可观测性


def test_snapshot_reports_limit_holders_and_waiters():
    """并发度 >1 时 snapshot 必须报出**全部**持有者。

    改造前只有一个 holder 字段，后来者会覆盖前者——排队告警于是打印错的持有时长。
    """
    _with_limits({"ONLINE_CHAT": 2})

    async def main():
        release = asyncio.Event()
        inside = asyncio.Event()
        seen = 0

        async def worker(i: int):
            nonlocal seen
            async with scheduler.acquire("ONLINE_CHAT", tag=f"job{i}"):
                seen += 1
                if seen == 2:
                    inside.set()
                await release.wait()

        running = [asyncio.create_task(worker(i)) for i in range(3)]
        await inside.wait()
        for _ in range(20):
            await asyncio.sleep(0)  # 让第 3 个任务真的排进队列
        snap = scheduler.snapshot()["ONLINE_CHAT"]
        release.set()
        await asyncio.gather(*running)
        return snap

    stats = asyncio.run(main())
    assert stats["limit"] == 2
    assert stats["holding"] == 2
    assert stats["holders"] == ["job0", "job1"]
    assert stats["waiting"] == 1
    # holder / held_seconds 是单值摘要（持有最久的那个），兼容旧读法
    assert stats["holder"] == "job0、job1"
    assert stats["peak_holding"] == 2
    assert stats["peak_waiting"] >= 1


def test_snapshot_only_lists_used_resources():
    """没被 acquire 过的槽不该出现在 snapshot 里（否则界面上全是 0 行噪音）。"""
    _with_limits({"LOCAL": 1, "EXTRA": 1})

    async def main():
        async with scheduler.acquire("LOCAL", tag="t"):
            pass

    asyncio.run(main())
    assert set(scheduler.snapshot()) == {"LOCAL"}


def test_averages_are_computed_over_acquisitions():
    _with_limits({"LOCAL": 1})

    async def main():
        for _ in range(2):
            async with scheduler.acquire("LOCAL", tag="t"):
                await asyncio.sleep(0)

    asyncio.run(main())
    stats = scheduler.snapshot()["LOCAL"]
    assert stats["acquired"] == 2
    assert stats["avg_wait"] >= 0.0
    assert stats["avg_hold"] >= 0.0


def test_reset_state_clears_statistics():
    _with_limits({"LOCAL": 1})

    async def main():
        async with scheduler.acquire("LOCAL", tag="t"):
            pass

    asyncio.run(main())
    scheduler.reset_state()
    assert scheduler.snapshot() == {}


# ---------------------------------------------------------------- 与 registry 的接线


def test_registry_installs_the_resolver_on_import():
    """``core.llm.registry`` 一被导入就把并发度解析装到调度器上。

    间接注入而不是让 scheduler 直接 import registry，是为了避开
    scheduler → registry → settings 的导入环；代价是「谁来装」变成了隐式的——
    删掉那行 import 副作用不会有任何报错，只会让所有闸门静默退成并发 1。
    这条用例就是那行代码的唯一守卫。
    """
    assert _RESOLVER_AT_IMPORT is registry.concurrency_of


def test_unknown_resource_names_resolve_to_one():
    """认不出的资源名一律 1，与当前 .env 无关。

    ``gate_of()`` 对未绑定角色返回 ``"unbound"``，它永远不是槽名——真被拿去
    建闸门时必须是最保守的那个值。
    """
    assert registry.concurrency_of("NOT_A_SLOT") == 1
    assert registry.concurrency_of(registry.GATE_UNBOUND) == 1
    assert registry.concurrency_of("") == 1


def test_resource_names_are_case_insensitive_for_the_resolver():
    """资源名来自 ``gate_of()``（恒为大写槽名），但解析器不该因大小写而误判成 1。"""
    assert registry.concurrency_of("local") == registry.concurrency_of("LOCAL")
