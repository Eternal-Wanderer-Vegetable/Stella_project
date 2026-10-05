# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""对话归属独立 oracle（2026-10-05 整改计划 P0）。

**刻意不 import 任何 memory/core 业务模块**：判定只依赖夹具元数据与最终
发送文本，作为与实现无关的验收基准（复核报告 §3「独立 oracle」）。
关键词/规则只服务本项目的固定现场语料，不是通用中文语义判定。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dialogue_attribution"

_SCENE_FIXTURES = (
    "scene-090046-private-share.json",
    "scene-131951-nox-compound.json",
    "scene-132230-author-inversion.json",
    "scene-140919-proactive-third-party.json",
)

# speaker_swap：Bot 把自己对用户说的话反怪到用户头上（13:31 现场原句及同型）
_SPEAKER_SWAP_MARKS = (
    "谁说我脏手",
    "你说我脏手",
    "我说过脏手？",
    "我什么时候说脏手",
)
# stale_premise：纠正后仍维护旧前提（对象倒置未翻篇）
_STALE_PREMISE_MARKS = (
    "你肘我",
    "肘的就是我",
    "你刚才肘我",
)
# subject_swap：把别人的自我背景安到当前目标头上（14:09 现场形状）
_SUBJECT_SWAP_RE = re.compile(r"(你|您)[^，。！？\n]{0,12}开发\s*Stella", re.IGNORECASE)


@dataclass
class Verdict:
    """单次判定结果。critical 命中即 fail；warnings 不影响通过。"""

    passed: bool
    critical_class: str = ""
    detail: str = ""
    warnings: list[str] = field(default_factory=list)


def load_scene_fixture(fixture_id: str) -> dict:
    """按 fixture_id 加载现场夹具。"""
    for name in _SCENE_FIXTURES:
        data = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        if data["fixture_id"] == fixture_id:
            return data
    raise FileNotFoundError(f"unknown scene fixture: {fixture_id}")


def judge_reply(fixture: dict, final_text: str) -> Verdict:
    """按夹具 oracle.critical_classes 判定最终发送文本。

    这是独立于实现的验收判定：只看夹具声明的关键错误类与最终文本，
    不读被测代码的任何中间状态。
    """
    text = (final_text or "").strip()
    critical = set(fixture.get("oracle", {}).get("critical_classes", []))
    warnings: list[str] = []

    if "speaker_swap" in critical:
        for mark in _SPEAKER_SWAP_MARKS:
            if mark in text:
                return Verdict(
                    False,
                    "speaker_swap",
                    f"bot 原话被翻成用户所说（命中「{mark}」）",
                    warnings,
                )

    if "stale_premise" in critical:
        for mark in _STALE_PREMISE_MARKS:
            if mark in text:
                return Verdict(
                    False,
                    "stale_premise",
                    f"纠正后仍维护旧前提（命中「{mark}」）",
                    warnings,
                )

    if "subject_swap" in critical:
        m = _SUBJECT_SWAP_RE.search(text)
        if m:
            return Verdict(
                False,
                "subject_swap",
                f"把他人背景安到当前目标头上（命中「{m.group(0)}」）",
                warnings,
            )

    if "alias_transfer" in critical:
        # 夹具里 bot 用「红中」称呼的目标是 candidate_object_of_bot_call，
        # 对当前纠正者使用该称呼即转移
        obj = fixture.get("evaluation", {}).get("identity", {}).get(
            "candidate_object_of_bot_call"
        )
        sender_key = fixture.get("evaluation", {}).get("current_sender")
        participants = fixture.get("participants", {})
        if obj == "H" and sender_key in participants and sender_key and re.search(
            rf"{sender_key}[，,]?[^，。！？\n]{{0,8}}红中", text
        ):
            return Verdict(
                False,
                "alias_transfer",
                "第三人称呼被转移到纠正者身上",
                warnings,
            )

    return Verdict(True, "", "ok", warnings)


def judge_identity(fixture: dict, registered_alias: str | None) -> Verdict:
    """按夹具 identity 块判定身份登记结果（场景 131951）。"""
    identity = fixture.get("evaluation", {}).get("identity") or {}
    expect = identity.get("expect_alias_registered")
    if expect is None:
        return Verdict(True, "", "no identity clause in fixture")
    normalized = (registered_alias or "").strip().lower()
    if normalized != expect.strip().lower():
        return Verdict(
            False,
            "identity_drop",
            f"期望登记 {expect!r}，实际 {registered_alias!r}",
        )
    return Verdict(True, "", "ok")
