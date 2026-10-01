# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebUI 的 cometa 后端认证服务（providers 服务同款纪律）。

对齐 ``webui/services/providers.py`` 的交互契约：

- 状态只回 ``has_api_key`` 布尔，**永不回显 key/token 原文**；
- ``apply_*`` 的 api_key 空串语义 = 保留原值（custom-endpoint）；首次配置
  无原值时明确拒绝；
- 连通性测试复用 ``deploy.probe`` 现成探针；
- 写操作由路由层记 audit（detail 不含秘密）。

与 providers 页的**有意差异**：认证落托管 codex_home、probe/任务启动现读
现用——**免重启**（providers 是 .env + import 期冻结所以需要重启）。

设备码登录是进程内 session 注册表：bot 重启丢失，前端重新发起即可（每次
start 都是一次新的登录尝试，无副作用残留）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from cometa.backends import codex_auth
from cometa.config import BackendConfig
from cometa.service import CometaService
from deploy.probe import fetch_endpoint_models
from webui.responses import ApiError

# 设备码登录会话的保留时长（codex 侧设备码有效期约 15 分钟，取保守值）。
_DEVICE_SESSION_TTL_SECONDS = 600.0


def _require_codex_backend(service: CometaService, backend_id: str) -> BackendConfig:
    backend = service.config.backend_of(backend_id)
    if backend is None or not backend.enabled:
        raise ApiError(f"未知后端 {backend_id!r}（或未启用）")
    if backend.type != "codex":
        raise ApiError(f"后端 {backend_id!r} 类型为 {backend.type!r}，只有 codex 后端支持认证配置")
    return backend


def status(service: CometaService, backend_id: str) -> dict:
    """认证状态快照（纯文件面，无网络调用；秘密零回显）。"""
    backend = _require_codex_backend(service, backend_id)
    state = codex_auth.auth_state(backend)
    return {
        "backend_id": backend_id,
        "mode": state.mode,
        "ready": state.ready,
        "reason": state.reason,
        "has_api_key": state.has_api_key,
        "has_custom_endpoint": codex_auth.custom_endpoint_present(backend),
        "legacy_available": codex_auth.legacy_auth_available(),
        "account": _device_account_cache.get(backend_id),
    }


async def apply_api_key(service: CometaService, backend_id: str, api_key: str) -> dict:
    """OpenAI API key 登录（经 SDK 写 auth.json 到托管 home）。空串拒绝。"""
    backend = _require_codex_backend(service, backend_id)
    if not (api_key or "").strip():
        raise ApiError("api_key 不能为空（如需更换请提供新 key；如需登出请用 logout）")
    try:
        account = await codex_auth.login_with_api_key(backend, api_key)
    except codex_auth.CodexAuthUnavailable as e:
        raise ApiError(str(e), status_code=503) from None
    except Exception as e:  # SDK 侧登录失败（网络/被拒）→ 可解释 400
        raise ApiError(f"API key 登录失败：{type(e).__name__}: {e}") from None
    _device_account_cache[backend_id] = account
    return {"account": account, **status(service, backend_id)}


async def apply_custom_endpoint(
    service: CometaService,
    backend_id: str,
    payload: dict,
) -> dict:
    """自定义端点配置（codex 原生 config.toml + 托管凭据）。

    api_key 空串 = 保留原值（providers「留空不变」语义）；首次配置没有
    原值时必须提供。wire_api 只接受 responses（codex 0.159.2 已移除 chat）。
    """
    backend = _require_codex_backend(service, backend_id)
    base_url = str(payload.get("base_url", "")).strip()
    model = str(payload.get("model", "")).strip()
    api_key = str(payload.get("api_key", "") or "").strip()
    wire_api = str(payload.get("wire_api", "") or "").strip()
    if wire_api and wire_api != codex_auth.CUSTOM_WIRE_API:
        raise ApiError(
            f"wire_api 只支持 {codex_auth.CUSTOM_WIRE_API!r}"
            "（codex 0.159.2 已移除 chat wire API）；自定义端点必须实现 OpenAI Responses API"
        )
    if not api_key:
        credential = codex_auth.read_custom_credential(backend)
        if credential is None or not credential.get("api_key"):
            raise ApiError("首次配置自定义端点必须提供 api_key（空串仅在修改已有配置时表示保留）")
        api_key = str(credential["api_key"])
    try:
        codex_auth.write_custom_endpoint(
            codex_auth.codex_home_for(backend),
            base_url=base_url,
            api_key=api_key,
            model=model,
            wire_api=wire_api or codex_auth.CUSTOM_WIRE_API,
        )
    except ValueError as e:
        raise ApiError(str(e)) from None
    return status(service, backend_id)


