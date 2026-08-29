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
        "status_api_reachable": False,
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


def test_total_checks_positive_and_consistent():
    # GUI 契约：summary.ok 由「总数 − 有问题的项数」推算（通过即 None、不产生
    # CheckResult，无法从结果列表反推分母），total 必须与 _ALL_CHECKS 一致。
    assert checks.total_checks() == len(checks._ALL_CHECKS)
    assert checks.total_checks() > 0


def test_report_summary_derives_ok_from_total():
    from deploy import report

    s = report._summarize(checks.run_all(_healthy_snapshot()))
    assert s["total"] == checks.total_checks()
    assert s["ok"] == checks.total_checks()  # 健康快照全部跳过 → 全部计为 ok
    assert s["error"] == 0 and s["warn"] == 0
    assert s["blocking"] is False


def test_to_json_gui_contract():
    import json

    from deploy import report

    snap = _healthy_snapshot(allowed_groups=[])
    doc = json.loads(report.to_json(checks.run_all(snap)))
    assert doc["version"] == 1
    assert isinstance(doc["items"], list)
    assert doc["summary"]["total"] == checks.total_checks()
    assert doc["summary"]["error"] >= 1
    assert doc["summary"]["blocking"] is True
    assert "llm" not in doc  # 不传 snapshot 时结构不变（老 GUI 不该看到多出来的键）


def _llm_snapshot(**overrides):
    return _healthy_snapshot(
        llm_endpoints={
            "LOCAL": {
                "slot": "LOCAL",
                "base_url": "http://127.0.0.1:1234",
                "kind": "local",
                "has_api_key": False,
                "concurrency": 1,
                "timeout": 120.0,
            },
            "ONLINE_CHAT": {
                "slot": "ONLINE_CHAT",
                "base_url": "https://api.example.com",
                "kind": "online",
                "has_api_key": True,
                "concurrency": 4,
                "timeout": 60.0,
            },
            "EXTRA": {"slot": "EXTRA", "base_url": "", "kind": "local"},
        },
        llm_roles={
            "chat": {
                "role": "chat",
                "slot": "ONLINE_CHAT",
                "model": "deepseek-chat",
                "gate": "ONLINE_CHAT",
                "kind": "online",
            },
            "extract": {
                "role": "extract",
                "slot": "LOCAL",
                "model": "stella-chat",
                "gate": "LOCAL",
                "kind": "local",
            },
        },
        llm_endpoint_reachable={"LOCAL": True, "ONLINE_CHAT": None},
        llm_endpoint_models={"LOCAL": ["stella-chat"]},
        llm_embedding_gate="LOCAL",
        **overrides,
    )


def test_to_json_llm_section_shows_effective_routing():
    """GUI 的模型服务面板照这段渲染：它必须是「当前生效的」而非 .env 的字面值。"""
    import json

    from deploy import report

    snap = _llm_snapshot()
    doc = json.loads(report.to_json(checks.run_all(snap), snap))
    assert doc["llm"]["roles"]["chat"]["slot"] == "ONLINE_CHAT"
    assert doc["llm"]["endpoints"]["ONLINE_CHAT"]["reachable"] is None
    assert doc["llm"]["endpoints"]["LOCAL"]["models"] == ["stella-chat"]
    assert "EXTRA" not in doc["llm"]["endpoints"]  # 没配地址的槽不列
    assert doc["llm"]["embedding_gate"] == "LOCAL"


def test_to_json_llm_section_never_carries_api_key_values():
    """端点段只搬 describe() 的输出，因此只有 has_api_key 布尔，没有 key 本身。

    doctor 的 --json 会被贴进 issue、被 GUI 存进日志，漏一次就是泄一次。
    """
    from deploy import report

    snap = _llm_snapshot()
    text = report.to_json(checks.run_all(snap), snap)
    assert "has_api_key" in text
    assert '"api_key"' not in text


def test_to_terminal_prints_role_to_endpoint_table():
    """「无缝切换」要能被信任，前提是用户能一眼看到请求实际走了谁。"""
    from deploy import report

    snap = _llm_snapshot()
    text = report.to_terminal(checks.run_all(snap), snap)
    assert "模型服务" in text
    assert "deepseek-chat" in text
    assert "ONLINE_CHAT" in text
    assert "未探测" in text  # reachable=None 要显式说明是「没探」，不是「不通」
    assert "恒定本地" in text


