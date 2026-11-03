# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""主动 @ 编排（原 ``ai_gateway`` 主动验证区，2026-11-03 计划 §3.1 S1-02 外移）。

行为与外移前逐行等价；宿主相关的 bot 句柄、群锁、发送计划、门控访问器与
观测探针由 :mod:`aoede.host` 注入（转发合同保持 gateway 级 monkeypatch
语义）。本模块不导入 NoneBot 适配器类型，bot 按鸭子类型使用。

``ai_gateway._proactive_at_user`` / ``_check_reply_later`` 保留为薄委托，
调用方迁移完毕后删除（计划 §3 装配边界）。
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from nonebot import logger

from aoede.controller import ProactiveController
from aoede.host import ProactiveHost
from aoede.prompts import build_instruction, is_proactive_skip
from aoede.storage.legacy_state import record_reply_result
from core.context import ChatContext
from core.runtime.facade import E_CANCELLED, RuntimeTurnError, new_turn_deadline
from core.social.contracts import (
    ConversationScope,
    delivered_texts,
    new_trace_id,
)
from core.social.delivery import DeliveryPlanError, deliver_lines
from core.transport import BotRef, OutboundMessage, OutboundSegment, SceneRef
from gravitas.errors import DeadlineExceeded

# 主动 @ 的后台回应检测任务集合：任务引用必须被持有，否则可能
# 在完成前被 GC。装配层关停时统一 drain。
reply_check_tasks: set[asyncio.Task] = set()


def register_reply_check_task(task: asyncio.Task, *, host: ProactiveHost | None = None) -> None:
    """登记后台任务引用并在完成时自动丢弃（防 GC）。

    宿主提供 ``register_task`` 时优先交给装配层集合（与旧
    ``ai_gateway._reply_check_tasks`` 语义一致）；否则落本模块集合。
    """
    hook = getattr(host, "register_task", None) if host is not None else None
    if hook is not None:
        hook(task)
        return
    reply_check_tasks.add(task)
    task.add_done_callback(reply_check_tasks.discard)


