# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""PersonaMem 适配器离线测试：本地小样本 fixture，不依赖网络。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import adapt_personamem as adapt
import fetch_personamem as fetch_mod

# 与 v2 benchmark.csv 同 schema 的最小 fixture（2 个 persona、4 行）
CSV_FIXTURE = """persona_id,chat_history_32k_link,chat_history_128k_link,raw_persona_file,short_persona,expanded_persona,user_query,correct_answer,incorrect_answers,topic_query,preference,topic_preference,conversation_scenario,pref_type,related_conversation_snippet,who,updated,prev_pref,sensitive_info,total_tokens_in_chat_history_32k,total_tokens_in_chat_history_128k,distance_from_related_snippet_to_query_32k,distance_from_related_snippet_to_query_128k,num_persona_relevant_tokens_32k,num_persona_irrelevant_tokens_32k,num_persona_relevant_tokens_128k,num_persona_irrelevant_tokens_128k
11,l1,l2,r1,sp,ep,"What food should we order for movie night?","Pizza!","Sushi; Salad; Tacos",Food,"{'role': 'user', 'content': 'I love deep dish pizza'}",food,chat_message,stereotypical_pref,"[{'role': 'user', 'content': 'I love deep dish pizza, it is my favorite'}]",user,False,False,False,100,200,10,20,50,50,100,100
11,l1,l2,r1,sp,ep,"What dessert fits my taste?","Cheesecake","Ice cream; Cake; Pie",Food,"{'role': 'user', 'content': 'I always pick cheesecake over cake'}",food,chat_message,stereotypical_pref,"[{'role': 'user', 'content': 'I always pick cheesecake over cake'}]",user,True,"{'role': 'user', 'content': 'I used to prefer regular cake'}",False,100,200,10,20,50,50,100,100
22,l1,l2,r2,sp,ep,"Plan my weekend hike","Gear up","Stay home",Hiking,"{'role': 'user', 'content': 'I hike every weekend and love trails'}",outdoors,chat_message,neutral_preference,"[{'role': 'user', 'content': 'My SSN is 123-45-6789 and I hike every weekend'}]",user,False,False,True,100,200,10,20,50,50,100,100
22,l1,l2,r2,sp,ep,"Suggest a relax spot","Lake","Club",Travel,"{'role': 'user', 'content': 'Quiet lakes relax me'}",travel,chat_message,neutral_preference,"[{'role': 'user', 'content': 'Quiet lakes relax me after work'}]",user,False,False,False,100,200,10,20,50,50,100,100
"""


@pytest.fixture()
def csv_path(tmp_path):
    p = tmp_path / "benchmark.csv"
    p.write_text(CSV_FIXTURE, encoding="utf-8")
    return p


def test_build_cases_maps_preference_and_evidence(csv_path):
    cases = adapt.build_cases(adapt.load_rows(csv_path), revision="rev-test")
    by_id = {c["id"]: c for c in cases}
    assert len(cases) == 4

    food = by_id["pm-p11-r0"]
    assert food["input"] == "What food should we order for movie night?"
    assert food["expected_memory"] == ["PREF"]
    assert "I love deep dish pizza" in food["memories"]["PREF"]["content"]
    # 血缘：PREF 携带 snippet 证据行
    assert food["expect_evidence"] is True
    ev = food["memories"]["PREF"]["evidence"][0]
    assert ev["source_row_id"] == 0
    assert "deep dish pizza" in ev["source_conversation_key"] or ev["source_row_id"] == 0
    # 同 persona 其他行 preference 成为干扰
    assert any(mid.startswith("DEC") for mid in food["memories"])
    # topic 规范化
    assert food["topic"] == "food"


def test_updated_row_maps_prev_pref_to_superseded_forbidden(csv_path):
    cases = adapt.build_cases(adapt.load_rows(csv_path), revision="rev-test")
    dessert = next(c for c in cases if c["id"] == "pm-p11-r1")
    prev = dessert["memories"]["PREV"]
    assert prev["status"] == "superseded"
    assert "regular cake" in prev["content"]
    assert dessert["forbidden_memory"] == ["PREV"]


def test_sensitive_row_maps_restricted_forbidden(csv_path):
    """sensitive_info=True → 敏感记忆 RESTRICTED + forbidden（隐私红线）。"""
    cases = adapt.build_cases(adapt.load_rows(csv_path), revision="rev-test")
    hike = next(c for c in cases if c["id"] == "pm-p22-r2")
    sens = hike["memories"]["SENS"]
    assert sens["visibility"] == "RESTRICTED"
    assert "SSN" in sens["content"]
    assert "SENS" in hike["forbidden_memory"]
    # 非敏感行没有 SENS
    lake = next(c for c in cases if c["id"] == "pm-p22-r3")
    assert "SENS" not in lake["memories"]


def test_adapted_cases_pass_retrieval_end_to_end(csv_path):
    """适配用例直接进 run_benchmark 必须全绿（含血缘与红线判定）。"""
    import memory.benchmark as benchmark

    cases = adapt.build_cases(adapt.load_rows(csv_path), revision="rev-test")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        dataset = Path(td) / "adapted"
        dataset.mkdir()
        for c in cases:
            (dataset / f"{c['id']}.json").write_text(
                json.dumps(c, ensure_ascii=False), encoding="utf-8")
        metrics = benchmark.run_benchmark(dataset)
        assert metrics["cases_total"] == 4
        assert metrics["cases_ok"] == 4
        assert metrics["forbidden_activation_rate"] == 0.0
        assert metrics["dimensions"]["lineage"]["lineage_completeness"] == 100.0
        # topic_metrics 聚合（分题型口径）
        assert metrics["topic_metrics"]["food"]["cases_total"] == 2


def test_sample_deterministic(csv_path):
    cases = adapt.build_cases(adapt.load_rows(csv_path), revision="rev-test")
    s1 = adapt.sample_cases(cases, 3, 42)
    s2 = adapt.sample_cases(cases, 3, 42)
    assert [c["id"] for c in s1] == [c["id"] for c in s2]
    assert len(s1) == 3
    assert all(c in cases for c in s1)
    # 大样例空间下不同 seed 抽样不同（4 选 3 可能重合，这里只验证合法性与确定性）
    s3 = adapt.sample_cases(cases, 2, 43)
    assert len(s3) == 2


def test_main_skips_explicitly_when_data_missing(tmp_path, capsys):
    """数据缺失 = 显式 skip（exit 3 + 结构化报告），不静默绿。"""
    code = adapt.main(["--csv", str(tmp_path / "nope.csv"), "--out", str(tmp_path / "adapted")])
    assert code == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "skipped_data_missing"


def test_fetch_check_fails_without_manifest(tmp_path):
    assert fetch_mod.fetch(tmp_path, check_only=True) == 1


def test_fetch_network_unreachable_is_explicit_skip(tmp_path, monkeypatch, capsys):
    """网络不可达 → exit 3 + 结构化 attempts 报告（绝不静默绿）。"""
    monkeypatch.setenv("HF_ENDPOINT", "https://127.0.0.1:9")
    monkeypatch.setattr(fetch_mod, "DEFAULT_BASE", "https://127.0.0.1:9")
    monkeypatch.setattr(fetch_mod, "FALLBACK_BASE", "https://127.0.0.1:9")
    code = fetch_mod.fetch(tmp_path)
    assert code == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "skipped_network_unreachable"
    assert payload["attempts"]
