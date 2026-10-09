# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""社交学习闭环的平台无关契约（计划 §6.1）。

三个不可变数据契约是整条「证据 → 投递 → 效果 → 资产」链路的公共语言：

- :class:`ConversationScope`：新学习资产的隔离键 ``(platform, bot_id, group_id)``。
  禁止拿 user_id=0 代表「全群反馈对象」——全群目标用 ``target_user_id=None``
  表达（见 social_effects），scope 本身只描述「哪个群」。
- :class:`MessageEvidence`：一条标准化群消息证据。平台时间（event_at_utc）
  只用于展示；服务接收时间（received_at_utc）与入库 rowid 用于稳定排序；
  所有时间保存 UTC。无平台 ID 的事件使用独立 UUID 作 event_id，
  **绝不把 0 当全局唯一键**；平台 ID 的去重由 (platform, bot_id, group_id,
  platform_message_id) 复合唯一索引承担，不能只以 QQ message ID 全局去重。
- :class:`DeliveryReceipt`：一个发送片段的平台回执。状态机
  pending → acknowledged / failed / unknown；多段逻辑回复另聚合为
  complete / partial / failed / unknown（:func:`aggregate_delivery_status`）。

时间格式：全部 UTC ISO8601 字符串（:func:`utc_now_iso`），同格式字符串排序
即时间排序；monotonic 时间**绝不入库**（跨重启不可比，计划 §2 优先修复项）。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---- 单段投递回执状态（social_deliveries.status） ----
DELIVERY_PENDING = "pending"  # 已提交平台、未拿到结果（短暂中间态，落库前会定型）
DELIVERY_ACKNOWLEDGED = "acknowledged"  # 平台接口已接受（不保证群成员已读）
DELIVERY_FAILED = "failed"  # 平台明确拒绝/异常，未发出
DELIVERY_UNKNOWN = "unknown"  # 超时/发送成功但本地未确认——不承诺不重发，只记录

# ---- 多段逻辑回复的聚合状态 ----
AGGREGATE_COMPLETE = "complete"  # 全部片段 acknowledged
AGGREGATE_PARTIAL = "partial"  # 至少一段 acknowledged，且有 failed/unknown
AGGREGATE_FAILED = "failed"  # 没有任何片段送达
AGGREGATE_UNKNOWN = "unknown"  # 没有失败但也没有任何确认（如全部 unknown）

_TEXT_EXCERPT_MAX = 200


