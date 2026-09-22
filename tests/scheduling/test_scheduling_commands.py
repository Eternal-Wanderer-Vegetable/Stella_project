# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""任务指令解析器的基线（形状正确性 + 与既有命令词表的机械不冲突）。"""

from __future__ import annotations

from stella_project.plugins.bot_main.scheduling.commands import (
    parse_scheduling_command,
)


def test_bare_prefix_is_help():
    cmd = parse_scheduling_command("定时")
    assert cmd is not None and cmd.action == "help"
    assert parse_scheduling_command("定时帮助").action == "help"


def test_add_parses_cron_timezone_and_text():
    cmd = parse_scheduling_command(
        "定时添加 0 9 * * MON-FRI Asia/Shanghai 站会提醒 别迟到"
    )
    assert cmd is not None
    assert cmd.action == "add"
    assert cmd.cron_expr == "0 9 * * MON-FRI"
    assert cmd.timezone == "Asia/Shanghai"
    assert cmd.objective == "站会提醒 别迟到"
    assert "malformed" not in cmd.fields


def test_add_collapses_extra_whitespace():
    cmd = parse_scheduling_command("定时添加  0  9  *  *  MON   Asia/Shanghai   喝水")
    assert cmd is not None
    assert cmd.cron_expr == "0 9 * * MON"
    assert cmd.objective == "喝水"


def test_add_missing_arguments_is_malformed_not_none():
    """参数不齐仍算指令（回格式帮助），不能落回普通聊天。"""
    cmd = parse_scheduling_command("定时添加 0 9 * * MON 提醒")
    assert cmd is not None
    assert cmd.action == "add"
    assert cmd.fields.get("malformed") is True


def test_agent_create_verb():
    cmd = parse_scheduling_command("定时智能 0 6 * * * UTC+8 总结昨天的群聊")
    assert cmd is not None
    assert cmd.action == "add_agent"
    assert cmd.cron_expr == "0 6 * * *"
    assert cmd.timezone == "UTC+8"
    assert cmd.objective == "总结昨天的群聊"


def test_simple_id_commands():
    for verb, action in [
        ("详情", "show"),
        ("暂停", "pause"),
        ("停用", "pause"),
        ("启用", "resume"),
        ("取消", "cancel"),
        ("立即", "run_now"),
        ("历史", "history"),
    ]:
        cmd = parse_scheduling_command(f"定时{verb} abc123")
        assert cmd is not None and cmd.action == action
        assert cmd.task_id == "abc123"


def test_tool_allowlist_commands_split_id_and_tool():
    cmd = parse_scheduling_command("定时允许 abc123 mcp_fs_read_file")
    assert cmd is not None
    assert cmd.action == "allow_tool"
    assert cmd.task_id == "abc123"
    assert cmd.tool_name == "mcp_fs_read_file"
    cmd = parse_scheduling_command("定时禁止 abc123 mcp_fs_read_file")
    assert cmd is not None and cmd.action == "deny_tool"


def test_edit_parses_kv_with_spaces_in_values():
    cmd = parse_scheduling_command(
        "定时编辑 abc12 cron=30 8 * * * tz=UTC+8 text=新文案 记得加句号 notify=always rev=3"
    )
    assert cmd is not None
    assert cmd.action == "edit"
    assert cmd.task_id == "abc12"
    assert cmd.fields["cron"] == "30 8 * * *"
    assert cmd.fields["tz"] == "UTC+8"
    assert cmd.fields["text"] == "新文案 记得加句号"
    assert cmd.fields["notify"] == "always"
    assert cmd.expected_revision == 3


def test_edit_without_known_keys_is_malformed():
    cmd = parse_scheduling_command("定时编辑 abc12 随便说说")
    assert cmd is not None
    assert cmd.fields.get("malformed") is True


def test_non_commands_return_none():
    """既不是任务指令、也不能误伤日常聊天与既有命令。"""
    for text in [
        "",
        "定时任务什么时候上线",   # 未命中动词 → 落回聊天
        "定时器",                 # 未命中动词
        "安静",
        "恢复一下",
        "你能做什么",
        "把称呼改成队长",
        "今天天气怎么样",
    ]:
        assert parse_scheduling_command(text) is None, text


def test_help_text_lists_verbs():
    from stella_project.plugins.bot_main.scheduling.commands import format_help

    help_text = format_help()
    for verb in ("定时添加", "定时智能", "定时列表", "定时编辑", "定时暂停", "定时立即"):
        assert verb in help_text
