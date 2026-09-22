# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE.
"""WebChat ingress（方案 §13，M4）：面板里与 Stella 私聊。

三重隔离（评审定案 ③ 的落地）：
1. **虚拟群号** ``-1``（QQ 群号恒为正，零冲突），不进 ALLOWED_GROUPS →
   主动发言/参与度/定时任务对它天然失效（那些机制都以白名单为前提）；
2. **专属空间** ``webchat``（首次使用自动创建 toml，qq_groups=[-1]）——
   长期记忆与画像按空间隔离，群聊记忆物理上摸不到这里；
3. **独立串行锁**：同一时刻只跑一次 WebChat 推理（等价群级锁语义）。

消息链路：record_message(AT_MENTION) → pipeline.run（pre hooks 全链：
短期上下文/记忆检索/能力激活 原样生效）→ 回复行按 BOT_SELF 落库。
预算走 CHAT 角色同池诚实记账。工具与 Router 通道与群聊完全对等。

**懒解析管线**：``ai_gateway`` 只有在 Bot 进程里才可导入（插件 __init__
依赖 nonebot driver），所以管线在调用时解析而非 import 期——独立模式
（dev server）下聊天端点报「需要 Bot 运行环境」而不是炸掉整个 WebUI。
"""

from __future__ import annotations

import asyncio

WEBCHAT_GROUP_ID = -1
WEBCHAT_SPACE = "webchat"
# 单管理员（定案 ③）：dashboard 用户 ↔ 固定 webchat 身份
WEBCHAT_USER_ID = 800_000_000

_lock = asyncio.Lock()


def _ensure_webchat_space() -> None:
    from config import spaces as spaces_mod
    from webui.services.spaces import spaces_dir

    toml = spaces_dir() / f"{WEBCHAT_SPACE}.toml"
    if toml.exists():
        return
    toml.parent.mkdir(parents=True, exist_ok=True)
    tmp = toml.with_suffix(".toml.tmp")
    tmp.write_text("qq_groups = [-1]\n", encoding="utf-8")
    tmp.replace(toml)
    spaces_mod.reload()


def _resolve_pipeline():
    """运行时解析宿主管线。失败抛 ApiError（不炸进程）。"""
    try:
        from plugins.bot_main import ai_gateway  # Bot 进程内（nonebot 已挂 sys.path）
    except ImportError:
        try:
            from stella_project.plugins.bot_main import ai_gateway  # 打包/源码直跑
        except Exception as e:
            raise RuntimeError(
                "WebChat 需要 Bot 运行环境（独立模式下管线不可用）"
            ) from e
    return ai_gateway.pipeline


async def run_turn(message: str, username: str) -> dict:
    """跑一轮 WebChat 对话，返回 {lines, thought, ts}。"""
    from core.context import ChatContext
    from memory.pre_processors import record_message

    _ensure_webchat_space()
    ctx = ChatContext(
        user_id=WEBCHAT_USER_ID,
        group_id=WEBCHAT_GROUP_ID,
        msg_id=0,
        message=message.strip(),
        source_kind="AT_MENTION",
        group_shared_space=WEBCHAT_SPACE,
        trigger="reply",
    )
    await record_message(ctx)

    pipeline = _resolve_pipeline()
    async with _lock:  # 同群串行（等价群级锁语义）
        ctx = await pipeline.run(ctx)

    lines = [line for line in (ctx.lines or []) if line.strip()]
    for line in lines:  # 回复按 BOT_SELF 落库，给下一轮整合提供语境
        await record_message(
            ChatContext(
                user_id=WEBCHAT_USER_ID,
                group_id=WEBCHAT_GROUP_ID,
                msg_id=0,
                message=line,
                source_kind="BOT_SELF",
                group_shared_space=WEBCHAT_SPACE,
            )
        )
    return {"lines": lines, "thought": ctx.thought}
