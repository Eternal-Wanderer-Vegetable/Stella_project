# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 的公共协议：枚举、数据类与时间口径（方案 §6.1/§6.2）。

关键不变量（方案 §1.3，本模块是它们的类型化落点）：

- accepted / running / succeeded / 消息 sent 是**不同事实**，分别对应
  :class:`TaskState`、attempt 租约与 :class:`NotificationState`，绝不共用字段；
- 任务所有者、原始会话与授权来自 :class:`Origin`（可信入口构造），
  不由模型生成、不经聊天上下文恢复；
- ``heartbeat_at`` 是 worker 存活，``last_activity_at`` 是最近 Agent 事件，
  两个字段不得混用；
- 时间落库一律 UTC 定宽 ISO 串（与 scheduling/models.py 同款口径）。

所有持久 DTO 带 ``schema_version=1``。task_id / attempt_id 用 UUID hex；
``short_id`` 取前 8 位只供人读，冲突时必须回退完整 ID（服务层负责）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

UTC = timezone.utc

SCHEMA_VERSION = 1
# Origin 独立的 schema 版本（计划 §6.8）：新增 conversation_kind/peer_id/
# conversation_key 时升到 2。**不**随动全包 SCHEMA_VERSION——那会影响所有 DTO。
ORIGIN_SCHEMA_VERSION = 2


# ============================================================
# 时间助手（与 scheduling/models.py 同款：测试可 monkeypatch utc_now）
# ============================================================


