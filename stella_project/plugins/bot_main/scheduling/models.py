# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""调度子系统的枚举、数据类与时间助手。

时间口径（全子系统统一，不许各自为政）：

- **落库一律 UTC**，格式取 ``isoformat(timespec="microseconds")`` 的固定宽度
  aware 串（``2026-09-22T01:23:45.000000+00:00``）。定宽保证 SQLite 的字符串
  比较与时间序严格一致——``scheduled_for_utc <= now`` 这类 WHERE 条件靠它。
- **业务时区**只在两处出现：Cron 表达式的解释（见 :mod:`.cron`）与投递文案里
  的本地时间展示。库里永远只有 UTC。
- 配额按 UTC 自然日切分（``day_key``）：它是运算符可预期的固定边界，跟着群时区
  走反而会出现「配额窗口随 DST 漂移」的诡异行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

UTC = timezone.utc


def utc_now() -> datetime:
    """当前 UTC 时刻（aware）。独立成函数：测试可 monkeypatch 它造假时钟。"""
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    """aware datetime → 定宽 UTC ISO 串（落库格式，见模块 docstring）。"""
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def parse_iso_utc(value: str | None) -> datetime | None:
    """库里的 ISO 串 → aware datetime；空值/非法返回 None（调用方按缺省处理）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # 理论上不会出现（写入端恒为 aware）；防御式按 UTC 解释而不是本地时区
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def day_key(value: datetime) -> str:
    """UTC 自然日的 ``YYYY-MM-DD`` 键（每日配额的分组键）。"""
    return value.astimezone(UTC).strftime("%Y-%m-%d")


def lease_deadline(value: datetime, seconds: float) -> datetime:
    """租约到期时刻；秒数非正时退回 1s，避免「永不过期」的租约被意外写进库。"""
    return value + timedelta(seconds=max(seconds, 1.0))


class TaskMode(str, Enum):
    """任务模式：reminder 把 objective 当**固定文案**直接投递；agent 把它当目标
    交给有界 Agent 运行器生成。"""

    REMINDER = "reminder"
    AGENT = "agent"


class TaskStatus(str, Enum):
    """任务生命周期。cancelled 是终态：不删除行，历史与审计需要它。"""

    ACTIVE = "active"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class RunState(str, Enum):
    """运行状态机（迁移见 store，投递判定见 delivery）。

    链路::

        queued → claimed → running → ready → sending → sent
                                       │            ├→ delivery_unknown
                                       │            └→ (异常) failed
                                       ├→ silent   （策略允许的空产出）
                                       ├→ skipped  （gate 拒绝/配额/群忙放弃）
                                       └→ cancelled（任务被取消或修订过期）

    ``sending`` 之后进程死亡 → ``delivery_unknown``：平台调用可能已发生，
    重发有刷屏风险，因此**只能人工重试**，不自动重投。
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    READY = "ready"
    SENDING = "sending"
    SENT = "sent"
    SILENT = "silent"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    DELIVERY_UNKNOWN = "delivery_unknown"


# 仍在占用「每任务/每群各一个活跃运行」名额的状态。
ACTIVE_RUN_STATES: tuple[RunState, ...] = (
    RunState.QUEUED,
    RunState.CLAIMED,
    RunState.RUNNING,
    RunState.READY,
    RunState.SENDING,
)

# 租约仍然「活着」的状态：recover_expired_leases 只对这些状态做回收。
LEASABLE_RUN_STATES: tuple[RunState, ...] = (
    RunState.CLAIMED,
    RunState.RUNNING,
    RunState.READY,
    RunState.SENDING,
)

TERMINAL_RUN_STATES: frozenset[RunState] = frozenset(RunState) - set(ACTIVE_RUN_STATES)


class CoalesceMode(str, Enum):
    """错过多次 Cron 触发（停机/积压）时的补跑策略。

    ``latest`` 只补最近一次（agent 任务的默认——旧目标重放多遍没有意义）；
    ``all`` 逐个补跑但有上限（短时提醒的默认，漏了就是用户的事没被提醒）。
    """

    LATEST = "latest"
    ALL = "all"


class NotificationMode(str, Enum):
    """结果投递策略。

    ``always``：objective 本身就是消息（reminder），有产出必投；
    ``on_content``：Agent 跑完没有可发内容时记 ``silent`` 而不是发空消息。
    """

    ALWAYS = "always"
    ON_CONTENT = "on_content"


@dataclass(slots=True)
class Task:
    """一条可持久化的调度任务。``revision`` 是乐观锁：每次编辑 +1，排队与
    在途运行带着旧 revision，认领与发送前都要对上，对不上即作废（防「编辑
    竞态」：改完 Cron 的瞬间旧触发达队，旧行为会按旧配置跑一遍）。"""

    task_id: str
    bot_id: str
    group_id: int
    owner_id: int
    mode: TaskMode
    objective: str
    cron_expr: str
    timezone: str
    revision: int = 1
    status: TaskStatus = TaskStatus.ACTIVE
    policy: dict = field(default_factory=dict)
    instance_id: str = ""
    next_run_utc: datetime | None = None
    last_run_utc: datetime | None = None
    max_model_rounds: int = 4
    max_tool_calls: int = 8
    run_timeout_seconds: float = 300.0
    output_max_chars: int = 1200
    notification_mode: NotificationMode = NotificationMode.ON_CONTENT
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Run:
    """一次具体的触发执行。``scheduled_for_utc`` 是 Cron 语义上的「应当触发
    时刻」（不是实际执行时刻）；``(task_id, task_revision, scheduled_for_utc)`
    唯一，人工 run-now 用 ``request_id`` 参与幂等键。"""

    run_id: str
    task_id: str
    task_revision: int
    group_id: int
    idempotency_key: str
    state: RunState = RunState.QUEUED
    scheduled_for_utc: datetime | None = None
    request_id: str = ""
    lease_owner: str = ""
    lease_expires_utc: datetime | None = None
    model_rounds: int = 0
    tool_calls: int = 0
    result_text: str = ""
    error: str = ""
    delivery_receipt: str = ""
    delivery_error: str = ""
    fingerprint: str = ""
    queued_at_utc: datetime | None = None
    claimed_at_utc: datetime | None = None
    finished_at_utc: datetime | None = None

    @property
    def is_manual(self) -> bool:
        return bool(self.request_id)


@dataclass(slots=True)
class AuditEntry:
    """一次受控变更的审计记录（谁、在哪个群、对哪个任务、做了什么）。"""

    audit_id: int
    created_at_utc: datetime | None
    actor_id: int
    group_id: int
    task_id: str
    action: str
    detail: str = ""


__all__ = [
    "ACTIVE_RUN_STATES",
    "LEASABLE_RUN_STATES",
    "TERMINAL_RUN_STATES",
    "UTC",
    "AuditEntry",
    "CoalesceMode",
    "NotificationMode",
    "Run",
    "RunState",
    "Task",
    "TaskMode",
    "TaskStatus",
    "day_key",
    "iso_utc",
    "lease_deadline",
    "parse_iso_utc",
    "utc_now",
]
