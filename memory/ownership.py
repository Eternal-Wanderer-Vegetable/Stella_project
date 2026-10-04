# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""记忆归属与访问范围（计划 §6.4/§6.6）。

把「这条记忆属于谁（owner）」和「这场对话允许读谁（scope）」做成可信代码
生成的值对象：**模型只提交查询文本/候选 fact hint，永不提交 owner、scope
列表或读他人的请求**。所有检索路径（SQL/FTS/embedding/Planner/v1/native）
共用同一份 :class:`MemoryAccessScope`，授权在候选构造阶段（SQL WHERE）生效，
而不是先全库召回再过滤。

受众（audience）与既有 visibility 正交：
- ``CURRENT_SPACE`` 只在来源空间可见（群关系/群行为）；
- ``PRIVATE_ONLY`` 仅本人私聊可见；
- ``USER_SHARED`` 本人可用（同 Bot 的任何群/私聊），不授权其他用户。

scope 缺失、非法或主体不明（user_id<=0 等）时，调用方只能得到 SPACE-only
scope——旧行为的安全超集是「更少」，不是「更多」。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# owner_type（持久化值）
OWNER_TYPE_SPACE = "SPACE"
OWNER_TYPE_PERSON = "PERSON"

# audience（持久化值）
AUDIENCE_CURRENT_SPACE = "CURRENT_SPACE"
AUDIENCE_PRIVATE_ONLY = "PRIVATE_ONLY"
AUDIENCE_USER_SHARED = "USER_SHARED"

ALL_AUDIENCES = frozenset(
    {AUDIENCE_CURRENT_SPACE, AUDIENCE_PRIVATE_ONLY, AUDIENCE_USER_SHARED}
)

# 私聊 PERSON 行写进 group_shared_space 列的兼容 namespace（计划 §6.4）：
# 不可与任何真实群空间名匹配，旧读取路径按 space 相等过滤时永远看不到它。
PERSON_COMPAT_NAMESPACE_PREFIX = "personal:"

POLICY_VERSION = "2026-10-03.0"


def space_owner_key(space: str) -> str:
    return f"space:{space}"


def person_owner_key(platform: str, bot_id: str, user_id: str | int) -> str:
    return f"person:{platform}:{bot_id}:{user_id}"


def person_compat_space(owner_key: str, audience: str) -> str:
    """PERSON 行在 group_shared_space 列的兼容值。"""
    return f"{PERSON_COMPAT_NAMESPACE_PREFIX}{owner_key}:{audience}"


@dataclass(frozen=True, slots=True)
class MemoryOwner:
    """一行记忆的归属。subject_key 只对 PERSON 有意义。"""

    owner_type: str
    owner_key: str
    subject_key: str = ""

    def validated(self) -> "MemoryOwner":
        if self.owner_type not in (OWNER_TYPE_SPACE, OWNER_TYPE_PERSON):
            raise ValueError(f"非法 owner_type: {self.owner_type!r}")
        if not self.owner_key:
            raise ValueError("owner_key 不能为空")
        if self.owner_type == OWNER_TYPE_PERSON and not self.subject_key:
            raise ValueError("PERSON owner 必须携带 subject_key")
        if self.owner_type == OWNER_TYPE_SPACE and self.subject_key:
            raise ValueError("SPACE owner 不携带 subject_key")
        return self


def space_owner(space: str) -> MemoryOwner:
    return MemoryOwner(OWNER_TYPE_SPACE, space_owner_key(space))


def person_owner(platform: str, bot_id: str, user_id: str | int) -> MemoryOwner:
    subject = f"{platform}:{user_id}"
    return MemoryOwner(
        OWNER_TYPE_PERSON,
        person_owner_key(platform, bot_id, user_id),
        subject_key=subject,
    )


