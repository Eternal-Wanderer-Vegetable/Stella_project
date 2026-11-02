# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""场景合同：适配器产出的回放场景 / 场景索引的加载、校验与抽样。"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

SCENARIO_SCHEMA = "memory-eval-locomo-scenario/1"
INDEX_SCHEMA = "memory-eval-locomo-index/1"


def load_index(data_dir: Path) -> dict[str, Any]:
    index_path = data_dir / "index.json"
    if not index_path.exists():
        raise FileNotFoundError(f"缺少场景索引：{index_path}（先运行 scripts/adapt_locomo.py）")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema") != INDEX_SCHEMA:
        raise ValueError(f"索引 schema 不符：{index.get('schema')!r} ≠ {INDEX_SCHEMA!r}")
    return index


def load_scenario(data_dir: Path, name: str) -> dict[str, Any]:
    path = data_dir / name
    scenario = json.loads(path.read_text(encoding="utf-8"))
    if scenario.get("schema") != SCENARIO_SCHEMA:
        raise ValueError(f"场景 schema 不符：{path} {scenario.get('schema')!r}")
    for key in ("scenario_id", "group_id", "conversation_key", "bot_id", "sessions", "qa"):
        if key not in scenario:
            raise ValueError(f"场景缺少字段 {key!r}：{path}")
    return scenario


def load_scenarios(data_dir: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """按索引顺序加载场景（limit=0 表示全部）。"""
    index = load_index(data_dir)
    entries = index["scenarios"]
    if limit is not None and limit > 0:
        entries = entries[:limit]
    return [load_scenario(data_dir, entry["file"]) for entry in entries]


def select_qa(scenario: dict[str, Any], sample_per_category: int = 0, seed: int = 0) -> list[dict[str, Any]]:
    """选取要评测的 QA；sample_per_category>0 时按类别均匀抽样（固定种子）。"""
    qa = list(scenario.get("qa") or [])
    if sample_per_category <= 0:
        return qa
    rng = random.Random(seed)
    by_category: dict[int, list[dict[str, Any]]] = {}
    for item in qa:
        by_category.setdefault(int(item.get("category") or 0), []).append(item)
    picked: list[dict[str, Any]] = []
    for category in sorted(by_category):
        bucket = by_category[category]
        if len(bucket) <= sample_per_category:
            picked.extend(bucket)
        else:
            picked.extend(rng.sample(bucket, sample_per_category))
    picked.sort(key=lambda item: item.get("qid") or "")
    return picked


def evidence_texts(scenario: dict[str, Any]) -> dict[str, str]:
    """dia_id → 原文（QA 证据覆盖与写侧覆盖评估用）。"""
    texts: dict[str, str] = {}
    for session in scenario.get("sessions") or []:
        for msg in session.get("messages") or []:
            texts[str(msg.get("dia_id") or "")] = str(msg.get("text") or "")
    return texts
