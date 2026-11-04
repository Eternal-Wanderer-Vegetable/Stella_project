# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""Aoede 宿主注入面（2026-11-03 计划 §3.1）。

Aoede 的编排核心（``aoede.service`` / ``aoede.verification.service``）不依赖
NoneBot 类型，也不导入插件模块：bot 句柄、发送、引擎轮次、群锁、观测探针、
门控与状态访问器全部由 Stella 装配层（``ai_gateway``）构造成本数据类显式
注入。bot 句柄按鸭子类型使用（``self_id`` / ``get_group_member_info``），
因此本模块不需要导入 OneBot 适配器。

**转发合同**：装配层构造宿主时，可被测试/运维替换的符号（``can_speak``、
``get_proactive``、``DB_PATH`` 等）一律以「调用时经装配层模块属性转发」的
lambda 注入——保持既有 monkeypatch（``gateway.can_speak`` 等）语义不变。

类型标注全部为运行时字符串（``from __future__ import annotations``），
本模块只依赖标准库。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
    return None


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


@dataclass
class ProactiveHost:
    """ai_gateway 注入给 Aoede 编排层的显式依赖集。

    字段语义与被替换的 ``ai_gateway`` 符号一一对应（转发合同见模块 docstring）：

    引擎与会话
    - ``run_turn``                —— ``_run_turn_via_engine``（唯一轮次执行入口）
    - ``register_group_ref``      —— ``_register_group_ref``（可信会话注册）
    - ``group_locks``             —— ``_group_locks``（群互斥锁，ai_gateway 持有）

    门控与状态（原 ai_gateway 模块级符号，测试以 monkeypatch 替换）
    - ``can_speak``               —— ``can_speak``（主动硬门禁）
    - ``get_proactive``           —— ``get_proactive``（活跃度控制器单例）
    - ``get_reply_gate``          —— ``get_reply_gate``
    - ``get_consolidator``        —— ``get_consolidator``
    - ``get_participation_manager`` —— ``get_participation_manager``
    - ``record_at``               —— ``record_at``（主动 @ 配额记账）
    - ``db_path``                 —— ``DB_PATH`` 的调用时读取

    发送与投递
    - ``delivery_target_for_context`` —— ``_delivery_target_for_context``
    - ``seal_ctx_delivery_plan``  —— ``_seal_ctx_delivery_plan``
    - ``delivery_plan_is_current`` —— ``_delivery_plan_is_current``
    - ``social_delivery_enabled`` —— ``_social_delivery_enabled``
    - ``record_bot_lines``        —— ``_record_bot_lines``（Bot 自身发言落库）
    - ``join_lines_naturally``    —— ``_join_lines_naturally``（多行合并）
    - ``resolve_nickname``        —— ``_resolve_nickname``（群名片/昵称，OneBot 调用）
    - ``send_background_message`` / ``resolve_background_bot`` —— transport_delivery 适配

    观测与编排回调（保持 gateway 级 monkeypatch 合同）
    - ``flow_decision`` / ``flow_span`` / ``flow_checkpoint`` / ``flow_set_outcome``
    - ``check_reply_later``       —— ``_check_reply_later``（回应检测后台任务）
    - ``proactive_contract_mode`` —— ``_proactive_contract_mode``
    - ``proactive_speak_for_group`` —— ``_proactive_speak_for_group``（spawn 回调）
    - ``schedule_compact``        —— ``schedule_compact``
    """

    # 引擎与会话
    run_turn: Callable[[str, Any], Awaitable[Any]]
    register_group_ref: Callable[[str, int], Any]
    group_locks: dict[int, asyncio.Lock] = field(
        default_factory=lambda: defaultdict(asyncio.Lock)
    )

    # 门控与状态
    can_speak: Callable[[int, str], tuple[bool, str]] = _noop
    get_proactive: Callable[[], Any] = _noop
    get_reply_gate: Callable[[], Any] = _noop
    get_consolidator: Callable[[], Any] = _noop
    get_participation_manager: Callable[[], Any] = _noop
    record_at: Callable[..., None] = _noop
    pick_target: Callable[..., Any] = _noop
    get_outbound_service: Callable[[], Any] = _noop
    db_path: Callable[[], str] = _noop

    # 发送与投递
    delivery_target_for_context: Callable[..., Any] = _noop
    seal_ctx_delivery_plan: Callable[..., dict] = _noop
    delivery_plan_is_current: Callable[..., bool] = _noop
    social_delivery_enabled: Callable[[], bool] = _noop
    record_bot_lines: Callable[..., Awaitable[None]] = _noop_async
    join_lines_naturally: Callable[[list[str]], str] = _noop
    resolve_nickname: Callable[..., Awaitable[str]] = _noop_async
    send_background_message: Callable[..., Awaitable[Any]] | None = None
    resolve_background_bot: Callable[..., Any] | None = None

    # 观测与编排回调
    flow_decision: Callable[..., None] = _noop
    flow_span: Callable[..., Any] = _noop
    flow_checkpoint: Callable[..., None] = _noop
    flow_set_outcome: Callable[[Any, str], None] = _noop
    check_reply_later: Callable[..., Awaitable[None]] = _noop_async
    proactive_contract_mode: Callable[[], str] = _noop
    proactive_speak_for_group: Callable[..., Awaitable[None]] = _noop_async
    schedule_compact: Callable[..., None] = _noop
    register_task: Callable[[asyncio.Task], None] = _noop


_install: ProactiveHost | None = None


def install_host(host: ProactiveHost) -> None:
    """装配层启动时安装宿主；测试可重复安装覆盖。"""
    global _install
    _install = host


def get_host() -> ProactiveHost:
    """取当前宿主；未安装时显式失败（编排层不允许静默裸跑）。"""
    if _install is None:
        raise RuntimeError(
            "aoede host is not installed; the Stella assembly layer must call "
            "aoede.host.install_host() before proactive orchestration runs"
        )
    return _install


def reset_host_for_tests() -> None:
    """清空宿主（测试隔离用）。"""
    global _install
    _install = None
