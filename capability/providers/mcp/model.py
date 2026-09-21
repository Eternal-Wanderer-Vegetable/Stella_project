# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""MCP 数据模型：Server 配置、运行状态与工具描述符（方案 §6）。

本模块**纯数据与纯函数**：不 import ``mcp`` SDK、不做 IO（读 TOML 除外）、
不起任务。client / manager / backend 都以它为公共词汇。

安全边界（方案 §6.2 / §10）在解析层就落地：

- stdio 只收 ``command + args`` 列表；出现 shell 元字符直接判非法——调用侧永远
  不经过 shell，这里再拦一道是防配置写法本身把人引向错误的心智模型；
- 密钥只存**环境变量名**（``auth_env``），任何 ``to_dict`` / 日志路径都只允许出现
  变量名，值永远不落内存里的诊断结构；
- ``last_error`` 出诊断前必须过 :func:`sanitize_error`：URL 换占位符、截断——
  状态接口响应体有「不含凭据与自由文本」的硬约束（见 capability/inventory.py）。
"""

from __future__ import annotations

import contextlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10 需要 tomli 兜底
    import tomli as tomllib

# 传输方式（方案 §3.2：第一版只有 stdio 与 Streamable HTTP，HTTP+SSE 延后）
TRANSPORT_STDIO = "stdio"
TRANSPORT_HTTP = "streamable_http"
TRANSPORTS = (TRANSPORT_STDIO, TRANSPORT_HTTP)

# Server 运行状态（方案 §6.3）。与 Provider 的单工具退避（registry.CapabilityProvider）
# 是**两层**：Server 挂了，其下所有 Provider is_live=False，但 Capability 声明不动。
SERVER_DISABLED = "disabled"
SERVER_STARTING = "starting"
SERVER_READY = "ready"
SERVER_DEGRADED = "degraded"
SERVER_RECONNECTING = "reconnecting"
SERVER_STOPPED = "stopped"

# 内部命名空间工具名的长度上限（OpenAI function name 约束 ≤64，且只允许
# [A-Za-z0-9_-]）。远程工具名可能含点或更长的名字，组名时统一清洗。
TOOL_NAME_MAX = 64

# 诊断/日志里的错误文本：URL 换占位符（异常文本里唯一会被顺手带进来的敏感物），
# 并截断。与 capability/inventory.py 的 _safe_reason 同一策略，但那边是展示层、
# 这里是数据源——两边都要有，因为 MCP 状态还会走 deploy CLI 与日志。
_URL_RE = re.compile(r"\b(?:https?|ws|wss|ftp)://\S+", re.IGNORECASE)
_ERROR_MAX = 300

# stdio command 里不许出现的 shell 元字符。command 是**单个可执行文件**的路径或名字，
# 参数一律走 args 列表；写了元字符说明使用者想走 shell，而那是被禁止的（方案 §6.2）。
_SHELL_META_RE = re.compile(r"[|&;<>()$`\\\"'\n]")


def sanitize_error(text: str) -> str:
    """错误文本出诊断面（状态接口 / CLI / 日志）前的唯一出口：去 URL、截断。"""
    cleaned = _URL_RE.sub("<url>", (text or "").strip())
    return cleaned if len(cleaned) <= _ERROR_MAX else cleaned[: _ERROR_MAX - 1] + "…"


def sanitize_name_part(part: str) -> str:
    """把 server_id / 远程工具名清洗成可拼进内部工具名的片段。"""
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", (part or "").strip())
    return cleaned[:TOOL_NAME_MAX] or "_"


def mcp_tool_name(server_id: str, remote_tool: str) -> str:
    """MCP 工具的内部命名空间名：``mcp_<server>_<tool>``。

    必须带 Server 段：两个 Server 的同名工具若共用一个内部名，模型调用与
    ``_record_health`` 的健康度记账都会串线（方案 §10）。
    """
    return f"mcp_{sanitize_name_part(server_id)}_{sanitize_name_part(remote_tool)}"


@dataclass
class ServerConfig:
    """一个 MCP Server 的连接配置（方案 §6.2 的字段面）。

    ``allowed_tools`` 的语义是**路由白名单**而不是发现过滤器：

    - 非空：只有清单内的工具可参与自然语言路由（``is_live``），全部工具仍可被
      显式声明后调用；
    - 空：全部发现、全部**不可路由**（默认拒绝；显式声明不能越过这道闸）。
    """

    server_id: str = ""
    enabled: bool = False
    transport: str = TRANSPORT_STDIO
    # stdio
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # streamable_http
    url: str = ""
    auth_env: str = ""  # 存 Bearer token 的环境变量**名**，不是值
    # 共享
    allowed_tools: list[str] = field(default_factory=list)
    connect_timeout: float = 10.0
    call_timeout: float = 30.0
    reconnect_base_seconds: float = 2.0
    reconnect_max_seconds: float = 60.0
    max_output_chars: int = 20000  # 单次工具结果的字符上限（方案 §3.4）
    max_schema_chars: int = 8000  # 单个工具 inputSchema 的序列化预算

    def validate(self) -> list[str]:
        """配置合法性检查，返回问题列表（空列表 = 合法）。"""
        problems: list[str] = []
        if not self.server_id or sanitize_name_part(self.server_id) != self.server_id:
            problems.append("server_id 缺失或含非法字符（只允许字母数字与 -_）")
        if self.transport not in TRANSPORTS:
            problems.append(f"transport 必须是 {' / '.join(TRANSPORTS)}")
        if self.transport == TRANSPORT_STDIO:
            if not self.command.strip():
                problems.append("stdio 传输必须配置 command")
            elif _SHELL_META_RE.search(self.command):
                problems.append("command 含 shell 元字符：stdio 只接受单个可执行文件，参数请写入 args 列表")
            if not isinstance(self.args, list):
                problems.append("args 必须是字符串列表")
        if self.transport == TRANSPORT_HTTP and not self.url.lower().startswith(
            ("http://", "https://"),
        ):
            problems.append("streamable_http 传输必须配置 http(s) url")
        if self.connect_timeout <= 0 or self.call_timeout <= 0:
            problems.append("connect_timeout / call_timeout 必须为正数")
        return problems

    def tool_allowed(self, remote_tool: str) -> bool:
        """该远程工具是否可参与路由（白名单语义见类 docstring）。"""
        if not self.allowed_tools:
            return False
        return remote_tool in self.allowed_tools


def server_config_from_toml(server_id: str, raw: Any) -> ServerConfig:
    """把 ``[servers.<id>]`` 表解析成 ServerConfig；raw 不是表时返回 enabled=False 的空壳。"""
    cfg = ServerConfig(server_id=server_id)
    if not isinstance(raw, dict):
        return cfg
    cfg.enabled = bool(raw.get("enabled", False))
    cfg.transport = str(raw.get("transport") or TRANSPORT_STDIO).strip()
    cfg.command = str(raw.get("command") or "")
    args = raw.get("args") or []
    cfg.args = [str(a) for a in args] if isinstance(args, list) else []
    env = raw.get("env") or {}
    cfg.env = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}
    cfg.url = str(raw.get("url") or "").strip()
    cfg.auth_env = str(raw.get("auth_env") or "").strip()
    allowed = raw.get("allowed_tools") or []
    cfg.allowed_tools = [str(t) for t in allowed if str(t).strip()] if isinstance(allowed, list) else []
    with contextlib.suppress(TypeError, ValueError):
        cfg.connect_timeout = float(raw.get("connect_timeout", 10.0))
    with contextlib.suppress(TypeError, ValueError):
        cfg.call_timeout = float(raw.get("call_timeout", 30.0))
    with contextlib.suppress(TypeError, ValueError):
        cfg.max_output_chars = int(raw.get("max_output_chars", 20000))
    return cfg


def default_config_path() -> Path:
    """配置文件位置：``STELLA_HOME/config/<MCP_CONFIG_FILE>``（默认 mcp.toml）。

    延迟取 STELLA_HOME：本模块要能在没起 config 的单测里直接用。
    """
    from config import STELLA_HOME

    name = "mcp.toml"
    try:
        from config import settings

        name = str(getattr(settings, "MCP_CONFIG_FILE", name))
    except Exception:
        pass
    return Path(STELLA_HOME) / "config" / name


def load_mcp_configs(path: Path | None = None) -> dict[str, ServerConfig]:
    """读 MCP Server 配置，返回 ``server_id → ServerConfig``。

    文件不存在返回空 dict（MCP_ENABLED=true 但没写配置 = 一个 Server 都没有，
    属于可运行的退化态，不是错误）。单个 Server 段坏了只跳过该段。
    """
    target = path if path is not None else default_config_path()
    try:
        with target.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except Exception:
        return {}

    servers = data.get("servers")
    if not isinstance(servers, dict):
        return {}
    configs: dict[str, ServerConfig] = {}
    for server_id, raw in servers.items():
        cfg = server_config_from_toml(str(server_id), raw)
        configs[cfg.server_id] = cfg
    return configs


@dataclass
class ToolDescriptor:
    """一个已发现的 MCP 工具（tools/list 的规范化产物）。

    ``description`` 是**不可信文本**（远程 Server 返回，可能超长甚至带提示注入，
    方案 §10）：进 ToolSet 前在 :func:`descriptor_from_remote` 里截断；
    ``input_schema`` 超预算的工具整体拒收（截断的 schema 比没有 schema 更糟——
    模型会按残缺的参数表编参数）。
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}},
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


