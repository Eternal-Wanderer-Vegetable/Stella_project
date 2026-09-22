# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""真 Docker daemon 集成测试（plan §8：marker/条件运行）。

与 ``test_docker_runner.py``（MockTransport 协议测试）互补：这一组对
**真实 daemon** 验证容器级硬约束真的生效——非 root、只读 rootfs、
无网络、workspace 隔离、超时终止、退出码语义、资源回收。

运行条件（缺一即整组 skip，CI 无 Docker 时自动跳过）：

1. 镜像 ``SANDBOX_IMAGE``（默认 python:3.12-slim）已存在于 daemon；
2. 端点可达：环境变量 ``STELLA_DOCKER_TEST_ENDPOINT``（如
   ``http://127.0.0.1:2377``）或缺省端点探测成功。Windows + Docker
   Desktop 只有 npipe 时，先起桥：

   ::

      python tests/sandbox/_npipe_bridge.py --port 2377
      set STELLA_DOCKER_TEST_ENDPOINT=http://127.0.0.1:2377
      python -m pytest tests/sandbox/test_docker_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest
from sandbox_helpers import make_action, make_spec

from skills.audit import AuditLog, reset_audit
from skills.model import SandboxLimits
from skills.orchestrator import SkillOrchestrator
from skills.runners.docker import DockerSandboxExecutor

pytestmark = pytest.mark.xdist_group("docker_integration")


def _daemon_endpoint() -> str | None:
    import os

    return os.getenv("STELLA_DOCKER_TEST_ENDPOINT") or None


def _real_executor(tmp_path: Path, **kwargs: object) -> DockerSandboxExecutor:
    from skills.runners.docker import default_endpoint

    return DockerSandboxExecutor(
        image="python:3.12-slim",
        workspace_root=tmp_path,
        endpoint=_daemon_endpoint() or default_endpoint(),
        **kwargs,  # type: ignore[arg-type]
    )


def _docker_cli(*args: str) -> str:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=60
    )
    return result.stdout


@pytest.fixture(scope="module", autouse=True)
def _require_real_daemon():
    """daemon 可达且镜像存在才运行本组；否则整组 skip（不是失败）。"""
    import tempfile

    probe_workspace = Path(tempfile.mkdtemp(prefix="stella-sb-probe-"))
    executor = _real_executor(probe_workspace)
    info = executor.availability()
    if not info.available:
        pytest.skip(f"Docker daemon 不可达，跳过真机集成: {info.reason}")
    images = _docker_cli("images", "python:3.12-slim", "--format", "{{.Repository}}")
    if "python" not in images:
        pytest.skip("镜像 python:3.12-slim 不存在（沙盒不自动拉镜像），先 docker pull")


@pytest.fixture(autouse=True)
def _isolated_audit(tmp_path, monkeypatch):
    """审计单例钉到每个用例的临时文件，供「沙盒启动/清理已审计」断言。"""
    import skills.audit as audit_mod
    import skills.sandbox as sandbox_mod

    log = AuditLog(tmp_path / "audit" / "skills_audit.jsonl")
    monkeypatch.setattr(audit_mod, "_default", log)
    monkeypatch.setattr(sandbox_mod, "audit", lambda: log)
    yield log
    reset_audit()


@pytest.fixture(autouse=True)
def _no_leftover_containers():
    """每组用例后核查资源回收：不留 stella-sb-* 残留容器。"""
    yield
    leftover = _docker_cli(
        "ps", "-a", "--filter", "name=stella-sb-", "--format", "{{.ID}}"
    )
    assert not leftover.strip(), f"沙盒容器未回收: {leftover!r}"


def _run(executor, spec, action):
    return asyncio.run(executor.execute(spec, action))


# ---------- 容器级硬约束（真机验证） ----------


