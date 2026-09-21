# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""Skill 数据契约：纯数据模型，不持有任何可执行对象。

plan §6.1 的边界纪律：

* 模型只保存**规范化相对路径**、名称、描述、来源层、信任等级、大小/摘要
  与可选目录能力——manifest 里没有文件句柄、没有 callable、没有任意对象。
* ``SkillCandidate`` 是给 Router/Selector 看的 metadata-only 视图：名称、
  描述、来源与目录摘要，**永远不含正文**（渐进披露是 Anthropic Skills 的
  核心形态，plan §1）。
* ``SkillResult`` 是唯一允许回到主链路的载体：有界 summary、结构化
  metrics、``ArtifactRef`` 与 audit id。原始 stdout/stderr 留在沙盒审计
  存储，不进 prompt（plan §6.3）。
* ``SandboxLimits`` / ``SandboxSpec`` 是沙盒协议的输入契约；构造即校验，
  负数预算在构造期就失败，而不是等到容器已经跑起来。

路径协议刻意平台无关：所有 skill 内部引用都用 POSIX 风格相对路径
（``references/x.md``），前端与容器内都只看 workspace 相对路径
（plan §6.4：POSIX/Windows 无关的相对路径协议）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

# Skill 名即目录名：小写字母/数字开头，允许 . _ -，总长 ≤64。
# 禁止大写与空白：目录名要跨 Windows/Linux 挂载进容器，大小写不敏感
# 文件系统上 ``Pdf`` 与 ``pdf`` 会撞名；空白则会让 shell 协议的引号规则变复杂。
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def skill_name_is_valid(name: str) -> bool:
    """Skill 名称是否合法（同时是目录名的白名单校验）。"""
    return bool(name) and _NAME_RE.match(name) is not None and ".." not in name


def safe_relative_path(raw: str) -> PurePosixPath | None:
    """把 skill 内部引用解析成安全的相对路径；越界返回 None。

    拒绝：绝对路径、``..`` 跳层、盘符/反斜杠（Windows 语义不允许从
    metadata 里溜进来）、空段。这是 loader/沙盒挂载前的最后一道
    路径白名单，规则与 plan §6.1.5 / §6.4 的目录边界一致。
    """
    text = (raw or "").strip()
    if not text or "\\" in text:
        return None
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return None
    path = PurePosixPath(text)
    # PurePosixPath(".") 与空串的 parts 都是 ()：显式拒绝「没有真实段」的引用
    if path.is_absolute() or not path.parts:
        return None
    if any(part in ("", ".", "..") for part in path.parts):
        return None
    return path


class SkillSource(str, Enum):
    """Skill 的四个来源层。合并优先级固定 workspace > user > plugin > builtin。"""

    BUILTIN = "builtin"
    PLUGIN = "plugin"
    USER = "user"
    WORKSPACE = "workspace"


#: 同名冲突时的层优先级（越大越优先）。plan §6.1.5 固定顺序，不可配置。
SOURCE_PRIORITY: dict[SkillSource, int] = {
    SkillSource.BUILTIN: 0,
    SkillSource.PLUGIN: 1,
    SkillSource.USER: 2,
    SkillSource.WORKSPACE: 3,
}


class SkillTrustLevel(str, Enum):
    """信任等级由来源层决定，不由 Skill 自己声明。

    front matter 里的任何字段都不能抬高自己的信任（plan §6.4：不得把
    权限写进 Skill 自己的 front matter）。
    """

    CONTROLLED = "controlled"  # 仓库内受控目录，随版本发布
    MANAGED = "managed"  # 管理员管理的用户/插件目录
    UNTRUSTED = "untrusted"  # 会话工作区，最低信任


def trust_for_source(source: SkillSource) -> SkillTrustLevel:
    """来源层 → 信任等级的固定映射。"""
    if source is SkillSource.BUILTIN:
        return SkillTrustLevel.CONTROLLED
    if source in (SkillSource.USER, SkillSource.PLUGIN):
        return SkillTrustLevel.MANAGED
    return SkillTrustLevel.UNTRUSTED