async def migrate_legacy(service: CometaService, backend_id: str) -> dict:
    """旧版 ~/.codex 认证一键迁移进托管 home（仅显式触发，已有认证则拒绝）。"""
    backend = _require_codex_backend(service, backend_id)
    try:
        codex_auth.migrate_legacy_auth(backend)
    except FileNotFoundError as e:
        raise ApiError(str(e)) from None
    except FileExistsError as e:
        raise ApiError(str(e)) from None
    return status(service, backend_id)


async def logout(service: CometaService, backend_id: str) -> dict:
    """登出 = 删除托管 home 的 auth.json；自定义端点配置与设备码会话不受影响。"""
    backend = _require_codex_backend(service, backend_id)
    codex_auth.clear_managed_auth(codex_auth.codex_home_for(backend))
    _device_account_cache.pop(backend_id, None)
    return status(service, backend_id)


async def test_endpoint(service: CometaService, backend_id: str, payload: dict) -> dict:
    """自定义端点连通性测试（复用 providers.test 同款探针；api_key 仅本次使用）。"""
    _require_codex_backend(service, backend_id)
    base_url = str(payload.get("base_url", "")).strip()
    api_key = str(payload.get("api_key", "") or "").strip()
    if not base_url:
        raise ApiError("base_url 不能为空")
    models, err = await asyncio.to_thread(fetch_endpoint_models, base_url, api_key)
    return {"models": models, "error": err}


# ── 设备码登录会话（进程内；bot 重启丢失，前端重新发起）──────────


@dataclass
class _DeviceSession:
    session_id: str
    login: codex_auth.DeviceLoginSession
    state: str = "pending"  # pending | completed | failed
    error: str = ""
    account: dict | None = None
    created_at: float = field(default_factory=time.monotonic)

    def snapshot(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "user_code": self.login.user_code,
            "verification_url": self.login.verification_url,
            "account": self.account,
            "error": self.error,
        }


_device_sessions: dict[str, _DeviceSession] = {}
_device_account_cache: dict[str, dict] = {}

# 每次轮询给登录等待的时间片；UI 轮询周期 ~2s，完成态最多滞后一个周期。
_POLL_SLICE_SECONDS = 0.05


async def _gc_device_sessions() -> None:
    """过期会话清理：关掉 app-server 客户端（防子进程泄漏）。"""
    now = time.monotonic()
    stale = [
        sid
        for sid, s in _device_sessions.items()
        if now - s.created_at > _DEVICE_SESSION_TTL_SECONDS
    ]
    for sid in stale:
        session = _device_sessions.pop(sid)
        await session.login.cancel()
        await session.login.close()


async def start_device_login(
    service: CometaService, backend_id: str, stella_home: Path | None = None
) -> dict:
    """发起设备码登录：返回 user_code + verification_url 供页面展示。"""
    backend = _require_codex_backend(service, backend_id)
    await _gc_device_sessions()
    try:
        login = await codex_auth.start_device_login(backend, stella_home)
    except codex_auth.CodexAuthUnavailable as e:
        raise ApiError(str(e), status_code=503) from None
    except Exception as e:  # start 不可达（网络/代理）→ 可解释 400
        raise ApiError(f"设备码登录发起失败：{type(e).__name__}: {e}") from None
    session = _DeviceSession(session_id=uuid.uuid4().hex[:12], login=login)
    _device_sessions[session.session_id] = session
    return session.snapshot()


async def device_login_status(
    service: CometaService, backend_id: str, session_id: str
) -> dict:
    """轮询设备码登录状态；pending 时短等待登录通知（轮询驱动收敛）。

    完成的收尾（账号摘要 + 关 client）也在这里做——不依赖后台任务：
    TestClient 每请求一个 loop，生产里 UI 轮询周期 ~2s，完成态最多滞后
    一个周期，client 关闭同样由轮询路径保证。"""
    backend = _require_codex_backend(service, backend_id)
    session = _device_sessions.get(session_id)
    if session is None:
        raise ApiError("登录会话不存在或已过期；请重新发起", status_code=404)
    if session.state == "pending":
        try:
            await asyncio.wait_for(
                session.login.wait(), timeout=_POLL_SLICE_SECONDS
            )
            session.state = "completed"
            with contextlib.suppress(Exception):
                session.account = await codex_auth.account_status(backend)
                _device_account_cache[backend.backend_id] = session.account or {}
        except asyncio.TimeoutError:
            pass
        except Exception as e:  # 用户拒绝/会话过期/网络断
            session.state = "failed"
            session.error = f"{type(e).__name__}: {e}"[:200]
            await session.login.close()
    return session.snapshot()


__all__ = [
    "apply_api_key",
    "apply_custom_endpoint",
    "device_login_status",
    "logout",
    "migrate_legacy",
    "start_device_login",
    "status",
    "test_endpoint",
]
