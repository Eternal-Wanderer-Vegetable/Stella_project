# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""cometa 测试共享助手。

刻意放在 tests/ 根并通过 ``from tests.cometa_helpers import ...`` 导入：
tests/<dir>/conftest.py 在 pytest prepend 模式下都以顶层名 ``conftest``
共存，互相 ``from conftest import`` 会撞到先加载的那个模块（实测）。
tests/ 自身无 __init__.py，作为 PEP 420 命名空间包被 pythonpath=["."]
覆盖，跨目录导入安全。
"""

from __future__ import annotations

from datetime import timedelta

from cometa.models import Origin, TaskSpec, utc_now
from cometa.store import CometaStore


def make_origin(**overrides) -> Origin:
    fields = {
        "instance_id": "inst-test",
        "platform": "qq",
        "bot_id": "10000",
        "conversation_id": "12345",
        "requester_id": "777",
        "source_request_id": "req-1",
        "reply_to_message_id": "m-1",
    }
    fields.update(overrides)
    return Origin(**fields)


def make_spec(**overrides) -> TaskSpec:
    fields = {"objective": "整理测试目标", "permission_profile": "coding"}
    fields.update(overrides)
    return TaskSpec(**fields)


def submit_task(
    store: CometaStore,
    config,
    *,
    origin: Origin | None = None,
    spec: TaskSpec | None = None,
    key: str = "k1",
    workspace_id: str = "",
    backend_id: str = "fake",
    deadline_seconds: float = 1800.0,
) -> str:
    origin = origin or make_origin()
    spec = spec or make_spec()
    task_id, _created = store.submit_task(
        origin=origin,
        spec=spec,
        idempotency_key=key,
        requester_id=origin.requester_id,
        group_id=origin.conversation_id if origin.platform == "qq" else "",
        backend_id=backend_id,
        profile=spec.permission_profile,
        workspace_id=workspace_id,
        workspace_key=f"ws:{workspace_id}" if workspace_id else "",
        deadline_at=utc_now() + timedelta(seconds=deadline_seconds),
        config_snapshot={
            "limits": {
                "per_user_active": config.limits.per_user_active,
                "per_group_active": config.limits.per_group_active,
            }
        },
    )
    return task_id


def claim_task(store: CometaStore, *, worker: str = "w-test", backend_ids=None):
    claimed = store.claim_next_task(
        instance_id="inst-test",
        worker_id=worker,
        backend_ids=backend_ids or {"fake"},
        lease_seconds=30.0,
    )
    assert claimed is not None, "认领失败：队列中没有可认领任务"
    return claimed
