# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""codex 认证唯一真源：托管 codex_home 的解析、状态判定与凭据写入。

设计要点（docs/plans/2026-10-01-gitnexus-plan-cometa-codex-auth-webui.md §6 C1）：

- 每后端托管 home：``STELLA_HOME/cometa/codex_home/<backend_id>/``；toml
  ``[backends.<id>.env]`` 显式声明 ``CODEX_HOME`` 时以声明为准。
- 认证是**凭据**不是路由配置：不进 cometa.toml，因此不进 config_hash——
  改认证不触碰在途任务一致性守卫，且 probe/任务启动现读现用（免重启）。
- probe 与 ``_build_codex`` 必须经本模块解析**同一路径**（消除「bot 进程
  env vs toml 透传 env」两处解析不一致的潜伏缺陷）。
- 秘密纪律：key/token 只落 auth.json 与 stella_credentials.json；本模块
  对外状态不携带原文（WebUI 只回 ``has_api_key`` 布尔）。

模式（:func:`auth_state`）：``ready_custom | ready_chatgpt | ready_api_key |
legacy | none``。T-0 实证（openai-codex 0.159.2，2026-10-01）：

- ``login_api_key`` 写 ``CODEX_HOME/auth.json``，形状 ``{OPENAI_API_KEY,
  auth_mode}``；
- 自定义 provider **必须** ``wire_api = "responses"``（"chat" 已被移除，
  加载即拒绝）；
- 设备码登录 start 经代理可达，返回 verification_url + user_code。

登录包装（login/device-code）按需 lazy import SDK；CI 无可选 SDK 时这些
函数报 :class:`CodexAuthUnavailable`，文件面函数（解析/判定/写入）不依赖
SDK，单测全覆盖。
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ImportError:  # Py3.10 回退，与 cometa/config.py 同款
    import tomli as tomllib

from cometa.config import BackendConfig

# 注入 app-server 的 API key 环境变量名（codex config.toml env_key 指向它）。
CODEX_API_KEY_ENV = "STELLA_CODEX_API_KEY"
# 自定义 provider 在 codex config.toml 里的 provider id（Stella 专用命名）。
CUSTOM_PROVIDER_ID = "stella_custom"
AUTH_FILENAME = "auth.json"
CONFIG_FILENAME = "config.toml"
CREDENTIAL_FILENAME = "stella_credentials.json"

# codex 0.159.2 已移除 chat wire API；自定义端点必须实现 OpenAI Responses API。
CUSTOM_WIRE_API = "responses"

_SDK_IMPORT_NAME = "openai_codex"


class CodexAuthUnavailable(RuntimeError):  # noqa: N818 - 可用性信号，不是错误
    """SDK 缺失或登录流不可用（fail-closed，不是降级信号）。"""


@dataclass(slots=True)
class CodexAuthState:
    """认证状态判定结果。reason 面向用户；**永不**包含凭据原文。"""

    mode: str  # ready_custom | ready_chatgpt | ready_api_key | legacy | none
    reason: str = ""
    has_api_key: bool = False

    @property
    def ready(self) -> bool:
        return self.mode in ("ready_custom", "ready_chatgpt", "ready_api_key")


# ── home 解析（probe 与 _build_codex 的共同真源）──────────────────


def default_stella_home() -> Path:
    """数据根定位（与 cometa.config 同一规则；env 优先，回落 config.home）。"""
    from cometa.config import _resolve_stella_home

    return _resolve_stella_home(dict(os.environ))