def test_to_terminal_without_snapshot_is_unchanged():
    from deploy import report

    results = checks.run_all(_healthy_snapshot(allowed_groups=[]))
    assert "模型服务" not in report.to_terminal(results)


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
        {"superseded_env_keys": ["LLM_SCHEDULER_GATE_EMBEDDING"]},
        {"llm_issues": [{"level": "error", "message": "端点 ONLINE_CHAT 没配 API_KEY"}]},
        {
            "llm_endpoints": {
                "ONLINE_CHAT": {"base_url": "https://api.example.com", "kind": "online"}
            },
            "llm_endpoint_reachable": {"ONLINE_CHAT": False},
            "llm_endpoint_error": {"ONLINE_CHAT": "timeout"},
        },
        {
            "llm_roles": {
                "chat": {"kind": "online", "slot": "ONLINE_CHAT", "model": "typo-model"}
            },
            "llm_endpoint_models": {"ONLINE_CHAT": ["real-model"]},
        },
        {
            "embedding_enabled": True,
            "embedding_base_url": "https://api.example.com",
            "llm_endpoints": {
                "ONLINE_CHAT": {"base_url": "https://api.example.com", "kind": "online"}
            },
        },
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
    assert "不是 Stella 自己" in r.detail


def test_onebot_reverse_port_busy_but_self_is_ok():
    """状态接口可达 = 端口是自己占的：这是运行中的正常状态，不报告。"""
    assert (
        checks.check_onebot_reverse_port(
            _healthy_snapshot(
                onebot_mode="reverse",
                onebot_port_in_use=True,
                status_api_reachable=True,
            )
        )
        is None
    )


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


def test_stella_home_reports_split_layout():
    """数据目录与程序分离时，doctor 要把两个目录都说清楚（用户得知道去哪备份）。"""
    r = checks.check_stella_home(
        _healthy_snapshot(
            stella_home="D:/StellaData",
            program_root="D:/Stella-3.1.0",
            stella_home_source="指针文件",
            home_pointer_exists=True,
        )
    )
    assert r is not None and r.level == "ok"
    assert "D:/StellaData" in r.detail and "D:/Stella-3.1.0" in r.detail


def test_stella_home_without_pointer_is_warn():
    """指针文件丢了 → 换一份新解压的程序就找不到数据，「升级一步走」失效。"""
    r = checks.check_stella_home(
        _healthy_snapshot(
            stella_home="D:/StellaData",
            program_root="D:/Stella-3.1.0",
            home_pointer_exists=False,
        )
    )
    assert r is not None and r.level == "warn"
    assert "deploy" in r.fix_hint


def test_stella_home_legacy_layout_is_ok():
    """旧布局（数据在安装目录内）不是问题，但要提示升级时用 migrate 带过去。"""
    r = checks.check_stella_home(
        _healthy_snapshot(stella_home="D:/Stella", program_root="D:/Stella")
    )
    assert r is not None and r.level == "ok"
    assert "deploy migrate" in r.detail


def test_stella_home_portable_mode_is_ok_but_warns_about_the_cost():
    """便携模式（数据在程序目录内）是合法选择，但代价必须说清楚。

    程序目录是升级时被整体替换、也会被用户当「旧版本」删掉的那个——不提醒，
    这个布局迟早会吃掉某个用户的全部记忆。
    """
    r = checks.check_stella_home(
        _healthy_snapshot(
            stella_home="D:/Stella-3.1.0/StellaData",
            program_root="D:/Stella-3.1.0",
            stella_home_source="便携模式：安装目录内的 StellaData",
            home_pointer_exists=False,
        )
    )
    assert r is not None and r.level == "ok"
    assert "便携" in r.title
    # 缺指针在便携模式下是正常的，不该被报成「找不到数据」那条警告
    assert "指针" not in r.detail
    assert "migrate" in r.fix_hint


def test_version_marks_downgrade_is_warn():
    """旧代码打开新版本写过的库：schema 更高、列更多，报错方式毫无提示性，必须先说破。"""
    r = checks.check_version_marks(
        _healthy_snapshot(
            program_version="3.0.0",
            last_run_version="3.1.0",
            version_transition="downgrade",
        )
    )
    assert r is not None and r.level == "warn"
    assert "3.1.0" in r.detail and r.fix_hint


def test_version_marks_first_run_points_to_migrate():
    """新数据目录 + 用户其实是升上来的 = 老记忆还在旧目录，这时该去跑 migrate。"""
    r = checks.check_version_marks(
        _healthy_snapshot(program_version="3.1.0", version_transition="first-run")
    )
    assert r is not None and r.level == "ok"
    assert "deploy migrate" in r.fix_hint


def test_version_marks_upgrade_is_reported():
    r = checks.check_version_marks(
        _healthy_snapshot(
            program_version="3.1.0",
            last_run_version="3.0.0",
            version_transition="upgrade",
        )
    )
    assert r is not None and r.level == "ok"
    assert "3.0.0" in r.title and "3.1.0" in r.title


def test_version_marks_read_error_is_warn():
    """标记读不出来不影响运行，但升级判定失效——降级为 warn 并给出重建方法。"""
    r = checks.check_version_marks(_healthy_snapshot(state_file_error="JSON 解析失败"))
    assert r is not None and r.level == "warn"
    assert r.fix_hint