def utc_now() -> datetime:
    """当前 UTC 时刻（aware）。"""
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    """aware datetime → 定宽 UTC ISO 串（落库格式，字符串比较即时间序）。"""
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def parse_iso_utc(value: str | None) -> datetime | None:
    """库里的 ISO 串 → aware datetime；空值/非法返回 None。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # 写入端恒为 aware；防御式按 UTC 解释而不是本地时区
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def lease_deadline(value: datetime, seconds: float) -> datetime:
    """租约到期时刻；秒数非正时退回 1s，避免「永不过期」的租约入库。"""
    return value + timedelta(seconds=max(seconds, 1.0))


def new_id() -> str:
    """持久 UUID（task / attempt / event 去重的唯一来源；进程内计数不用于此）。"""
    return uuid.uuid4().hex


def short_id(task_id: str) -> str:
    """人读短 ID（前 8 位）。只用于展示；冲突由服务层回退完整 ID。"""
    return task_id[:8]


# ============================================================
# 状态机（方案 §6.2）
# ============================================================


class TaskState(str, Enum):
    """任务业务状态。

    链路::

        queued → starting → running → succeeded | partial | failed
                          ↕
                waiting_input / waiting_approval
        queued → cancelled
        starting/running/waiting_* → cancelling → cancelled
        starting/running/waiting_* → recovering → running/waiting_*/recovery_required
        任一未完成任务到达预算/期限 → cancelling → timed_out（确认停止后）

    - ``recovering``：正在核对重启/断流后的执行状态；
    - ``recovery_required``：无法确认是否仍在执行或能否安全恢复，等管理员处理，
      **不等同于失败后可重跑**；
    - 后端「turn completed」先映射为待结果校验，由 executor 校验后才落终态。
    """

    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    WAITING_APPROVAL = "waiting_approval"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    RECOVERING = "recovering"
    RECOVERY_REQUIRED = "recovery_required"


# 仍占用执行槽/工作区锁的状态（配额按它计数）。
ACTIVE_TASK_STATES: tuple[TaskState, ...] = (
    TaskState.QUEUED,
    TaskState.STARTING,
    TaskState.RUNNING,
    TaskState.WAITING_INPUT,
    TaskState.WAITING_APPROVAL,
    TaskState.CANCELLING,
    TaskState.RECOVERING,
)

TERMINAL_TASK_STATES: frozenset[TaskState] = frozenset(TaskState) - set(
    ACTIVE_TASK_STATES
)


class LaunchPhase(str, Enum):
    """attempt 的启动阶段（方案 §6.8 启动协议：崩溃窗口的证据）。

    ``dispatching`` 表示启动请求**可能已发出但 turn handle 未落库**——
    宿主在此窗口崩溃时，launch_phase 可证明「启动结果不明」，禁止盲目重发。
    """

    CLAIMED = "claimed"
    PREPARING = "preparing"
    CONNECTING = "connecting"
    DISPATCHING = "dispatching"
    RUNNING = "running"


class EventKind(str, Enum):
    """归一事件类型（方案 §6.11 统一 kind）。"""

    ACCEPTED = "accepted"
    STARTED = "started"
    PROGRESS = "progress"
    INPUT_REQUIRED = "input_required"
    APPROVAL_REQUIRED = "approval_required"
    ARTIFACT_CREATED = "artifact_created"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    RECOVERY_REQUIRED = "recovery_required"


# 必须立即刷盘、且不被进度节流合并的关键事件。
CRITICAL_EVENT_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.ACCEPTED,
        EventKind.STARTED,
        EventKind.INPUT_REQUIRED,
        EventKind.APPROVAL_REQUIRED,
        EventKind.COMPLETED,
        EventKind.FAILED,
        EventKind.CANCEL_REQUESTED,
        EventKind.CANCELLED,
        EventKind.RECOVERY_REQUIRED,
    }
)


class ControlKind(str, Enum):
    """控制命令类型（controls 表）。"""

    CANCEL = "cancel"
    RESPOND = "respond"


class ControlState(str, Enum):
    """控制命令状态：pending → delivered → consumed；确认丢失留 pending。"""

    PENDING = "pending"
    DELIVERED = "delivered"
    CONSUMED = "consumed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class NotificationKind(str, Enum):
    """通知类型（notifications 表；与 EventKind 对应但可合并节流）。"""

    ACK = "ack"
    PROGRESS = "progress"
    INPUT_REQUIRED = "input_required"
    FINAL = "final"


class NotificationState(str, Enum):
    """通知投递状态（方案 §6.5/§6.11：accepted ≠ sent）。

    ``server_emitted`` 只声称服务端发出了响应（WebChat SSE complete），
    不声称用户已阅读；``delivery_unknown`` 不自动重发。
    """

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    SERVER_EMITTED = "server_emitted"
    DELIVERY_UNKNOWN = "delivery_unknown"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"


class ArtifactAvailability(str, Enum):
    """产物可用性：文件在库 = available；已发布但文件缺失必须显示 unavailable。"""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"


class InputRequestState(str, Enum):
    """输入/审批请求状态。用户沉默不等于批准：到期由 worker 中断任务。"""

    PENDING = "pending"
    ANSWERED = "answered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class HealthState(str, Enum):
    """后端健康状态（方案 §6.13）。"""

    DISABLED = "disabled"
    READY = "ready"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    INCOMPATIBLE = "incompatible"


class EvidenceSource(str, Enum):
    """结果证据的来源分级（方案 §6.12：宿主只信 observed/host_checked）。"""

    AGENT_REPORTED = "agent_reported"
    OBSERVED_TOOL_EVENT = "observed_tool_event"
    HOST_CHECKED = "host_checked"


class VerificationStatus(str, Enum):
    """验收状态（与 outcome 分开：有补丁但测试失败 = partial + failed）。"""

    NOT_REQUIRED = "not_required"
    PASSED = "passed"
    FAILED = "failed"
    UNVERIFIED = "unverified"


class Outcome(str, Enum):
    """AgentResult 的业务结局。succeeded = 验收标准满足。"""

    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================
# 协议 DTO（方案 §6.1 表格的必需字段）
# ============================================================


@dataclass(slots=True)
class Origin:
    """任务来源（方案 §6.1）。**只由 QQ/WebChat 可信入口构造**。

    来自受信宿主而不是可接受用户任意提交的 JSON；服务层再核验 profile 与
    用户的绑定。长文本输出、原始事件与异常堆栈不作为身份依据。
    """

    instance_id: str
    platform: str  # qq | webchat
    bot_id: str
    conversation_id: str
    requester_id: str
    source_request_id: str = ""
    reply_to_message_id: str = ""
    # 会话代际：WebChat reset 推进代际，旧代际结果留在任务中心不回写聊天。
    conversation_generation: int = 1
    # ---- Origin v2（计划 §6.8）：持久会话种类与对端，投递地址的真相源 ----
    # group 会话才有真实 group_id（=conversation_id）；private 的 peer 是
    # sender QQ 号，conversation_id 不再被当群 ID 使用。v2 Origin 缺 kind/peer
    # 校验失败——不猜默认群。
    conversation_kind: str = ""  # group | private | webchat
    peer_id: str = ""
    conversation_key: str = ""  # 规范键 qq:<bot_id>:group:<gid> / qq:<bot_id>:private:<uid>

    def __post_init__(self) -> None:
        if self.conversation_kind and self.conversation_kind not in (
            "group",
            "private",
            "webchat",
        ):
            raise ValueError(f"非法 conversation_kind: {self.conversation_kind!r}")

    def to_dict(self) -> dict:
        data = {
            "schema_version": SCHEMA_VERSION,
            "instance_id": self.instance_id,
            "platform": self.platform,
            "bot_id": self.bot_id,
            "conversation_id": self.conversation_id,
            "requester_id": self.requester_id,
            "source_request_id": self.source_request_id,
            "reply_to_message_id": self.reply_to_message_id,
            "conversation_generation": self.conversation_generation,
        }
        if not self.conversation_kind:
            # 部分 v1 形状（无 kind）：序列化为 legacy dict，读回时按平台解释
            # （QQ→群 / webchat→webchat）。可信入口构造的 Origin 必须带 kind。
            return data
        data["origin_schema_version"] = ORIGIN_SCHEMA_VERSION
        data["conversation_kind"] = self.conversation_kind
        data["peer_id"] = self.peer_id
        data["conversation_key"] = self.conversation_key
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Origin":
        kind = str(data.get("conversation_kind", "") or "")
        peer = str(data.get("peer_id", "") or "")
        conv_key = str(data.get("conversation_key", "") or "")
        version = int(data.get("origin_schema_version", 0) or 0)
        if not kind:
            if version >= ORIGIN_SCHEMA_VERSION:
                # v2 起缺 kind 是数据损坏，不猜默认群（计划 §6.8）
                raise ValueError("Origin v2 缺少 conversation_kind，拒绝解析")
            # v1 兼容：旧 QQ Origin 全部按历史群解释；webchat 按其平台解释。
            kind = "webchat" if str(data.get("platform", "")) == "webchat" else "group"
            peer = str(data.get("conversation_id", "") or "")
        if not peer:
            raise ValueError("Origin 缺少 peer_id，拒绝解析")
        if not conv_key:
            # conversation_key 是其余字段的规范函数（非猜测）：v1 遗留行与
            # 「legacy 解析后再持久化」的 roundtrip 都在这里补齐。kind/peer
            # 缺失没有规范推导，仍然拒绝。
            if kind == "webchat":
                conv_key = f"webchat:{peer}"
            else:
                conv_key = (
                    f"{data.get('platform', 'qq')}:{data.get('bot_id', '')}"
                    f":{kind}:{peer}"
                )
        return cls(
            instance_id=str(data.get("instance_id", "")),
            platform=str(data.get("platform", "")),
            bot_id=str(data.get("bot_id", "")),
            conversation_id=str(data.get("conversation_id", "")),
            requester_id=str(data.get("requester_id", "")),
            source_request_id=str(data.get("source_request_id", "")),
            reply_to_message_id=str(data.get("reply_to_message_id", "")),
            conversation_generation=int(data.get("conversation_generation", 1)),
            conversation_kind=kind,
            peer_id=peer,
            conversation_key=conv_key,
        )


@dataclass(slots=True)
class TaskSpec:
    """委派给外部 Agent 的任务规格（方案 §6.1）。"""

    objective: str
    context_excerpt: str = ""
    required_capabilities: list[str] = field(default_factory=list)
    backend_preference: str = ""  # 空 = 按配置优先级选择
    workspace_id: str = ""  # 空 = 无工作区（纯研究类任务）
    permission_profile: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    limits: dict = field(default_factory=dict)

    def content_fingerprint(self) -> str:
        """受理幂等的内容指纹：同 key 同内容回原 receipt，同 key 不同内容冲突。"""
        import hashlib
        import json

        payload = json.dumps(
            {
                "objective": self.objective,
                "context_excerpt": self.context_excerpt,
                "required_capabilities": list(self.required_capabilities),
                "backend_preference": self.backend_preference,
                "workspace_id": self.workspace_id,
                "permission_profile": self.permission_profile,
                "acceptance_criteria": list(self.acceptance_criteria),
                "limits": self.limits,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "objective": self.objective,
            "context_excerpt": self.context_excerpt,
            "required_capabilities": list(self.required_capabilities),
            "backend_preference": self.backend_preference,
            "workspace_id": self.workspace_id,
            "permission_profile": self.permission_profile,
            "acceptance_criteria": list(self.acceptance_criteria),
            "limits": dict(self.limits),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskSpec":
        return cls(
            objective=str(data.get("objective", "")),
            context_excerpt=str(data.get("context_excerpt", "")),
            required_capabilities=[
                str(c) for c in (data.get("required_capabilities") or [])
            ],
            backend_preference=str(data.get("backend_preference", "")),
            workspace_id=str(data.get("workspace_id", "")),
            permission_profile=str(data.get("permission_profile", "")),
            acceptance_criteria=[str(c) for c in (data.get("acceptance_criteria") or [])],
            limits=dict(data.get("limits") or {}),
        )


@dataclass(slots=True)
class SubmissionReceipt:
    """受理回执（方案 §6.1）。落库成功才返回；**不代表 Agent 已启动**。"""

    task_id: str
    accepted_at: datetime
    state: TaskState = TaskState.QUEUED
    backend_selection_state: str = "pending"  # pending | selected | unavailable
    ack_notification_id: str = ""


@dataclass(slots=True)
class ControlReceipt:
    """控制命令（取消/答复）回执。cancel 返回「已请求取消」，不提前声称已取消。"""

    task_id: str
    control_id: str
    state: TaskState
    control_state: ControlState = ControlState.PENDING
    message: str = ""


@dataclass(slots=True)
class TaskSnapshot:
    """任务当前状态快照（方案 §6.1）。用户可见进度的唯一真源。"""

    task_id: str
    state: TaskState
    created_at: datetime | None = None
    updated_at: datetime | None = None
    backend_id: str = ""
    attempt_id: str = ""
    attempt_no: int = 0
    phase: str = ""
    last_activity_at: datetime | None = None
    heartbeat_at: datetime | None = None
    deadline_at: datetime | None = None
    waiting_request_id: str = ""
    waiting_question: str = ""
    result_id: str = ""
    delivery_state: str = ""
    retry_of: str = ""


@dataclass(slots=True)
class AgentEvent:
    """归一事件（方案 §6.1）。sequence 按 (task_id, sequence) 唯一递增。"""

    schema_version: int = SCHEMA_VERSION
    task_id: str = ""
    attempt_id: str = ""
    sequence: int = 0
    backend_event_id: str | None = None
    kind: EventKind = EventKind.PROGRESS
    occurred_at: datetime | None = None
    payload: dict = field(default_factory=dict)


@dataclass(slots=True)
class ArtifactRef:
    """产物引用（results/manifest 内的条目）。"""

    artifact_id: str
    display_name: str
    relative_storage_key: str
    sha256: str
    size: int
    mime: str = ""
    availability: ArtifactAvailability = ArtifactAvailability.AVAILABLE


@dataclass(slots=True)
class AgentResult:
    """最终结果（方案 §6.1/§6.12）。

    outcome 与 verification_status 分开；evidence 标注来源分级；
    完整日志不进聊天上下文，只传 summary 与产物引用。
    """

    outcome: Outcome
    summary: str = ""
    final_text_ref: str = ""  # 完整最终文本的存储键（不进上下文）
    artifacts: list[ArtifactRef] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    limitations: list[str] = field(default_factory=list)
    error: str = ""
    usage: dict = field(default_factory=dict)  # token/费用拿不到就 unknown，不虚构 0

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "final_text_ref": self.final_text_ref,
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "display_name": a.display_name,
                    "relative_storage_key": a.relative_storage_key,
                    "sha256": a.sha256,
                    "size": a.size,
                    "mime": a.mime,
                    "availability": a.availability.value,
                }
                for a in self.artifacts
            ],
            "evidence": list(self.evidence),
            "verification_status": self.verification_status.value,
            "limitations": list(self.limitations),
            "error": self.error,
            "usage": dict(self.usage),
        }


# ============================================================
# 后端协议 DTO（方案 §6.6；这些是 cometa 内部类型，不是 Codex SDK 的逐字 API）
# ============================================================


@dataclass(slots=True)
class LifecycleCapabilities:
    """后端生命周期能力声明。不支持的能力必须返回明确 unsupported，
    不能用一次新执行伪装 resume。"""

    supports_inspect: bool = False
    supports_resume: bool = False
    supports_event_replay: bool = False
    supports_cancel: bool = False
    supports_approval: bool = False
    supports_steer: bool = False
    supports_usage: bool = False


@dataclass(slots=True)
class BackendDescriptor:
    """后端静态描述（registry 显式登记）。"""

    backend_id: str
    backend_type: str
    capabilities: list[str] = field(default_factory=list)  # cometa 能力 ID
    lifecycle: LifecycleCapabilities = field(default_factory=LifecycleCapabilities)
    version: str = ""
    model: str = ""  # 空 = 用后端账号的配置默认值，不硬编码最新模型


@dataclass(slots=True)
class BackendHealth:
    """probe 结果。health 缓存有时效；启动前复验（方案 §9）。"""

    backend_id: str
    state: HealthState
    version: str = ""
    available_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    reason: str = ""
    checked_at: datetime | None = None


@dataclass(slots=True)
class SessionHandle:
    """一次后端会话。worker 崩溃后凭 session_id 核对，不捏造历史。"""

    session_id: str
    backend_id: str
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class TurnHandle:
    """一轮执行的句柄。start_turn 返回后立即落库（launch_phase=running）。"""

    turn_id: str
    session_id: str


@dataclass(slots=True)
class BackendEvent:
    """后端原始事件的归一载体（codex_events 的输出、executor 的输入）。

    ``backend_event_id`` 可空：可空时 executor 以 (attempt, sequence) 去重。
    """

    kind: str  # 归一 kind，见 backends/base.py 的约定
    payload: dict = field(default_factory=dict)
    backend_event_id: str | None = None
    occurred_at: datetime | None = None
    raw_kind: str = ""


@dataclass(slots=True)
class BackendSnapshot:
    """inspect 的结果：恢复矩阵「后端是否仍在执行」的证据来源。"""

    session_found: bool = False
    turn_running: bool = False
    turn_completed: bool = False
    turn_failed: bool = False
    detail: str = ""


@dataclass(slots=True)
class BackendControlResult:
    """respond/cancel 的后端侧结果。confirmed=False 表示确认丢失。"""

    ok: bool
    confirmed: bool = False
    detail: str = ""


__all__ = [
    "ACTIVE_TASK_STATES",
    "CRITICAL_EVENT_KINDS",
    "SCHEMA_VERSION",
    "TERMINAL_TASK_STATES",
    "UTC",
    "AgentEvent",
    "AgentResult",
    "ArtifactAvailability",
    "ArtifactRef",
    "BackendControlResult",
    "BackendDescriptor",
    "BackendEvent",
    "BackendHealth",
    "BackendSnapshot",
    "ControlKind",
    "ControlReceipt",
    "ControlState",
    "EventKind",
    "EvidenceSource",
    "HealthState",
    "InputRequestState",
    "LaunchPhase",
    "LifecycleCapabilities",
    "NotificationKind",
    "NotificationState",
    "Origin",
    "Outcome",
    "SessionHandle",
    "SubmissionReceipt",
    "TaskSnapshot",
    "TaskSpec",
    "TaskState",
    "TurnHandle",
    "VerificationStatus",
    "iso_utc",
    "lease_deadline",
    "new_id",
    "parse_iso_utc",
    "short_id",
    "utc_now",
]