def descriptor_from_remote(
    name: str,
    description: Any,
    input_schema: Any,
    *,
    max_description_chars: int = 500,
    max_schema_chars: int = 8000,
) -> ToolDescriptor | None:
    """把 tools/list 里的一项规范化成 ToolDescriptor；不合法返回 None（拒收该工具）。

    拒收而不是截断 schema：模型按残缺参数表调用只会换来一连串失败重试，不如让
    这个工具直接不可用并在日志里点名。
    """
    import json

    tool_name = str(name or "").strip()
    if not tool_name or len(tool_name) > 256:
        return None
    desc = str(description or "").strip()
    if len(desc) > max_description_chars:
        desc = desc[: max_description_chars - 1] + "…"
    if input_schema is None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
    elif isinstance(input_schema, dict):
        schema = dict(input_schema)
        schema.setdefault("type", "object")
        if not isinstance(schema.get("properties"), dict):
            schema["properties"] = {}
    else:
        return None
    try:
        if len(json.dumps(schema, ensure_ascii=False)) > max_schema_chars:
            return None
    except (TypeError, ValueError):
        return None
    return ToolDescriptor(name=tool_name, description=desc, input_schema=schema)


@dataclass
class ServerStatus:
    """一个 MCP Server 的运行状态（方案 §6.3 的字段面）。

    与 Provider 健康度（``CapabilityProvider.failures / disabled_until``）分开维护：
    前者是连接层的（断线、重连），后者是调用层的（连续失败退避）。
    """

    state: str = SERVER_STOPPED
    last_error: str = ""
    last_success_at: float = 0.0
    last_tools_refresh_at: float = 0.0
    tool_count: int = 0
    call_count: int = 0
    failure_count: int = 0
    backoff_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """结构化状态，可直接进状态接口。**不含 url、command、args、env**——
        命令行与地址都可能夹带密钥（方案 §10），这里的字段面是白名单式给的。"""
        return {
            "state": self.state,
            "last_error": sanitize_error(self.last_error) if self.last_error else "",
            "last_success_at": self.last_success_at,
            "last_tools_refresh_at": self.last_tools_refresh_at,
            "tool_count": self.tool_count,
            "call_count": self.call_count,
            "failure_count": self.failure_count,
            "backoff_seconds": round(max(0.0, self.backoff_seconds), 1),
        }

    def snapshot_now(self) -> dict[str, Any]:
        """``to_dict`` 加一个取值时刻。供 inventory 把 ``backoff_seconds`` 换算成剩余秒。"""
        data = self.to_dict()
        data["now"] = time.time()
        return data


__all__ = [
    "SERVER_DEGRADED",
    "SERVER_DISABLED",
    "SERVER_READY",
    "SERVER_RECONNECTING",
    "SERVER_STARTING",
    "SERVER_STOPPED",
    "TOOL_NAME_MAX",
    "TRANSPORTS",
    "TRANSPORT_HTTP",
    "TRANSPORT_STDIO",
    "ServerConfig",
    "ServerStatus",
    "ToolDescriptor",
    "default_config_path",
    "descriptor_from_remote",
    "load_mcp_configs",
    "mcp_tool_name",
    "sanitize_error",
    "sanitize_name_part",
    "server_config_from_toml",
]
