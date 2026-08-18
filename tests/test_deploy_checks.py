# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""doctor 判断层的单元测试。

检查函数都是纯函数（只读 Snapshot），因此测试不需要真实环境——
用 ``_healthy_snapshot(**overrides)`` 构造即可覆盖每个分支。

两条全局不变量：
1. 健康快照跑 run_all 必须全 ok（防止新检查误伤正常环境）；
2. 任何非 ok 结论必须有 fix_hint（只报告问题不给解法没有价值）。
"""

from __future__ import annotations

import pytest

from deploy import checks
from deploy.models import Snapshot

_LEVEL_ORDER = {"error": 0, "warn": 1, "ok": 2}


def _healthy_snapshot(**overrides) -> Snapshot:
    base = {
        "python_version": (3, 12, 0),
        "missing_packages": [],
        "env_exists": True,
        "deprecated_env_keys": [],
        "allowed_groups": [123456789],
        "db_cleanup_on_start": False,
        "onebot_mode": "reverse",
        "onebot_host": "0.0.0.0",
        "onebot_port": 8080,
        "onebot_port_in_use": False,
        "onebot_forward_reachable": None,
        "lm_reachable": True,
        "lm_error": "",
        "lm_models": ["google/gemma-4-e4b", "stella-chat", "stella-embed"],
        "lm_model_chat": "stella-chat",
        "lm_model_consolidation": "google/gemma-4-e4b",
        "lm_model_extract": "stella-chat",
        "lm_model_embedding": "stella-embed",
        "embedding_enabled": False,
        "db_exists": True,
        "db_path": "memory/agent_memory.db",
        "db_writable": True,
        "schema_version": 8,
        "code_schema_version": 8,
        "legacy_group_id_tables": [],
        "source_kind_counts": {"AT_MENTION": 1, "PASSIVE": 1, "BOT_SELF": 1},
        "space_conflicts": [],
        "space_assignment_mismatch": [],
        "persona_exists": True,
        "persona_size": 1024,
        "disk_free_mb": 8192.0,
    }
    base.update(overrides)
    return Snapshot(**base)


# ── 全局不变量 ──


def test_healthy_snapshot_is_all_ok():
    results = checks.run_all(_healthy_snapshot())
    assert all(r.level == "ok" for r in results)


@pytest.mark.parametrize(
    "overrides",
    [
        {"python_version": (3, 8, 0)},
        {"missing_packages": ["nonebot"]},
        {"env_exists": False},
        {"allowed_groups": []},
        {"onebot_mode": "unknown"},
        {"onebot_port_in_use": True},
        {"lm_reachable": False},
        {"lm_model_chat": "not-loaded"},
        {"db_writable": False},
        {"schema_version": 3, "code_schema_version": 8},
        {"source_kind_counts": {"": 5}},
        {"source_kind_counts": {"AT_MENTION": 0, "BOT_SELF": 5}},
        {"space_conflicts": [{"group_id": 1, "spaces": ["a", "b"]}]},
        {"persona_exists": False},
        {"disk_free_mb": 100.0},
        {"db_cleanup_on_start": True},
        {"deprecated_env_keys": ["NAPCAT_QQ_PASSWORD", "NAPCAT_SHELL_PATH"]},
        {"embedding_enabled": True, "lm_model_embedding": ""},
    ],
)
def test_all_non_ok_results_have_fix_hint(overrides: dict):
    results = checks.run_all(_healthy_snapshot(**overrides))
    assert results, "任何覆盖都应触发至少一条结论"
    for r in results:
        if r.level != "ok":
            assert r.fix_hint.strip(), f"{r.id} 的非 ok 结论缺少 fix_hint"


def test_run_all_sorts_error_warn_ok():
    snap = _healthy_snapshot(
        allowed_groups=[],
        deprecated_env_keys=["NAPCAT_SHELL_PATH"],
    )
    levels = [r.level for r in checks.run_all(snap)]
    assert levels == sorted(levels, key=lambda lv: _LEVEL_ORDER[lv])
    assert levels[0] == "error"


def test_run_all_flattens_multi_result_check():
    snap = _healthy_snapshot(
        deprecated_env_keys=["NAPCAT_QQ_PASSWORD", "NAPCAT_QQ_ACCOUNT"]
    )
    ids = {r.id for r in checks.run_all(snap)}
    assert "deprecated_env_keys" in ids
    assert "deprecated_env_secrets" in ids


# ── Python 与依赖 ──


def test_python_version_too_old():
    r = checks.check_python_version(_healthy_snapshot(python_version=(3, 9, 5)))
    assert r is not None and r.level == "error"


def test_python_310_missing_tomli():
    r = checks.check_python_version(
        _healthy_snapshot(python_version=(3, 10, 0), missing_packages=["tomli"])
    )
    assert r is not None and r.level == "error"


def test_python_version_ok():
    assert checks.check_python_version(_healthy_snapshot()) is None


def test_dependencies_missing():
    r = checks.check_dependencies(_healthy_snapshot(missing_packages=["nonebot"]))
    assert r is not None and r.level == "error"
    assert "nonebot" in r.detail


# ── 配置文件 ──


def test_env_file_missing():
    r = checks.check_env_file(_healthy_snapshot(env_exists=False))
    assert r is not None and r.level == "error"


def test_allowed_groups_empty():
    r = checks.check_allowed_groups(_healthy_snapshot(allowed_groups=[]))
    assert r is not None and r.level == "error"


# ── OneBot 连接 ──


def test_onebot_mode_unknown():
    r = checks.check_onebot_mode(_healthy_snapshot(onebot_mode="unknown"))
    assert r is not None and r.level == "error"


def test_onebot_reverse_port_busy_is_warn():
    r = checks.check_onebot_reverse_port(
        _healthy_snapshot(onebot_mode="reverse", onebot_port_in_use=True)
    )
    assert r is not None and r.level == "warn"


def test_onebot_reverse_port_free_ok():
    assert (
        checks.check_onebot_reverse_port(
            _healthy_snapshot(onebot_mode="reverse", onebot_port_in_use=False)
        )
        is None
    )


def test_onebot_reverse_port_probe_failed_is_warn():
    r = checks.check_onebot_reverse_port(
        _healthy_snapshot(onebot_mode="reverse", onebot_port_in_use=None)
    )
    assert r is not None and r.level == "warn"


def test_onebot_forward_unreachable_is_error():
    r = checks.check_onebot_forward(
        _healthy_snapshot(onebot_mode="forward", onebot_forward_reachable=False)
    )
    assert r is not None and r.level == "error"


def test_onebot_forward_ok():
    assert (
        checks.check_onebot_forward(
            _healthy_snapshot(onebot_mode="forward", onebot_forward_reachable=True)
        )
        is None
    )


# ── LM Studio ──


def test_lm_studio_unreachable_is_error():
    r = checks.check_lm_studio_reachable(
        _healthy_snapshot(lm_reachable=False, lm_error="Connection refused")
    )
    assert r is not None and r.level == "error"
    assert "Connection refused" in r.detail


def test_lm_studio_probe_failed_is_warn():
    r = checks.check_lm_studio_reachable(_healthy_snapshot(lm_reachable=None))
    assert r is not None and r.level == "warn"


def test_lm_model_chat_not_loaded_suggests():
    r = checks.check_lm_model_chat(
        _healthy_snapshot(lm_model_chat="gemma-4-e4b")
    )
    assert r is not None and r.level == "error"
    assert "你可能想写的是" in r.fix_hint


def test_lm_model_chat_empty_is_warn():
    r = checks.check_lm_model_chat(_healthy_snapshot(lm_model_chat=""))
    assert r is not None and r.level == "warn"


def test_lm_model_consolidation_not_loaded_is_error():
    r = checks.check_lm_model_consolidation(
        _healthy_snapshot(lm_model_consolidation="nope")
    )
    assert r is not None and r.level == "error"


def test_lm_model_extract_not_loaded_is_warn():
    r = checks.check_lm_model_extract(_healthy_snapshot(lm_model_extract="nope"))
    assert r is not None and r.level == "warn"


def test_lm_model_extract_empty_skipped():
    # 修 4b：提取模型为空不单独报——MEMORY_EXTRACT_LM_STUDIO_MODEL 默认继承
    # LM_STUDIO_MODEL，它为空只可能是聊天模型也为空（那已由 check_lm_model_chat
    # 报出），再报一条是把同一个根因说两遍。
    assert checks.check_lm_model_extract(_healthy_snapshot(lm_model_extract="")) is None


def test_lm_model_embedding_disabled_skipped():
    assert checks.check_lm_model_embedding(_healthy_snapshot()) is None


def test_lm_model_embedding_not_loaded_is_error():
    r = checks.check_lm_model_embedding(
        _healthy_snapshot(embedding_enabled=True, lm_model_embedding="nope")
    )
    assert r is not None and r.level == "error"


def test_suggest_model_close_match():
    assert checks._suggest_model("gemma-4-e4b", ["google/gemma-4-e4b"]).startswith(
        "你可能想写的是"
    )


# ── 数据库 ──


def test_db_missing_returns_none():
    # 修 3：首次安装时「数据库不存在」不是问题——首次启动会自动建库。
    # 保留空实现而非删除 check_database_exists：id 为 db_exists 的结果曾出现在
    # 输出里，GUI 侧可能已按它做过映射（见函数 docstring）。
    assert checks.check_database_exists(_healthy_snapshot(db_exists=False)) is None


def test_db_not_writable_is_error():
    r = checks.check_database_writable(_healthy_snapshot(db_writable=False))
    assert r is not None and r.level == "error"


def test_db_writable_unknown_is_warn():
    r = checks.check_database_writable(_healthy_snapshot(db_writable=None))
    assert r is not None and r.level == "warn"


def test_schema_lower_is_warn():
    r = checks.check_schema_version(
        _healthy_snapshot(schema_version=3, code_schema_version=8)
    )
    assert r is not None and r.level == "warn"


def test_schema_higher_is_error():
    r = checks.check_schema_version(
        _healthy_snapshot(schema_version=9, code_schema_version=8)
    )
    assert r is not None and r.level == "error"


def test_schema_matching_is_ok():
    assert checks.check_schema_version(_healthy_snapshot()) is None


def test_schema_unknown_is_warn():
    r = checks.check_schema_version(_healthy_snapshot(schema_version=None))
    assert r is not None and r.level == "warn"


def test_schema_version_skipped_when_db_missing():
    # 修 2：DB 还没建立时「版本未知」是必然的，不该再报一次——同一件事报两次
    # 会让首次配置的用户以为出了两个问题。
    assert checks.check_schema_version(_healthy_snapshot(db_exists=False)) is None


def test_all_empty_config_has_no_noise_ids():
    # 修 5（回归锚点）：首次 init 后「全空配置」场景——群号、三个模型 ID 全空、
    # DB 尚未建立。此时不该出现 schema_version / db_exists / lm_model_extract
    # 这三条噪音；而真正的根因（聊天模型为空、群号为空）必须仍然报出。
    snap = _healthy_snapshot(
        allowed_groups=[],
        lm_model_chat="",
        lm_model_consolidation="",
        lm_model_extract="",
        db_exists=False,
    )
    ids = {r.id for r in checks.run_all(snap)}
    assert "schema_version" not in ids
    assert "db_exists" not in ids
    assert "lm_model_extract" not in ids
    # 反向断言：根因必须还在，防止把该报的错误一起吞掉。
    assert "lm_model_chat" in ids
    assert "allowed_groups" in ids


def test_legacy_group_id_tables_is_error():
    r = checks.check_legacy_group_id_tables(
        _healthy_snapshot(legacy_group_id_tables=["memories"])
    )
    assert r is not None and r.level == "error"
    assert "v8 之前的旧结构" in r.title
    assert "agent_memory.db" in r.fix_hint


def test_source_kind_all_empty_is_error():
    r = checks.check_source_kind(_healthy_snapshot(source_kind_counts={"": 5}))
    assert r is not None and r.level == "error"


def test_source_kind_normal_ok():
    assert checks.check_source_kind(_healthy_snapshot()) is None


def test_at_mention_health_flagged():
    r = checks.check_at_mention_health(
        _healthy_snapshot(source_kind_counts={"BOT_SELF": 5, "AT_MENTION": 0})
    )
    assert r is not None and r.level == "warn"
    assert "AT_MENTION" in r.detail


def test_at_mention_health_ok():
    assert checks.check_at_mention_health(_healthy_snapshot()) is None


def test_at_mention_health_no_data():
    assert checks.check_at_mention_health(_healthy_snapshot(source_kind_counts={})) is None


# ── 群组空间 ──


def test_space_conflicts_is_error():
    r = checks.check_spaces_conflicts(
        _healthy_snapshot(space_conflicts=[{"group_id": 1, "spaces": ["a", "b"]}])
    )
    assert r is not None and r.level == "error"


def test_space_assignment_mismatch_is_warn():
    r = checks.check_space_assignment_mismatch(
        _healthy_snapshot(
            space_assignment_mismatch=[
                {"group_id": 1, "ledger": "space_1", "explicit": "alpha"}
            ]
        )
    )
    assert r is not None and r.level == "warn"


# ── 其它 ──


def test_persona_missing_is_warn():
    r = checks.check_persona_file(_healthy_snapshot(persona_exists=False))
    assert r is not None and r.level == "warn"


def test_persona_empty_is_warn():
    r = checks.check_persona_file(_healthy_snapshot(persona_size=0))
    assert r is not None and r.level == "warn"


def test_disk_low_is_error():
    r = checks.check_disk_space(_healthy_snapshot(disk_free_mb=100.0))
    assert r is not None and r.level == "error"


def test_disk_medium_is_warn():
    r = checks.check_disk_space(_healthy_snapshot(disk_free_mb=1000.0))
    assert r is not None and r.level == "warn"


def test_disk_unknown_is_warn():
    r = checks.check_disk_space(_healthy_snapshot(disk_free_mb=None))
    assert r is not None and r.level == "warn"


def test_db_cleanup_on_start_warn():
    r = checks.check_db_cleanup_on_start(
        _healthy_snapshot(db_cleanup_on_start=True, db_exists=True)
    )
    assert r is not None and r.level == "warn"


# ── 废弃环境变量 ──


def test_deprecated_env_single_secret_returns_both():
    r = checks.check_deprecated_env_keys(
        _healthy_snapshot(deprecated_env_keys=["NAPCAT_QQ_PASSWORD"])
    )
    assert isinstance(r, list) and len(r) == 2
    assert {x.id for x in r} == {"deprecated_env_keys", "deprecated_env_secrets"}


def test_deprecated_env_with_secret_returns_two():
    r = checks.check_deprecated_env_keys(
        _healthy_snapshot(
            deprecated_env_keys=["NAPCAT_QQ_PASSWORD", "NAPCAT_SHELL_PATH"]
        )
    )
    assert isinstance(r, list) and len(r) == 2
    assert {x.id for x in r} == {"deprecated_env_keys", "deprecated_env_secrets"}


def test_deprecated_env_plain_returns_one():
    r = checks.check_deprecated_env_keys(
        _healthy_snapshot(deprecated_env_keys=["NAPCAT_SHELL_PATH"])
    )
    assert isinstance(r, list) and len(r) == 1
    assert r[0].id == "deprecated_env_keys"


def test_deprecated_env_none():
    assert checks.check_deprecated_env_keys(_healthy_snapshot()) is None
