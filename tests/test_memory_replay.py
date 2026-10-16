# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""写路径回放（M4）测试：recorded 确定性、fabrication 规则、live 缺席语义。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import eval_memory_replay as replay

SUITE = Path(__file__).resolve().parent.parent / "memory" / "benchmark" / "_replay" / "daily-life"


def _replay_once(tmp_root: Path):
    """跑一次 recorded 回放，返回 (db_path, suite)。"""
    tmp_root.mkdir(parents=True, exist_ok=True)
    suite = replay._load_suite(SUITE)
    db_path = replay._replay_recorded(suite, tmp_root)
    return db_path, suite


def test_recorded_replay_deterministic(tmp_path):
    """同一录制件两次回放 → 指标完全一致（uuid 主键除外）。"""
    r1 = replay._evaluate_metrics(*_replay_once(tmp_path / "a"))
    r2 = replay._evaluate_metrics(*_replay_once(tmp_path / "b"))
    assert r1["metrics"] == r2["metrics"]
    qa1 = [(q["id"], q["pass"]) for q in r1["details"]["qa_with"]]
    qa2 = [(q["id"], q["pass"]) for q in r2["details"]["qa_with"]]
    assert qa1 == qa2


def test_replay_gate_all_green(tmp_path):
    """录制套件门禁：抽取/编造/晋升/QA/记忆增量全绿。"""
    db_path, suite = _replay_once(tmp_path)
    evaluation = replay._evaluate_metrics(db_path, suite)
    assert replay._gate(evaluation["metrics"]) == []
    assert evaluation["metrics"]["fabrication_rate"] == 0.0
    assert evaluation["metrics"]["memory_delta"] > 0.0


def test_fabrication_rule_flags_ungrounded_content():
    """编造规则：候选内容与窗口原文无 4-gram 交集即编造；引用原文不误报。"""
    corpus = replay._grams("我喜欢周末去爬山，每周都去\n今天地铁检修")
    assert replay._fabricated("我喜欢周末去爬山", corpus) is False   # 引用原文
    assert replay._fabricated("用户最喜欢的节目是歌剧", corpus) is True  # 凭空内容
    assert replay._fabricated("", corpus) is False  # 空内容不判编造（无 gram）


def test_live_without_backend_is_explicit_skip(tmp_path, capsys, monkeypatch):
    """live 模式在 CONSOLIDATION 角色未配置时显式 skip（exit 3）。

    backend_for 打桩为 None：测试绝不触真实端点配置（数据边界）。"""
    import core.llm.registry as registry

    monkeypatch.setattr(registry, "backend_for", lambda role: None)
    code = replay.main([
        "--suite", str(SUITE),
        "--live",
        "--json", str(tmp_path / "report.json"),
    ])
    assert code == 3