class TestHardConstraints:
    def test_shell_hello(self, tmp_path):
        executor = _real_executor(tmp_path)
        outcome = _run(
            executor,
            make_spec(tmp_path),
            make_action("run_shell", command="echo hello-sandbox"),
        )
        assert outcome.ok
        assert "hello-sandbox" in outcome.output

    def test_non_root_uid_65532(self, tmp_path):
        executor = _real_executor(tmp_path)
        outcome = _run(
            executor, make_spec(tmp_path), make_action("run_shell", command="id -u")
        )
        assert outcome.ok
        assert outcome.output.strip() == "65532"

    def test_readonly_rootfs_rejects_writes(self, tmp_path):
        """只读根文件系统：写 /usr 必须失败（exit code 非 0）。"""
        executor = _real_executor(tmp_path)
        outcome = _run(
            executor,
            make_spec(tmp_path),
            make_action("run_shell", command="touch /usr/should-fail && echo written"),
        )
        assert not outcome.ok
        assert outcome.error_code == "execution_failed"

    def test_workspace_writable_but_container_fs_readonly(self, tmp_path):
        """workspace 可写（bind）、根只读——读写分离的边界同时成立。"""
        executor = _real_executor(tmp_path)
        spec = make_spec(tmp_path)
        write = _run(
            executor, spec, make_action("write_file", path="out/a.md", content="内容")
        )
        assert write.ok
        assert write.artifact is not None and write.artifact.path == "out/a.md"
        # bind 真的落到宿主 workspace
        assert (Path(spec.workspace) / "out" / "a.md").read_text(
            encoding="utf-8"
        ) == "内容"
        # 根文件系统仍然只读
        root_write = _run(
            executor,
            spec,
            make_action("run_shell", command="touch /should-fail"),
        )
        assert not root_write.ok

    def test_no_network_egress(self, tmp_path):
        """NetworkMode=none：容器内出网必须失败。"""
        executor = _real_executor(tmp_path)
        outcome = _run(
            executor,
            make_spec(tmp_path),
            make_action(
                "run_python",
                code=(
                    "import socket\n"
                    "socket.setdefaulttimeout(5)\n"
                    "socket.create_connection(('1.1.1.1', 443))\n"
                    "print('network-up')"
                ),
            ),
        )
        assert not outcome.ok
        assert "network-up" not in outcome.output

    def test_workspace_isolation_no_project_or_env_leak(self, tmp_path):
        """容器里只有 workspace：项目目录与 .env 不可见。"""
        executor = _real_executor(tmp_path)
        spec = make_spec(tmp_path)
        # /app 是 python 官方镜像自带的空目录；bot.py 只存在于项目根。
        # 容器里能看到 bot.py = 项目根被挂载 = 隔离被破坏。
        project = _run(
            executor,
            spec,
            make_action("run_shell", command="test -f /app/bot.py"),
        )
        assert not project.ok  # 项目根没有挂进容器
        env_probe = _run(
            executor,
            spec,
            make_action("run_shell", command="test -f /.env"),
        )
        assert not env_probe.ok
        listing = _run(executor, spec, make_action("list_files", path="."))
        assert listing.ok

    def test_exit_code_semantics(self, tmp_path):
        executor = _real_executor(tmp_path)
        fail = _run(
            executor, make_spec(tmp_path), make_action("run_shell", command="exit 3")
        )
        assert not fail.ok
        assert fail.error_code == "execution_failed"
        missing = _run(
            executor,
            make_spec(tmp_path),
            make_action("read_file", path="references/nope.md"),
        )
        assert not missing.ok

    def test_resource_limits_visible_in_cgroup(self, tmp_path):
        """容器内 cgroup 可见 PIDs/Memory 上限（Docker Desktop 为 cgroup v2）。"""
        executor = _real_executor(tmp_path)
        spec = make_spec(tmp_path, limits=SandboxLimits(memory_mb=256, pids=64))
        outcome = _run(
            executor,
            spec,
            make_action(
                "run_shell",
                command="cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/pids.max 2>/dev/null",
            ),
        )
        if not outcome.ok:
            pytest.skip("容器内无 cgroup v2 接口，跳过限额可见性断言")
        assert "268435456" in outcome.output  # 256MB
        assert "64" in outcome.output

    def test_timeout_kills_and_reports(self, tmp_path):
        executor = _real_executor(tmp_path)
        spec = make_spec(tmp_path, limits=SandboxLimits(timeout_seconds=3))
        outcome = _run(
            executor, spec, make_action("run_shell", command="sleep 30 && echo done")
        )
        assert not outcome.ok
        assert outcome.error_code == "timeout"


