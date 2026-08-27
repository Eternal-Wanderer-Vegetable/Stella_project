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