async def check_reply_later(group_id: int, user_id: int, asked_at: float) -> None:
    """延迟检查主动 @ 是否获得回应，据此更新退避计数。

    判定标准：在 PROACTIVE_REPLY_WINDOW_SECONDS 内该用户是否**对 Bot 说过话**
    （@ / 回复 Bot 的消息 / 昵称呼叫，即 OneBot 的 to_me）。用内存中的时间戳，不查库。

    此前判的是「窗口内有没有说话」，在活跃群里几乎恒为真：被追问的人本来就是
    「近期活跃用户」，随后必然还会在群里说话，于是 consecutive_no_reply 一直被
    清零、PROACTIVE_MAX_NO_REPLY 的自动退避形同虚设（bug_report_2026_8_31#1 §5.1）。

    代价是纯文本接话（不 @、不回复）会被判为未回应。这类漏判由 reset_no_reply
    在下一次「对 Bot 说话」时归零来兜底，不会把人永久踢出验证池。

    无回应即累计 consecutive_no_reply，达到 PROACTIVE_MAX_NO_REPLY 后
    can_at_user 会拒绝继续追问该用户，这是对「不想聊的人」的自动退避。

    S2-01 将把本函数替换为持久 attempt + deadline 结算（内存 last_tome
    时间戳没有候选/问题关联语义）。
    """
    from config import PROACTIVE_REPLY_WINDOW_SECONDS

    try:
        await asyncio.sleep(PROACTIVE_REPLY_WINDOW_SECONDS)
        last = get_proactive_standalone().last_tome_ts(group_id, user_id)
        replied = last is not None and last > asked_at
        record_reply_result(group_id, user_id, replied)
        logger.info(
            f"{'✅' if replied else '🔇'} [主动@] 群 {group_id} 用户 {user_id} "
            f"{'已回应' if replied else '未回应'}（窗口 {PROACTIVE_REPLY_WINDOW_SECONDS:.0f}s）"
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning(f"⚠️ [主动@] 回应检测异常（跳过）: {e}")


def get_proactive_standalone() -> ProactiveController:
    """门控/回应检测直接使用的控制器单例（非宿主转发路径）。

    宿主路径（``host.get_proactive``）存在时优先返回宿主实例，保证测试
    monkeypatch 单例时两条路径看到同一对象；未装配宿主时回退本包单例。
    """
    from aoede import controller as _controller
    from aoede import host as _host_mod

    if _host_mod._install is not None:
        managed = _host_mod._install.get_proactive()
        if managed is not None:
            return managed
    return _controller.get_proactive()


def proactive_contract_mode() -> str:
    """主动验证合同模式（复核 F1）：读配置，异常按 off。"""
    try:
        from config.settings import PROACTIVE_VERIFICATION_CONTRACT_MODE

        return str(PROACTIVE_VERIFICATION_CONTRACT_MODE or "off").strip().lower()
    except Exception:
        return "off"


def build_proactive_contract(host: ProactiveHost, group_id: int, target):
    """从候选行 + 来源行构建主动验证合同（复核 F11，服务端构建）。

    支持的候选：当前共享空间中的 SPACE/CURRENT_SPACE 事实、事实主体等于
    选定目标、来源/lineage/epoch仍有效且谓词有服务端模板。其余返回
    (None, None, reason)——enforce 下跳过，shadow 下记录原因。
    返回 (contract, selected_variant, error_reason)。
    """
    import json
    import sqlite3 as _sqlite3

    from aoede.contract import (
        QuestionVariant,
        VerificationContract,
        compute_candidate_digest,
    )

    conn = _sqlite3.connect(host.db_path())
    try:
        row = conn.execute(
            "SELECT id, type, content, status, owner_type, owner_key, subject_key, fact_key, "
            "audience, source_conversation_key, group_shared_space"
            " FROM memory_candidates WHERE id = ?",
            (str(target.candidate_id or ""),),
        ).fetchone()
        if row is None:
            return None, None, "candidate_missing"
        (
            cid, ctype, content, status, owner_type, owner_key, subject_key,
            fact_key, audience, candidate_conversation, group_shared_space,
        ) = row
        expected_conversation = f"qq:{target.source_bot_id}:group:{group_id}"
        if str(status or "").upper() != "OBSERVING":
            return None, None, "candidate_inactive"
        if (
            str(owner_type or "") != "SPACE"
            or str(audience or "") != "CURRENT_SPACE"
            or str(owner_key or "") != f"space:{group_shared_space}"
            or str(group_shared_space or "") == ""
            or str(owner_key or "") != str(target.owner_key or "")
            or str(target.owner_type or "") != "SPACE"
            or str(target.audience or "") != "CURRENT_SPACE"
            or str(subject_key or "") != ""
        ):
            return None, None, "owner_not_current_space"
        if not target.source_bot_id:
            return None, None, "source_binding_missing"
        if str(candidate_conversation or "") != expected_conversation:
            return None, None, "candidate_conversation_mismatch"
        if str(target.source_conversation_key or "") != expected_conversation:
            return None, None, "source_conversation_mismatch"
        subject_key = str(target.fact_subject_key or "")
        subject_uid = subject_key.removeprefix("qq:")
        if subject_key != f"qq:{target.user_id}" or not subject_uid.isdecimal():
            return None, None, "subject_not_target"
        if (
            str(target.fact_key or "") != str(fact_key or "")
            or not target.evidence_ids
            or not target.source_row_ids
            or len(target.evidence_ids) != len(target.source_row_ids)
            or len(target.evidence_ids) != len(target.source_digests)
            or not target.captured_scope_versions
        ):
            return None, None, "evidence_binding_missing"

        placeholders = ",".join("?" for _ in target.evidence_ids)
        evidence_rows = conn.execute(
            "SELECT e.id, e.source_row_id, e.source_conversation_key, e.source_digest, "
            "e.fact_subject_key, e.provenance_json "
            "FROM memory_evidence e "
            "JOIN memory_claim_links l ON l.evidence_id = e.id "
            "JOIN memory_claim_links s ON s.owner_key = e.owner_key "
            "AND s.audience = e.audience AND s.entity_type = 'claim_state' "
            "AND s.entity_id = e.fact_key AND s.claim_key = e.fact_key "
            "AND s.projection_slot = 'eligibility' AND s.status = 'active' "
            "WHERE e.id IN (" + placeholders + ") AND e.candidate_id = ? "
            "AND e.owner_key = ? AND e.audience = ? AND e.fact_key = ? "
            "AND e.verification_status = 'accepted' "
            "AND l.entity_type = 'memory_candidate' AND l.entity_id = ? "
            "AND l.claim_key = e.fact_key AND l.projection_slot = 'candidate' "
            "AND l.status = 'active' ORDER BY e.id",
            (
                *target.evidence_ids, str(cid), str(owner_key), str(audience),
                str(fact_key), str(cid),
            ),
        ).fetchall()
        evidence_by_id = {str(item[0]): item for item in evidence_rows}
        if set(evidence_by_id) != set(target.evidence_ids):
            return None, None, "evidence_lineage_changed"
        from memory.evidence_contract import ASSESSMENT_VERSION, verify_source_snapshot

        provenance_rows = []
        for index, evidence_id in enumerate(target.evidence_ids):
            evidence = evidence_by_id[evidence_id]
            _, source_row_id, source_conversation, source_digest, fact_subject, raw = evidence
            try:
                provenance = json.loads(raw or "{}")
            except (TypeError, ValueError):
                return None, None, "evidence_provenance_malformed"
            snapshot = provenance.get("source_snapshot")
            if str(fact_subject) != f"qq:{target.user_id}":
                return None, None, "subject_not_target"
            if (
                str(source_row_id) != str(target.source_row_ids[index])
                or str(source_digest) != target.source_digests[index]
                or str(source_conversation) != expected_conversation
                or provenance.get("assessment_version") != ASSESSMENT_VERSION
                or provenance.get("verification_status") != "accepted"
                or provenance.get("claim_key") != fact_key
                or provenance.get("recording_author_key") != subject_key
                or provenance.get("fact_object_key") != subject_key
                or provenance.get("exact_support_span") != str(content or "")
                or provenance.get("conversation_key") != expected_conversation
                or str(provenance.get("source_id")) != str(source_row_id)
                or not isinstance(snapshot, dict)
                or str(snapshot.get("group_id")) != str(group_id)
                or str(snapshot.get("user_id")) != str(target.user_id)
                or str(snapshot.get("bot_id")) != str(target.source_bot_id)
                or str(snapshot.get("conversation_key")) != expected_conversation
                or str(snapshot.get("source_kind") or "").upper() == "BOT_SELF"
                or not verify_source_snapshot(snapshot, str(source_digest), conn=conn)
            ):
                return None, None, "source_binding_changed"
            provenance_rows.append(provenance)
        predicates = {str(item.get("predicate_key") or "") for item in provenance_rows}
        if len(predicates) != 1:
            return None, None, "predicate_mismatch"
        predicate_key = next(iter(predicates))
        predicate = {
            "preference.general": "address_preference",
            "profile.nickname": "self_alias",
        }.get(predicate_key, "other")
        if predicate == "other":
            return None, None, "predicate_unsupported"
        polarities = {str(item.get("polarity") or "unknown") for item in provenance_rows}
        if len(polarities) != 1 or next(iter(polarities)) not in {"positive", "negative"}:
            return None, None, "polarity_unknown"
        polarity_value = next(iter(polarities))
        recording_author = int(subject_uid)

        variants: list[QuestionVariant] = []
        term = str(content or "").strip()[:32]
        if predicate in ("self_alias", "address_preference") and term:
            variants.append(
                QuestionVariant(
                    variant_id="A",
                    question_template="对了 {nickname}，「{term}」这个说法现在还作数吗？",
                    filled_question=f"对了 {target.nickname}，「{term}」这个说法现在还作数吗？",
                    requires_bridge=False,
                )
            )

        contract = VerificationContract(
            candidate_id=str(cid),
            recording_author_id=recording_author,
            fact_subject_id=int(subject_uid),
            fact_object_id=None,
            selected_target_user_id=int(target.user_id),
            predicate_type=predicate,
            polarity=polarity_value,
            source_conversation_key=expected_conversation,
            source_row_ids=list(target.source_row_ids),
            candidate_content_digest=compute_candidate_digest(
                {"type": ctype or "", "content": content or ""}
            ),
            question_variants=variants,
            bridge_event_requirement=False,
            owner_type=str(owner_type),
            owner_key=str(owner_key),
            audience=str(audience),
            fact_subject_key=subject_key,
            fact_key=str(fact_key),
            source_bot_id=str(target.source_bot_id),
            source_group_id=str(group_id),
            evidence_ids=list(target.evidence_ids),
            source_digests=list(target.source_digests),
            captured_scope_versions=dict(target.captured_scope_versions),
        )
        return contract, variants[0] if variants else None, ""
    finally:
        conn.close()


def validate_proactive_output(
    host: ProactiveHost,
    contract,
    selected_variant,
    contract_error: str,
    lines: list[str],
) -> tuple[bool, str]:
    """发送前合同复核（复核 F11）：候选漂移/目标未绑定/编造问题 → 拒发。"""
    if contract_error:
        return False, contract_error
    if contract is None:
        return False, "contract_missing"
    if selected_variant is None:
        return False, "no_valid_variant"
    import sqlite3 as _sqlite3

    from aoede.contract import validate_contract_consistency

    conn = _sqlite3.connect(host.db_path())
    try:
        row = conn.execute(
            "SELECT id, type, content, status, owner_type, owner_key, audience, fact_key, "
            "source_conversation_key FROM memory_candidates WHERE id = ?",
            (str(contract.candidate_id),),
        ).fetchone()
        if row is None:
            return False, "candidate_missing"
        current = {
            "id": row[0], "type": row[1], "content": row[2], "status": row[3],
            "owner_type": row[4], "owner_key": row[5], "audience": row[6],
            "fact_key": row[7], "source_conversation_key": row[8],
        }
        ok, reason = validate_contract_consistency(contract, current, conn=conn)
        if not ok:
            return False, reason
    finally:
        conn.close()
    expected = selected_variant.filled_question.strip()
    actual = " ".join(str(line).strip() for line in (lines or []) if str(line).strip())
    if actual != expected:
        return False, "output_not_variant"
    return True, "ok"


async def proactive_at_user(host: ProactiveHost, bot, group_id: int, *, flow_ctx=None) -> bool:
    """尝试主动 @ 一位活跃用户以获取/验证记忆；返回是否已发言。

    与话题插话互斥：本函数返回 True 时调用方不再尝试话题插话，
    同一轮只做一件事，避免连续两次发言。

    流程：选目标（配额/冷却/退避过滤）→ 生成指令 → 跑 Pipeline →
    发送（带 @ 段）→ 记账（发出即计数）→ 起延迟任务检测回应。

    流程观测（计划 §6.4）：``flow_ctx`` 缺省时自建 ``proactive_at`` 独立
    root（避免只在生成开始后才有 trace）；定时任务传入其 timer root 时
    复用之开子 span，不另建 root。
    """
    turn_deadline = new_turn_deadline()
    own_root = flow_ctx is None
    caller_flow_ctx = flow_ctx
    if own_root:
        try:
            from core.observability import message_flow

            flow_ctx = message_flow.begin_trace(
                root_kind="proactive_at", platform="qq",
                scope=f"qq:{group_id}", origin="spawn",
                source_message_key=f"proactive_at:{group_id}:{new_trace_id()[:8]}",
            )
        except Exception:
            flow_ctx = None

        def _at_end(outcome: str) -> None:
            try:
                from core.observability import message_flow

                if flow_ctx is not None and not flow_ctx.ended:
                    message_flow.end_trace(flow_ctx, outcome=outcome)
            except Exception:
                pass
    else:
        def _at_end(outcome: str) -> None:
            return None

    outcome = ""
    try:
        allowed, reason = host.can_speak(group_id, "at")
        if not allowed:
            # 门控拒绝也有可查询原因（计划 §6.4）
            host.flow_decision(flow_ctx, "proactive.at.preflight", status="blocked",
                               reason_code=f"can_speak:{reason}",
                               instance_key=f"grp:{group_id}")
            logger.debug(f"[主动@] 群 {group_id} 跳过：{reason}")
            outcome = "gate_blocked"
            return False
        proactive = host.get_proactive()

        # 排除 Bot 自身，避免自问自答
        try:
            self_id = int(bot.self_id)
        except (TypeError, ValueError):
            self_id = 0
        # 选人观测只在调用方显式传入 ctx 时下发（计划 §6.2 显式传递）；
        # 调用方未传时保持原调用形状——自建 root 记录网关级决策，
        # 逐用户/候选事实由 pick_target 的直接调用方按需传递。
        # pick_target 经宿主调用时解析，保持 gateway 级 monkeypatch 合同。
        if caller_flow_ctx is not None:
            target = host.pick_target(group_id, exclude_user_ids={self_id, 0},
                                      bot_id=str(bot.self_id),
                                      flow_ctx=flow_ctx,
                                      instance_key=f"grp:{group_id}")
        else:
            target = host.pick_target(
                group_id,
                exclude_user_ids={self_id, 0},
                bot_id=str(bot.self_id),
            )
        if target is None:
            # 无候选 = noop 有原因：逐项原因已由 pick_target 落
            # at.preflight/at.select（计划 §6.4）
            outcome = "no_candidate"
            return False

        target.nickname = await host.resolve_nickname(bot, group_id, target.user_id)
        logger.info(
            f"🎯 [主动@] 群 {group_id} 选定用户 {target.user_id}"
            f"（{target.nickname}）：{target.reason}"
        )

        lock = host.group_locks[group_id]
        # 主动验证合同（整改计划 P5，复核 F1/F11）：pick_target 之后由服务端
        # 从候选行+来源行构建；enforce 下模型只能发送合同内变体或跳过。
        contract_mode = host.proactive_contract_mode()
        contract = None
        selected_variant = None
        contract_error = ""
        contract_data: dict = {}
        if contract_mode in ("shadow", "enforce"):
            try:
                from dataclasses import asdict

                contract, selected_variant, contract_error = build_proactive_contract(
                    host, group_id, target
                )
                if contract is not None:
                    contract_data = asdict(contract)
            except Exception as e:
                logger.warning(f"⚠️ [主动@] 合同构建异常（按无合同继续）: {e}")
                contract_error = contract_error or "contract_build_error"
        conversation_ref = host.register_group_ref(str(bot.self_id), group_id)
        async with lock:
            ctx = ChatContext(
                user_id=target.user_id,
                group_id=group_id,
                msg_id=0,
                # enforce + 合格变体：任务指令附带受限输出约束（只能输出变体
                # 原文或为空）；off/shadow 保持原指令逐字节不变
                message=(
                    build_instruction(target)
                    if not (contract_mode == "enforce" and selected_variant)
                    else build_instruction(target)
                    + "\n\n【任务约束】本轮你只能逐字输出下面这条追问（不要改写、"
                    "不要附加别的内容），如果确实没有自然承接就输出 SKIP：\n"
                    + selected_variant.filled_question
                ),
                # trigger 用 reply：主动 @ 是「对着某个具体人说话」，
                # 需要该用户的画像与记忆参与上下文构建（proactive 走的是群级检索）
                trigger="reply",
                # 纯诊断字段：日志据此区分「用户 @ 我」与「我主动 @ 人」
                intent="proactive_at",
                # v3 会话身份（计划 §6.1）：主体是 pick_target 验证过的目标
                # uid（ctx.user_id）；不补会话身份字段的话 scope_for_chat_context
                # 会按旧入口处理，目标的 USER_SHARED 个人事实永远进不来
                # （多人身份修复计划 §6.1/T18）。
                conversation_kind="group",
                conversation_key=conversation_ref.conversation_key,
                bot_ref=BotRef(
                    f"legacy-qq:{bot.self_id}", "onebot-v11", "qq", str(bot.self_id)
                ),
                scene_ref=SceneRef("group", str(group_id)),
                connection_id=f"legacy-qq:{bot.self_id}",
                adapter_name="onebot-v11",
                platform_scope="qq",
                scene_kind="group",
                scene_id=str(group_id),
                bot_id=str(bot.self_id),
                peer_id=str(group_id),
                storage_session_id=conversation_ref.storage_session_id,
                # 复核 F1：typed 检索查询 = 候选主题（不再拿整段指令模板查询）
                retrieval_query=(
                    str(target.candidate_content or "")[:80] if contract_data else ""
                ),
                verification_contract=contract_data,
                trace_id=new_trace_id(),
                turn_deadline=turn_deadline,
            )
            try:
                ctx = await host.run_turn(conversation_ref.runtime_key, ctx)
            except DeadlineExceeded as e:
                logger.info(f"⏳ [主动@] 群 {group_id} 总期限耗尽，跳过发送（{e.phase}）")
                host.flow_decision(flow_ctx, "proactive.turn", status="timed_out",
                                   reason_code=f"turn_deadline_{e.phase}",
                                   instance_key=f"grp:{group_id}")
                outcome = "deadline_exceeded"
                return False
            except RuntimeTurnError as e:
                # 取消（reset/新直接请求抢占）：无发送、无记账，不落通用异常兜底
                if e.code == E_CANCELLED:
                    logger.info(f"🔇 [主动@] 群 {group_id} 轮次已取消，静默退出")
                    host.flow_decision(flow_ctx, "proactive.turn", status="cancelled",
                                       reason_code="turn_cancelled",
                                       instance_key=f"grp:{group_id}")
                    outcome = "cancelled"
                    return False
                raise
            except Exception as e:
                logger.error(f"主动 @ Pipeline 异常: {e}")
                host.flow_decision(flow_ctx, "proactive.turn", status="failed",
                                   reason_code="pipeline_error",
                                   instance_key=f"grp:{group_id}")
                outcome = "turn_error"
                return False

            if not ctx.lines:
                host.flow_decision(flow_ctx, "proactive.filter", status="skipped",
                                   reason_code="empty_output",
                                   instance_key=f"grp:{group_id}")
                outcome = "empty_output"
                return False

            # 发送前合同复核（整改计划 P5，复核 F11）：候选漂移/主体错位/
            # 编造问题一律跳过——不发送、不记账、原因落 flow。
            if contract_mode == "enforce":
                ok, reason = validate_proactive_output(
                    host, contract, selected_variant, contract_error, ctx.lines
                )
                if not ok:
                    proactive.mark_proactive_skip(
                        group_id, target.user_id, target.skip_subject
                    )
                    host.flow_decision(flow_ctx, "proactive.contract", status="skipped",
                                       reason_code=f"contract:{reason}",
                                       instance_key=f"grp:{group_id}")
                    logger.info(
                        f"🛡️ [主动@] 群 {group_id} 合同复核拒绝（{reason}），"
                        f"跳过发送与记账"
                    )
                    outcome = "contract_rejected"
                    return False
                # 输出即为服务端变体原文：回填一行，防多行拼接走样
                ctx.lines = [selected_variant.filled_question]

            if is_proactive_skip(ctx.lines):
                proactive.mark_proactive_skip(
                    group_id,
                    target.user_id,
                    target.skip_subject,
                )
                host.flow_decision(flow_ctx, "proactive.filter", status="skipped",
                                   reason_code="naturalness_skip",
                                   instance_key=f"grp:{group_id}")
                logger.info(
                    f"⏭️ [主动@] 群 {group_id} 用户 {target.user_id} "
                    f"当前没有自然承接，跳过发送与记账（subject={target.skip_subject}）"
                )
                outcome = "naturalness_skip"
                return False

            # 主动 @ 只发一句：追问必须简短，多行会像连续质询
            line = host.join_lines_naturally(ctx.lines) if len(ctx.lines) > 1 else ctx.lines[0].strip()
            if not line:
                host.flow_decision(flow_ctx, "proactive.filter", status="skipped",
                                   reason_code="empty_joined_line",
                                   instance_key=f"grp:{group_id}")
                outcome = "empty_output"
                return False

            if proactive.recently_spoken(group_id, [line]):
                host.flow_decision(flow_ctx, "proactive.filter", status="skipped",
                                   reason_code="duplicate_output",
                                   instance_key=f"grp:{group_id}")
                logger.info(f"🛑 [主动@] 群 {group_id} 与已发言内容重复，跳过")
                outcome = "duplicate_output"
                return False

            # 逐段发送 + 回执收集（计划 §6.1）：发送确认之后才记账。原实现先记账
            # 后发送，发送失败时配额/发言占用/学习全被白白消耗。
            scope = ConversationScope.from_context(ctx) if host.social_delivery_enabled() else None

            async def _send_at_segment(seg_line: str, _i: int):
                message = OutboundMessage((
                    OutboundSegment.at(str(target.user_id), target.nickname),
                    OutboundSegment.text_segment(" " + seg_line),
                ))
                return await host.get_outbound_service().send(
                    host.delivery_target_for_context(ctx), message, bot_handle=bot,
                    deadline=getattr(ctx, "turn_deadline", None),
                )

            delivery_target = str(target.user_id)
            try:
                delivery_plan = host.seal_ctx_delivery_plan(
                    ctx, [line], target_user_id=delivery_target,
                    variant_origin=("proactive-contract" if contract_mode == "enforce"
                                    else "proactive-at-user"),
                )
            except DeliveryPlanError as e:
                host.flow_decision(flow_ctx, "proactive.send", status="blocked",
                                   reason_code="invalid_delivery_plan",
                                   summary=str(e)[:160], instance_key=f"grp:{group_id}")
                outcome = "delivery_plan_rejected"
                return False
            receipts = await deliver_lines(
                delivery_plan,
                scope=scope,
                trace_id=ctx.trace_id,
                turn_id=ctx.turn_id,
                send_one=_send_at_segment,
                deadline=getattr(ctx, "turn_deadline", None),
                plan_guard=lambda plan: host.delivery_plan_is_current(
                    ctx, plan, target_user_id=delivery_target,
                ),
            )
            delivered = delivered_texts(receipts)
            if not delivered:
                logger.error(f"[主动@] 群 {group_id} 发送失败，不记账不学习")
                host.flow_decision(flow_ctx, "proactive.send", status="failed",
                                   reason_code="no_segment_delivered",
                                   instance_key=f"grp:{group_id}")
                outcome = "not_delivered"
                return False

            # 只对确认送达的段记账（计划 §6.4）：记账事实随 span 可查
            with host.flow_span(flow_ctx, "proactive.after",
                                instance_key=f"grp:{group_id}"):
                host.flow_checkpoint(flow_ctx, "proactive.after",
                                     summary="acknowledged-only bookkeeping",
                                     metrics={"delivered_segments": len(delivered),
                                              "total_segments": len(receipts)})
                proactive.mark_spoke(group_id)
                proactive.record_spoken(group_id, delivered)
                # 评分层记账：主动 @ 同样算主动发言（上游 §14 的区分只针对被动应答）
                with contextlib.suppress(Exception):
                    host.get_participation_manager().note_stella_spoke(group_id, "proactive")
                host.flow_checkpoint(flow_ctx, "proactive.after",
                                     summary="note_stella_spoke(proactive)")
                # 回复效果学习（设计阶段六）：目标是「主动 @ 是否被回应/忽略」；
                # message 传空——build_instruction 的罐头指令不是用户的表达素材。
                from memory import expression_learning

                expression_learning.on_reply_sent(
                    group_id=group_id,
                    group_shared_space=ctx.group_shared_space,
                    user_id=target.user_id,
                    message="",
                    lines=delivered,
                    trigger="proactive",
                    turn_id=ctx.turn_id,
                    trace_id=ctx.trace_id,
                    intent="proactive_at",
                    bot_id=scope.bot_id if scope else "",
                    connection_id=scope.connection_id if scope else "",
                )
                logger.success(f"✨ [主动@] 群 {group_id} → {target.user_id}: {delivered[0]}")

                await host.record_bot_lines(
                    self_id, conversation_ref.storage_session_id, delivered,
                    origin=ctx, receipts=receipts,
                )

                # 主动 @ 同样推进对话：回复后异步触发压缩（不阻塞本次发言）
                if ctx.tail_start_id:
                    host.schedule_compact(
                        conversation_ref.storage_session_id, ctx.tail_start_id
                    )
                    host.flow_checkpoint(flow_ctx, "proactive.after",
                                         summary="compact spawned, not awaited")

        # 发出即计数（不论是否获得回应），否则无回应的追问不占配额，
        # 会导致对同一个人连续搭话
        host.record_at(
            group_id,
            target.user_id,
            candidate_id=target.candidate_id,
        )

        # 起后台任务检测回应；登记到集合防止被 GC 回收（经宿主注册，
        # 装配层关停 drain 与既有测试断言共用同一集合）。
        task = asyncio.create_task(
            host.check_reply_later(group_id, target.user_id, time.monotonic())
        )
        register_reply_check_task(task, host=host)
        outcome = "delivered"
        return True
    finally:
        _at_end(outcome or "closed")
