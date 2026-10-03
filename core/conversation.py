# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""会话身份值对象（计划 §6.1）。

三个身份显式分开，不再让一个 ``group_id`` 整数同时扮演三个角色：

- **会话身份**：:class:`ConversationRef`——runtime owner、重置/取消、trace、
  消息去重、回复地址的唯一依据；
- **用户身份**：``subject_key=qq:<user_id>`` / 个人 owner=``person:qq:<bot_id>:<user_id>``
  （见 memory/ownership.py）；
- **空间身份**：``resolve_space(real_group_id)``——群记忆/画像/知识权限照旧。

ConversationRef 只由**可信入口**（QQ 插件 matcher、WebChat ingress）构造；
peer_id 必须来自事件的真实字段，绝不能从消息正文、模型 JSON 或来源群推导。
storage_session_id 由会话注册表（memory/conversation_registry.py）分配：

- group   → 原正整数 QQ 群号（旧消息表物理键兼容）；
- webchat → 固定 ``-1``（既有约定，永不被私聊复用）;
- private → 注册表从专用序列分配的**负整数**（不与任何真实群号/用户号同构，
  不能用 ``-user_id``，也不能从正负号反推 kind）。

core 不 import memory/webui（反向依赖成环），resolve_space 在工厂内延迟导入。
"""

from __future__ import annotations

from dataclasses import dataclass

# 会话种类（持久化值，不要改名）
KIND_GROUP = "group"
KIND_PRIVATE = "private"
KIND_WEBCHAT = "webchat"

# 平台标识（与 cometa Origin.platform 同口径）
PLATFORM_QQ = "qq"
PLATFORM_WEBCHAT = "webchat"

_VALID_KINDS = frozenset({KIND_GROUP, KIND_PRIVATE, KIND_WEBCHAT})


def conversation_key(platform: str, bot_id: str, kind: str, peer_id: str) -> str:
    """规范会话键：``qq:<bot_id>:group:<群号>`` / ``qq:<bot_id>:private:<QQ号>``。

    全链路（trace/去重/Cometa origin/注册表主键）统一使用；WebChat 沿用
    既有 ``webchat:<user>`` 键，不进入 QQ 命名空间。
    """
    if kind == KIND_WEBCHAT:
        return f"webchat:{peer_id}"
    return f"{platform}:{bot_id}:{kind}:{peer_id}"


def private_memory_space(platform: str, bot_id: str, peer_id: str) -> str:
    """私聊的隔离空间名。

    它是私聊本地上下文与旧 SPACE 归属语义的落点，**不能**因此获得任何
    群知识权限，也不能与真实群空间名碰撞（冒号前缀 ``private:`` 留给本约定）。
    """
    return f"private:{platform}:{bot_id}:{peer_id}"


@dataclass(frozen=True, slots=True)
class ConversationRef:
    """一次会话的不可变身份。构造请用下方工厂（它们做全量校验）。"""

    platform: str
    bot_id: str
    kind: str
    peer_id: str
    storage_session_id: int
    runtime_key: str
    memory_space: str

    @property
    def conversation_key(self) -> str:
        return conversation_key(self.platform, self.bot_id, self.kind, self.peer_id)

    @property
    def is_group(self) -> bool:
        return self.kind == KIND_GROUP

    @property
    def is_private(self) -> bool:
        return self.kind == KIND_PRIVATE

    def require_group_id(self) -> int:
        """只有 group 会话才有真实群号；其余种类调用即编程错误。"""
        if self.kind != KIND_GROUP:
            raise ValueError(f"conversation {self.conversation_key} 没有 group_id")
        return int(self.peer_id)

    def subject_key(self) -> str:
        """本会话当前说话者的 subject_key（QQ 号维度认人，不含 Bot）。"""
        return f"{self.platform}:{self.peer_id}"

    def person_owner_key(self) -> str:
        """本会话说话者在本 Bot 下的个人 owner 键。"""
        return f"person:{self.platform}:{self.bot_id}:{self.peer_id}"


def qq_group_ref(
    bot_id: str,
    group_id: int,
    *,
    storage_session_id: int | None = None,
    runtime_key: str | None = None,
    memory_space: str | None = None,
) -> ConversationRef:
    """构造 QQ 群会话引用。

    群历史沿用正整数群号作存储键；runtime_key 默认保留旧 ``qq:<group_id>``
    别名（注册表按 Bot 绑定决定，多 Bot 历史归属不明的群不盲绑）。空间由
    真实群号解析——**绝不允许**拿 storage_session_id/负数调用空间解析。
    """
    group_id = int(group_id)
    if group_id <= 0:
        raise ValueError(f"QQ 群号必须为正整数，收到 {group_id}")
    if storage_session_id is None:
        storage_session_id = group_id
    if storage_session_id != group_id:
        raise ValueError("群会话的 storage_session_id 必须等于真实群号")
    if runtime_key is None:
        runtime_key = f"qq:{group_id}"
    if memory_space is None:
        from config.spaces import resolve_space

        memory_space = resolve_space(group_id)
    return ConversationRef(
        platform=PLATFORM_QQ,
        bot_id=str(bot_id),
        kind=KIND_GROUP,
        peer_id=str(group_id),
        storage_session_id=storage_session_id,
        runtime_key=runtime_key,
        memory_space=memory_space,
    )


def qq_private_ref(
    bot_id: str,
    user_id: int,
    *,
    storage_session_id: int,
    runtime_key: str | None = None,
) -> ConversationRef:
    """构造 QQ 私聊会话引用。

    ``storage_session_id`` 必须由注册表分配（负整数）；runtime_key 用规范
    会话键（私聊没有历史别名）。调用方必须保证 ``user_id`` 是当轮真实 sender。
    """
    user_id = int(user_id)
    if user_id <= 0:
        raise ValueError(f"QQ 用户号必须为正整数，收到 {user_id}")
    if int(storage_session_id) >= 0:
        raise ValueError(
            "私聊 storage_session_id 必须由注册表分配负整数，"
            f"收到 {storage_session_id}（正数会与真实群号冲突）"
        )
    if runtime_key is None:
        runtime_key = conversation_key(PLATFORM_QQ, str(bot_id), KIND_PRIVATE, str(user_id))
    return ConversationRef(
        platform=PLATFORM_QQ,
        bot_id=str(bot_id),
        kind=KIND_PRIVATE,
        peer_id=str(user_id),
        storage_session_id=int(storage_session_id),
        runtime_key=runtime_key,
        memory_space=private_memory_space(PLATFORM_QQ, str(bot_id), str(user_id)),
    )


def webchat_ref(
    *,
    user_id: int,
    storage_session_id: int = -1,
    runtime_key: str | None = None,
    memory_space: str = "webchat",
) -> ConversationRef:
    """构造 WebChat 会话引用（保留既有 -1/空间/键约定，见 webui/chat_ingress.py）。"""
    if storage_session_id != -1:
        raise ValueError("WebChat storage_session_id 固定为 -1（既有约定）")
    if runtime_key is None:
        runtime_key = f"webchat:{user_id}"
    return ConversationRef(
        platform=PLATFORM_WEBCHAT,
        bot_id="",
        kind=KIND_WEBCHAT,
        peer_id=str(user_id),
        storage_session_id=storage_session_id,
        runtime_key=runtime_key,
        memory_space=memory_space,
    )


def ref_from_conversation_key(
    key: str,
    *,
    storage_session_id: int,
    runtime_key: str | None = None,
) -> ConversationRef:
    """从注册表持久化的 conversation_key 还原 ref（M1 注册表读取用）。

    只接受本模块产出的规范键；WebChat 键（``webchat:<user>``）不是本函数
    的职责（它有自己的入口常量）。
    """
    parts = key.split(":")
    if len(parts) != 4:
        raise ValueError(f"无法解析会话键: {key!r}")
    platform, bot_id, kind, peer_id = parts
    if platform not in (PLATFORM_QQ, PLATFORM_WEBCHAT) or kind not in _VALID_KINDS:
        raise ValueError(f"非法会话键: {key!r}")
    if runtime_key is None:
        runtime_key = key
    if kind == KIND_GROUP:
        return qq_group_ref(bot_id, int(peer_id), storage_session_id=int(peer_id), runtime_key=runtime_key)
    if kind == KIND_PRIVATE:
        return qq_private_ref(bot_id, int(peer_id), storage_session_id=storage_session_id, runtime_key=runtime_key)
    return webchat_ref(user_id=int(peer_id), storage_session_id=storage_session_id, runtime_key=runtime_key)