@dataclass(frozen=True, slots=True)
class MemoryAccessScope:
    """一场对话允许检索的记忆范围（服务端生成，不可由模型输入构造）。

    owners 有序：当前 SPACE 在前，PERSON 在后；person_audiences 是 PERSON 行
    在**当前会话种类**下允许的受众集合。fingerprint 进缓存键（计划 §6.6）。
    """

    space_key: str
    person_owner_key: str = ""
    subject_key: str = ""
    person_audiences: tuple[str, ...] = ()

    @property
    def has_person(self) -> bool:
        return bool(self.person_owner_key and self.subject_key and self.person_audiences)

    def fingerprint(self) -> str:
        payload = json.dumps(
            {
                "space": self.space_key,
                "person": self.person_owner_key,
                "subject": self.subject_key,
                "audiences": list(self.person_audiences),
                "policy": POLICY_VERSION,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def audience_allowed(self, audience: str) -> bool:
        return audience in self.person_audiences


def space_only_scope(space: str) -> MemoryAccessScope:
    """旧路径的缺省范围：仅当前空间（PERSON 一律不可见）。"""
    return MemoryAccessScope(space_key=space_owner_key(space))


def scope_for_chat_context(ctx: Any, *, memory_space: str) -> "MemoryAccessScope | None":
    """从可信 ``ChatContext`` 决定当前检索的权限主体（多人身份修复计划 §6.1）。

    权威链：当前发言者只由平台事件确定（``ctx.user_id``）；``peer_id`` 在群聊
    里是**会话地址（群号）不是人**，绝不参与 PERSON 构造。各路径：

    - 普通群聊 / 私聊 / WebChat：主体 = ``ctx.user_id``（平台 sender；主动 @
      路径上它是经过 pick_target 触发链验证的目标 uid）；
    - 群级主动发言（``trigger == "proactive"``）：无当前个人主体 → ``None``
      （调用方保持 SPACE-only / 旧 user_id 过滤，不会用群号或 0 构造 PERSON）；
    - 旧入口（``conversation_kind`` 为空）：``None``，与升级前行为逐字一致。

    返回 ``None`` 表示「本轮不应用 owner scope」——不是授权放行：检索侧对
    ``None`` 的处理是旧有行为（SPACE / user_id 过滤），永远不会扩大可见范围。
    """
    if getattr(ctx, "trigger", "") == "proactive":
        return None
    kind = str(getattr(ctx, "conversation_kind", "") or "")
    if kind not in ("group", "private", "webchat"):
        return None
    user_id = getattr(ctx, "user_id", 0) or 0
    try:
        if int(user_id) <= 0:
            return None
    except (TypeError, ValueError):
        return None
    return scope_for_conversation(
        kind=kind,
        memory_space=memory_space,
        platform="webchat" if kind == "webchat" else "qq",
        bot_id=str(getattr(ctx, "bot_id", "") or ""),
        user_id=str(user_id),
    )


def scope_for_conversation(
    *,
    kind: str,
    memory_space: str,
    platform: str,
    bot_id: str,
    user_id: int | str,
) -> MemoryAccessScope:
    """按会话种类生成检索范围（计划 §6.6）。

    - group：当前 SPACE + 当前用户 USER_SHARED；
    - private：私聊隔离 SPACE + 当前用户 PRIVATE_ONLY/USER_SHARED；
    - 其他/主体不可信（user<=0）：SPACE-only。
    """
    owner_key = space_owner_key(memory_space)
    user_str = str(user_id)
    try:
        if int(user_str) <= 0:
            return MemoryAccessScope(space_key=owner_key)
    except ValueError:
        return MemoryAccessScope(space_key=owner_key)
    person = person_owner_key(platform, bot_id, user_str)
    subject = f"{platform}:{user_str}"
    if kind == "private":
        audiences = (AUDIENCE_PRIVATE_ONLY, AUDIENCE_USER_SHARED)
    elif kind == "group":
        audiences = (AUDIENCE_USER_SHARED,)
    else:
        return MemoryAccessScope(space_key=owner_key)
    return MemoryAccessScope(
        space_key=owner_key,
        person_owner_key=person,
        subject_key=subject,
        person_audiences=audiences,
    )


# ── SQL 谓词构造（所有检索后端共用，计划 §6.6 的候选池下推） ──────────────


def owner_scope_sql(scope: MemoryAccessScope, *, alias: str = "") -> tuple[str, list[Any]]:
    """生成 owner/audience 过滤的 WHERE 片段与**位置**参数。

    返回 ``(sql_fragment, params)``；fragment 以 ``AND`` 开头、占位符一律 ``?``，
    参数按出现顺序排列——SQL 与 FTS 检索路径按位置绑定（与两处的既有
    tuple 风格一致，避免命名/位置混用）。旧列回退：owner_type/owner_key 为
    空的行经 COALESCE 按 space 列还原（迁移回填前的写入兜底）。

    PERSON 分支只在 scope 声明了受众时生成——没有受众就没有 PERSON 行，
    不存在「先召回再按受众过滤」的旁路。
    """
    col = f"{alias}." if alias else ""
    params: list[Any] = [scope.space_key]
    person_clause = ""
    if scope.has_person:
        placeholders = ",".join("?" * len(scope.person_audiences))
        person_clause = (
            f" OR ({col}owner_type = 'PERSON' AND {col}owner_key = ? "
            f"AND {col}subject_key = ? AND {col}audience IN ({placeholders}))"
        )
        params.extend(
            [scope.person_owner_key, scope.subject_key, *scope.person_audiences]
        )
    fragment = (
        f" AND (({col}owner_type = 'SPACE' AND "
        f"COALESCE({col}owner_key, 'space:' || {col}group_shared_space) = ?)"
        f"{person_clause})"
    )
    return fragment, params


def normalize_audience(value: str | None) -> str:
    """非法/缺省 audience 回退 CURRENT_SPACE（写入口的最后一道闸）。"""
    aud = (value or "").strip().upper()
    return aud if aud in ALL_AUDIENCES else AUDIENCE_CURRENT_SPACE
