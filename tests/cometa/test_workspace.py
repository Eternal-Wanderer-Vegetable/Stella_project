# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""工作区与产物的安全矩阵（方案 §8.1 test_workspace / test_artifacts、§6.9/§6.12）。

拒绝矩阵：路径穿越、symlink 逃逸、超大文件、缺文件、哈希不符、
存储键越界；工作区：同工作区互斥、脏仓库不影响 worktree、清理。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from cometa.artifacts import ArtifactCollector, ArtifactError
from cometa.config import WorkspaceConfig
from cometa.workspace import WorkspaceError, WorkspaceManager
from tests.cometa_helpers import make_origin, submit_task


class TestArtifacts:
    @pytest.fixture()
    def collector(self, tmp_path) -> ArtifactCollector:
        return ArtifactCollector(tmp_path / "artifacts")

    @pytest.fixture()
    def workspace(self, tmp_path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "patch.diff").write_bytes(b"hello patch\n")
        return ws

    def test_collect_within_workspace(self, collector, workspace):
        artifact = collector.collect("task-1", "patch.diff", workspace_path=workspace)
        assert artifact.display_name == "patch.diff"
        assert artifact.sha256
        assert artifact.size == len(b"hello patch\n")
        path = collector.artifact_path("task-1", artifact.relative_storage_key)
        assert path.is_file()

    def test_rejects_path_traversal(self, collector, workspace, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("top secret", encoding="utf-8")
        with pytest.raises(ArtifactError, match="越出工作区"):
            collector.collect("task-1", "../secret.txt", workspace_path=workspace)

    def test_rejects_absolute_path_outside(self, collector, workspace, tmp_path):
        with pytest.raises(ArtifactError):
            collector.collect("task-1", tmp_path / "outside.txt", workspace_path=workspace)

    def test_rejects_symlink_escape(self, collector, workspace, tmp_path):
        secret = tmp_path / "secret.txt"
        secret.write_text("x", encoding="utf-8")
        link = workspace / "link.txt"
        try:
            link.symlink_to(secret)
        except OSError:
            pytest.skip("当前环境无 symlink 特权（Windows 普通用户）")
        with pytest.raises(ArtifactError, match="链接"):
            collector.collect("task-1", "link.txt", workspace_path=workspace)

    def test_rejects_missing_file(self, collector, workspace):
        with pytest.raises(ArtifactError, match="常规文件"):
            collector.collect("task-1", "nope.diff", workspace_path=workspace)

    def test_rejects_oversized(self, tmp_path):
        collector = ArtifactCollector(tmp_path / "a", max_bytes=10)
        ws = tmp_path / "ws2"
        ws.mkdir()
        (ws / "big.bin").write_bytes(b"x" * 100)
        with pytest.raises(ArtifactError, match="上限"):
            collector.collect("task-1", "big.bin", workspace_path=ws)

    def test_rejects_total_overrun(self, tmp_path):
        collector = ArtifactCollector(tmp_path / "a", max_bytes=100, total_max_bytes=150)
        ws = tmp_path / "ws3"
        ws.mkdir()
        for name in ("a.bin", "b.bin", "c.bin"):
            (ws / name).write_bytes(b"x" * 100)
        collector.collect("task-1", "a.bin", workspace_path=ws)
        with pytest.raises(ArtifactError, match="总量"):
            collector.collect("task-1", "b.bin", workspace_path=ws)

    def test_rejects_bad_display_name(self, collector, workspace):
        with pytest.raises(ArtifactError, match="展示名"):
            collector.collect("task-1", "patch.diff", workspace_path=workspace,
                              display_name="../evil")

    def test_storage_key_traversal_rejected(self, collector, workspace):
        with pytest.raises(ArtifactError, match="存储键"):
            collector.artifact_path("task-1", "../escape.txt")

    def test_availability_missing_file(self, collector, workspace):
        artifact = collector.collect("task-1", "patch.diff", workspace_path=workspace)
        # 模拟文件被外部删除：必须显示 unavailable（§6.12）
        collector.artifact_path("task-1", artifact.relative_storage_key).unlink()
        assert collector.verify_availability(
            "task-1", artifact.relative_storage_key
        ).value == "unavailable"

    def test_final_text_roundtrip(self, collector):
        ref = collector.save_final_text("task-2", "完整结果" * 10)
        assert ref == "final_text.md"
        assert "完整结果" in collector.read_final_text("task-2")
        assert collector.read_final_text("task-3") == ""


class TestWorkspace:
    def test_directory_mode_returns_repo_itself(self, git_repo, config):
        config.workspaces["stella"] = WorkspaceConfig(
            workspace_id="stella", repository=git_repo, mode="directory"
        )
        manager = WorkspaceManager(config)
        prep = manager.prepare(config.workspaces["stella"], "task-abc")
        assert prep.mode == "directory"
        assert prep.path == git_repo
        assert prep.created_worktree is False
        assert prep.base_commit

    def test_worktree_mode_creates_and_cleans(self, git_repo, config):
        config.workspaces["stella"] = WorkspaceConfig(
            workspace_id="stella", repository=git_repo, mode="worktree", base_ref="HEAD"
        )
        manager = WorkspaceManager(config)
        prep = manager.prepare(config.workspaces["stella"], "task-abc")
        assert prep.created_worktree is True
        assert prep.path.is_dir()
        assert prep.base_commit
        # worktree 内修改不影响主仓
        (prep.path / "hack.txt").write_text("dirty", encoding="utf-8")
        readme = git_repo / "README.md"
        assert "hello" in readme.read_text(encoding="utf-8")
        assert not manager.cleanup(prep), "脏 worktree 普通清理应保留现场"
        assert prep.path.exists()
        assert manager.cleanup(prep, force=True)
        assert not prep.path.exists()

    def test_worktree_records_base_commit(self, git_repo, config):
        config.workspaces["stella"] = WorkspaceConfig(
            workspace_id="stella", repository=git_repo, mode="worktree"
        )
        manager = WorkspaceManager(config)
        prep = manager.prepare(config.workspaces["stella"], "task-abc")
        head = subprocess.run(
            ["git", "-C", str(git_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert prep.base_commit == head
        manager.cleanup(prep)

    def test_missing_repo_rejected(self, tmp_path, config):
        config.workspaces["ghost"] = WorkspaceConfig(
            workspace_id="ghost", repository=tmp_path / "nope", mode="directory"
        )
        manager = WorkspaceManager(config)
        with pytest.raises(WorkspaceError, match="不存在"):
            manager.prepare(config.workspaces["ghost"], "task-x")

    def test_workspace_mutex_across_claims(self, store, config):
        """同工作区最多一个写任务：由 store 认领事务保证（§6.9）。"""
        config.limits.per_user_active = 8
        config.limits.per_group_active = 8
        submit_task(store, config, key="ka", workspace_id="stella")
        submit_task(
            store,
            config,
            key="kb",
            workspace_id="stella",
            origin=make_origin(requester_id="888", source_request_id="rb"),
        )
        first = store.claim_next_task(
            instance_id="inst-test", worker_id="w1", backend_ids={"fake"}, lease_seconds=30
        )
        assert first is not None
        second = store.claim_next_task(
            instance_id="inst-test", worker_id="w2", backend_ids={"fake"}, lease_seconds=30
        )
        assert second is None, "同工作区第二个写任务不可认领"
