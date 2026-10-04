# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对话历史的纯数据投影（多人对话归属修复计划 §6.2）。

职责刻意收窄：**有符号平台 message ID 解析** + **已可信消息行的投影/序列化**。
不含 DB、模型、会话队列或语义实体抽取——正文只表示「某人说过这些话」，
绝不从正文正则抽取「已发生」事件。身份信封由调用方（pre_processors /
session_compact / ai_gateway）从平台事件或已入库行提供，本模块不做任何猜测。

为什么是「每个逻辑回复一个物理行」：预算 v2（core/context_budget.py）按物理
换行丢弃历史行。多气泡回复若渲染成多行，预算可能砍掉后续气泡、留下孤立
前文（2026-10-04 复现的输入表达薄弱点之一）。把一次回复的**全部已确认气泡**
JSON 转义后装进同一物理行，预算要么整行保留、要么整行移除。

格式版本：渲染格式变更时递增 :data:`PROJECTION_FORMAT_VERSION`。部署以新
进程启用（不复用旧进程已组装的缓存）；冻结回放始终消费当时的 parts_input
字符串，与本版本号无关。
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

# 投影格式版本（§6.2）：随渲染格式演进递增；进尾巴段头供诊断与验收对照。
PROJECTION_FORMAT_VERSION = 1

# 正文太长时的护栏（防御异常大图/刷屏文本占满预算；正常消息远小于此）。
_BUBBLE_TEXT_MAX_CHARS = 2000


