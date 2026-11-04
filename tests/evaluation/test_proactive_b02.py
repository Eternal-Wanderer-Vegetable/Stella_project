# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors

from __future__ import annotations

import hashlib
import json

import pytest

from proactive_eval.b02_plugins import (
    always_silent,
    always_speak,
    last_explicit_question,
    score_source_label,
)
from proactive_eval.source_adapters import (
    adapt_social_ai_ambient,
    adapt_when2speak_token,
    write_jsonl,
)


def _write_source(path, rows):
    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _when_row(messages, label):
    return {
        "messages": [
            {"role": "user", "content": message} for message in messages
        ]
        + [{"role": "assistant", "content": label}]
    }


def _social_scene():
    return {
        "id": "scene-1",
        "category": "planning",
        "description": "Private report-only metadata.",
        "num_turns": 3,
        "num_respond": 1,
        "num_silent": 2,
        "turns": [
            {"turn_index": 0, "speaker": "Alex", "message": "I have a question", "expected_output": "SILENT"},
            {"turn_index": 1, "speaker": "Emma", "message": "What is it?", "expected_output": "RESPOND"},
            {"turn_index": 2, "speaker": "Alex", "message": "Thanks", "expected_output": "SILENT"},
        ],
    }


def test_when2speak_adapter_separates_final_token_and_preserves_context(tmp_path):
    source = tmp_path / "when2speak.jsonl"
    digest = _write_source(source, [_when_row(["Speaker_0: hello", "Speaker_1: [AGENT], thoughts?"], "<")])

    corpus = adapt_when2speak_token(source, expected_sha256=digest, revision="pinned-revision")

    assert corpus.raw_records == 1
    assert corpus.label_counts == {"SPEAK": 1, "SILENT": 0}
    scenario = corpus.scenarios[0]
    assert [event["text"] for event in scenario["events"]] == [
        "Speaker_0: hello",
        "Speaker_1: [AGENT], thoughts?",
    ]
    assert all(event["time_source"] == "synthetic" for event in scenario["events"])
    assert scenario["accessible_memories"] == []
    serialized_actor = json.dumps(scenario)
    assert "source_label" not in serialized_actor
    assert "expected_output" not in serialized_actor
    assert corpus.gold[0]["source_label"] == "SPEAK"
    assert corpus.gold[0]["event_id"] == scenario["events"][-1]["event_id"]
    assert corpus.gold[0]["label_origin"] == "official"


def test_when2speak_adapter_rejects_hash_and_label_drift(tmp_path):
    source = tmp_path / "when2speak.jsonl"
    digest = _write_source(source, [_when_row(["Speaker_0: hello"], "<")])
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        adapt_when2speak_token(source, expected_sha256="0" * 64, revision="pinned-revision")

    _write_source(source, [_when_row(["Speaker_0: hello"], "?" )])
    with pytest.raises(ValueError, match="unsupported token label"):
        adapt_when2speak_token(
            source, expected_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), revision="pinned-revision"
        )
    assert len(digest) == 64


def test_social_adapter_builds_only_causal_prefixes_and_keeps_category_report_side(tmp_path):
    source = tmp_path / "social.jsonl"
    digest = _write_source(source, [_social_scene()])

    corpus = adapt_social_ai_ambient(source, expected_sha256=digest, revision="pinned-revision")

    assert corpus.raw_records == 1
    assert len(corpus.scenarios) == len(corpus.gold) == 3
    assert corpus.label_counts == {"SPEAK": 1, "SILENT": 2}
    first, second, third = corpus.scenarios
    assert [event["text"] for event in first["events"]] == ["I have a question"]
    assert [event["text"] for event in second["events"]] == ["I have a question", "What is it?"]
    assert len(third["events"]) == 3
    assert first["episode_id"] == second["episode_id"] == third["episode_id"] == "scene-1"
    assert all("expected_output" not in event for scenario in corpus.scenarios for event in scenario["events"])
    assert all("description" not in scenario and "category" not in scenario for scenario in corpus.scenarios)
    assert set(corpus.category_by_scenario.values()) == {"planning"}
    assert [row["source_label"] for row in corpus.gold] == ["SILENT", "SPEAK", "SILENT"]


def test_social_adapter_rejects_noncontiguous_turns_and_stale_scene_counts(tmp_path):
    source = tmp_path / "social.jsonl"
    row = _social_scene()
    row["turns"][1]["turn_index"] = 7
    digest = _write_source(source, [row])
    with pytest.raises(ValueError, match="turn_index must be contiguous"):
        adapt_social_ai_ambient(source, expected_sha256=digest, revision="pinned-revision")

    row = _social_scene()
    row["num_respond"] = 2
    digest = _write_source(source, [row])
    with pytest.raises(ValueError, match="num_respond does not match"):
        adapt_social_ai_ambient(source, expected_sha256=digest, revision="pinned-revision")


def test_b02_baselines_are_local_and_use_only_the_current_message():
    scenario = {
        "events": [
            {"text": "A prior question?"},
            {"text": "A plain current message."},
        ],
        "accessible_memories": [],
    }
    assert always_silent(scenario)["action"] == "DROP"
    assert always_speak(scenario)["action"] == "SPEAK"
    assert last_explicit_question(scenario)["action"] == "DROP"
    scenario["events"][-1]["text"] = "A current question？"
    assert last_explicit_question(scenario)["action"] == "SPEAK"
    scenario["accessible_memories"] = [{"content": "memory"}]
    with pytest.raises(ValueError, match="empty memory context"):
        always_silent(scenario)


@pytest.mark.parametrize(
    ("expected", "action", "error_kind"),
    [
        ("SPEAK", "DROP", "missed_intervention"),
        ("SILENT", "SPEAK", "false_interruption"),
        ("SILENT", "DROP", None),
    ],
)
def test_scorer_maps_binary_actions_and_retains_error_class(expected, action, error_kind):
    result = score_source_label({"source_label": expected}, {"action": action, "method": "test"})
    assert result["expected"] == expected
    assert result["error_kind"] == error_kind
    assert result["correct"] is (error_kind is None)


def test_jsonl_writer_is_deterministic_and_returns_the_written_hash(tmp_path):
    target = tmp_path / "derived.jsonl"
    digest = write_jsonl(target, [{"text": "问候", "value": 1}])
    assert digest == hashlib.sha256(target.read_bytes()).hexdigest()
    assert json.loads(target.read_text(encoding="utf-8")) == {"text": "问候", "value": 1}
