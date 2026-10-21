# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""定时任务管理（方案 §6.10）。直接复用 SchedulingService——群内指令与
WebUI 走同一套校验（配额/权限/审计一个不少，方案 §17 红线 4）。

WebUI 操作者身份：调用时 ``is_group_admin=True``（受信边界内的管理员视角，
方案契约 §3），配额与 revision 乐观锁照常生效。``SCHEDULING_ENABLED=false``
时只允许读，拒绝写（409）。
"""

from __future__ import annotations

from pathlib import Path

import config.settings as settings
from webui.responses import ApiError

_ACTOR = 0  # WebUI 管理员的合成 actor（QQ 号体系外；审计里可识别）


def _service():
    try:
        from stella_project.plugins.bot_main.scheduling.service import SchedulingService
        from stella_project.plugins.bot_main.scheduling.store import TaskStore
    except Exception as e:
        # 独立模式（dev server）下 bot_main 包 __init__ 需要 nonebot driver
        raise ApiError(
            "定时任务管理需要 Bot 运行环境（独立 dev server 不可用）", status_code=503
        ) from e

    db_path = getattr(settings, "SCHEDULING_DB_PATH", None) or (
        Path(settings.STELLA_HOME) / "scheduling" / "tasks.db"
    )
    store = TaskStore(db_path)
    from stella_project.plugins.bot_main.scheduling.service import SchedulingLimits

    limits = SchedulingLimits(
        global_admin_ids=frozenset(getattr(settings, "SCHEDULING_GLOBAL_ADMINS", set()) or set())
    )
    return SchedulingService(store, limits=limits)


def _task_dict(task) -> dict:
    return {
        "task_id": task.task_id,
        "group_id": int(task.group_id),
        "bot_id": str(getattr(task, "bot_id", "") or ""),
        "mode": getattr(task, "mode", "").value if hasattr(task, "mode") else str(getattr(task, "mode", "")),
        "objective": getattr(task, "objective", ""),
        "cron_expr": task.cron_expr,
        "timezone": task.timezone,
        "revision": task.revision,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
        "created_by": getattr(task, "created_by", None),
    }


def _ensure_enabled(*, write: bool) -> None:
    if write and not getattr(settings, "SCHEDULING_ENABLED", False):
        raise ApiError("定时任务未启用（SCHEDULING_ENABLED=false），请在配置页开启", status_code=409)


def _active_onebot_bots() -> list[dict[str, str]]:
    """Return the exact connected OneBot V11 identities scheduling can target."""
    try:
        from nonebot import get_bots

        bots = get_bots().values()
    except Exception as e:
        raise ApiError(
            "定时任务目标列表需要 Bot 运行环境（独立 dev server 不可用）",
            status_code=503,
        ) from e

    available: dict[str, dict[str, str]] = {}
    for bot in bots:
        try:
            bot_id = str(bot.self_id)
            adapter_name = str(bot.adapter.get_name())
        except Exception:
            continue
        if adapter_name != "OneBot V11" or not bot_id.isdecimal() or int(bot_id) <= 0:
            continue
        available[bot_id] = {"bot_id": bot_id, "adapter": adapter_name}
    return [available[key] for key in sorted(available, key=lambda value: (int(value), value))]


def list_bots() -> dict:
    """Expose only connected OneBot V11 accounts accepted by SchedulingService."""
    return {"bots": _active_onebot_bots()}


def list_tasks(group_id: str | None = None, *, include_cancelled: bool = False) -> dict:
    service = _service()
    groups = [group_id] if group_id else _all_groups_with_tasks(service)
    tasks = []
    for gid in groups:
        for task in service.list_tasks(group_id=int(gid), include_cancelled=include_cancelled):
            tasks.append(_task_dict(task))
    return {"tasks": tasks}


def _all_groups_with_tasks(service) -> list[str]:
    conn_path = getattr(settings, "SCHEDULING_DB_PATH", None) or (
        Path(settings.STELLA_HOME) / "scheduling" / "tasks.db"
    )
    import sqlite3

    if not Path(conn_path).exists():
        return []
    conn = sqlite3.connect(f"file:{Path(conn_path).as_posix()}?mode=ro", uri=True)
    try:
        return [row[0] for row in conn.execute("SELECT DISTINCT group_id FROM tasks")]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def create_task(payload: dict) -> dict:
    _ensure_enabled(write=True)
    service = _service()
    bot_id = str(payload.get("bot_id") or "").strip()
    available_bot_ids = {item["bot_id"] for item in _active_onebot_bots()}
    if bot_id not in available_bot_ids:
        raise ApiError("请选择当前已连接的 OneBot V11 机器人账号", status_code=409)
    group_id = int(payload["group_id"])
    from stella_project.plugins.bot_main.scheduling.targets import legacy_qq_target

    target = legacy_qq_target(bot_id, group_id)
    if target is None:
        raise ApiError("群或机器人账号不是有效的 QQ 投递目标")
    task = service.create_task(
        actor_id=_ACTOR,
        group_id=group_id,
        bot_id=bot_id,
        target=target,
        is_group_admin=True,
        mode=payload.get("mode", "reminder"),
        objective=payload.get("objective", ""),
        cron_expr=payload["cron_expr"],
        timezone=payload.get("timezone", "Asia/Shanghai"),
        notification_mode=payload.get("notification_mode"),
        policy=payload.get("policy"),
    )
    return _task_dict(task)


def get_task(group_id: int, task_id: str) -> dict:
    return _task_dict(_service().show_task(actor_id=_ACTOR, group_id=int(group_id),
                                           task_id_prefix=task_id, is_group_admin=True))


def edit_task(group_id: int, task_id: str, payload: dict) -> dict:
    _ensure_enabled(write=True)
    task = _service().edit_task(
        actor_id=_ACTOR,
        group_id=int(group_id),
        task_id_prefix=task_id,
        expected_revision=int(payload["expected_revision"]),
        is_group_admin=True,
        cron_expr=payload.get("cron_expr"),
        timezone=payload.get("timezone"),
        objective=payload.get("objective"),
        notification_mode=payload.get("notification_mode"),
        policy=payload.get("policy"),
    )
    return _task_dict(task)


def _status_action(action: str, group_id: int, task_id: str, expected_revision: int) -> dict:
    _ensure_enabled(write=True)
    service = _service()
    task = getattr(service, action)(
        actor_id=_ACTOR, group_id=int(group_id), task_id_prefix=task_id,
        expected_revision=int(expected_revision), is_group_admin=True,
    )
    return _task_dict(task)


def run_now(group_id: int, task_id: str) -> dict:
    _ensure_enabled(write=True)
    run = _service().run_now(actor_id=_ACTOR, group_id=int(group_id),
                             task_id_prefix=task_id, is_group_admin=True)
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "state": run.state.value if hasattr(run.state, "value") else str(run.state),
    }


def history(group_id: int, task_id: str, *, limit: int = 20) -> dict:
    runs = _service().history(actor_id=_ACTOR, group_id=int(group_id),
                              task_id_prefix=task_id, is_group_admin=True, limit=limit)
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "task_id": r.task_id,
                "state": r.state.value if hasattr(r.state, "value") else str(r.state),
                "ts": getattr(r, "ts", None),
                "note": getattr(r, "note", "") or getattr(r, "skip_reason", "") or "",
            }
            for r in runs
        ]
    }


def audit(group_id: str | None, *, limit: int = 50) -> dict:
    service = _service()
    groups = [group_id] if group_id else _all_groups_with_tasks(service)
    entries = []
    for gid in groups:
        for entry in service.audit_log(group_id=int(gid), limit=limit):
            entries.append(
                {
                    "ts": getattr(entry, "ts", None),
                    "group_id": getattr(entry, "group_id", gid),
                    "actor_id": getattr(entry, "actor_id", None),
                    "action": getattr(entry, "action", ""),
                    "task_id": getattr(entry, "task_id", ""),
                    "detail": getattr(entry, "detail", ""),
                }
            )
    return {"entries": entries}
