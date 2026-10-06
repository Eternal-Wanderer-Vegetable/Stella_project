# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE.
"""四个现场夹具 × 独立 oracle 的常驻验收（整改计划 P0/P7）。

夹具与判定互不依赖业务代码：oracle 只看夹具元数据与最终发送文本。
这里固化方向性探针——真实错归形状必须被判 fail，干净回复必须 pass。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import attribution_oracle as oracle


def test_all_scene_fixtures_load():
    ids = []
    for name in oracle._SCENE_FIXTURES:
        import json

        data = json.loads((oracle.FIXTURE_DIR / name).read_text(encoding="utf-8"))
        ids.append(data["fixture_id"])
    assert len(ids) == 4
    assert len(set(ids)) == 4


def test_scene_132231_speaker_swap_detected():
    """13:31 现场：Bot 把自己的「脏手别摸」翻成用户说的 → 必判 fail。"""
    fixture = oracle.load_scene_fixture("scene-132230-author-inversion")
    bad = "才没有呢 别想套我话呀 刚才是谁说我脏手来着？"
    verdict = oracle.judge_reply(fixture, bad)
    assert not verdict.passed and verdict.critical_class == "speaker_swap"
    good = "才没有呢，私聊的记忆我可都好好收着呢"
    assert oracle.judge_reply(fixture, good).passed


def test_scene_140919_subject_swap_detected():
    """14:09 现场：他人背景被安到当前目标头上 → 必判 fail。"""
    fixture = oracle.load_scene_fixture("scene-140919-proactive-third-party")
    verdict = oracle.judge_reply(fixture, "话说你开发Stella多久啦？")
    assert not verdict.passed and verdict.critical_class == "subject_swap"
    assert oracle.judge_reply(fixture, "（这轮没有能自然承接的话题，跳过）").passed


def test_scene_131951_alias_transfer_and_identity():
    """13:19 现场：第三人称呼转移到纠正者身上必判 fail；身份判定对照。"""
    fixture = oracle.load_scene_fixture("scene-131951-nox-compound")
    verdict = oracle.judge_reply(fixture, "N，你平时会叫红中吗？")
    assert not verdict.passed and verdict.critical_class == "alias_transfer"
    assert oracle.judge_reply(fixture, "了解啦，Nox！").passed
    assert oracle.judge_identity(fixture, "Nox").passed
    verdict = oracle.judge_identity(fixture, None)
    assert not verdict.passed and verdict.critical_class == "identity_drop"
