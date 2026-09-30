# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""cometa 的 typed 配置（方案 §6.13）。

两层配置，各管各的：

- **环境变量**（``COMETA_*``）：总开关、模式、路径与运维上限。解析在
  :meth:`CometaConfig.load` 里直接读传入的 env 映射——独立 worker 进程
  （``python -m cometa.worker``）与 Bot 进程共用这一份逻辑，不依赖 Bot 的
  ``config.settings``（那会连带加载 .env 与 nonebot 侧初始化）；
- **TOML 详细配置**（``STELLA_HOME/config/cometa.toml``）：后端、工作区、
  profile 与访问白名单。解析失败**抛** :class:`CometaConfigError`——
  配置坏了宁可停用 cometa 也不能带错权限跑（fail-closed）。

``config_hash`` 是 TOML 原始字节的 sha256：服务与 worker 必须持同一版本
（方案 §6.13「单一真源」）；配置调整不得静默扩大在途任务权限。
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import SCHEMA_VERSION


class CometaConfigError(RuntimeError):
    """TOML 配置非法。调用方必须停用 cometa，不得带病运行。"""


def _env_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = (env.get(key) or "").strip().strip("\"'").lower()
    if not raw:
        return default
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def _env_int(env: dict[str, str], key: str, default: int) -> int:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(env: dict[str, str], key: str, default: float) -> float:
    raw = (env.get(key) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(env: dict[str, str], key: str, default: str) -> str:
    return (env.get(key) or "").strip() or default


def _resolve_stella_home(env: dict[str, str]) -> Path:
    """定位用户数据根。Bot 进程与 worker 都靠 ``STELLA_HOME``；
    未设置时回退 Bot 的 config.home（同机部署它们一致）。"""
    raw = (env.get("STELLA_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        from config.home import resolve

        root = resolve(Path(__file__).resolve().parent.parent)
        return Path(root.path).expanduser().resolve()
    except Exception:  # pragma: no cover - 部署异常兜底
        cwd = Path.cwd()
        return (cwd / "StellaData").resolve()


def _parse_int_list(raw: list, field_name: str) -> set[int]:
    result: set[int] = set()
    for item in raw:
        try:
            result.add(int(item))
        except (TypeError, ValueError):
            raise CometaConfigError(
                f"access.{field_name} 含非法整数项 {item!r}"
            ) from None
    return result


@dataclass(slots=True)
class LimitsConfig:
    """[limits]：并发与保留上限（方案 §6.13 TOML 示例的默认值）。"""

    per_user_active: int = 1
    per_group_active: int = 2
    input_wait_seconds: float = 600.0
    artifact_max_bytes: int = 20 * 1024 * 1024
    artifact_total_max_bytes: int = 100 * 1024 * 1024
    retention_days: float = 7.0

    @classmethod
    def from_toml(cls, data: dict) -> "LimitsConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise CometaConfigError(f"[limits] 含未知键: {sorted(unknown)}")
        return cls(
            per_user_active=int(data.get("per_user_active", 1)),
            per_group_active=int(data.get("per_group_active", 2)),
            input_wait_seconds=float(data.get("input_wait_seconds", 600.0)),
            artifact_max_bytes=int(data.get("artifact_max_bytes", 20 * 1024 * 1024)),
            artifact_total_max_bytes=int(
                data.get("artifact_total_max_bytes", 100 * 1024 * 1024)
            ),
            retention_days=float(data.get("retention_days", 7.0)),
        )


@dataclass(slots=True)
class BackendConfig:
    """[backends.<id>]。capabilities 只是**期望能力**；probe 未通过的能力
    不可路由（方案 §6.13）。"""

    backend_id: str
    type: str
    enabled: bool = True
    transport: str = "stdio"
    executable: str = ""
    auth_profile: str = ""
    model: str = ""  # 空 = 后端账号的配置默认值
    capabilities: list[str] = field(default_factory=list)
    # 传给后端子进程的额外环境变量（如代理：HTTP_PROXY/HTTPS_PROXY）。
    # codex 类型经 SDK CodexConfig(env=...) 注入 app-server；部署里写这比
    # 依赖 bot 终端的环境变量可靠（worker 是独立子进程）。
    env: dict[str, str] = field(default_factory=dict)
    # 仅 type="fake" 可用的演示行为（人工验收脚本；正式后端必须留空）：
    #   complete = 按脚本直接完成；fail = 按脚本失败；
    #   input   = 先请求补充信息、答复后完成；hang/空 = 流挂起直到取消
    fake_behavior: str = ""

    @classmethod
    def from_toml(cls, backend_id: str, data: dict) -> "BackendConfig":
        if not isinstance(data, dict):
            raise CometaConfigError(f"[backends.{backend_id}] 必须是表")
        known = {
            "type", "enabled", "transport", "executable", "auth_profile", "model",
            "capabilities", "fake_behavior", "env",
        }
        unknown = set(data) - known
        if unknown:
            raise CometaConfigError(f"[backends.{backend_id}] 含未知键: {sorted(unknown)}")
        btype = str(data.get("type", "")).strip()
        if not btype:
            raise CometaConfigError(f"[backends.{backend_id}] 缺少 type")
        fake_behavior = str(data.get("fake_behavior", "")).strip()
        if fake_behavior and btype != "fake":
            raise CometaConfigError(
                f"[backends.{backend_id}] fake_behavior 只允许 type=\"fake\" 的后端使用"
            )
        if fake_behavior not in ("", "complete", "fail", "input", "hang"):
            raise CometaConfigError(
                f"[backends.{backend_id}] fake_behavior 只支持"
                " complete/fail/input/hang（空=挂起）"
            )
        return cls(
            backend_id=backend_id,
            type=btype,
            enabled=bool(data.get("enabled", True)),
            transport=str(data.get("transport", "stdio")),
            executable=str(data.get("executable", "")),
            auth_profile=str(data.get("auth_profile", "")),
            model=str(data.get("model", "")),
            capabilities=[str(c) for c in (data.get("capabilities") or [])],
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            fake_behavior=fake_behavior,
        )


@dataclass(slots=True)
class WorkspaceConfig:
    """[workspaces.<id>]：管理员声明 workspace_id → 允许的仓库根路径。
    用户提交的是 ID；模型不能指定任意 cwd（方案 §6.9）。"""

    workspace_id: str
    repository: Path
    base_ref: str = "HEAD"
    mode: str = "worktree"  # worktree | directory

    @classmethod
    def from_toml(cls, workspace_id: str, data: dict) -> "WorkspaceConfig":
        if not isinstance(data, dict):
            raise CometaConfigError(f"[workspaces.{workspace_id}] 必须是表")
        known = {"repository", "base_ref", "mode"}
        unknown = set(data) - known
        if unknown:
            raise CometaConfigError(f"[workspaces.{workspace_id}] 含未知键: {sorted(unknown)}")
        repo = str(data.get("repository", "")).strip()
        if not repo:
            raise CometaConfigError(f"[workspaces.{workspace_id}] 缺少 repository")
        mode = str(data.get("mode", "worktree"))
        if mode not in ("worktree", "directory"):
            raise CometaConfigError(
                f"[workspaces.{workspace_id}] mode 只支持 worktree/directory，得到 {mode!r}"
            )
        return cls(
            workspace_id=workspace_id,
            repository=Path(repo).expanduser().resolve(),
            base_ref=str(data.get("base_ref", "HEAD")),
            mode=mode,
        )


@dataclass(slots=True)
class ProfileConfig:
    """[profiles.<name>]：后端 + 工作区 + 权限差量（方案 §6.9）。"""

    name: str
    backend: str
    workspace: str = ""
    allow_network: bool = False
    allow_workspace_write: bool = False

    @classmethod
    def from_toml(cls, name: str, data: dict) -> "ProfileConfig":
        if not isinstance(data, dict):
            raise CometaConfigError(f"[profiles.{name}] 必须是表")
        known = {"backend", "workspace", "allow_network", "allow_workspace_write"}
        unknown = set(data) - known
        if unknown:
            raise CometaConfigError(f"[profiles.{name}] 含未知键: {sorted(unknown)}")
        backend = str(data.get("backend", "")).strip()
        if not backend:
            raise CometaConfigError(f"[profiles.{name}] 缺少 backend")
        return cls(
            name=name,
            backend=backend,
            workspace=str(data.get("workspace", "")),
            allow_network=bool(data.get("allow_network", False)),
            allow_workspace_write=bool(data.get("allow_workspace_write", False)),
        )


@dataclass(slots=True)
class AccessConfig:
    """[access]：QQ 用户/群与操作员白名单。**空列表表示未授权**；
    WebUI 管理员走现有认证，不在本表内（方案 §6.13）。"""

    qq_user_ids: set[int] = field(default_factory=set)
    qq_group_ids: set[int] = field(default_factory=set)
    operator_user_ids: set[int] = field(default_factory=set)

    @classmethod
    def from_toml(cls, data: dict) -> "AccessConfig":
        if not isinstance(data, dict):
            raise CometaConfigError("[access] 必须是表")
        known = {"qq_user_ids", "qq_group_ids", "operator_user_ids"}
        unknown = set(data) - known
        if unknown:
            raise CometaConfigError(f"[access] 含未知键: {sorted(unknown)}")
        return cls(
            qq_user_ids=_parse_int_list(data.get("qq_user_ids") or [], "qq_user_ids"),
            qq_group_ids=_parse_int_list(data.get("qq_group_ids") or [], "qq_group_ids"),
            operator_user_ids=_parse_int_list(
                data.get("operator_user_ids") or [], "operator_user_ids"
            ),
        )


@dataclass(slots=True)
class CometaConfig:
    """cometa 总配置。``load()`` 是唯一构造入口（Bot 进程与 worker 共用）。"""

    enabled: bool = False
    delegation_mode: str = "explicit"  # explicit | auto
    db_path: Path = Path("cometa/tasks.db")
    artifacts_dir: Path = Path("cometa/artifacts")
    config_path: Path = Path("config/cometa.toml")
    max_concurrent: int = 2
    submit_timeout_seconds: float = 2.0
    task_timeout_seconds: float = 1800.0
    progress_interval_seconds: float = 120.0
    result_max_chars: int = 2000
    lease_seconds: float = 30.0
    lease_renew_seconds: float = 5.0
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    backends: dict[str, BackendConfig] = field(default_factory=dict)
    workspaces: dict[str, WorkspaceConfig] = field(default_factory=dict)
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    access: AccessConfig = field(default_factory=AccessConfig)
    # 显式委派命令未指明 profile 时使用的默认项（必须引用已定义的 profile；
    # 空 = 仅当恰好定义了一个 profile 时才可省略）。QQ 委派命令没有 profile
    # 槽位，多 profile 部署没有默认项时命令必然被拒（2026-09-30 用户实测）。
    default_profile: str = ""

    config_hash: str = ""  # TOML 原始字节的 sha256；空 = 无 TOML 文件

    # ── 便捷查询 ─────────────────────────────────────────
    def backend_of(self, backend_id: str) -> BackendConfig | None:
        return self.backends.get(backend_id)

    def profile_of(self, name: str) -> ProfileConfig | None:
        return self.profiles.get(name)

    def workspace_of(self, workspace_id: str) -> WorkspaceConfig | None:
        return self.workspaces.get(workspace_id)

    def enabled_backends(self) -> list[BackendConfig]:
        return [b for b in self.backends.values() if b.enabled]

    def validate_references(self) -> None:
        """profile 引用的 backend/workspace 必须存在（启动期 fail-closed）。"""
        if self.default_profile and self.default_profile not in self.profiles:
            raise CometaConfigError(
                f"default_profile 引用了未定义的 profile {self.default_profile!r}"
            )
        for profile in self.profiles.values():
            if profile.backend not in self.backends:
                raise CometaConfigError(
                    f"[profiles.{profile.name}] 引用了未定义的后端 {profile.backend!r}"
                )
            if profile.workspace and profile.workspace not in self.workspaces:
                raise CometaConfigError(
                    f"[profiles.{profile.name}] 引用了未定义的工作区 {profile.workspace!r}"
                )

    # ── 构造 ─────────────────────────────────────────────
    @classmethod
    def load(cls, env: dict[str, str] | None = None) -> "CometaConfig":
        """从环境变量 + TOML 文件加载。TOML 缺失 = 只有默认值（功能仍可用，
        但没有后端/工作区/profile 可路由）；TOML 非法 = 抛错停用。"""
        env = dict(env) if env is not None else dict(os.environ)
        home = _resolve_stella_home(env)

        config_rel = _env_str(env, "COMETA_CONFIG_FILE", "cometa.toml")
        config_path = Path(config_rel)
        if not config_path.is_absolute():
            config_path = home / "config" / config_rel

        db_rel = _env_str(env, "COMETA_DB_PATH", "")
        db_path = Path(db_rel) if db_rel else home / "cometa" / "tasks.db"
        if not db_path.is_absolute():
            db_path = home / db_rel

        artifacts_dir = db_path.parent / "artifacts"

        cfg = cls(
            enabled=_env_bool(env, "COMETA_ENABLED", False),
            delegation_mode=_env_str(env, "COMETA_DELEGATION_MODE", "explicit"),
            db_path=db_path,
            artifacts_dir=artifacts_dir,
            config_path=config_path,
            max_concurrent=max(1, _env_int(env, "COMETA_MAX_CONCURRENT", 2)),
            submit_timeout_seconds=max(0.5, _env_float(env, "COMETA_SUBMIT_TIMEOUT_SECONDS", 2.0)),
            task_timeout_seconds=max(60.0, _env_float(env, "COMETA_TASK_TIMEOUT_SECONDS", 1800.0)),
            progress_interval_seconds=max(
                10.0, _env_float(env, "COMETA_PROGRESS_INTERVAL_SECONDS", 120.0)
            ),
            result_max_chars=max(200, _env_int(env, "COMETA_RESULT_MAX_CHARS", 2000)),
        )
        if cfg.delegation_mode not in ("explicit", "auto"):
            cfg.delegation_mode = "explicit"

        raw = cls._read_toml(config_path)
        if raw is not None:
            cfg._apply_toml(raw)
        cfg.validate_references()
        return cfg

    @staticmethod
    def _read_toml(path: Path) -> dict | None:
        if not path.is_file():
            return None
        try:
            import tomllib
        except ImportError:  # Py3.10 回退，与 config/spaces.py 同款
            import tomli as tomllib
        raw_bytes = path.read_bytes()
        try:
            data = tomllib.loads(raw_bytes.decode("utf-8"))
        except Exception as e:
            raise CometaConfigError(f"cometa.toml 解析失败 ({path}): {e}") from e
        if not isinstance(data, dict):
            raise CometaConfigError("cometa.toml 顶层必须是表")
        data["_raw_sha256"] = hashlib.sha256(raw_bytes).hexdigest()
        return data

    def _apply_toml(self, data: dict) -> None:
        self.config_hash = str(data.get("_raw_sha256", ""))
        schema_version = int(data.get("schema_version", SCHEMA_VERSION))
        if schema_version != SCHEMA_VERSION:
            raise CometaConfigError(
                f"cometa.toml schema_version={schema_version} 与本程序支持的 "
                f"{SCHEMA_VERSION} 不一致，拒绝加载"
            )
        known_top = {
            "schema_version",
            "limits",
            "backends",
            "workspaces",
            "profiles",
            "access",
            "default_profile",
            "_raw_sha256",
        }
        unknown = set(data) - known_top
        if unknown:
            raise CometaConfigError(f"cometa.toml 含未知顶层键: {sorted(unknown)}")
        if "limits" in data:
            self.limits = LimitsConfig.from_toml(data["limits"])
        for backend_id, payload in (data.get("backends") or {}).items():
            backend = BackendConfig.from_toml(str(backend_id), payload)
            self.backends[backend.backend_id] = backend
        for workspace_id, payload in (data.get("workspaces") or {}).items():
            workspace = WorkspaceConfig.from_toml(str(workspace_id), payload)
            self.workspaces[workspace.workspace_id] = workspace
        for name, payload in (data.get("profiles") or {}).items():
            profile = ProfileConfig.from_toml(str(name), payload)
            self.profiles[profile.name] = profile
        if "access" in data:
            self.access = AccessConfig.from_toml(data["access"])
        self.default_profile = str(data.get("default_profile", "")).strip()


__all__ = [
    "AccessConfig",
    "BackendConfig",
    "CometaConfig",
    "CometaConfigError",
    "LimitsConfig",
    "ProfileConfig",
    "WorkspaceConfig",
]
