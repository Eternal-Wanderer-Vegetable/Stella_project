# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 测试共享夹具。

- 目录**不带 __init__.py**：pytest prepend 模式下 tests 子包会遮蔽顶层
  ``cometa`` 包（repo 已知陷阱，见 tests/knowledge 的教训）；
- 临时库/临时 STELLA_HOME 全部走 tmp_path，不碰真实数据目录；
- FakeBackend 注入由 :func:`make_executor` 完成——每个用例拿到自己的
  行为脚本与记账句柄。
"""

from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from cometa.artifacts import ArtifactCollector
from cometa.backends.fake import FakeBackend
from cometa.backends.registry import BackendRegistry
from cometa.config import CometaConfig
from cometa.executor import AttemptExecutor
from cometa.models import Origin, TaskSpec, utc_now
from cometa.store import CometaStore
from cometa.workspace import WorkspaceManager


@pytest.fixture()
def config(tmp_path: Path) -> CometaConfig:
    """默认测试配置：FakeBackend 启用、任务期限放宽、数据库在 tmp。"""
    cfg = CometaConfig.load(env={"STELLA_HOME": str(tmp_path), "COMETA_ENABLED": "true"})
    cfg.max_concurrent = 4  # 用例自行控制并发
    cfg.limits.per_user_active = 8
    cfg.limits.per_group_active = 8
    cfg.limits.input_wait_seconds = 60.0
    # 无 cometa.toml 的测试环境：显式声明 fake 后端（executor 从 config 解析）
    from cometa.config import BackendConfig, ProfileConfig

    cfg.backends["fake"] = BackendConfig(backend_id="fake", type="fake", enabled=True)
    cfg.profiles["coding"] = ProfileConfig(name="coding", backend="fake")
    return cfg


@pytest.fixture()
def store(tmp_path: Path) -> CometaStore:
    return CometaStore(tmp_path / "cometa.db")


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """一个带初始提交的最小 git 仓库（worktree 测试用）。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    def _git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
        )
    _git("init", "-q")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", ".")
    _git("commit", "-q", "-m", "init")
    return repo


@pytest.fixture()
def make_executor(store: CometaStore, config: CometaConfig, tmp_path: Path):
    """executor 工厂：注入用例自己的 FakeBackend（行为可编程 + 记账）。"""

    def _make(backend: FakeBackend | None = None) -> tuple[AttemptExecutor, FakeBackend]:
        backend = backend or FakeBackend()
        registry = BackendRegistry()
        registry.register_type("fake", lambda cfg: backend)
        executor = AttemptExecutor(
            store=store,
            registry=registry,
            workspaces=WorkspaceManager(config),
            artifacts=ArtifactCollector(config.artifacts_dir),
            config=config,
            worker_id="w-test",
        )
        return executor, backend

    return _make


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
    config: CometaConfig,
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
