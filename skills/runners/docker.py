# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Docker 沙盒 runner：按调用创建受限容器执行抽象动作。

容器级硬约束（plan §6.4）——全部在 ``_container_config`` 里落地：

* 非 root 数字 UID（65532）运行，``ReadonlyRootfs`` 只读根文件系统；
* ``no-new-privileges`` + ``CapDrop=ALL``；``PidsLimit``/``Memory``/
  ``NanoCpus`` 来自 ``SandboxLimits``；``/tmp`` 用有大小上限的 tmpfs；
* ``NetworkMode=none``：进程内 runner **只支持无网络**。配置允许开网络
  是给外置 sidecar runner 预留的——本 runner 遇到 ``network_enabled``
  直接 policy 拒绝，不假装有白名单执行能力；
* workspace 目录只读绑定技能源；**绝不**挂载项目根、.env、记忆库、
  插件目录、Docker socket 或宿主用户目录。

端点边界：与 Docker daemon 的通信走 ``DOCKER_HOST``（tcp/http 代理端点）
或 POSIX socket。**部署上不给 Stella 容器挂 /var/run/docker.sock**——
需要 runner 时用 sidecar/代理端点（docs/skills.md 部署节）。Windows
命名管道无 httpx 传输支持：默认探测不可用，属明确降级而非猜测。