def test_version_marks_absent_when_version_unknown():
    """读不到 pyproject.toml 版本号时不产生结论，而不是报一条「未知」噪音。"""
    assert checks.check_version_marks(_healthy_snapshot()) is None


def test_legacy_group_id_tables_is_warn_and_points_to_migrate():
    """旧结构不再是「丢记忆」的死路：降级为 warn，并给出可执行的迁移命令。"""
    r = checks.check_legacy_group_id_tables(
        _healthy_snapshot(legacy_group_id_tables=["memories"])
    )
    assert r is not None and r.level == "warn"
    assert "自动迁移" in r.title
    assert "deploy migrate" in r.fix_hint
    # 绝不能再出现「把库移走让程序重建」这类等于丢记忆的建议
    assert "移出" not in r.fix_hint and "重建新库" not in r.fix_hint


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


# ── LLM 端点与角色 ──


def test_superseded_env_keys_names_the_replacement():
    """只说「这个键过时了」没用——用户需要知道改成哪个键。"""
    r = checks.check_superseded_env_keys(
        _healthy_snapshot(superseded_env_keys=["LLM_SCHEDULER_GATE_EMBEDDING"])
    )
    assert r is not None and r.level == "warn"
    assert "MEMORY_EMBEDDING_GATE" in r.detail
    assert "migrate" in r.fix_hint


def test_superseded_env_keys_none_when_clean():
    assert checks.check_superseded_env_keys(_healthy_snapshot()) is None


def test_llm_config_issues_are_grouped_by_level():
    """registry 的问题按级别各合成一条：一次写错常冒出好几条，逐条列会淹没别的检查。"""
    r = checks.check_llm_config_issues(
        _healthy_snapshot(
            llm_issues=[
                {"level": "error", "message": "端点 ONLINE_CHAT 是 online 但没配 API_KEY"},
                {"level": "error", "message": "角色 chat 用的是在线端点，但没配 MODEL"},
                {"level": "warn", "message": "端点 LOCAL 是本地服务但并发上限 4>1"},
            ]
        )
    )
    assert isinstance(r, list) and len(r) == 2
    by_id = {x.id: x for x in r}
    assert by_id["llm_config"].level == "error"
    assert "API_KEY" in by_id["llm_config"].detail
    assert "MODEL" in by_id["llm_config"].detail  # 同级别的多条合进一条 detail
    assert by_id["llm_config_warn"].level == "warn"


def test_llm_config_issues_none_when_clean():
    assert checks.check_llm_config_issues(_healthy_snapshot()) is None


def _endpoint_snapshot(kind: str, reachable: bool | None, **extra):
    return _healthy_snapshot(
        llm_endpoints={"ONLINE_CHAT": {"base_url": "https://api.example.com", "kind": kind}},
        llm_endpoint_reachable={"ONLINE_CHAT": reachable},
        llm_endpoint_error={"ONLINE_CHAT": "Connection refused"},
        **extra,
    )


def test_llm_endpoint_online_unreachable_is_only_warn():
    """在线端点探不到只能是 warn：/v1/models 是可选接口，不少服务商压根不开放。"""
    r = checks.check_llm_endpoint_reachable(_endpoint_snapshot("online", False))
    assert isinstance(r, list) and len(r) == 1
    assert r[0].id == "llm_endpoint_online_chat"
    assert r[0].level == "warn"
    assert "Connection refused" in r[0].detail


def test_llm_endpoint_local_unreachable_is_error():
    """本地端点探不到就是真的没起来——地址是自己机器上的，不存在「不开放」这回事。"""
    r = checks.check_llm_endpoint_reachable(_endpoint_snapshot("local", False))
    assert isinstance(r, list) and r[0].level == "error"


def test_llm_endpoint_unprobed_is_not_reported():
    """None = 没探（槽未配置或探测本身异常），不能当成「不通」报出来。"""
    assert checks.check_llm_endpoint_reachable(_endpoint_snapshot("online", None)) is None
    assert checks.check_llm_endpoint_reachable(_endpoint_snapshot("online", True)) is None


def test_llm_endpoint_sharing_lm_studio_address_is_not_reported_twice():
    """与 LM Studio 同地址的槽由 check_lm_studio_reachable 报——同一个服务没起来，
    说两遍会让用户以为有两个问题。"""
    snap = _healthy_snapshot(
        lm_base_url="http://127.0.0.1:1234",
        llm_endpoints={"LOCAL": {"base_url": "http://127.0.0.1:1234/", "kind": "local"}},
        llm_endpoint_reachable={"LOCAL": False},
    )
    assert checks.check_llm_endpoint_reachable(snap) is None


