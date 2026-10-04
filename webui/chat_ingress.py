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
# native 模式下的 conversation key（与 QQ 群命名空间隔离）
WEBCHAT_CONV_KEY = f"webchat:{WEBCHAT_USER_ID}"

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
    except Exception:
        try:
            from stella_project.plugins.bot_main import ai_gateway  # 打包/源码直跑
        except Exception as e:
            # 真包 __init__ 在 nonebot 未初始化时抛 ValueError（不只是 ImportError），
            # 兜底必须是 Exception——独立 dev server 下聊天要的是明确提示不是崩溃。
            raise RuntimeError(
                "WebChat 需要 Bot 运行环境（独立模式下管线不可用）"
            ) from e
    return ai_gateway.pipeline


def _flow_span(flow_ctx, node_id: str, **kw):
    try:
        from core.observability import message_flow

        return message_flow.span(flow_ctx, node_id, **kw)
    except Exception:
        import contextlib

        return contextlib.nullcontext()


async def run_turn(message: str, username: str, *, flow_ctx=None) -> dict:
    """跑一轮 WebChat 对话，返回 {lines, thought, ts}。

    ``flow_ctx``：router 鉴权后建的流程 root（计划 §6.2）；缺省时这里
    兜底自建（直连调用方仍可观测）。
    """
    from core.context import ChatContext
    from core.social.contracts import (
        DELIVERY_ACKNOWLEDGED,
        ConversationScope,
        DeliveryReceipt,
        new_trace_id,
        utc_now_iso,
    )
    from memory import conversation_registry, social_store
    from memory.pre_processors import record_message

    _ensure_webchat_space()
    # 注册表登记（计划 §6.1）：WebChat 保留 -1 存储/独立主体，不被私聊复用
    import sqlite3 as _sqlite3

    from config import DB_PATH

    ref = None
    if DB_PATH.parent.exists():
        conn = _sqlite3.connect(DB_PATH)
        try:
            ref = conversation_registry.get_or_register_webchat(conn, WEBCHAT_USER_ID)
        except Exception:
            ref = None
        finally:
            conn.close()
    if flow_ctx is None:
        try:
            from core.observability import message_flow

            flow_ctx = message_flow.begin_trace(
                root_kind="webchat", platform="webchat", scope="webchat",
                source_message_key=f"webchat:{username}:{new_trace_id()[:8]}",
            )
        except Exception:
            flow_ctx = None
    ctx = ChatContext(
        user_id=WEBCHAT_USER_ID,
        group_id=WEBCHAT_GROUP_ID,
        msg_id=0,
        message=message.strip(),
        source_kind="AT_MENTION",
        group_shared_space=WEBCHAT_SPACE,
        # v3 会话身份（计划 §6.1）：WebChat kind 不可被认作 QQ 用户
        conversation_kind="webchat" if ref else "",
        conversation_key=ref.conversation_key if ref else "",
        peer_id=str(WEBCHAT_USER_ID) if ref else "",
        storage_session_id=ref.storage_session_id if ref else 0,
        trigger="reply",
        # 身份绑定：root 已有 trace_id 就共用（facade 不再另造，计划 §6.2）
        trace_id=getattr(flow_ctx, "trace_id", "") or new_trace_id(),
    )
    try:
        from core.observability import message_flow

        message_flow.attach(ctx, flow_ctx)
    except Exception:
        pass
    with _flow_span(flow_ctx, "web.space_context"):
        await record_message(ctx)

    outcome = "delivered"
    pipeline = _resolve_pipeline()
    with _flow_span(flow_ctx, "web.session_lock"):
        async with _lock:  # 同群串行（等价群级锁语义）
            # 轮次经 facade（prepare/finalize 留 Python，生成是进程内 provider
            # 调用）；锁语义由 facade per-key owner 接管
            from core.runtime.facade import ensure_shared_facade_started

            facade = await ensure_shared_facade_started()
            try:
                ctx = await facade.submit_turn(WEBCHAT_CONV_KEY, pipeline, ctx)
            except Exception as e:
                # reset 取消不是失败（计划 §6.9）：root 终态照实区分后原样上抛
                cancelled = type(e).__name__ == "RuntimeTurnError" and getattr(e, "code", "") == "E_CANCELLED"
                _end_flow(flow_ctx, "cancelled" if cancelled else "error")
                raise

    lines = [line for line in (ctx.lines or []) if line.strip()]
    with _flow_span(flow_ctx, "web.output") as out_span:
        # 回复按 BOT_SELF 落库，给下一轮整合提供语境。v16 信封契约与 QQ 侧
        # 一致（多人身份修复计划 §6.2）：一次回复共享 logical_message_id、
        # 递增 part_index，收件人 = 面板用户；WebChat 无平台 message ID，
        # msg_id 保持未知（不伪造）。
        logical_id = ctx.turn_id or ctx.trace_id
        for i, line in enumerate(lines):
            await record_message(
                ChatContext(
                    user_id=WEBCHAT_USER_ID,
                    group_id=WEBCHAT_GROUP_ID,
                    msg_id=0,
                    message=line,
                    source_kind="BOT_SELF",
                    group_shared_space=WEBCHAT_SPACE,
                    conversation_kind=getattr(ctx, "conversation_kind", "") or "",
                    conversation_key=getattr(ctx, "conversation_key", "") or "",
                    bot_id=str(getattr(ctx, "bot_id", "") or ""),
                    logical_message_id=logical_id,
                    part_index=i,
                    reply_recipient_user_id=str(WEBCHAT_USER_ID),
                    turn_id=ctx.turn_id,
                    relation_version=1 if logical_id else 0,
                )
            )
        out_span.finish(status="succeeded" if lines else "skipped",
                        reason_code="" if lines else "empty_lines",
                        metrics={"lines": len(lines)})
    # server_emitted 投递事实（计划 §6.1）：面板对话的「服务端已产出回复」
    # 与 QQ 平台 acknowledged 是两种投递语义，以 platform='webchat' 区分；
    # 群社交效果学习默认只认 platform='qq'，WebChat 行不进入任何群归因。
    if lines:
        from config import SOCIAL_ENABLED

        if SOCIAL_ENABLED:
            scope = ConversationScope(platform="webchat", bot_id="", group_id=str(WEBCHAT_GROUP_ID))
            for i, line in enumerate(lines):
                social_store.record_delivery(
                    DeliveryReceipt(
                        trace_id=ctx.trace_id,
                        turn_id=ctx.turn_id,
                        part_index=i,
                        status=DELIVERY_ACKNOWLEDGED,
                        text=line,
                        acknowledged_at_utc=utc_now_iso(),
                        scope=scope,
                    )
                )
    else:
        outcome = "empty"
    _end_flow(flow_ctx, outcome)
    return {"lines": lines, "thought": ctx.thought}


def _end_flow(flow_ctx, outcome: str) -> None:
    try:
        from core.observability import message_flow

        message_flow.end_trace(flow_ctx, outcome=outcome)
    except Exception:
        pass


async def reset_webchat_runtime() -> None:
    """WebChat reset 协调（计划 §R.5）：

    先 fence/cancel 在途轮次 + epoch 递增（拒旧轮晚到），再由调用方清消息库
    ——已取消旧轮不能晚到后重建历史。
    """
    from core.runtime.facade import ensure_shared_facade_started

    facade = await ensure_shared_facade_started()
    await facade.reset_session(WEBCHAT_CONV_KEY)