每个动作一个容器（动作间隔离），workspace 目录跨动作保留以串联产物。
任何 API 失败都折叠为带原因的失败 outcome；容器删除尽力而为并审计。
"""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from skills.audit import audit
from skills.model import (
    SandboxAction,
    SandboxActionOutcome,
    SandboxSpec,
    safe_relative_path,
)
from skills.sandbox import SandboxAvailability, validate_spec

BACKEND_DOCKER = "docker"
# 非 root 数字 UID（未在镜像内声明的确定性 UID，无 home、无特权组映射）
_SANDBOX_UID_GID = "65532:65532"
_CONTAINER_NAME_PREFIX = "stella-sb-"
_POSIX_SOCKET = "/var/run/docker.sock"
_POSIX_ENDPOINT = f"unix://{_POSIX_SOCKET}"
_API_VERSION = "v1.41"
_OUTPUT_HARD_CAP = 1024 * 1024  # demux 层的绝对上限，之后按预算再截

_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def default_endpoint() -> str:
    """Docker API 端点：显式 DOCKER_HOST 优先；POSIX 回落 socket。

    Windows 默认命名管道（npipe）httpx 不支持——返回占位并在探测时
    给出可诊断原因，由部署者改配 DOCKER_HOST 指向远程 runner。
    """
    import os
    import sys

    host = os.getenv("DOCKER_HOST", "").strip()
    if host:
        return host
    if sys.platform == "win32":
        return "npipe:////./pipe/docker_engine"
    return _POSIX_ENDPOINT


def _transport_for(endpoint: str) -> httpx.AsyncHTTPTransport:
    if endpoint.startswith("unix://"):
        return httpx.AsyncHTTPTransport(uds=endpoint[len("unix://") :])
    return httpx.AsyncHTTPTransport()


def _base_url(endpoint: str) -> str:
    if endpoint.startswith("unix://"):
        return "http://docker"  # socket 传输的占位主机名，路径才承载语义
    if endpoint.startswith(("http://", "https://")):
        return endpoint.rstrip("/")
    return "http://docker"


def _action_command(action: SandboxAction) -> list[str] | None:
    """把抽象动作翻译成容器内 argv（POSIX、全部落在 /workspace 语义下）。

    返回 None 表示动作不可翻译（未知动作/参数缺失/路径越界）。
    content 类参数走 argv 而不是拼进 shell 字符串——规划模型给的参数
    不可信，绝不让它接触 shell 语法。
    """
    args = action.args
    if action.action == "run_shell":
        command = args.get("command", "").strip()
        if not command:
            return None
        return ["/bin/sh", "-c", command]
    if action.action == "run_python":
        code = args.get("code", "")
        if not code.strip():
            return None
        return ["python3", "-c", code]
    if action.action == "read_file":
        rel = safe_relative_path(args.get("path", ""))
        if rel is None:
            return None
        return ["cat", str(PurePosixPath("/workspace") / rel)]
    if action.action == "write_file":
        rel = safe_relative_path(args.get("path", ""))
        content = args.get("content")
        if rel is None or content is None:
            return None
        return [
            "python3",
            "-c",
            "import sys; open(sys.argv[1], 'w', encoding='utf-8').write(sys.argv[2])",
            str(PurePosixPath("/workspace") / rel),
            content,
        ]
    if action.action == "list_files":
        rel = safe_relative_path(args.get("path", "") or ".")
        if rel is None:
            return None
        return [
            "find",
            str(PurePosixPath("/workspace") / rel),
            "-maxdepth",
            "2",
            "-not",
            "-path",
            "*/.git*",
        ]
    return None


def _demux_docker_stream(data: bytes) -> str:
    """还原 Docker 多路复用日志流（8 字节帧头）；TTY 流原样解码。"""
    parts: list[str] = []
    i = 0
    while i + 8 <= len(data):
        size = int.from_bytes(data[i + 4 : i + 8], "big")
        stream_type = data[i]
        chunk = data[i + 8 : i + 8 + size]
        if stream_type in (1, 2) and chunk:
            parts.append(chunk.decode("utf-8", "replace"))
        i += 8 + size
    if not parts and data:
        return data.decode("utf-8", "replace")
    return "".join(parts)


class DockerSandboxExecutor:
    """按调用创建受限容器的执行器。动作失败不抛异常，折叠为 outcome。"""

    backend = BACKEND_DOCKER

    def __init__(
        self,
        *,
        image: str,
        workspace_root: Path,
        network_enabled: bool = False,
        network_allowlist: tuple[str, ...] = (),
        endpoint: str | None = None,
        transport: Any | None = None,
        api_timeout: float = 10.0,
    ) -> None:
        self._image = image
        self._workspace_root = Path(workspace_root)
        self._network_enabled = network_enabled
        self._network_allowlist = network_allowlist
        self._endpoint = endpoint or default_endpoint()
        self._transport = transport
        self._api_timeout = api_timeout

    # ---------- 能力探测 ----------

    def availability(self) -> SandboxAvailability:
        endpoint = self._endpoint
        if endpoint.startswith("npipe://"):
            return SandboxAvailability(
                backend=self.backend,
                available=False,
                reason="Windows 命名管道端点不受进程内 runner 支持；"
                "请将 DOCKER_HOST 指向远程/代理 runner",
            )
        try:
            with httpx.Client(
                transport=self._transport or _sync_transport(endpoint),
                base_url=_base_url(endpoint),
                timeout=2.0,
            ) as client:
                resp = client.get(f"/{_API_VERSION}/_ping")
            if resp.status_code == 200:
                return SandboxAvailability(
                    backend=self.backend, available=True, reason="Docker daemon 可达"
                )
            return SandboxAvailability(
                backend=self.backend,
                available=False,
                reason=f"Docker API 返回 HTTP {resp.status_code}",
            )
        except Exception as exc:
            return SandboxAvailability(
                backend=self.backend,
                available=False,
                reason=f"Docker daemon 不可达（{endpoint}）: {exc}",
            )

    # ---------- 执行 ----------

    async def execute(
        self, spec: SandboxSpec, action: SandboxAction
    ) -> SandboxActionOutcome:
        problems = validate_spec(spec, workspace_root=self._workspace_root)
        if problems:
            audit().emit(
                "sandbox_policy_denied",
                invocation_id=spec.invocation_id,
                session=spec.session_id,
                action=action.action,
                problems=";".join(problems),
            )
            return SandboxActionOutcome(
                action=action.action, ok=False, error_code="policy_denied"
            )
        if spec.network_enabled:
            # 进程内 runner 不具名配额与白名单执行能力：fail-closed
            audit().emit(
                "sandbox_policy_denied",
                invocation_id=spec.invocation_id,
                session=spec.session_id,
                action=action.action,
                problems="进程内 Docker runner 仅支持无网络执行；"
                "网络白名单需要外置 runner",
                policy_version="v1-no-network",
            )
            return SandboxActionOutcome(
                action=action.action, ok=False, error_code="policy_denied"
            )
        command = _action_command(action)
        if command is None:
            audit().emit(
                "sandbox_action_invalid",
                invocation_id=spec.invocation_id,
                action=action.action,
            )
            return SandboxActionOutcome(
                action=action.action, ok=False, error_code="policy_denied"
            )
        try:
            output = await self._run_container(spec, command)
        except asyncio.TimeoutError:
            audit().emit(
                "sandbox_timeout",
                invocation_id=spec.invocation_id,
                action=action.action,
                timeout=spec.limits.timeout_seconds,
            )
            return SandboxActionOutcome(
                action=action.action,
                ok=False,
                error_code="timeout",
                output=f"动作超时（{spec.limits.timeout_seconds:.0f}s）",
            )
        except Exception as exc:
            audit().emit(
                "sandbox_error",
                invocation_id=spec.invocation_id,
                action=action.action,
                reason=str(exc)[:500],
            )
            return SandboxActionOutcome(
                action=action.action, ok=False, error_code="sandbox_unavailable"
            )
        if len(output) >= spec.limits.output_max_chars:
            audit().emit(
                "sandbox_output_truncated",
                invocation_id=spec.invocation_id,
                action=action.action,
            )
        artifact = _artifact_of(action) if action.action == "write_file" else None
        return SandboxActionOutcome(
            action=action.action,
            ok=True,
            output=output[: spec.limits.output_max_chars],
            artifact=artifact,
        )

    async def cleanup(self, spec: SandboxSpec) -> None:
        """删除残留容器（正常路径容器已被删）。尽力而为，不抛异常。"""
        name = _container_name(spec.invocation_id)
        try:
            async with self._client() as client:
                await client.delete(
                    f"/{_API_VERSION}/containers/{name}", params={"force": "true"}
                )
            audit().emit(
                "sandbox_cleanup",
                invocation_id=spec.invocation_id,
                container=name,
            )
        except Exception:
            pass

    # ---------- Docker API ----------

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport or _transport_for(self._endpoint),
            base_url=_base_url(self._endpoint),
            timeout=httpx.Timeout(self._api_timeout),
        )

    async def _run_container(self, spec: SandboxSpec, command: list[str]) -> str:
        """create → start → wait(限时) → logs → rm；返回截断前的输出。"""
        name = _container_name(spec.invocation_id)
        config = _container_config(spec, command, self._image)
        async with self._client() as client:
            created = await client.post(
                f"/{_API_VERSION}/containers/create",
                params={"name": name},
                json=config,
            )
            if created.status_code == 404:
                raise RuntimeError(
                    f"镜像 {self._image} 不存在，请先手动拉取（沙盒不自动拉镜像）"
                )
            if created.status_code >= 400:
                raise RuntimeError(f"容器创建失败 HTTP {created.status_code}")
            container_id = (created.json() or {}).get("Id", "")
            if not container_id:
                raise RuntimeError("容器创建响应缺少 Id")
            audit().emit(
                "sandbox_start",
                invocation_id=spec.invocation_id,
                container=name,
                image=self._image,
                network="none",
                policy_version="v1-no-network",
                cpu=spec.limits.cpu,
                memory_mb=spec.limits.memory_mb,
                pids=spec.limits.pids,
                timeout=spec.limits.timeout_seconds,
            )
            started = await client.post(
                f"/{_API_VERSION}/containers/{container_id}/start"
            )
            if started.status_code >= 400:
                raise RuntimeError(f"容器启动失败 HTTP {started.status_code}")
            try:
                waited = await asyncio.wait_for(
                    client.post(
                        f"/{_API_VERSION}/containers/{container_id}/wait",
                        timeout=httpx.Timeout(
                            spec.limits.timeout_seconds + self._api_timeout
                        ),
                    ),
                    timeout=spec.limits.timeout_seconds,
                )
            except asyncio.TimeoutError:
                await client.delete(
                    f"/{_API_VERSION}/containers/{container_id}",
                    params={"force": "true"},
                )
                raise
            if waited.status_code >= 400:
                raise RuntimeError(f"容器等待失败 HTTP {waited.status_code}")
            logs = await client.get(
                f"/{_API_VERSION}/containers/{container_id}/logs",
                params={"stdout": "true", "stderr": "true", "tail": "4096"},
            )
            output = _demux_docker_stream(logs.content)
            await client.delete(
                f"/{_API_VERSION}/containers/{container_id}",
                params={"force": "true", "v": "true"},
            )
        return output[:_OUTPUT_HARD_CAP]


def _sync_transport(endpoint: str) -> httpx.HTTPTransport:
    if endpoint.startswith("unix://"):
        return httpx.HTTPTransport(uds=endpoint[len("unix://") :])
    return httpx.HTTPTransport()


def _container_name(invocation_id: str) -> str:
    safe = _NAME_RE.sub("-", invocation_id)[:48] or uuid.uuid4().hex[:16]
    return f"{_CONTAINER_NAME_PREFIX}{safe}"


def _artifact_of(action: SandboxAction):
    from skills.model import ArtifactRef

    rel = safe_relative_path(action.args.get("path", ""))
    if rel is None:
        return None
    return ArtifactRef(path=str(rel), size_bytes=len(action.args.get("content", "")))


def _container_config(
    spec: SandboxSpec, command: list[str], image: str
) -> dict[str, Any]:
    """受限容器配置。这里的每个字段都是安全边界，改动须过安全评审。"""
    limits = spec.limits
    binds = [f"{spec.workspace}:/workspace"]
    for host_path, container_path in spec.read_only_mounts:
        binds.append(f"{host_path}:{container_path}:ro")
    return {
        "Image": image,
        "Cmd": command,
        "User": _SANDBOX_UID_GID,
        "WorkingDir": "/workspace",
        "Tty": False,
        "NetworkDisabled": True,
        "HostConfig": {
            "Binds": binds,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "PidsLimit": limits.pids,
            "Memory": int(limits.memory_mb) * 1024 * 1024,
            "NanoCpus": int(limits.cpu * 1_000_000_000),
            "NetworkMode": "none",
            "Tmpfs": {
                "/tmp": f"rw,noexec,nosuid,size={min(64, max(8, limits.memory_mb // 4))}m"
            },
        },
    }
