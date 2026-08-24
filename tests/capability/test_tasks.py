# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Task / Result / TaskGraph 协议的单测。

协议是纯逻辑，完全离线。重点钉三件事：
1. status 的语义（工具成功 ≠ 任务成功）；
2. 任务图成环与悬空依赖必须**抛错**而不是静默跳过；
3. 拓扑排序按层返回（同层可并发），不能退化成扁平序列。
"""

import pytest

from core.tasks import (
    Result,
    ResultStatus,
    Task,
    TaskGraph,
    TaskGraphError,
    TaskType,
    next_task_id,
)


def _task(task_id: str, deps: list[str] | None = None) -> Task:
    return Task(
        task_id=task_id,
        type=TaskType.TOOL_EXECUTE,
        capability="weather.query",
        objective="查询东京明天天气",
        dependencies=deps or [],
    )


# ---------- Task / Result ----------


def test_task_id_is_monotonic():
    a, b = next_task_id(), next_task_id()
    assert a != b
    assert int(a[1:]) < int(b[1:])


def test_task_type_is_str_enum():
    """继承 str 的意义：日志/JSON 里直接是 "tool.execute"，不必到处写 .value。"""
    assert TaskType.TOOL_EXECUTE == "tool.execute"
    assert f"{TaskType.MEMORY_RETRIEVE.value}" == "memory.retrieve"


def test_task_defaults_are_independent():
    """dataclass 的可变默认值必须是 field(default_factory)，否则两个任务共享同一个 dict。"""
    a, b = _task("t1"), _task("t2")
    a.input["city"] = "东京"
    a.dependencies.append("t0")
    assert b.input == {}
    assert b.dependencies == []


def test_result_ok_covers_success_and_partial():
    """partial 也算可用：三个工具里两个查到了，那两条照样该给 Stella。"""
    assert Result("t1", ResultStatus.SUCCESS).ok
    assert Result("t1", ResultStatus.PARTIAL).ok
    assert not Result("t1", ResultStatus.FAILED).ok
    assert not Result("t1", ResultStatus.CANCELLED).ok


def test_failed_and_cancelled_are_distinct():
    """failed 要告警（工具坏了），cancelled 是正常提前退出，混在一起会淹掉真问题。"""
    assert ResultStatus.FAILED != ResultStatus.CANCELLED


def test_result_repr_does_not_dump_full_data():
    """data 常是大段 JSON，repr 里只给长度——日志里打全量会把文件冲爆。"""
    r = Result("t1", ResultStatus.SUCCESS, data={"x": "y" * 500}, summary="东京 27℃")
    text = repr(r)
    assert "东京 27℃" in text
    assert "y" * 100 not in text


# ---------- TaskGraph ----------


def test_add_rejects_duplicate_id():
    """覆盖会让先前登记的依赖悄悄指向新任务，必须报错。"""
    graph = TaskGraph()
    graph.add(_task("t1"))
    with pytest.raises(TaskGraphError, match="任务号重复"):
        graph.add(_task("t1"))


def test_validate_rejects_dangling_dependency():
    """悬空依赖单独报错，比在拓扑排序里表现为成环更好懂。"""
    graph = TaskGraph()
    graph.add(_task("t2", deps=["t1"]))
    with pytest.raises(TaskGraphError, match="不存在的任务 t1"):
        graph.validate()


def test_ready_returns_only_unblocked_tasks():
    graph = TaskGraph()
    graph.add(_task("t1"))
    graph.add(_task("t2", deps=["t1"]))
    assert [t.task_id for t in graph.ready()] == ["t1"]
    assert [t.task_id for t in graph.ready(done={"t1"})] == ["t2"]


def test_topological_order_groups_parallel_tasks():
    """方案第 17 节：Memory 与 Comes 可并行——它们必须落在同一层。"""
    graph = TaskGraph()
    graph.add(_task("mem"))
    graph.add(_task("tool"))
    graph.add(_task("chat", deps=["mem", "tool"]))
    layers = graph.topological_order()
    assert [[t.task_id for t in layer] for layer in layers] == [["mem", "tool"], ["chat"]]


def test_topological_order_detects_cycle():
    """成环在运行期表现为「某些任务永远不执行」，静默处理极难定位。"""
    graph = TaskGraph()
    graph.add(_task("a", deps=["b"]))
    graph.add(_task("b", deps=["a"]))
    with pytest.raises(TaskGraphError, match="成环"):
        graph.topological_order()


def test_topological_order_is_deterministic():
    """同层按 task_id 排序，保证测试与日志可比对。"""
    graph = TaskGraph()
    for tid in ("t3", "t1", "t2"):
        graph.add(_task(tid))
    assert [t.task_id for t in graph.topological_order()[0]] == ["t1", "t2", "t3"]


def test_empty_graph_is_falsy_and_orders_to_nothing():
    graph = TaskGraph()
    assert not graph
    assert len(graph) == 0
    assert graph.topological_order() == []
