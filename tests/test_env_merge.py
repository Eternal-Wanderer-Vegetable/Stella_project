# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""``.env`` 合并器的单元测试（deploy/env_merge.py）。

四类键各有一条：沿用、走默认值、废弃移除、无法识别。另外两条硬要求：
模板注释必须留住（那是给用户的说明书），敏感值绝不出现在报告里。
"""

from __future__ import annotations

from deploy import env_merge

TEMPLATE = """\
# ---------- OneBot 连接 ----------
# 反向 WS：在 NapCat 里添加「WebSocket 客户端」，地址 ws://HOST:PORT/onebot/v11/ws
HOST=127.0.0.1
PORT=8080
# 正向 WS（与上面二选一）
# ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]
ONEBOT_ACCESS_TOKEN=

# ---------- 模型 ----------
LM_STUDIO_MODEL=
# 主动发言的冷却秒数
# PROACTIVE_COOLDOWN=600
# 本版新增的开关
NEW_FEATURE_ENABLED=false
"""

OLD_ENV = """\
# 我自己加的注释
HOST=0.0.0.0
PORT=9000
ONEBOT_ACCESS_TOKEN=s3cr3t-token
LM_STUDIO_MODEL=google/gemma-4-26b
PROACTIVE_COOLDOWN=1200
NAPCAT_QQ_ACCOUNT=10001
NAPCAT_WATCHDOG_INTERVAL=30
MY_OWN_HACK=1
"""


def _merge(**kwargs):
    return env_merge.merge_env(OLD_ENV, TEMPLATE, **kwargs)


def test_user_values_are_carried_over():
    """旧值逐项沿用，包括模板里被注释掉的键（要取消注释并填值）。"""
    rendered, report = _merge()
    values = env_merge.parse_env(rendered)

    assert values["HOST"] == "0.0.0.0"
    assert values["PORT"] == "9000"
    assert values["LM_STUDIO_MODEL"] == "google/gemma-4-26b"
    # 模板里是 `# PROACTIVE_COOLDOWN=600`，用户设过 → 必须取消注释并用用户值
    assert values["PROACTIVE_COOLDOWN"] == "1200"
    assert {"HOST", "PORT", "PROACTIVE_COOLDOWN"} <= set(report.kept)


def test_template_comments_survive():
    """模板注释是给用户的说明书，合并后必须一字不少。"""
    rendered, _ = _merge()
    assert "# ---------- OneBot 连接 ----------" in rendered
    assert "在 NapCat 里添加「WebSocket 客户端」" in rendered
    assert "# 正向 WS（与上面二选一）" in rendered


def test_new_keys_stay_at_template_default():
    """新版新增的键保持模板默认值，并在报告里列为「走默认值」。"""
    rendered, report = _merge()
    values = env_merge.parse_env(rendered)

    assert values["NEW_FEATURE_ENABLED"] == "false"
    assert "NEW_FEATURE_ENABLED" in report.missing


def test_deprecated_keys_removed_with_reason():
    """废弃键主动移除并说明原因——留着一行不生效的配置比删掉更坏。"""
    rendered, report = _merge()
    values = env_merge.parse_env(rendered)

    assert "NAPCAT_QQ_ACCOUNT" not in values
    assert "NAPCAT_WATCHDOG_INTERVAL" not in values  # 前缀匹配也要抓到
    removed = dict(report.removed)
    assert "NAPCAT_QQ_ACCOUNT" in removed
    assert "NapCat" in removed["NAPCAT_QQ_ACCOUNT"]
    assert "NAPCAT_WATCHDOG_INTERVAL" in removed


def test_unknown_keys_kept_at_end():
    """谁都不认识的键保留在末尾并标注——删掉别人手工加的东西比留着更糟。"""
    rendered, report = _merge()
    values = env_merge.parse_env(rendered)

    assert values["MY_OWN_HACK"] == "1"
    assert report.unknown == ["MY_OWN_HACK"]
    assert "无法识别" in rendered


def test_key_known_to_code_but_missing_from_template_is_appended():
    """模板漏了、但 settings.py 仍在读的键要追加回去，否则用户的配置静默失效。"""
    rendered, report = _merge(schema_keys={"MY_OWN_HACK"})
    values = env_merge.parse_env(rendered)

    assert values["MY_OWN_HACK"] == "1"
    assert report.unknown == []
    assert report.appended == ["MY_OWN_HACK"]
    assert "MY_OWN_HACK" in report.kept


def test_report_never_prints_secret_values():
    """敏感项只说「已沿用」，值绝不进报告——报告会被贴进 issue。"""
    _, report = _merge()
    markdown = report.to_markdown()

    assert "s3cr3t-token" not in markdown
    assert "ONEBOT_ACCESS_TOKEN" in markdown
    assert "敏感项已沿用" in markdown


SUPERSEDED_TEMPLATE = """\
# ---------- 记忆语义检索 ----------
# MEMORY_EMBEDDING_GATE=auto

