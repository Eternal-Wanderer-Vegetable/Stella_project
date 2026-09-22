# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Docker runner 测试：动作翻译、容器硬约束、API 序列、降级路径。

全部通过 httpx.MockTransport 走**假 Docker API**——不要求测试机装 Docker；
真实 daemon 的不可达降级在 availability 里有独立断言（本机没有可达
daemon 时它必须报告不可用而不是抛异常）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
from sandbox_helpers import make_action, make_spec

from skills.model import SandboxLimits
from skills.runners.docker import (
    DockerSandboxExecutor,
    _action_command,
    _container_config,
    _container_name,
    _demux_docker_stream,
    default_endpoint,
)
from skills.sandbox import SandboxAvailability


def _executor(
    tmp_path: Path, transport=None, endpoint="http://docker"
) -> DockerSandboxExecutor:
    # workspace_root 与 make_spec 的基线一致（spec 的 workspace 建在其下）
    return DockerSandboxExecutor(
        image="python:3.12-slim",
        workspace_root=tmp_path,
        endpoint=endpoint,
        transport=transport,
    )


# Docker 日志帧：8 字节头 [类型, 0,0,0, 长度(大端 uint32)] + 载荷
def _frame(stream_type: int, payload: bytes) -> bytes:
    return bytes([stream_type, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


STDOUT_HELLO = _frame(1, b"abc")
STDERR_BANG = _frame(2, b"!")
BIG_OUTPUT = _frame(1, b"x" * 500)


class TestActionCommand:
    def test_shell_and_python(self):
        argv = _action_command(make_action("run_shell", command="ls -la"))
        assert argv == ["/bin/sh", "-c", "ls -la"]
        argv = _action_command(make_action("run_python", code="print(1)"))
        assert argv[:2] == ["python3", "-c"]
        assert argv[2] == "print(1)"

    def test_paths_pinned_to_workspace_posix(self):
        argv = _action_command(make_action("read_file", path="docs/a.md"))
        assert argv == ["cat", "/workspace/docs/a.md"]

    def test_rejects_escape_and_missing_args(self):
        assert _action_command(make_action("read_file", path="../x")) is None
        assert _action_command(make_action("read_file", path="/etc/passwd")) is None
        assert _action_command(make_action("run_shell")) is None
        assert _action_command(make_action("write_file", path="a.txt")) is None
        assert _action_command(make_action("unknown_action")) is None

    def test_write_file_content_via_argv_not_shell(self):
        argv = _action_command(
            make_action("write_file", path="out/a.txt", content="rm -rf /; $(x)")
        )
        assert argv[0] == "python3"
        # 内容是独立 argv，不进任何 shell 字符串
        assert argv[-1] == "rm -rf /; $(x)"


class TestDemux:
    def test_multiplexed_stream(self):
        assert _demux_docker_stream(STDOUT_HELLO + STDERR_BANG) == "abc!"

    def test_tty_fallback(self):
        assert _demux_docker_stream(b"plain output") == "plain output"

    def test_empty(self):
        assert _demux_docker_stream(b"") == ""


class TestContainerConfig:
    def test_hard_constraints_present(self, tmp_path):
        spec = make_spec(
            tmp_path,
            limits=SandboxLimits(cpu=2.0, memory_mb=128, pids=32, timeout_seconds=10),
        )
        config = _container_config(spec, ["cat", "/workspace/a"], "img")
        assert config["User"] == "65532:65532"
        assert config["HostConfig"]["ReadonlyRootfs"] is True
        assert config["HostConfig"]["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in config["HostConfig"]["SecurityOpt"]
        assert config["HostConfig"]["PidsLimit"] == 32
        assert config["HostConfig"]["Memory"] == 128 * 1024 * 1024
        assert config["HostConfig"]["NanoCpus"] == 2_000_000_000
        assert config["HostConfig"]["NetworkMode"] == "none"
        assert config["NetworkDisabled"] is True
        assert config["HostConfig"]["Binds"] == [f"{spec.workspace}:/workspace"]
        assert "/tmp" in config["HostConfig"]["Tmpfs"]

    def test_skill_source_mounted_readonly(self, tmp_path):
        import dataclasses

        spec = dataclasses.replace(
            make_spec(tmp_path),
            read_only_mounts=(("/skills-src/pdf", "/skills/pdf"),),
        )
        config = _container_config(spec, ["true"], "img")
        binds = config["HostConfig"]["Binds"]
        assert binds[1] == "/skills-src/pdf:/skills/pdf:ro"


class TestContainerName:
    def test_sanitized_and_prefixed(self):
        name = _container_name("ABC/def 123")
        assert name.startswith("stella-sb-")
        assert "/" not in name and " " not in name


class _FakeDockerAPI:
    """可编程的 Docker API 假实现（httpx.MockTransport handler 工厂）。"""

    def __init__(
        self,
        *,
        logs: bytes = b"",
        fail_create: bool = False,
        exit_code: int = 0,
        existing: list[str] | None = None,
    ):
        self.calls: list[tuple[str, str]] = []
        self.logs = logs
        self.fail_create = fail_create
        self.exit_code = exit_code
        self.existing = existing or []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.url.path.endswith("/_ping"):
            return httpx.Response(200, text="OK")
        if request.url.path.endswith("/containers/create"):
            if self.fail_create:
                return httpx.Response(404, json={"message": "No such image"})
            return httpx.Response(201, json={"Id": "cid123"})
        if request.url.path.endswith("/containers/json"):
            return httpx.Response(200, json=[{"Id": i} for i in self.existing])
        if request.url.path.endswith("/start"):
            return httpx.Response(204)
        if request.url.path.endswith("/wait"):
            return httpx.Response(200, json={"StatusCode": self.exit_code})
        if request.url.path.endswith("/logs"):
            return httpx.Response(200, content=self.logs)
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)


class TestExecuteWithFakeAPI:
    def test_run_shell_end_to_end(self, tmp_path):
        api = _FakeDockerAPI(logs=STDOUT_HELLO + STDERR_BANG)
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        spec = make_spec(tmp_path)
        outcome = asyncio.run(
            executor.execute(spec, make_action("run_shell", command="ls"))
        )
        assert outcome.ok
        assert outcome.output == "abc!"
        # 完整序列：create → start → wait → logs → rm
        paths = [p for _, p in api.calls]
        assert any(p.endswith("/containers/create") for p in paths)
        assert any(p.endswith("/start") for p in paths)
        assert any(p.endswith("/wait") for p in paths)
        assert any(p.endswith("/logs") for p in paths)
        assert any(m == "DELETE" and p.endswith("cid123") for m, p in api.calls)

    def test_output_truncated_to_budget(self, tmp_path):
        api = _FakeDockerAPI(logs=BIG_OUTPUT * 40)
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        spec = make_spec(tmp_path, limits=SandboxLimits(output_max_chars=100))
        outcome = asyncio.run(
            executor.execute(spec, make_action("run_shell", command="x"))
        )
        assert len(outcome.output) == 100

    def test_write_file_yields_artifact_ref(self, tmp_path):
        api = _FakeDockerAPI()
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        outcome = asyncio.run(
            executor.execute(
                make_spec(tmp_path),
                make_action("write_file", path="out/a.md", content="hello"),
            )
        )
        assert outcome.ok
        assert outcome.artifact is not None
        assert outcome.artifact.path == "out/a.md"
        assert outcome.artifact.size_bytes == 5

    def test_nonzero_exit_marks_action_failed_with_output(self, tmp_path):
        api = _FakeDockerAPI(logs=STDOUT_HELLO, exit_code=1)
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        outcome = asyncio.run(
            executor.execute(
                make_spec(tmp_path), make_action("run_shell", command="cat x")
            )
        )
        assert not outcome.ok
        assert outcome.error_code == "execution_failed"
        assert outcome.output == "abc"  # 报错输出保留给摘要与审计

    def test_missing_image_is_diagnosable(self, tmp_path):
        api = _FakeDockerAPI(fail_create=True)
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        outcome = asyncio.run(
            executor.execute(
                make_spec(tmp_path), make_action("run_shell", command="ls")
            )
        )
        assert not outcome.ok
        assert outcome.error_code == "sandbox_unavailable"

    def test_network_enabled_refused_by_policy(self, tmp_path):
        api = _FakeDockerAPI()
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        spec = make_spec(
            tmp_path, network_enabled=True, network_allowlist=("a.com:443",)
        )
        outcome = asyncio.run(
            executor.execute(spec, make_action("run_shell", command="curl x"))
        )
        assert not outcome.ok
        assert outcome.error_code == "policy_denied"
        assert not any(p.endswith("/containers/create") for _, p in api.calls)

    def test_workspace_outside_root_refused(self, tmp_path):
        api = _FakeDockerAPI()
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        spec = make_spec(tmp_path, workspace=tmp_path.parent / "elsewhere" / "inv")
        outcome = asyncio.run(
            executor.execute(spec, make_action("run_shell", command="ls"))
        )
        assert not outcome.ok
        assert outcome.error_code == "policy_denied"


class TestAvailabilityAndDegradation:
    def test_ping_ok(self, tmp_path):
        api = _FakeDockerAPI()
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        info = executor.availability()
        assert isinstance(info, SandboxAvailability)
        assert info.available is True

    def test_unreachable_daemon_reports_not_available(self, tmp_path):
        # 指向一个必然关闭的本地 TCP 端口：必须返回不可用诊断而不是异常
        executor = DockerSandboxExecutor(
            image="python:3.12-slim",
            workspace_root=tmp_path,
            endpoint="http://127.0.0.1:9",
        )
        info = executor.availability()
        assert info.available is False
        assert "不可达" in info.reason

    def test_default_endpoint_is_sane(self):
        endpoint = default_endpoint()
        assert endpoint  # socket / npipe / DOCKER_HOST 之一

    def test_npipe_endpoint_reports_unavailable(self, tmp_path):
        executor = DockerSandboxExecutor(
            image="python:3.12-slim",
            workspace_root=tmp_path,
            endpoint="npipe:////./pipe/docker_engine",
        )
        info = executor.availability()
        assert info.available is False
        assert "DOCKER_HOST" in info.reason


class TestCleanup:
    def test_cleanup_deletes_and_audits(self, tmp_path):
        api = _FakeDockerAPI(existing=["cid-stale"])
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        asyncio.run(executor.cleanup(make_spec(tmp_path)))
        assert any(
            m == "DELETE" and p.endswith("containers/cid-stale") for m, p in api.calls
        )

    def test_cleanup_no_listed_containers_is_noop(self, tmp_path):
        api = _FakeDockerAPI(existing=[])
        executor = _executor(tmp_path, transport=httpx.MockTransport(api.handler))
        asyncio.run(executor.cleanup(make_spec(tmp_path)))
        assert not any(m == "DELETE" for m, _ in api.calls)

    def test_cleanup_survives_api_errors(self, tmp_path):
        def _boom(request):
            raise RuntimeError("daemon 没了")

        executor = _executor(tmp_path, transport=httpx.MockTransport(_boom))
        asyncio.run(executor.cleanup(make_spec(tmp_path)))  # 不抛异常
