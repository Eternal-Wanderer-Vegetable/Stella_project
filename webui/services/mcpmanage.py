# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""MCP Server 管理写侧（方案 §6.5.2）。

配置真身是 ``config/mcp.toml``（``[servers.<id>]`` 表）；写入 = 读取全部
→ 修改一份 → 整体重写（toml 很小，整体重写最不容易写坏）。保存后热生效：
``MCP_ENABLED`` 时 close→start→sync（manager.start 不先关旧连接是上游的
坑，顺序必须 close 在前）；未启用时只落盘并注明「启用后生效」。
"""

from __future__ import annotations

import json
from pathlib import Path

from webui.responses import ApiError


def config_path() -> Path:
    from capability.providers.mcp.model import default_config_path

    return default_config_path()


def _load_configs() -> dict:
    from capability.providers.mcp.model import load_mcp_configs

    return load_mcp_configs(config_path())


def _toml_inline_dict(d: dict[str, str]) -> str:
    """TOML 内联表：``{KEY = "v"}``——JSON 的 ``"KEY": "v"`` 在 TOML 里非法
    （内联表用 = 不是 :），实测 load_mcp_configs 的宽 except 会把它吞成
    「整个文件没有任何 server」。"""
    inner = ", ".join(
        f"{k} = {json.dumps(v, ensure_ascii=False)}" for k, v in d.items()
    )
    return "{ " + inner + " }" if d else "{}"


def _dump(configs: dict) -> str:
    """手写最小 TOML（字段面固定；避免引入 tomli_w 依赖）。"""
    lines: list[str] = []
    for name, cfg in configs.items():
        lines.append(f"[servers.{name}]")
        lines.append(f"enabled = {json.dumps(bool(cfg.enabled))}")
        lines.append(f"transport = {json.dumps(str(cfg.transport))}")
        if cfg.transport == "stdio":
            lines.append(f"command = {json.dumps(str(cfg.command))}")
            lines.append(f"args = {json.dumps(list(cfg.args))}")
            if cfg.env:
                lines.append(f"env = {_toml_inline_dict(dict(cfg.env))}")
        else:
            lines.append(f"url = {json.dumps(str(cfg.url))}")
            if cfg.auth_env:
                lines.append(f"auth_env = {json.dumps(str(cfg.auth_env))}")
        if cfg.allowed_tools:
            lines.append(f"allowed_tools = {json.dumps(list(cfg.allowed_tools))}")
        lines.append(f"connect_timeout = {float(cfg.connect_timeout)}")
        lines.append(f"call_timeout = {float(cfg.call_timeout)}")
        lines.append(f"max_output_chars = {int(cfg.max_output_chars)}")
        lines.append("")
    return "\n".join(lines)


def _write_configs(configs: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(_dump(configs), encoding="utf-8")
    tmp.replace(path)


def list_servers() -> dict:
    from capability.providers.mcp import manager

    configs = _load_configs()
    try:
        status = manager.status()
    except Exception:
        status = {}
    servers = []
    for name, cfg in configs.items():
        live = status.get(name, {})
        servers.append(
            {
                "server_id": name,
                "enabled": bool(cfg.enabled),
                "transport": cfg.transport,
                "command": cfg.command,
                "url": cfg.url,
                "allowed_tools": cfg.allowed_tools,
                "live": live,
            }
        )
    return {"servers": servers, "config_path": str(config_path())}


def _config_from_payload(payload: dict, server_id: str):
    from capability.providers.mcp.model import ServerConfig

    cfg = ServerConfig(
        server_id=server_id,
        enabled=bool(payload.get("enabled", False)),
        transport=str(payload.get("transport", "stdio")),
        command=str(payload.get("command", "")),
        args=[str(a) for a in payload.get("args", [])],
        env={str(k): str(v) for k, v in (payload.get("env") or {}).items()},
        url=str(payload.get("url", "")),
        auth_env=str(payload.get("auth_env", "")),
        allowed_tools=[str(t) for t in payload.get("allowed_tools", [])],
    )
    problems = cfg.validate()
    if problems:
        raise ApiError(f"配置非法：{'；'.join(problems)}")
    return cfg


def save_server(server_id: str, payload: dict) -> dict:
    if not server_id or not server_id.replace("-", "").replace("_", "").isalnum():
        raise ApiError("server id 只能包含字母、数字、- 与 _")
    cfg = _config_from_payload(payload, server_id)
    configs = _load_configs()
    configs[server_id] = cfg
    _write_configs(configs)
    return {"server_id": server_id, "saved": True}


def delete_server(server_id: str) -> dict:
    configs = _load_configs()
    if server_id not in configs:
        raise ApiError("server 不存在", status_code=404)
    del configs[server_id]
    _write_configs(configs)
    return {"server_id": server_id, "deleted": True}


async def test_server(server_id: str) -> dict:
    """试连接：显式置 enabled（绕过开关，同 deploy mcp test），起临时 client。"""
    from capability.providers.mcp.client import McpServerClient
    from capability.providers.mcp.model import SERVER_READY, load_mcp_configs

    configs = load_mcp_configs(config_path())
    if server_id not in configs:
        raise ApiError("server 不存在", status_code=404)
    cfg = configs[server_id]
    cfg.enabled = True
    problems = cfg.validate()
    if problems:
        raise ApiError(f"配置非法：{'；'.join(problems)}")
    client = McpServerClient(cfg)
    try:
        await client.start()
        state = client.status_dict().get("state")
        tools = [
            {"name": t.name, "description": getattr(t, "description", "")}
            for t in (client.catalog() or [])
        ]
        return {"ok": state == SERVER_READY, "state": state, "tools": tools}
    finally:
        await client.close()


def server_tools(server_id: str) -> dict:
    from capability.providers.mcp import manager

    catalog = manager.catalog(server_id)
    if catalog is None:
        raise ApiError("server 未连接（未启用或未启动）", status_code=409)
    tools = [
        {
            "name": getattr(t, "name", ""),
            "description": getattr(t, "description", ""),
        }
        for t in catalog
    ]
    return {"server_id": server_id, "tools": tools}


async def apply_runtime() -> dict:
    """保存/启停后的热生效（MCP_ENABLED=true 时）。"""
    from capability.adapters import mcp as mcp_adapter

    await mcp_adapter.close_mcp_runtime()
    states = await mcp_adapter.start_mcp_runtime()
    mcp_adapter.install_mcp_runtime()
    synced = mcp_adapter.sync_mcp_providers()
    return {"states": states, "synced": synced}
