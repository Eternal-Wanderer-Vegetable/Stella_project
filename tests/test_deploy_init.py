# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""deploy init 向导的纯逻辑层测试（校验 + 渲染 + 应答文件往返）。

交互层（input / fetch_loaded_models）不测。渲染测试的重点是：逐行替换后
**模板注释必须原样保留**——防止将来有人改成从零拼接丢掉 OneBot 那段说明书。
"""

from __future__ import annotations

import json
from dataclasses import replace
from io import StringIO

from dotenv import dotenv_values

from deploy.init_wizard import (
    Answers,
    load_answers,
    render_env,
    save_answers,
    validate_answers,
)

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底
    import tomli as tomllib


def _valid_answers(**overrides) -> Answers:
    base = Answers(
        allowed_groups=[123456789],
        onebot_mode="reverse",
        host="127.0.0.1",
        port=8080,
        ws_urls=[],
        access_token="",
        lm_base_url="http://127.0.0.1:1234",
        chat_model="google/gemma-4-26b-a4b-qat",
        consolidation_model="google/gemma-4-e4b",
    )
    return replace(base, **overrides)


# ── validate_answers ──


def test_validate_all_ok_reverse():
    assert validate_answers(_valid_answers()) == []


def test_validate_all_ok_forward():
    a = _valid_answers(
        onebot_mode="forward",
        ws_urls=["ws://127.0.0.1:3001"],
        access_token="secret",
    )
    assert validate_answers(a) == []


def test_validate_groups_empty():
    problems = validate_answers(_valid_answers(allowed_groups=[]))
    assert problems and any("群号" in p for p in problems)


def test_validate_groups_non_positive():
    problems = validate_answers(_valid_answers(allowed_groups=[123, 0, -5]))
    assert problems and any("群号" in p for p in problems)


def test_validate_port_zero():
    problems = validate_answers(_valid_answers(port=0))
    assert problems and any("端口" in p for p in problems)


def test_validate_port_too_big():
    problems = validate_answers(_valid_answers(port=70000))
    assert problems and any("端口" in p for p in problems)


def test_validate_forward_ws_empty():
    problems = validate_answers(_valid_answers(onebot_mode="forward", ws_urls=[]))
    assert problems and any("WS 地址" in p for p in problems)


def test_validate_forward_http_url():
    problems = validate_answers(
        _valid_answers(onebot_mode="forward", ws_urls=["http://127.0.0.1:3001"])
    )
    assert problems and any("ws://" in p for p in problems)


def test_validate_models_empty():
    problems = validate_answers(_valid_answers(chat_model="", consolidation_model=""))
    assert problems and any("模型" in p for p in problems)


def test_validate_bad_mode():
    problems = validate_answers(_valid_answers(onebot_mode="sideways"))
    assert problems and any("连接方式" in p for p in problems)


def test_validate_bad_lm_base_url():
    problems = validate_answers(_valid_answers(lm_base_url="127.0.0.1:1234"))
    assert problems and any("http://" in p for p in problems)


# ── render_env ──


def test_render_replaces_uncommented_key():
    rendered = render_env(_valid_answers(port=9000), "HOST=127.0.0.1\nPORT=8080\n")
    assert "PORT=9000" in rendered
    assert "PORT=8080" not in rendered


def test_render_uncomments_and_replaces():
    template = '# ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]\nPORT=8080\n'
    a = _valid_answers(
        onebot_mode="forward",
        ws_urls=["ws://127.0.0.1:3001"],
    )
    rendered = render_env(a, template)
    assert 'ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]' in rendered
    assert "# ONEBOT_WS_URLS=" not in rendered


def test_render_reverse_keeps_forward_line_commented():
    template = '# ONEBOT_WS_URLS=["ws://127.0.0.1:3001"]\n'
    rendered = render_env(_valid_answers(), template)
    assert "# ONEBOT_WS_URLS=" in rendered


def test_render_appends_missing_key():
    a = _valid_answers(allowed_groups=[1, 2, 3])
    template = (
        "HOST=127.0.0.1\n"
        "PORT=8080\n"
        "LM_STUDIO_BASE_URL=http://127.0.0.1:1234\n"
        "LM_STUDIO_MODEL=x\n"
        "CONSOLIDATION_LM_STUDIO_MODEL=y\n"
        "ONEBOT_ACCESS_TOKEN=\n"
    )
    rendered = render_env(a, template)
    assert rendered.endswith("ALLOWED_GROUPS=1,2,3\n")
    assert "# 由 deploy init 追加" in rendered


def test_render_preserves_comments():
    # 最重要的一条：模板注释是给用户的说明书，逐行替换必须原样保留
    template = (
        "# NapCat 侧：网络配置 → 添加「WebSocket 客户端」，URL 填\n"
        "#   ws://<Bot 地址>:<PORT>/onebot/v11/ws\n"
        "PORT=8080\n"
    )
    rendered = render_env(_valid_answers(port=9000), template)
    assert "NapCat 侧：网络配置" in rendered
    assert "ws://<Bot 地址>:<PORT>/onebot/v11/ws" in rendered


def test_render_only_first_occurrence():
    template = "ALLOWED_GROUPS=111\n# ALLOWED_GROUPS=222\n"
    rendered = render_env(_valid_answers(allowed_groups=[1, 2, 3]), template)
    assert rendered.count("ALLOWED_GROUPS=1,2,3") == 1
    assert "# ALLOWED_GROUPS=222" in rendered


def test_render_parseable_by_dotenv():
    a = _valid_answers(
        allowed_groups=[1, 2, 3],
        port=9000,
        lm_base_url="http://127.0.0.1:1234",
        chat_model="google/gemma-4-26b-a4b-qat",
        consolidation_model="google/gemma-4-e4b",
        access_token="tok",
    )
    rendered = render_env(a, "ALLOWED_GROUPS=0\nPORT=8080\nLM_STUDIO_MODEL=\n")
    values = dotenv_values(stream=StringIO(rendered))
    assert values["ALLOWED_GROUPS"] == "1,2,3"
    assert values["PORT"] == "9000"
    assert values["LM_STUDIO_MODEL"] == "google/gemma-4-26b-a4b-qat"
    assert values["CONSOLIDATION_LM_STUDIO_MODEL"] == "google/gemma-4-e4b"
    assert values["ONEBOT_ACCESS_TOKEN"] == "tok"


def test_render_groups_format_no_spaces():
    rendered = render_env(_valid_answers(allowed_groups=[1, 2, 3]), "PORT=8080\n")
    assert "ALLOWED_GROUPS=1,2,3" in rendered


def test_render_forward_ws_urls_valid_json():
    a = _valid_answers(
        onebot_mode="forward",
        ws_urls=["ws://127.0.0.1:3001", "ws://127.0.0.1:3002"],
    )
    rendered = render_env(a, "PORT=8080\n")
    line = next(ln for ln in rendered.splitlines() if ln.startswith("ONEBOT_WS_URLS="))
    value = line.split("=", 1)[1]
    parsed = json.loads(value)
    assert parsed == ["ws://127.0.0.1:3001", "ws://127.0.0.1:3002"]


# ── 应答文件往返 ──


def test_answers_roundtrip(tmp_path):
    a = Answers(
        allowed_groups=[1, 2, 3],
        onebot_mode="forward",
        host="0.0.0.0",
        port=9000,
        ws_urls=["ws://127.0.0.1:3001"],
        access_token="tok-123",
        lm_base_url="http://127.0.0.1:1234",
        chat_model="google/gemma-4-26b-a4b-qat",
        consolidation_model="google/gemma-4-e4b",
    )
    path = tmp_path / "answers.toml"
    save_answers(a, path)
    assert load_answers(path) == a


def test_saved_toml_parses_with_tomllib(tmp_path):
    a = _valid_answers(allowed_groups=[1, 2, 3], access_token='tok"quote')
    path = tmp_path / "answers.toml"
    save_answers(a, path)
    with path.open("rb") as f:
        data = tomllib.load(f)
    assert data["allowed_groups"] == [1, 2, 3]
    assert data["access_token"] == 'tok"quote'
    assert data["onebot_mode"] == "reverse"