class SkillErrorCode(str, Enum):
    """Skill 失败的机器可读原因。进诊断与审计，不直接进 prompt。"""

    NOT_FOUND = "not_found"
    POLICY_DENIED = "policy_denied"
    BODY_TOO_LARGE = "body_too_large"
    PATH_ESCAPED = "path_escaped"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    EXECUTION_FAILED = "execution_failed"
    TIMEOUT = "timeout"
    OUTPUT_TRUNCATED = "output_truncated"
    CATALOG_UNAVAILABLE = "catalog_unavailable"


class SkillStatus(str, Enum):
    """一次 Skill 调用的终态。"""

    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class SkillManifest:
    """一个已发现 Skill 的完整元数据（catalog 的最小存储单元）。

    ``root`` 是磁盘上的技能目录（发现层解析出的绝对路径）；其余路径性
    字段一律是相对 ``root`` 的 POSIX 相对路径。``content_digest`` 是
    ``SKILL.md`` 字节摘要，同时充当技能版本号：catalog 快照版本、selector
    缓存键与调用审计都引用它。
    """

    name: str
    description: str
    source: SkillSource
    root: Any  # Path；类型写 Any 与 core.context.route 同理（避免模型层绑死 IO 类型）
    body_size: int = 0
    content_digest: str = ""
    origin: str = ""  # plugin 来源的插件目录名；其他层为空
    metadata: dict[str, str] = field(default_factory=dict)  # 仅白名单标量键

    @property
    def trust(self) -> SkillTrustLevel:
        return trust_for_source(self.source)

    @property
    def priority(self) -> int:
        return SOURCE_PRIORITY[self.source]

    @property
    def version(self) -> str:
        """技能版本摘要（正文 digest 的短形态），供调用记录与缓存键。"""
        return (self.content_digest or "")[:16]

    def candidate(self, score: float = 0.0, reason: str = "") -> SkillCandidate:
        """导出 metadata-only 候选视图。这是候选的**唯一**产生方式。"""
        return SkillCandidate(
            name=self.name,
            description=self.description,
            source=self.source,
            trust=self.trust,
            content_digest=self.content_digest,
            score=score,
            reason=reason,
        )


@dataclass(frozen=True)
class SkillCandidate:
    """给 Router/Selector 消费的候选视图：只有 metadata，没有正文与路径。

    字段集合刻意最小（plan §6.2）：进 Route/Context 的候选不允许携带
    磁盘路径——路径属于 catalog 内部，泄漏到 prompt 组装层只会诱导
    模型去拼文件引用。
    """

    name: str
    description: str
    source: SkillSource
    trust: SkillTrustLevel
    content_digest: str = ""
    score: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ArtifactRef:
    """一次调用产物的引用。路径是 **workspace 相对**的 POSIX 路径。

    前端拿到的只有这个引用（预览/下载由状态 API 另行提供），永远拿不到
    宿主绝对路径（plan §6.4：前端只看 workspace 相对路径）。
    """

    path: str
    size_bytes: int = 0
    media_type: str = ""


@dataclass(frozen=True)
class SkillInvocation:
    """一次 Skill 调用的预算与授权快照（orchestrator 创建后只读）。

    ``allowed_actions`` 是本次调用允许的抽象沙盒动作白名单（``run_shell`` /
    ``run_python`` / ``read_file`` / ``write_file`` / ``list_files``）。
    Agent 只能请求这些动作，且每一个都必须经 ``SandboxExecutor`` 执行
    （plan §6.3：不允许直接 subprocess / eval / exec）。
    """

    invocation_id: str
    session_id: str
    skill_name: str
    skill_version: str
    source: SkillSource
    trust: SkillTrustLevel
    allowed_actions: tuple[str, ...]
    total_timeout: float
    max_output_chars: int
    created_at: float = 0.0


@dataclass(frozen=True)
class SkillResult:
    """Skill 调用的结果契约。主链路（hooks → pipeline）只见得到它。"""

    invocation_id: str
    skill_name: str
    status: SkillStatus
    error_code: SkillErrorCode | None = None
    summary: str = ""  # 有界摘要（orchestrator 负责截断到预算内）
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRef, ...] = ()
    audit_id: str = ""

    @property
    def ok(self) -> bool:
        return self.status is SkillStatus.COMPLETED


