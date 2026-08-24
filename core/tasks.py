# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Task / Result 协议：模块之间唯一的通信形式。

设计动机（见 design_docs/Capability Router 与 Comes 落地方案 v1.0.md 第 2 节）：
Stella / Memory / Comes 三个模块**不共享聊天上下文**，只传递「任务」与「结果」。
直接共享上下文会让工具描述污染聊天上下文，且插件数量增加后不可扩展——一个装了
20 个插件的部署会把 8192 的工作窗口塞满工具 schema，正常对话反而没地方站。

本模块只定义协议，不含任何执行逻辑，也不 import capability / memory / astrbot_compat：
它被四个模块共用，任何一条反向依赖都会变成 import 环。

三个关键约定：

1. **objective 属于语义层**。写「查询东京明天天气」，不写「调用 weather_api()」。
   具体走哪个 Provider、填什么参数由 Comes 决定——这样换插件不必改任务生成侧。
2. **status 与工具调用是否成功无关**。API 正常返回但查不到结果，是 ``failed``
   而不是 ``success``（方案第 5 节）。判定表见 ``ResultStatus``。
3. **data 不进 prompt，summary 才进**。``data`` 是工具原始返回（常是大段 JSON），
   只用于日志与调试；只有 ``summary`` 会被拼进 Stella 的 prompt。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# 任务号计数器：仅用于同一进程内区分任务，不做持久化、不要求全局唯一。
# 用 itertools.count 而非 uuid：日志里 "t7" 比一串十六进制好读得多，而任务号的
# 唯一性要求只到「同一次请求内不重复」。
_TASK_SEQ = itertools.count(1)


def next_task_id(prefix: str = "t") -> str:
    """生成进程内递增的任务号（如 ``t1`` / ``t2``）。"""
    return f"{prefix}{next(_TASK_SEQ)}"


class TaskType(str, Enum):
    """任务类型（方案第 4 节的 ``type`` 字段）。

    继承 ``str`` 是刻意的：日志与 JSON 序列化里直接就是 ``"tool.execute"``，
    不必到处写 ``.value``。
    """

    CHAT_RESPOND = "chat.respond"
    MEMORY_RETRIEVE = "memory.retrieve"
    TOOL_EXECUTE = "tool.execute"


class ResultStatus(str, Enum):
    """任务结果状态。

    | 情况 | status |
    |-|-|
    | 至少一个工具返回了非 error 的实质内容 | ``success`` |
    | 部分工具成功、部分失败 | ``partial`` |
    | 无工具被调用 / 全部报错 / 超时 | ``failed`` |
    | 上游中止（event.is_stopped()、闸门取消） | ``cancelled`` |

    ``failed`` 与 ``cancelled`` 必须分开：前者要告警（工具坏了），
    后者是正常的提前退出（插件钩子里 stop_event 了），混在一起会淹掉真问题。
    """

    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """系统需要完成的一项工作。

    属性:
        task_id: 任务唯一编号，用于并行任务管理、DAG 依赖与调试追踪；
        type: 任务类型（chat.respond / memory.retrieve / tool.execute）；
        capability: 需要的能力 id（如 ``weather.query``）。
            **Capability 不等于具体工具**——它是语义层的能力声明，
            由 Registry 映射到一个或多个 Provider。chat/memory 类任务留空；
        objective: 语义层的任务目标（「查询东京明天天气」，不是「调用 weather_api()」）；
        input: 结构化输入（已知的槽位，如 ``{"city": "东京"}``）。给了就省掉模型猜；
        dependencies: 依赖的 task_id 列表，用于形成任务 DAG；
        constraints: 执行约束（超时、最大步数等），由执行侧解释。
    """

    task_id: str
    type: TaskType
    capability: str = ""
    objective: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        cap = f" capability={self.capability}" if self.capability else ""
        deps = f" deps={self.dependencies}" if self.dependencies else ""
        return f"Task({self.task_id} {self.type.value}{cap} objective={self.objective!r}{deps})"


@dataclass
class Result:
    """任务执行结果。

    属性:
        task_id: 对应的任务号；
        status: 见 ``ResultStatus``——工具调用成功不代表任务成功；
        data: 完整结果（工具返回的原始内容）。**不进 prompt**，只用于日志/调试；
        summary: 压缩后的结果，是唯一会被拼进 Stella prompt 的字段；
        metadata: 来源、provider、执行耗时、调试信息。
    """

    task_id: str
    status: ResultStatus
    data: Any = None
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """是否产出了可用信息（success 或 partial）。

        ``partial`` 也算可用：三个工具里两个查到了，那两条结果照样该给 Stella。
        """
        return self.status in (ResultStatus.SUCCESS, ResultStatus.PARTIAL)

    def __repr__(self) -> str:
        return (
            f"Result({self.task_id} {self.status.value} "
            f"summary={self.summary[:40]!r} data_len={len(str(self.data or ''))})"
        )


class TaskGraphError(ValueError):
    """任务图非法（成环 / 依赖不存在）。"""


@dataclass
class TaskGraph:
    """一组带依赖关系的任务（方案第 4 节的 DAG）。

    刻意只做「登记 + 拓扑排序 + 成环检测」，不做调度：并发策略属于调用方，
    图本身只回答「谁必须在谁之前」。

    成环与悬空依赖都**抛错而不是静默跳过**：一个成了环的任务图在运行期表现为
    「某些任务永远不执行」，静默处理会让它看起来像功能没实现，极难定位。
    """

    tasks: dict[str, Task] = field(default_factory=dict)

    def add(self, task: Task) -> Task:
        """登记一个任务；task_id 重复即报错（覆盖会让先前的依赖悄悄指向新任务）。"""
        if task.task_id in self.tasks:
            raise TaskGraphError(f"任务号重复: {task.task_id}")
        self.tasks[task.task_id] = task
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def validate(self) -> None:
        """检查依赖是否都存在。悬空依赖单独报错，比在拓扑排序里表现为成环更好懂。"""
        for task in self.tasks.values():
            for dep in task.dependencies:
                if dep not in self.tasks:
                    raise TaskGraphError(
                        f"任务 {task.task_id} 依赖了不存在的任务 {dep}",
                    )

    def ready(self, done: set[str] | None = None) -> list[Task]:
        """返回当前所有依赖已满足、且自身未完成的任务（可并发执行的一批）。"""
        finished = done or set()
        return [
            t
            for t in self.tasks.values()
            if t.task_id not in finished and all(d in finished for d in t.dependencies)
        ]

    def topological_order(self) -> list[list[Task]]:
        """按依赖分层：返回 ``[[第一批], [第二批], ...]``，同一批内可并发。

        分层而不是给一条扁平序列：调用方需要知道「哪些能一起跑」，
        扁平序列会丢掉这个信息，退化成全串行。
        """
        self.validate()
        done: set[str] = set()
        layers: list[list[Task]] = []
        while len(done) < len(self.tasks):
            batch = self.ready(done)
            if not batch:
                remaining = sorted(set(self.tasks) - done)
                raise TaskGraphError(f"任务图成环，无法排序，涉及: {remaining}")
            # 排序保证同一批的顺序确定（便于测试与日志比对）
            batch.sort(key=lambda t: t.task_id)
            layers.append(batch)
            done.update(t.task_id for t in batch)
        return layers

    def __len__(self) -> int:
        return len(self.tasks)

    def __bool__(self) -> bool:
        return bool(self.tasks)


__all__ = [
    "Result",
    "ResultStatus",
    "Task",
    "TaskGraph",
    "TaskGraphError",
    "TaskType",
    "next_task_id",
]