def parse_platform_message_id(value) -> int | None:
    """解析平台 message ID：接受平台整数或规范十进制文本的**非零有符号**值。

    QQ（NTQQ/AstrBot 回执）的 message ID 可以是负数（真实回执
    ``-558868042``）。历史上三处 ``.isdigit()`` 把合法负数变成 0/unknown，
    造成「引用查不到作者」。本函数是唯一的解析入口：

    - 接受 ``int``（含负数）与形如 ``"381231377"`` / ``"-558868042"`` 的
      **规范十进制文本**（可选正负号 + 不含前导零的数字；``"-0"`` 同样拒绝）；
    - 拒绝 ``bool``（``True`` 是 1 不是 ID）、浮点、空串、纯空白、字母、
      ``0``、``"+123"``、前导零（``"007"``）等一切非规范形态；
    - 解析不了返回 ``None`` = unknown，调用方按「无平台 ID」处理，绝不猜。

    注意：这只放宽 **message ID** 的符号；user_id / bot_id 的校验口径不变。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value != 0 else None
    if isinstance(value, float) or value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    sign = 1
    if text[0] in "+-":
        # "+123" 非规范形态（平台不会发）；只接受负号
        if text[0] == "+":
            return None
        sign = -1
        text = text[1:]
    if not text.isdigit():
        return None
    if len(text) > 1 and text[0] == "0":
        return None  # 前导零不是平台形态（"007" 可能是人工脏数据）
    magnitude = int(text)
    if magnitude == 0:
        return None  # 0 = 「平台 ID 缺失」的哨兵值，不是合法 ID
    return sign * magnitude


def canonical_message_id_text(value) -> str:
    """平台 message ID 的规范文本（持久化/匹配统一用它）；非法返回空串。"""
    parsed = parse_platform_message_id(value)
    return str(parsed) if parsed is not None else ""


def _safe_atom(value) -> str:
    """头部落入渲染行的标量（uid/ID）：去控制字符与换行，防空隙注入。

    uid/ID 来自平台或数据库，正常情况是纯数字；这里只做防御性清理，
    不做任何语义判断。
    """
    text = str(value or "")
    return "".join(
        ch
        for ch in text
        if ch not in "\r\n\t" and unicodedata.category(ch) != "Cc"
    ).strip()


@dataclass(frozen=True, slots=True)
class TranscriptBubble:
    """逻辑回复内的单个已确认气泡（part_index 保留真实值，可为 0,1,2…）。"""

    part_index: int
    text: str


@dataclass(frozen=True, slots=True)
class TranscriptRecord:
    """一条历史记录的自足投影（一个逻辑回复 = 一个物理行）。

    全部字段来自可信信封；空串/空元组 = unknown，渲染为「未知」，
    **绝不**用相邻行或最近发言人补全。``author_is_bot`` 即 BOT_SELF 角色
    ——Bot 是发言作者，收件人/回复对象不是作者。
    """

    author_id: str  # 作者稳定 ID（BOT_SELF 行即 bot uid）
    author_is_bot: bool
    bubbles: tuple[TranscriptBubble, ...]  # 仅已确认内容，保留实际 part_index
    recipient_id: str = ""  # BOT_SELF 收件人；"" = unknown
    reply_to_msg_id: str = ""  # 用户消息引用的平台 ID；"" = 无引用
    reply_target_user_id: str = ""  # 引用原消息作者；"" = unknown
    mentioned_user_ids: tuple[str, ...] = ()
    origin_msg_id: str = ""  # BOT_SELF 逻辑单元的源输入平台 ID；"" = unknown

    def __post_init__(self) -> None:
        object.__setattr__(self, "author_id", _safe_atom(self.author_id))
        object.__setattr__(self, "recipient_id", _safe_atom(self.recipient_id))
        object.__setattr__(self, "reply_to_msg_id", _safe_atom(self.reply_to_msg_id))
        object.__setattr__(
            self, "reply_target_user_id", _safe_atom(self.reply_target_user_id)
        )
        object.__setattr__(
            self,
            "mentioned_user_ids",
            tuple(_safe_atom(m) for m in self.mentioned_user_ids if _safe_atom(m)),
        )
        object.__setattr__(self, "origin_msg_id", _safe_atom(self.origin_msg_id))
        bubbles = tuple(
            TranscriptBubble(
                part_index=max(0, int(b.part_index or 0)),
                text=str(b.text or "")[:_BUBBLE_TEXT_MAX_CHARS],
            )
            for b in self.bubbles
        )
        object.__setattr__(self, "bubbles", bubbles)


def _quoted_uid(role: str, uid: str) -> str:
    """「用户(uid)」形态；调用方保证 uid 非空。"""
    return f"{role}({_safe_atom(uid)})"


def render_transcript_record(record: TranscriptRecord) -> str:
    """渲染一条记录为**单个物理行**；正文经 JSON 转义，不产生额外行。

    形态（§6.2 拟定格式的落地版）::

        [作者=Bot(1694717255); 回复给=用户(176403822); 原输入=383945296] 说过: [{"part":0,"text":"谁是小孩啦"},…]
        [作者=用户(176403822); 回复给=用户(1694717255)] 说过: [{"part":0,"text":"摸摸"}]

    - ``回复给``：BOT_SELF 行是收件人（缺失=未知）；用户行是引用对象
      （有 reply_to 但作者未解析=未知；无引用则整段省略）；
    - ``提及``：仅在被提及时出现；
    - 正文里的换行/引号/伪造头（如「用户(9999): 」）都困在 JSON 字符串内，
      不会被误读成另一条记录或另一个说话人。
    """
    if not record.bubbles:
        return ""
    role = "Bot" if record.author_is_bot else "用户"
    author_label = record.author_id or "未知"
    header_parts: list[str] = [f"作者={role}({author_label})"]
    if record.author_is_bot:
        header_parts.append(
            f"回复给={_quoted_uid('用户', record.recipient_id)}"
            if record.recipient_id
            else "回复给=未知"
        )
        if record.origin_msg_id:
            header_parts.append(f"原输入={record.origin_msg_id}")
    else:
        if record.reply_to_msg_id:
            if record.reply_target_user_id:
                header_parts.append(f"回复给={_quoted_uid('用户', record.reply_target_user_id)}")
            else:
                header_parts.append("回复给=未知")
        if record.mentioned_user_ids:
            header_parts.append(
                "提及=" + "、".join(_quoted_uid("用户", m) for m in record.mentioned_user_ids)
            )
    payload = json.dumps(
        [
            {"part": bubble.part_index, "text": bubble.text}
            for bubble in record.bubbles
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"[{'; '.join(header_parts)}] 说过: {payload}"