@dataclass(frozen=True)
class SandboxLimits:
    """一次沙盒执行的资源预算。构造期即校验，负数直接失败。"""

    cpu: float = 1.0  # CPU 核数
    memory_mb: int = 256
    pids: int = 64
    timeout_seconds: float = 60.0
    output_max_chars: int = 65536  # 单次 stdout/stderr 合计上限
    artifact_max_bytes: int = 10 * 1024 * 1024  # 总产物大小上限

    def __post_init__(self) -> None:
        numeric = {
            "cpu": self.cpu,
            "memory_mb": self.memory_mb,
            "pids": self.pids,
            "timeout_seconds": self.timeout_seconds,
            "output_max_chars": self.output_max_chars,
            "artifact_max_bytes": self.artifact_max_bytes,
        }
        for field_name, value in numeric.items():
            if value <= 0:
                raise ValueError(f"SandboxLimits.{field_name} 必须为正数，得到 {value}")

    def narrowed(self, **overrides: Any) -> SandboxLimits:
        """用调用上下文的更小预算收窄当前预算（plan §6.4：更小者生效）。

        只允许收紧不允许放宽：override 值大于当前值时保持当前值。
        """
        current = {
            "cpu": self.cpu,
            "memory_mb": self.memory_mb,
            "pids": self.pids,
            "timeout_seconds": self.timeout_seconds,
            "output_max_chars": self.output_max_chars,
            "artifact_max_bytes": self.artifact_max_bytes,
        }
        merged = {}
        for key, base in current.items():
            override = overrides.get(key)
            merged[key] = min(base, override) if override is not None else base
        return SandboxLimits(**merged)


@dataclass(frozen=True)
class SandboxSpec:
    """一次沙盒执行的完整输入：镜像、workspace、只读挂载、网络策略与预算。

    ``read_only_mounts`` 是 ``(宿主路径, 容器内路径)`` 列表，只允许指向
    skill 源目录与 references（plan §6.4：禁止挂载项目根、.env、记忆库、
    插件目录、Docker socket、宿主用户目录——那些校验在 runner 与策略层）。
    """

    backend: str
    image: str
    invocation_id: str
    session_id: str
    workspace: Any  # Path：宿主侧 workspace 目录（挂载为容器 /workspace）
    limits: SandboxLimits
    read_only_mounts: tuple[tuple[Any, str], ...] = ()
    network_enabled: bool = False
    network_allowlist: tuple[str, ...] = ()
    entry_commands: tuple[tuple[str, ...], ...] = ()  # 预留：受控入口命令


# Agent 可请求的抽象沙盒动作全集（plan §6.3）。没有「import 宿主插件」、
# 没有「直接 subprocess」——动作只表达意图，执行全在 SandboxExecutor。
ACTION_RUN_SHELL = "run_shell"
ACTION_RUN_PYTHON = "run_python"
ACTION_READ_FILE = "read_file"
ACTION_WRITE_FILE = "write_file"
ACTION_LIST_FILES = "list_files"
ALL_ACTIONS: tuple[str, ...] = (
    ACTION_RUN_SHELL,
    ACTION_RUN_PYTHON,
    ACTION_READ_FILE,
    ACTION_WRITE_FILE,
    ACTION_LIST_FILES,
)

# 单个动作参数的防御性上限：动作计划是模型产出，参数既不能巨量也不能巨长。
MAX_ARGS_PER_ACTION = 16
MAX_ARG_VALUE_CHARS = 2000


@dataclass(frozen=True)
class SandboxAction:
    """一个待沙盒执行的动作。``args`` 值全部为字符串（经 orchestrator 归一）。"""

    action: str
    args: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxActionOutcome:
    """一个动作的执行结果。``output`` 已被 runner 截到输出预算内。"""

    action: str
    ok: bool
    output: str = ""
    error_code: str = ""  # SkillErrorCode.value；仅失败时非空
    artifact: ArtifactRef | None = None