def utc_now_iso() -> str:
    """当前 UTC 时间（ISO8601，毫秒精度）。所有社交表的时间写入统一走这里。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_trace_id() -> str:
    """接入入口在硬门禁前创建的追踪 ID（未进入 Facade 的静默决策也持有）。"""
    return uuid.uuid4().hex


def parse_utc(value: str | None) -> datetime | None:
    """解析本模块写入的 UTC 时间串；空/非法返回 None（不猜测）。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def content_hash(text: str) -> str:
    """消息文本的 SHA-256（用于去重与快照一致性核对，非安全用途）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConversationScope:
    """学习资产的隔离键。同词异群必须分别维护，跨群默认不共享（计划 §3.1）。"""

    platform: str
    bot_id: str
    group_id: str

    def __post_init__(self) -> None:
        if not self.platform or not self.group_id:
            raise ValueError(
                "ConversationScope 需要 platform 与 group_id；"
                "无真实群归属的旧资产用 group_id=''（legacy_unscoped），"
                "由存储层约定，不通过本契约构造"
            )

    @staticmethod
    def for_qq(group_id: int | str, bot_id: int | str = "") -> "ConversationScope":
        """QQ 群作用域。bot_id 未知时留空（单 bot 部署下不参与区分）。"""
        return ConversationScope(
            platform="qq", bot_id=str(bot_id or ""), group_id=str(group_id)
        )

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.bot_id}:{self.group_id}"

    def row(self) -> tuple[str, str, str]:
        """按存储列序展开 (platform, bot_id, group_id)。"""
        return (self.platform, self.bot_id, self.group_id)


@dataclass(frozen=True)
class MessageEvidence:
    """一条标准化群消息证据（social_events 行的内存形态）。

    event_id 恒为新生成的 UUID（或调用方显式传入的既有 id）；平台消息 ID
    缺失时为 None——唯一性交给复合索引，多个 NULL 互不冲突。
    """

    scope: ConversationScope
    event_id: str = ""
    platform_message_id: str | None = None
    received_at_utc: str = ""  # 服务接收时间：排序与窗口判定的事实基准
    event_at_utc: str = ""  # 平台事件时间：仅展示
    source_kind: str = "PASSIVE"
    user_id: str = ""
    reply_to_id: str | None = None
    mentioned_user_ids: tuple[str, ...] = ()
    text_excerpt: str = ""
    content_hash: str = ""
    trace_id: str = ""
    turn_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", self.event_id or uuid.uuid4().hex)
        object.__setattr__(
            self, "received_at_utc", self.received_at_utc or utc_now_iso()
        )
        object.__setattr__(self, "text_excerpt", (self.text_excerpt or "")[:_TEXT_EXCERPT_MAX])
        object.__setattr__(self, "content_hash", self.content_hash or content_hash(self.text_excerpt))


@dataclass(frozen=True)
class DeliveryReceipt:
    """一个发送片段的投递事实（social_deliveries 行的内存形态）。

    ``platform_message_id`` 只在平台回执里真实拿到时才有值；它是后续
    「引用归因」的强证据锚点（用户回复这条 ID → direct attribution）。

    规范会话身份（修复计划 §6.3，全部 optional 默认兼容）：群回执由
    ``scope`` 承载身份；私聊/WebChat 等无群 scope 的回执在 scope=None 时
    携带 canonical 字段（conversation_key/kind/peer/storage），落库为
    会话中立行（group_id=''、learning_eligible=0）——可查询、绝不进群学习。
    """

    trace_id: str
    turn_id: str
    part_index: int
    status: str = DELIVERY_PENDING
    epoch: int = 0
    platform_message_id: str | None = None
    acknowledged_at_utc: str = ""
    text: str = ""
    text_hash: str = ""
    scope: ConversationScope | None = None
    conversation_key: str = ""
    conversation_kind: str = ""
    peer_id: str = ""
    storage_session_id: int | None = None
    # 中立行的平台/Bot 归属（验收报告 H1）：scope=None 时身份来自规范
    # ConversationRef，platform/bot_id 不再从空 scope 取空值
    platform: str = ""
    bot_id: str = ""
    # 最终封存计划与 guard decision 摘要：每条 receipt 都指回同一 sealed plan。
    delivery_plan_id: str = ""
    delivery_plan_digest: str = ""
    decision_digest: str = ""
    created_at_utc: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        object.__setattr__(self, "text_hash", self.text_hash or content_hash(self.text))

    @property
    def delivered(self) -> bool:
        return self.status == DELIVERY_ACKNOWLEDGED

    @property
    def learning_eligible(self) -> bool:
        """群学习可用性：仅真实 QQ 群 scope 行为 True（修复计划 §6.3）。

        中立回执（scope=None）与 WebChat 等非 QQ 群 scope 一律 False。
        """
        return (
            self.scope is not None
            and self.scope.platform == "qq"
            and bool(self.scope.group_id)
        )


def aggregate_delivery_status(statuses: list[str]) -> str:
    """把多段回执聚合为一次逻辑回复的投递状态（计划 §6.1）。

    规则：全部 acknowledged → complete；有任何 acknowledged 且混有
    failed/unknown → partial；全部 failed（或空）→ failed；其余
    （无 acknowledged 且无 failed，如全部 unknown）→ unknown。
    评估只使用已确认送达的片段；unknown 不重发、不伪造成功。
    """
    if not statuses:
        return AGGREGATE_FAILED
    ack = statuses.count(DELIVERY_ACKNOWLEDGED)
    failed = statuses.count(DELIVERY_FAILED)
    if ack == len(statuses):
        return AGGREGATE_COMPLETE
    if ack > 0:
        return AGGREGATE_PARTIAL
    if failed > 0:
        return AGGREGATE_FAILED
    return AGGREGATE_UNKNOWN


def delivered_texts(receipts: list["DeliveryReceipt"]) -> list[str]:
    """只取已确认送达片段的文本（按片段序）：BOT_SELF 落库与效果观察的事实输入。"""
    return [r.text for r in sorted(receipts, key=lambda r: r.part_index) if r.delivered]
