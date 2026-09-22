# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""群内任务指令的解析（纯函数，无 NoneBot 依赖）。

v1 指令面（全部以「定时」开头，@Bot 后发送）::

    定时帮助                              —— 指令清单
    定时添加 <cron5> <时区> <提醒内容>      —— reminder（成员可用）
    定时智能 <cron5> <时区> <目标>          —— agent 任务（管理员）
    定时列表                              —— 本群任务
    定时详情 <任务id前缀>
    定时编辑 <id> [cron=...] [tz=...] [text=...] [notify=always|on_content] [rev=N]
    定时暂停 / 定时启用 / 定时取消 <id>
    定时立即 <id>                          —— run-now
    定时历史 <id>
    定时允许 / 定时禁止 <id> <工具名>       —— agent 工具允许清单（管理员）

设计约束：

- **机械可判别**：任何 ``parse_scheduling_command`` 返回非 None 的文本，都会被
  ai_gateway 的既有 priority=1 分类器（开关/称呼/能力查询）显式让路（计划 §6.3
  的 mutually-exclusive guards）。动词刻意避开开关关键词（用「启用/停用」
  而不是「恢复/停止」）；
- 解析只做形状，不做语义校验：cron/时区/权限全部交给 :mod:`.service`，
  错误信息由 service 的用户可读异常承载；
- ``edit`` 的 kv 值允许含空格（cron 的 5 个字段、text 的自由文本），按「下一个
  已知键」切片。

本层返回结构是**权限无关**的：谁是管理员、在哪个群，由 QQ 边界（ai_gateway）
注入 service，不在这里猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 触发前缀。以它开头且命中动词表才算任务指令；「定时xxx」的其余文本落回普通聊天。
PREFIX = "定时"

# 已知动词 → action。启用/停用 刻意替代 恢复/停止：后者是主动发言开关的关键词，
# 子串命中会让一句话同时撞上两个 priority=1 的 handler（2026-09 之前的互斥教训）。
_ACTIONS = {
    "帮助": "help",
    "添加": "add",
    "智能": "add_agent",
    "列表": "list",
    "详情": "show",
    "编辑": "edit",
    "暂停": "pause",
    "停用": "pause",
    "启用": "resume",
    "取消": "cancel",
    "立即": "run_now",
    "历史": "history",
    "允许": "allow_tool",
    "禁止": "deny_tool",
}

# edit 支持的键（值可含空格，按「下一个已知键」切片）
_EDIT_KEYS = ("cron", "tz", "text", "notify", "rev")
_EDIT_KEY_RE = re.compile(r"\b(" + "|".join(_EDIT_KEYS) + r")=")

# cron5 + 时区 + 自由文本 的最小 token 数（cron 5 + tz 1 + text 1）
_CREATE_MIN_TOKENS = 7


@dataclass(slots=True)
class SchedulingCommand:
    """解析后的任务指令。语义校验交给 :mod:`.service`。"""

    action: str
    raw_text: str
    task_id: str = ""
    cron_expr: str = ""
    timezone: str = ""
    objective: str = ""
    tool_name: str = ""
    fields: dict = field(default_factory=dict)
    expected_revision: int | None = None


def is_scheduling_command(text: str) -> bool:
    """廉价判别：文本是否是任务指令（ai_gateway 各分类器的让路判据）。

    与 :func:`parse_scheduling_command` 的判据刻意保持「同源单点」：这里 True
    当且仅当 parse 非 None，避免两处词表漂移。
    """
    return parse_scheduling_command(text) is not None


def parse_scheduling_command(text: str) -> SchedulingCommand | None:
    """解析任务指令；不是任务指令返回 None（调用方落回既有分类器/聊天）。"""
    stripped = (text or "").strip()
    if not stripped.startswith(PREFIX):
        return None
    body = stripped[len(PREFIX):].lstrip()
    if not body:
        # 裸「定时」当帮助入口
        return SchedulingCommand(action="help", raw_text=stripped)
    verb, _, rest = body.partition(" ")
    rest = rest.strip()
    action = _ACTIONS.get(verb)
    if action is None:
        return None
    cmd = SchedulingCommand(action=action, raw_text=stripped)
    if action == "help" or action == "list":
        return cmd
    if action in ("add", "add_agent"):
        return _parse_create(cmd, rest)
    if action in ("show", "pause", "resume", "cancel", "run_now", "history"):
        cmd.task_id = rest.split()[0] if rest.split() else ""
        return cmd
    if action in ("allow_tool", "deny_tool"):
        parts = rest.split()
        if len(parts) >= 2:
            cmd.task_id, cmd.tool_name = parts[0], parts[1]
        elif len(parts) == 1:
            cmd.task_id = parts[0]
        return cmd
    if action == "edit":
        return _parse_edit(cmd, rest)
    return cmd


def _parse_create(cmd: SchedulingCommand, rest: str) -> SchedulingCommand | None:
    """``<cron5> <时区> <内容>``：内容可含空格，cron 严格 5 段。

    先把连续空白归一成单空格（聊天输入常见双空格），再按位置切片。
    """
    rest = " ".join(rest.split())
    tokens = rest.split(" ") if rest else []
    if len(tokens) < _CREATE_MIN_TOKENS:
        # 参数不齐也返回命令对象，让 service/回帖层给出格式帮助（而不是当作聊天）
        cmd.fields["malformed"] = True
        cmd.objective = rest
        return cmd
    cmd.cron_expr = " ".join(tokens[:5])
    cmd.timezone = tokens[5]
    cmd.objective = rest.split(" ", 6)[6].strip()
    if not cmd.objective:
        cmd.fields["malformed"] = True
    return cmd


def _parse_edit(cmd: SchedulingCommand, rest: str) -> SchedulingCommand:
    """``<id> k=v...``；值可含空格，按下一个已知键切片。"""
    parts = rest.split()
    if not parts:
        cmd.fields["malformed"] = True
        return cmd
    cmd.task_id = parts[0]
    kv_region = rest[len(parts[0]):].strip()
    matches = list(_EDIT_KEY_RE.finditer(kv_region))
    for idx, match in enumerate(matches):
        key = match.group(1)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(kv_region)
        value = kv_region[match.end():end].strip()
        if key == "rev":
            if value.isdigit():
                cmd.expected_revision = int(value)
        else:
            cmd.fields[key] = value
    if not matches:
        cmd.fields["malformed"] = True
    return cmd


def format_help() -> str:
    """指令清单（回帖用；与 parse 的动词表同源维护）。"""
    return (
        "定时任务指令（@我使用）：\n"
        "定时添加 <cron> <时区> <提醒内容> —— 例：定时添加 0 9 * * MON-FRI Asia/Shanghai 站会啦\n"
        "定时智能 <cron> <时区> <目标> —— Agent 任务（管理员）\n"
        "定时列表 / 定时详情 <id> / 定时历史 <id>\n"
        "定时编辑 <id> cron=… tz=… text=… notify=always|on_content\n"
        "定时暂停 / 定时启用 / 定时取消 / 定时立即 <id>\n"
        "定时允许 / 定时禁止 <id> <工具名> —— Agent 工具清单（管理员）\n"
        "cron 为 5 字段（分 时 日 月 周），星期用 MON-SUN 名称；"
        "日和星期同时写时取交集。"
    )


__all__ = [
    "PREFIX",
    "SchedulingCommand",
    "format_help",
    "is_scheduling_command",
    "parse_scheduling_command",
]
