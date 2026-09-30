# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""工作区准备与隔离（方案 §6.9）。

- 管理员在 cometa.toml 声明 workspace_id → 仓库根；用户提交的是 ID，
  **模型不能指定任意 cwd**；
- 编程任务默认在固定 base commit 的独立 **git worktree** 中执行；保存
  base_commit、工作区路径与分支。首版基于提交快照，不拷贝未提交修改；
- worktree 是**冲突隔离，不是安全沙盒**——文件/网络/命令权限由后端沙盒
  与宿主策略约束；
- 同一工作区最多一个写任务：互斥由 tasks/workspace_leases 数据库锁承担
  （store.claim_next_task 已实现），本模块负责 worktree 的物理生命周期；
- 目录模式（mode=directory）用于只读 profile（如 research）：直接指向
  仓库根，不做 worktree。
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import CometaConfig, WorkspaceConfig
from .models import new_id

_LOGGER = logging.getLogger("cometa.workspace")


class WorkspaceError(RuntimeError):
    """工作区准备失败（仓库缺失/worktree 冲突/清理失败）。executor 把它落为
    明确的任务失败，绝不降级到任意路径。"""


@dataclass(slots=True)
class WorkspacePreparation:
    """一次工作区准备的产物（executor 传给后端）。"""

    workspace_id: str
    path: Path
    mode: str
    base_commit: str
    created_worktree: bool  # False = 目录模式或复用既有 worktree


def _run_git(repo: Path, *args: str, timeout: float = 60.0) -> str:
    """在 repo 里跑 git 子命令。参数数组 + 固定 executable，无 shell 拼接（§6.9）。"""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except FileNotFoundError as e:
        raise WorkspaceError("git 不可用（PATH 中没有 git）") from e
    except subprocess.TimeoutExpired as e:
        raise WorkspaceError(f"git {' '.join(args[:2])} 超时") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip()[:300]
        raise WorkspaceError(f"git {' '.join(args[:2])} 失败: {detail}") from e
    return (completed.stdout or "").strip()


class WorkspaceManager:
    """worktree/目录工作区的物理生命周期。目录布局::

        STELLA_HOME/cometa/workspaces/<task_id_short>-<nonce>/
    """

    def __init__(self, config: CometaConfig):
        self._config = config
        self._root = config.artifacts_dir.parent / "workspaces"

    def prepare(self, workspace: WorkspaceConfig, task_id: str) -> WorkspacePreparation:
        """为任务准备工作区。worktree 模式执行 ``git worktree add``；
        目录模式校验仓库存在后直接返回。"""
        repo = workspace.repository
        if not repo.is_dir():
            raise WorkspaceError(f"工作区仓库不存在: {repo}")
        if workspace.mode == "directory":
            base = _safe_head_commit(repo)
            return WorkspacePreparation(
                workspace_id=workspace.workspace_id,
                path=repo,
                mode="directory",
                base_commit=base,
                created_worktree=False,
            )
        base_ref = workspace.base_ref or "HEAD"
        base = _safe_head_commit(repo, base_ref)
        target = self._root / f"{task_id[:8]}-{new_id()[:6]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git(repo, "worktree", "add", "--detach", str(target), base)
        return WorkspacePreparation(
            workspace_id=workspace.workspace_id,
            path=target,
            mode="worktree",
            base_commit=base,
            created_worktree=True,
        )

    def cleanup(self, preparation: WorkspacePreparation, *, force: bool = False) -> bool:
        """清理任务工作区。只清理**自己创建的** worktree（目录模式不动仓库）。

        到期清理前调用方必须先确认引用与进程已释放（方案 §6.9）；
        保留默认 7 天，恢复中的任务与未交付结果不自动清理。
        """
        if not preparation.created_worktree:
            return True
        repo = self._config_worktree_repo(preparation)
        if repo is None:
            return False
        args = ["worktree", "remove", str(preparation.path)]
        if force:
            args.append("--force")
        try:
            _run_git(repo, *args)
            return True
        except WorkspaceError as e:
            _LOGGER.warning("worktree 清理失败（保留现场待人工处理）: %s", e)
            return False

    def _config_worktree_repo(self, preparation: WorkspacePreparation):
        workspace = self._config.workspaces.get(preparation.workspace_id)
        if workspace is None or not workspace.repository.is_dir():
            return None
        return workspace.repository


def _safe_head_commit(repo: Path, ref: str = "HEAD") -> str:
    try:
        return _run_git(repo, "rev-parse", ref)
    except WorkspaceError as e:
        raise WorkspaceError(f"无法解析 {repo} 的基准提交 {ref!r}: {e}") from e


__all__ = ["WorkspaceError", "WorkspaceManager", "WorkspacePreparation"]