def codex_home_for(backend: BackendConfig, stella_home: Path | None = None) -> Path:
    """该 backend 的 codex home。toml env 显式声明 CODEX_HOME 时以声明为准。"""
    explicit = (backend.env.get("CODEX_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    root = stella_home if stella_home is not None else default_stella_home()
    return root / "cometa" / "codex_home" / backend.backend_id


def legacy_auth_home() -> Path:
    """旧版（升级前）认证位置：进程 CODEX_HOME 或 ~/.codex（codex login 产物）。"""
    custom = os.getenv("CODEX_HOME", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".codex"


def legacy_auth_available() -> bool:
    return (legacy_auth_home() / AUTH_FILENAME).is_file()


# ── 状态判定 ─────────────────────────────────────────────


def _read_json(path: Path) -> dict | None:
    """容错 JSON 读取：缺失/损坏一律 None（损坏必须有可读 reason，由调用方补）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _custom_config_present(home: Path) -> bool:
    """托管 home 的 config.toml 是否声明了 Stella 自定义 provider。"""
    try:
        data = tomllib.loads((home / CONFIG_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return str(data.get("model_provider", "")) == CUSTOM_PROVIDER_ID


def auth_state(backend: BackendConfig, stella_home: Path | None = None) -> CodexAuthState:
    """判定该 backend 当前认证状态（文件面，纯函数式，无网络调用）。"""
    home = codex_home_for(backend, stella_home)
    credential = _read_json(home / CREDENTIAL_FILENAME)
    if credential is not None or _custom_config_present(home):
        if credential is not None and _custom_config_present(home):
            return CodexAuthState(
                mode="ready_custom",
                reason="使用自定义端点（codex config.toml + 托管凭据）",
                has_api_key=bool(credential.get("api_key")),
            )
        missing = "凭据文件" if credential is None else "config.toml"
        return CodexAuthState(
            mode="none",
            reason=f"自定义端点配置不完整：缺少 {missing}（{home}）；请在 WebUI 重新配置",
        )
    auth_path = home / AUTH_FILENAME
    if auth_path.is_file():
        auth = _read_json(auth_path)
        if auth is None:
            return CodexAuthState(
                mode="none",
                reason=f"认证文件损坏（{auth_path}）；请在 WebUI 重新配置",
            )
        tokens = auth.get("tokens")
        if isinstance(tokens, dict) and tokens:
            return CodexAuthState(
                mode="ready_chatgpt", reason="已通过 ChatGPT 账号登录", has_api_key=True
            )
        if auth.get("OPENAI_API_KEY"):
            return CodexAuthState(
                mode="ready_api_key", reason="已通过 API key 登录", has_api_key=True
            )
        return CodexAuthState(
            mode="none",
            reason=f"认证文件损坏或为空（{home / AUTH_FILENAME}）；请在 WebUI 重新配置",
        )
    if legacy_auth_available():
        return CodexAuthState(
            mode="legacy",
            reason=(
                f"发现旧版认证（{legacy_auth_home() / AUTH_FILENAME}），"
                "托管后端尚不可用；可在 WebUI 一键迁移或重新配置"
            ),
        )
    return CodexAuthState(
        mode="none",
        reason=f"未配置认证（{home}）；请在 WebUI cometa 页配置账号登录或自定义端点",
    )


# ── 自定义端点写入（codex 原生 config.toml + Stella 凭据文件）────────


def _toml_str(value: str) -> str:
    """TOML basic string 转义。TOML basic string 的转义集是 JSON 子集，
    值域（URL/模型名）内 json.dumps 产出即合法 TOML。"""
    return json.dumps(value, ensure_ascii=False)


def read_custom_credential(backend: BackendConfig, stella_home: Path | None = None) -> dict | None:
    """读托管凭据（内部用：apply 空串回填）。**返回值不得进任何响应/日志。**"""
    return _read_json(codex_home_for(backend, stella_home) / CREDENTIAL_FILENAME)


def write_custom_endpoint(
    home: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    wire_api: str = CUSTOM_WIRE_API,
) -> None:
    """把自定义端点写进托管 home（codex 原生 config.toml + Stella 凭据文件）。

    覆盖式写入是该 home 的语义（它是 Stella 托管的，不是用户手写区）；
    api_key 为空串时仅更新端点结构而**不新建**空凭据（调用方先回填旧值）。
    """
    base_url = base_url.strip()
    model = model.strip()
    wire_api = wire_api.strip() or CUSTOM_WIRE_API
    if not base_url:
        raise ValueError("base_url 不能为空")
    if not model:
        raise ValueError("model 不能为空（codex 自定义 provider 需要显式模型名）")
    home.mkdir(parents=True, exist_ok=True)
    config_text = (
        f"model = {_toml_str(model)}\n"
        f'model_provider = "{CUSTOM_PROVIDER_ID}"\n'
        "\n"
        f"[model_providers.{CUSTOM_PROVIDER_ID}]\n"
        'name = "Stella Custom Endpoint"\n'
        f"base_url = {_toml_str(base_url)}\n"
        f'env_key = "{CODEX_API_KEY_ENV}"\n'
        f"wire_api = {_toml_str(wire_api)}\n"
    )
    (home / CONFIG_FILENAME).write_text(config_text, encoding="utf-8")
    if api_key:
        cred_path = home / CREDENTIAL_FILENAME
        cred_path.write_text(
            json.dumps(
                {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "wire_api": wire_api,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        with contextlib.suppress(OSError):
            cred_path.chmod(0o600)  # POSIX 生效；Windows 尽力而为


def clear_managed_auth(home: Path) -> None:
    """登出 = 删除托管 home 的 auth.json（自定义端点配置不受影响）。"""
    with contextlib.suppress(FileNotFoundError):
        (home / AUTH_FILENAME).unlink()


def migrate_legacy_auth(backend: BackendConfig, stella_home: Path | None = None) -> Path:
    """把旧版 auth.json（可选连同 config.toml）复制进托管 home。仅显式触发。"""
    target = codex_home_for(backend, stella_home)
    source = legacy_auth_home()
    legacy_auth = source / AUTH_FILENAME
    if not legacy_auth.is_file():
        raise FileNotFoundError(f"旧版认证不存在：{legacy_auth}")
    target.mkdir(parents=True, exist_ok=True)
    existing = target / AUTH_FILENAME
    if existing.is_file():
        raise FileExistsError(f"托管 home 已有认证：{existing}（如需覆盖请先登出）")
    existing.write_bytes(legacy_auth.read_bytes())
    with contextlib.suppress(OSError):
        existing.chmod(0o600)
    legacy_config = source / CONFIG_FILENAME
    if legacy_config.is_file() and not (target / CONFIG_FILENAME).exists():
        (target / CONFIG_FILENAME).write_bytes(legacy_config.read_bytes())
    return existing


# ── 后端子进程 env（_build_codex 与登录流共用）──────────────────


def backend_spawn_env(backend: BackendConfig, stella_home: Path | None = None) -> dict:
    """app-server 环境装配：toml env ⊕ CODEX_HOME ⊕ 自定义端点 API key。"""
    env = dict(backend.env)
    home = codex_home_for(backend, stella_home)
    env["CODEX_HOME"] = str(home)
    credential = _read_json(home / CREDENTIAL_FILENAME)
    if credential is not None and credential.get("api_key"):
        env[CODEX_API_KEY_ENV] = str(credential["api_key"])
    return env


# ── SDK 登录包装（lazy import；SDK async API 内部自带 to_thread）────


def _import_sdk():
    """尝试导入官方 SDK。缺失不是错误——由调用方报 CodexAuthUnavailable。"""
    try:
        return __import__(_SDK_IMPORT_NAME)
    except ImportError:
        return None


def _account_brief(account: object) -> dict:
    """账号信息的有界摘要（给前端展示用；不含任何 token）。"""
    root = getattr(account, "root", account)
    kind = str(getattr(root, "type", "") or "")
    brief: dict = {"type": kind or "unknown"}
    for field in ("email", "plan_type", "account_id"):
        value = getattr(root, field, None)
        if value:
            brief[field] = str(value)
    return brief


def _spawn_client(sdk, backend: BackendConfig, stella_home: Path | None):
    return sdk.AsyncCodex(sdk.CodexConfig(env=backend_spawn_env(backend, stella_home)))


async def login_with_api_key(
    backend: BackendConfig, api_key: str, stella_home: Path | None = None
) -> dict:
    """API key 登录：经 app-server 写 auth.json 到托管 home，返回账号摘要。"""
    sdk = _import_sdk()
    if sdk is None:
        raise CodexAuthUnavailable(
            "openai-codex SDK 未安装（pip install openai-codex==0.159.2）"
        )
    if not (api_key or "").strip():
        raise ValueError("api_key 不能为空")
    client = _spawn_client(sdk, backend, stella_home)
    try:
        await client._ensure_initialized()
        await client.login_api_key(api_key.strip())
        return _account_brief(await client.account())
    finally:
        await client.close()


class DeviceLoginSession:
    """一次设备码登录尝试：client 与 handle 绑定同生命周期（不 close 即泄漏）。"""

    def __init__(self, client: object, handle: object):
        self._client = client
        self._handle = handle

    @property
    def login_id(self) -> str:
        return str(self._handle.login_id)

    @property
    def verification_url(self) -> str:
        return str(self._handle.verification_url)

    @property
    def user_code(self) -> str:
        return str(self._handle.user_code)

    async def wait(self):
        """阻塞直到用户在浏览器完成/拒绝登录（调用方负责超时与后台化）。"""
        return await self._handle.wait()

    async def cancel(self) -> None:
        with contextlib.suppress(Exception):
            await self._handle.cancel()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._client.close()


async def start_device_login(
    backend: BackendConfig, stella_home: Path | None = None
) -> DeviceLoginSession:
    """发起 ChatGPT 设备码登录（headless 可用）。T-0 已验证 start 可达。"""
    sdk = _import_sdk()
    if sdk is None:
        raise CodexAuthUnavailable(
            "openai-codex SDK 未安装（pip install openai-codex==0.159.2）"
        )
    client = _spawn_client(sdk, backend, stella_home)
    try:
        await client._ensure_initialized()
        handle = await client.login_chatgpt_device_code()
    except Exception:
        await client.close()
        raise
    return DeviceLoginSession(client=client, handle=handle)


async def account_status(
    backend: BackendConfig, stella_home: Path | None = None
) -> dict:
    """当前账号摘要（经 app-server 查询；未登录抛 SDK 侧错误）。"""
    sdk = _import_sdk()
    if sdk is None:
        raise CodexAuthUnavailable(
            "openai-codex SDK 未安装（pip install openai-codex==0.159.2）"
        )
    client = _spawn_client(sdk, backend, stella_home)
    try:
        await client._ensure_initialized()
        return _account_brief(await client.account())
    finally:
        await client.close()


__all__ = [
    "AUTH_FILENAME",
    "CODEX_API_KEY_ENV",
    "CONFIG_FILENAME",
    "CREDENTIAL_FILENAME",
    "CUSTOM_PROVIDER_ID",
    "CUSTOM_WIRE_API",
    "CodexAuthState",
    "CodexAuthUnavailable",
    "DeviceLoginSession",
    "_import_sdk",
    "account_status",
    "auth_state",
    "backend_spawn_env",
    "clear_managed_auth",
    "codex_home_for",
    "default_stella_home",
    "legacy_auth_available",
    "legacy_auth_home",
    "login_with_api_key",
    "migrate_legacy_auth",
    "read_custom_credential",
    "start_device_login",
    "write_custom_endpoint",
]