def _role_snapshot(model: str, listed: list[str], **extra):
    return _healthy_snapshot(
        llm_roles={"chat": {"kind": "online", "slot": "ONLINE_CHAT", "model": model}},
        llm_endpoint_models={"ONLINE_CHAT": listed},
        **extra,
    )


def test_llm_role_model_not_listed_is_warn_with_suggestion():
    r = checks.check_llm_role_model(_role_snapshot("deepseek-chatt", ["deepseek-chat"]))
    assert isinstance(r, list) and len(r) == 1
    assert r[0].id == "llm_role_model_chat"
    assert r[0].level == "warn"  # 服务商未必列全模型，判 error 会误伤能用的配置
    assert "deepseek-chat" in r[0].detail


def test_llm_role_model_ok_when_listed():
    assert checks.check_llm_role_model(_role_snapshot("deepseek-chat", ["deepseek-chat"])) is None


def test_llm_role_model_skipped_when_endpoint_lists_nothing():
    """拿不到模型列表时无从比对——空列表不等于「一个模型都没有」。"""
    assert checks.check_llm_role_model(_role_snapshot("deepseek-chat", [])) is None


def test_llm_role_model_empty_is_left_to_registry():
    """模型 ID 为空已由 registry.validate() 记成 error，这里再报一条是同一根因说两遍。"""
    assert checks.check_llm_role_model(_role_snapshot("", ["deepseek-chat"])) is None


def test_llm_role_model_ignores_local_roles():
    """本地角色的模型由 check_lm_model_* 那三条负责（它们读的是 LM Studio 已加载列表）。"""
    snap = _healthy_snapshot(
        llm_roles={"chat": {"kind": "local", "slot": "LOCAL", "model": "whatever"}},
        llm_endpoint_models={"LOCAL": ["stella-chat"]},
    )
    assert checks.check_llm_role_model(snap) is None


@pytest.mark.parametrize(
    ("role", "check_name", "overrides"),
    [
        ("chat", "check_lm_model_chat", {"lm_model_chat": "not-loaded"}),
        (
            "consolidation",
            "check_lm_model_consolidation",
            {"lm_model_consolidation": "not-loaded"},
        ),
        ("extract", "check_lm_model_extract", {"lm_model_extract": "not-loaded"}),
    ],
)
def test_legacy_lm_model_check_skipped_when_role_moved_online(role, check_name, overrides):
    """角色切到在线后，LM_STUDIO_MODEL 那一族键的值已经不被使用。

    还拿「LM Studio 里没加载这个模型」去报错就是纯噪音——真正该看的是在线端点
    那边的模型 ID，由 check_llm_role_model 负责。
    """
    check = getattr(checks, check_name)
    assert check(_healthy_snapshot(**overrides)) is not None  # 本地时照旧报
    online = _healthy_snapshot(
        llm_roles={role: {"kind": "online", "slot": "ONLINE_CHAT", "model": "x"}},
        **overrides,
    )
    assert check(online) is None


def test_embedding_locality_online_endpoint_is_warn():
    """R2：embedding 恒定本地。指到在线端点时每次语义检索都会把提问原文发出去。"""
    r = checks.check_embedding_locality(
        _healthy_snapshot(
            embedding_enabled=True,
            embedding_base_url="https://api.example.com/",
            llm_endpoints={
                "ONLINE_MEMORY": {"base_url": "https://api.example.com", "kind": "online"}
            },
        )
    )
    assert r is not None and r.level == "warn"
    assert "ONLINE_MEMORY" in r.detail


def test_embedding_locality_local_address_is_ok():
    snap = _healthy_snapshot(
        embedding_enabled=True,
        embedding_base_url="http://127.0.0.1:1234",
        llm_endpoints={
            "LOCAL": {"base_url": "http://127.0.0.1:1234", "kind": "local"},
            "ONLINE_CHAT": {"base_url": "https://api.example.com", "kind": "online"},
        },
    )
    assert checks.check_embedding_locality(snap) is None


def test_embedding_locality_skipped_when_disabled():
    snap = _healthy_snapshot(
        embedding_base_url="https://api.example.com",
        llm_endpoints={
            "ONLINE_CHAT": {"base_url": "https://api.example.com", "kind": "online"}
        },
    )
    assert checks.check_embedding_locality(snap) is None


def test_embedding_model_check_skipped_when_pointing_elsewhere():
    """已加载列表来自 LM_STUDIO_BASE_URL；embedding 在另一个实例上时无从比对。"""
    snap = _healthy_snapshot(
        embedding_enabled=True,
        lm_base_url="http://127.0.0.1:1234",
        embedding_base_url="http://127.0.0.1:5678",
        lm_model_embedding="bge-m3",  # 不在 lm_models 里，但那是另一台实例的事
    )
    assert checks.check_lm_model_embedding(snap) is None
