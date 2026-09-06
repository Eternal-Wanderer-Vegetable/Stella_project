# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""信号提取（上游工程方案 §9-§11/§22）：词表驱动的规则识别器。

所有词表来自 signals.toml（经 tables.SignalWords 传入），本模块不含词法常量。
判定均为小写子串匹配；输入是最近若干条消息文本（时间升序，末位为最新）。
"""
from __future__ import annotations

from dataclasses import dataclass

from memory.participation.tables import SignalWords


@dataclass(frozen=False)
class SignalSnapshot:
    """一次评分时提取到的全部信号（评分与 reason_flags 的共同输入）。"""

    open_question: bool = False        # 开放问题：明显社交空位（§10.1）
    question_to_group: bool = False    # 群级问句：次级空位
    unfinished: bool = False           # 未完成表达（§10.2）
    answered: bool = False             # 已被充分回应（§10.3）
    suspense: bool = False             # 悬念钩子（§11）
    strong_emotion: bool = False       # 强烈情绪（§11）
    fully_responded: bool = False      # 已经被充分回应（§11 负分档）
    direct_invite: bool = False        # 直接社交邀请（§11 +20 档）
    topic_shift: bool = False          # 承接/转移词（话题切换辅助）
    low_information: bool = False      # 低信息量消息（§22.4）
    high_velocity: bool = False        # 高速消息流（§10.4，由 state 计算）

    def flags(self) -> list[str]:
        return [name for name, hit in (
            ("open_question", self.open_question),
            ("question_to_group", self.question_to_group),
            ("unfinished", self.unfinished),
            ("answered", self.answered),
            ("strong_social_hook", self.suspense or self.direct_invite),
            ("strong_emotion", self.strong_emotion),
            ("fully_responded", self.fully_responded),
            ("direct_invite", self.direct_invite),
            ("topic_shift", self.topic_shift),
            ("low_information", self.low_information),
            ("high_message_velocity", self.high_velocity),
        ) if hit]


def _lower(text: str) -> str:
    return (text or "").lower()


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    t = _lower(text)
    return any(w in t for w in words)


def open_question_hit(text: str, words: SignalWords) -> bool:
    """开放问题：显式开放词（「有人玩过吗」），或 问号结尾+疑问词。"""
    t = _lower(text)
    if _contains_any(t, words.open_question_keywords):
        return True
    has_question_mark = any(t.endswith(s) for s in words.question_suffixes)
    has_tail = any(t.endswith(w) for w in words.question_tails)
    if not (has_question_mark or has_tail):
        return False
    return _contains_any(t, words.question_words)


def question_to_group_hit(text: str, words: SignalWords) -> bool:
    """群级问句：以问号/语气词结尾但没有开放词（次级空位）。"""
    t = _lower(text)
    if _contains_any(t, words.open_question_keywords):
        return False
    has_question_mark = any(t.endswith(s) for s in words.question_suffixes)
    has_tail = any(t.endswith(w) for w in words.question_tails)
    if not (has_question_mark or has_tail):
        return False
    return _contains_any(t, words.question_words)


def unfinished_hit(recent_texts: list[str], words: SignalWords) -> bool:
    """未完成表达：末条以省略/逗号结尾 + 含引导词，或倒数第二条留悬念后有人追问。

    recent_texts 时间升序，末位是最新消息。
    """
    if not recent_texts:
        return False
    last = _lower(recent_texts[-1])
    if any(last.endswith(s) for s in words.unfinished_suffixes) and _contains_any(
        last, words.unfinished_teasers
    ):
        return True
    if len(recent_texts) >= 2:
        prev = _lower(recent_texts[-2])
        teaser_before = _contains_any(prev, words.unfinished_teasers) or _contains_any(
            prev, words.suspense_keywords
        )
        followup = last in ("?", "？", "?", "啥", "咋了", "怎么了", "然后呢")
        if teaser_before and followup:
            return True
    return False


def answered_hit(recent_texts: list[str], words: SignalWords) -> bool:
    """已被充分回答：提问后紧跟认可性回应（§10.3「点这里 / 哦懂了」）。"""
    if len(recent_texts) < 2:
        return False
    question = _lower(recent_texts[-2])
    reply = _lower(recent_texts[-1])
    was_question = any(question.endswith(s) for s in words.question_suffixes) or _contains_any(
        question, words.open_question_keywords
    )
    return was_question and _contains_any(reply, words.acknowledgment_keywords)


def suspense_hit(text: str, words: SignalWords) -> bool:
    return _contains_any(text, words.suspense_keywords)


def strong_emotion_hit(text: str, words: SignalWords) -> bool:
    return _contains_any(text, words.emotion_keywords)


def fully_responded_hit(recent_texts: list[str], words: SignalWords) -> bool:
    """已经被群友充分回应：最新一两条都是认可性短语/低信息量刷屏。"""
    tail = recent_texts[-2:] if len(recent_texts) >= 2 else recent_texts
    if not tail:
        return False
    return all(_contains_any(t, words.acknowledgment_keywords) for t in tail)


def low_information_hit(text: str, words: SignalWords) -> bool:
    t = (text or "").strip()
    if not t or len(t) > words.low_info_max_length:
        return False
    return _contains_any(t, words.low_info_keywords)


def direct_invite_hit(text: str, words: SignalWords) -> bool:
    """直接社交邀请：点名 Stella（未 @，@ 属于 Hard Trigger 不走本层）+ 邀请句式。"""
    t = _lower(text)
    if not _contains_any(t, words.invite_name_variants):
        return False
    return _contains_any(t, words.invite_patterns)


def topic_shift_hit(text: str, words: SignalWords) -> bool:
    return _contains_any(text, words.topic_shift_keywords)


def extract(recent_texts: list[str], latest_text: str, words: SignalWords) -> SignalSnapshot:
    """从最近文本提取全部信号。latest_text 是触发评分的那条消息。"""
    latest = latest_text or (recent_texts[-1] if recent_texts else "")
    return SignalSnapshot(
        open_question=open_question_hit(latest, words),
        question_to_group=question_to_group_hit(latest, words),
        unfinished=unfinished_hit(recent_texts, words),
        answered=answered_hit(recent_texts, words),
        suspense=suspense_hit(latest, words),
        strong_emotion=strong_emotion_hit(latest, words),
        fully_responded=fully_responded_hit(recent_texts, words),
        direct_invite=direct_invite_hit(latest, words),
        topic_shift=topic_shift_hit(latest, words),
        low_information=low_information_hit(latest, words),
    )