# ---------- 向导会问的项 ----------
LM_STUDIO_MODEL=
"""


def test_superseded_key_value_is_converted_not_dropped():
    """被新键取代的旧键要**换算**再移除；只删不换等于把用户的选择改回默认值。

    ``LLM_SCHEDULER_GATE_EMBEDDING=false`` 的用户是主动关掉排队的，
    换算成 ``MEMORY_EMBEDDING_GATE=none`` 才逐字等价；若丢掉这一行，
    新键会走默认的 ``auto``、排队悄悄被打开。
    """
    rendered, report = env_merge.merge_env(
        "LLM_SCHEDULER_GATE_EMBEDDING=false\n", SUPERSEDED_TEMPLATE
    )
    values = env_merge.parse_env(rendered)

    assert "LLM_SCHEDULER_GATE_EMBEDDING" not in values
    assert values["MEMORY_EMBEDDING_GATE"] == "none"
    assert report.migrated == [
        ("LLM_SCHEDULER_GATE_EMBEDDING", "MEMORY_EMBEDDING_GATE", "none")
    ]
    assert "已换算到新键" in report.to_markdown()


def test_superseded_true_maps_to_auto():
    """``true`` → ``auto`` 而不是 ``LOCAL``：旧键的前提「embedding 与主聊天同实例」
    在对话可以切在线之后不再成立，auto 才是与端点无关的等价表达。"""
    rendered, _ = env_merge.merge_env(
        "LLM_SCHEDULER_GATE_EMBEDDING=true\n", SUPERSEDED_TEMPLATE
    )
    assert env_merge.parse_env(rendered)["MEMORY_EMBEDDING_GATE"] == "auto"


def test_explicit_new_key_beats_converted_old_value_in_both_orders():
    """用户同时写了新旧两个键时，显式写的新键赢——且不许依赖两行的先后顺序。

    换算值若用「先到先得」实现，旧键在前时就会覆盖用户显式设的新键。
    """
    for old_env in (
        "LLM_SCHEDULER_GATE_EMBEDDING=true\nMEMORY_EMBEDDING_GATE=LOCAL\n",
        "MEMORY_EMBEDDING_GATE=LOCAL\nLLM_SCHEDULER_GATE_EMBEDDING=true\n",
    ):
        rendered, report = env_merge.merge_env(old_env, SUPERSEDED_TEMPLATE)
        values = env_merge.parse_env(rendered)
        assert values["MEMORY_EMBEDDING_GATE"] == "LOCAL", old_env
        assert "LLM_SCHEDULER_GATE_EMBEDDING" not in values
        assert report.migrated == []
        assert dict(report.removed)["LLM_SCHEDULER_GATE_EMBEDDING"]


def test_superseded_migration_is_idempotent():
    """合并结果再合并一次不该继续变化——升级路径要能重复走。"""
    first, _ = env_merge.merge_env(
        "LLM_SCHEDULER_GATE_EMBEDDING=false\n", SUPERSEDED_TEMPLATE
    )
    second, report = env_merge.merge_env(first, SUPERSEDED_TEMPLATE)

    assert env_merge.parse_env(second)["MEMORY_EMBEDDING_GATE"] == "none"
    assert report.migrated == []


def test_superseded_key_is_absent_from_gui_schema():
    """旧键代码还在读，但界面上只该出现新键：同一件事摆两个控件，
    用户改了旧的、新的又优先，那就成了「改了没反应」。"""
    from config import PROJECT_ROOT
    from deploy.env_schema import build_schema

    keys = {
        f["key"]
        for f in build_schema(PROJECT_ROOT / "config" / "settings.py")["fields"]
    }
    assert "LLM_SCHEDULER_GATE_EMBEDDING" not in keys
    assert "MEMORY_EMBEDDING_GATE" in keys


def test_missing_old_file_falls_back_to_template(tmp_path):
    """旧文件不存在时等价于「直接用模板」，不该抛异常。"""
    template = tmp_path / ".env.example"
    template.write_text(TEMPLATE, encoding="utf-8")

    rendered, report = env_merge.merge_env_files(tmp_path / ".env", template)

    assert report.kept == []
    assert env_merge.parse_env(rendered)["HOST"] == "127.0.0.1"


def test_real_env_example_round_trips():
    """拿仓库真实的 .env.example 跑一遍：不能因为某个键的写法而炸。"""
    from config import PROJECT_ROOT

    template = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    old = "ALLOWED_GROUPS=123456\nLM_STUDIO_MODEL=demo/model\n"

    rendered, report = env_merge.merge_env(old, template)
    values = env_merge.parse_env(rendered)

    assert values["ALLOWED_GROUPS"] == "123456"
    assert values["LM_STUDIO_MODEL"] == "demo/model"
    assert report.unknown == []


def test_real_env_example_carries_the_new_keys():
    """模板是合并器的骨架：新键不在模板里，换算值只能追加到文件末尾——
    功能上还生效，但它会脱离所属章节的说明文字，用户看不懂那一行是干什么的。

    这里顺带守住 P1 端点/角色键进模板：``deploy init`` 生成的 ``.env`` 若没有
    这些行，用户就只能靠翻文档才知道有这些开关。
    """
    from config import PROJECT_ROOT

    template = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    keys = env_merge.template_keys(template)

    assert "MEMORY_EMBEDDING_GATE" in keys
    assert "LLM_SCHEDULER_GATE_EMBEDDING" not in keys, "旧键不该再出现在模板里"
    for slot in ("LOCAL", "ONLINE_CHAT", "ONLINE_MEMORY", "EXTRA"):
        for suffix in ("BASE_URL", "API_KEY", "KIND", "CONCURRENCY", "TIMEOUT"):
            assert f"LLM_ENDPOINT_{slot}_{suffix}" in keys
    for role in ("CHAT", "ROUTER", "PLUGIN", "COMPACT", "CONSOLIDATION", "EXTRACT"):
        for suffix in (
            "ENDPOINT",
            "MODEL",
            "TEMPERATURE",
            "MAX_TOKENS",
            "FALLBACK_ENDPOINT",
        ):
            assert f"LLM_ROLE_{role}_{suffix}" in keys


def test_real_env_example_migrates_the_superseded_gate_key_in_place():
    """真实模板下换算值必须**替换模板那一行**，而不是落到末尾的追加块。"""
    from config import PROJECT_ROOT

    template = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    rendered, report = env_merge.merge_env(
        "LLM_SCHEDULER_GATE_EMBEDDING=false\n", template
    )

    assert env_merge.parse_env(rendered)["MEMORY_EMBEDDING_GATE"] == "none"
    assert report.appended == []
    assert report.unknown == []