class TestLiveContainerInspection:
    def test_host_config_during_run(self, tmp_path):
        """容器运行中 docker inspect：HostConfig 硬约束逐项核对。"""
        executor = _real_executor(tmp_path)
        spec = make_spec(
            tmp_path, limits=SandboxLimits(cpu=1.5, memory_mb=256, pids=64)
        )
        import threading

        result: dict = {}

        def _worker():
            result["outcome"] = _run(
                executor, spec, make_action("run_shell", command="sleep 20")
            )

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        name = None
        import time

        for _ in range(100):
            name = _docker_cli(
                "ps", "--filter", "name=stella-sb-", "--format", "{{.Names}}"
            ).strip()
            if name:
                break
            time.sleep(0.2)
        assert name, "6 秒的 sleep 容器没有被观察到"
        raw = _docker_cli("inspect", name.splitlines()[0])
        info = json.loads(raw)[0]
        host = info["HostConfig"]
        assert host["PidsLimit"] == 64
        assert host["Memory"] == 256 * 1024 * 1024
        assert host["NanoCpus"] == 1_500_000_000
        assert host["ReadonlyRootfs"] is True
        assert host["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in host["SecurityOpt"]
        assert host["NetworkMode"] == "none"
        assert info["Config"]["User"] == "65532:65532"
        binds = host["Binds"]
        assert any(b.endswith(":/workspace") for b in binds)
        thread.join(timeout=60)
        # 容器正常跑完 sleep 并被回收：动作本身成功（默认超时 60s 覆盖 20s）
        assert result["outcome"].ok


class TestAuditAndCleanup:
    def test_start_and_cleanup_audited(self, tmp_path, _isolated_audit):
        executor = _real_executor(tmp_path)
        _run(executor, make_spec(tmp_path), make_action("run_shell", command="echo x"))
        asyncio.run(executor.cleanup(make_spec(tmp_path)))
        events = [e["event"] for e in _isolated_audit.read_recent(limit=50)]
        assert "sandbox_start" in events
        assert "sandbox_cleanup" in events
        start = next(
            e
            for e in _isolated_audit.read_recent(limit=50)
            if e["event"] == "sandbox_start"
        )
        assert start["network"] == "none"
        assert start["policy_version"]


# ---------- 编排器端到端（真沙盒 + 假规划器） ----------


class TestOrchestratorEndToEnd:
    def test_full_skill_invocation_with_real_sandbox(self, tmp_path, _isolated_audit):
        """plan §7.8 的最终路径：候选级编排 → 真容器执行 → 有界结果。"""
        from skills.model import (
            SkillManifest,
            SkillSource,
            SkillStatus,
        )

        manifest = SkillManifest(
            name="report",
            description="生成报告",
            source=SkillSource.USER,
            root=tmp_path / "report-skill",
            content_digest="e" * 64,
        )

        async def _plan(prompt):
            assert "run_shell" in prompt and "write_file" in prompt
            return json.dumps(
                {
                    "actions": [
                        {
                            "action": "write_file",
                            "args": {"path": "out/data.txt", "content": "42"},
                        },
                        {
                            "action": "run_shell",
                            "args": {"command": "cat /workspace/out/data.txt"},
                        },
                        {"action": "list_files", "args": {}},
                    ]
                }
            )

        executor = _real_executor(tmp_path)
        orchestrator = SkillOrchestrator(
            planner=_plan,
            executor=executor,
            workspace_root=tmp_path,
            limits=SandboxLimits(),
            backend="docker",
            image="python:3.12-slim",
            body_max_chars=24000,
            total_timeout=120.0,
            output_max_chars=2000,
            asset_max_bytes=524288,
        )
        result = asyncio.run(
            orchestrator.invoke("生成报告", manifest, session_id="群1:1000")
        )
        assert result.status is SkillStatus.COMPLETED
        assert result.metrics["actions_planned"] == 3
        assert result.metrics["actions_failed"] == 0
        # 摘要有界、含执行回声，但绝不含原始全文
        assert len(result.summary) <= 2000
        assert "run_shell: 42" in result.summary
        # 产物引用（workspace 相对）+ 宿主真实文件
        assert [a.path for a in result.artifacts] == ["out/data.txt"]
        audit_events = [e["event"] for e in _isolated_audit.read_recent(limit=100)]
        assert "sandbox_start" in audit_events
        assert "sandbox_cleanup" in audit_events
