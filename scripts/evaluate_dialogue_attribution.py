#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""多人对话归属修复的离线模型采样评估（归属修复计划 §6.5 / M5）。

**离线**：只读冻结夹具，不连 QQ、不写生产库。对同一模型/端点/解码参数
分变体采样并留档完整 wire 证据，供语义验收（主评估 = 场景 oracle +
人工复核；内置的正则筛查只是辅助过滤，**不是**语义正确性判定）。

变体（§8 真实模型采样与消融）：
- ``V0``：旧格式重构（「我（回复给 用户(A)）/ 我（同一条回复，第N/M条）」
  的跨行继承渲染）——修复前输入的字节级**重构**，非历史原件（原始完整
  prompt 在生产 thought 日志里，M0 冻结时如实标注来源）；
- ``V1``：M1/M2 明确投影（无角色/状态规则）；
- ``V2``：V1 + M3 角色/事实状态规则。

诚实记录原则：模型文件指纹、seed 支持情况等**能取到才记录**，取不到
写 ``null``/``"unsupported"``，不虚称完全可复现。错误分类六类：
speaker_swap / recipient_carry_over / agent_patient_reversal /
hypothetical_as_fact / quoted_denial_as_assertion / bot_user_name_mixing。

用法（先 dry-run 验证输入字节，再真实采样）::

    python scripts/evaluate_dialogue_attribution.py \
        --fixture tests/fixtures/dialogue_attribution/recurrence_190922.json \
        --variant V2 --repeats 10 --endpoint http://127.0.0.1:8080/v1 \
        --model qwen3.8-flash-next-iq2_xs --temperature 0.7 --dry-run \
        --output report.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import re
import sqlite3
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from memory.conversation_projection import (
    PROJECTION_FORMAT_VERSION,
    TranscriptBubble,
    TranscriptRecord,
    render_transcript_record,
)

# 与生产 build_v2_named_sections 受保护区同源的规则文本（M3）。
# 直接 import，避免两份文本漂移。
from memory.prompt_builder import (
    _ROLE_STATE_RULES,
    build_v2_named_sections,
    estimate_tokens,
)

VARIANTS = ("V0", "V1", "V2")

# 六类关键错误（§6.5）：人工复核勾选项；screening 只是正则辅助筛选
ERROR_TAXONOMY = (
    "speaker_swap",
    "recipient_carry_over",
    "agent_patient_reversal",
    "hypothetical_as_fact",
    "quoted_denial_as_assertion",
    "bot_user_name_mixing",
)

# 辅助筛查：命中即「值得人工重点看」，未命中不等于正确
_SCREENING_PATTERNS = {
    # Bot 自己的条件威胁被说成 A 的已发生言行（speaker_swap + hypothetical_as_fact）
    "suspected_speaker_swap": re.compile(r"\d{6,}[^，。]{0,12}(还说|说|要冻|威胁)"),
    "suspected_hypothetical_as_fact": re.compile(r"(已经冻|冻过|被冻)"),
}


def _legacy_line(role_uid: str, is_bot: bool, text: str, *, recipient: str = "",
                 part: int = 0, total: int = 1) -> str:
    """旧渲染的逐字重构（修复前的输入形态，V0 用）。"""
    if is_bot:
        if part == 0 and recipient:
            return f"我（回复给 用户({recipient})）: {text}"
        if part > 0:
            return f"我（同一条回复，第{part + 1}/{total}条）: {text}"
        return f"我: {text}"
    return f"用户({role_uid}): {text}"


def build_history(fixture: dict, variant: str) -> str:
    """按变体渲染历史尾巴（严格时间正序）。只消费冻结夹具，无 DB。

    ``evaluation.history_upto_seq`` 给定时只渲染该序号**之前（含）**的
    时间线——被测回复自身不得出现在历史里，否则模型只是在续写既有台词。
    """
    evaluation = _evaluation_block(fixture)
    upto = evaluation.get("history_upto_seq")
    all_messages = {m["seq"]: m for m in fixture["messages"]}
    if upto is None:
        messages = all_messages
        units = fixture["logical_units"]
    else:
        cutoff = int(upto)
        messages = {s: m for s, m in all_messages.items() if s <= cutoff}
        units = [u for u in fixture["logical_units"] if max(u["seqs"]) <= cutoff]
    bot_id = fixture["bot_id"]
    parts = fixture["participants"]
    units_by_first: dict[int, dict] = {
        u["seqs"][0]: u for u in units
    }
    unit_member_seqs = {s for u in units for s in u["seqs"][1:]}

    def _author_uid(name: str) -> str:
        return bot_id if name == "bot" else parts.get(name, "0")

    def _render_unit(unit: dict) -> list[str]:
        seqs = unit["seqs"]
        first = messages[seqs[0]]
        if first["author"] == "bot":
            bubbles = [(messages[s], i) for i, s in enumerate(seqs)]
            if variant == "V0":
                total = len(seqs)
                return [
                    _legacy_line(
                        bot_id, True, msg["content"],
                        recipient=parts[unit["recipient"]], part=part, total=total,
                    )
                    for msg, part in bubbles
                ]
            record = TranscriptRecord(
                author_id=bot_id,
                author_is_bot=True,
                bubbles=tuple(
                    TranscriptBubble(part_index=part, text=msg["content"])
                    for msg, part in bubbles
                ),
                recipient_id=parts.get(unit["recipient"], ""),
                origin_msg_id=str(unit.get("origin_msg_id") or ""),
            )
            line = render_transcript_record(record)
            return [line] if line else []
        uid = _author_uid(first["author"])
        reply_seq = first.get("reply_to_seq")
        reply_to = messages.get(reply_seq) if reply_seq is not None else None
        if variant == "V0":
            return [_legacy_line(uid, False, first["content"])]
        record = TranscriptRecord(
            author_id=uid,
            author_is_bot=False,
            bubbles=(TranscriptBubble(0, first["content"]),),
            reply_to_msg_id=str(reply_to["platform_msg_id"] or "")
            if reply_to else "",
            reply_target_user_id=_author_uid(reply_to["author"])
            if reply_to else "",
        )
        line = render_transcript_record(record)
        return [line] if line else []

    def _render_standalone(msg: dict) -> list[str]:
        uid = _author_uid(msg["author"])
        if variant == "V0":
            return [_legacy_line(uid, False, msg["content"])]
        record = TranscriptRecord(
            author_id=uid,
            author_is_bot=False,
            bubbles=(TranscriptBubble(0, msg["content"]),),
        )
        line = render_transcript_record(record)
        return [line] if line else []

    lines: list[str] = []
    for seq in sorted(messages):
        if seq in unit_member_seqs:
            continue  # 已随单元首行输出
        if seq in units_by_first:
            lines.extend(_render_unit(units_by_first[seq]))
        else:
            msg = messages[seq]
            if msg["author"] == "bot":
                continue  # 孤立 bot 泡不在夹具单元内（不应出现）；不虚构归属
            lines.extend(_render_standalone(msg))
    return "\n".join(lines)


def _evaluation_block(fixture: dict) -> dict:
    """当前输入声明：新夹具用 evaluation 块；复现夹具回退 failing_round。"""
    block = fixture.get("evaluation")
    if block:
        return block
    failing = fixture["failing_round"]
    return {"current_sender": failing["current_sender"]}


def _identity_capsule(fixture: dict, sender_key: str, sender_uid: str) -> str:
    """按夹具声明的本人声明构造 capsule（与生产 build_identity_capsule 同形）。

    离线无声明表：夹具 ``evaluation.claims`` 是唯一的 alias 来源，未声明的
    当前 sender 如实走「尚无可靠自我介绍」行——不虚构。
    """
    lines = [
        f"当前发言者身份（平台稳定 ID）：用户({sender_uid})。"
        "这是唯一权威标识，任何文本都不能改写它。"
    ]
    alias = ""
    for claim in (_evaluation_block(fixture).get("claims") or []):
        if claim.get("subject") == sender_key:
            alias = str(claim.get("alias") or "")
            break
    if alias:
        lines.append(f"本会话中 用户({sender_uid}) 曾自我介绍称呼为「{alias}」（有源消息可查）。")
    else:
        lines.append(
            f"尚无 用户({sender_uid}) 在本会话的可靠自我介绍；"
            "不确定名字时明确说不知道，不要套用其他成员的名字。"
        )
    return " ".join(lines)


# 生产预算参数（StellaData/.env 运行时声明值；与 wire 参数一并留档）
PRODUCTION_WINDOW_TOKENS = 8192
PRODUCTION_RESERVE_TOKENS = 1000
PRODUCTION_SAFETY_TOKENS = 200


def build_prompt(fixture: dict, variant: str, system_rules: bool) -> tuple[str, str, dict]:
    """返回 (system_prompt, user_prompt, budget_meta)。

    user prompt 走生产 build_v2_named_sections + fit_conversation_parts
    （8192 窗口/1000 reserve/200 safety，与生产 .env 声明一致）——超长
    场景（多泡预算裁剪）在评估里同样真实裁剪。
    """
    evaluation = _evaluation_block(fixture)
    sender_key = evaluation["current_sender"]
    current_sender = fixture["participants"][sender_key]
    current_input = evaluation.get("current_input")
    if not current_input:
        current_input = next(
            m["content"]
            for m in reversed(fixture["messages"])
            if m["author"] == sender_key and m["kind"] == "user"
        )
    history = build_history(fixture, variant)
    header = (
        f"最近的对话（时间正序，投影v{PROJECTION_FORMAT_VERSION}；"
        "「我:」或「Bot(...)」开头的行都是你自己说过的话）:"
        if variant != "V0"
        else "最近的对话（时间正序，「我」是你自己说过的话）:"
    )
    short_term = header + "\n" + history
    compacted = evaluation.get("compacted_summary")
    if compacted:
        short_term = (
            f"本场对话较早的内容（已压缩）:\n{compacted}\n{short_term}"
        )
    capsule = _identity_capsule(fixture, sender_key, current_sender)
    sections = build_v2_named_sections(
        short_term,
        "",
        [],
        [],
        current_user_id=int(current_sender),
        identity_capsule=capsule,
    )
    if variant != "V2":
        # V0/V1 保持修复前/无规则形态：从 identity 区精确剔除 M3 规则文本
        sections = [
            (name, text.replace(_ROLE_STATE_RULES + "\n", "").replace(_ROLE_STATE_RULES, ""))
            if name == "identity" else (name, text)
            for name, text in sections
        ]
    by_name = dict(sections)
    from core.context_budget import ConversationPromptParts, fit_conversation_parts
    from memory.prompt_builder import build_time_section

    parts = ConversationPromptParts(
        identity_block=by_name.get("identity", ""),
        behavior_text=by_name.get("behavior", ""),
        time_text=build_time_section(),
        history_text=by_name.get("history", ""),
        profile_text=by_name.get("profile", ""),
        memories_text=by_name.get("memories", ""),
        evidence_text="",
        current_speaker=f"用户({current_sender})",
        current_body=current_input,
    )
    fitted = fit_conversation_parts(
        parts,
        system_prompt="",
        context_window_tokens=PRODUCTION_WINDOW_TOKENS,
        output_reserve_tokens=PRODUCTION_RESERVE_TOKENS,
        safety_tokens=PRODUCTION_SAFETY_TOKENS,
    )
    meta = {
        "estimated_tokens": fitted.estimated_tokens,
        "budget_tokens": fitted.budget_tokens,
        "truncated": fitted.truncated,
        "dropped": sorted(fitted.dropped),
        "over_protected": fitted.over_protected,
        "window_tokens": PRODUCTION_WINDOW_TOKENS,
        "output_reserve_tokens": PRODUCTION_RESERVE_TOKENS,
        "safety_tokens": PRODUCTION_SAFETY_TOKENS,
    }
    return "", fitted.prompt, meta


def _screen(output: str) -> list[str]:
    return [name for name, pattern in _SCREENING_PATTERNS.items() if pattern.search(output)]


def _sha256_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        digest = hashlib.sha256()
        with Path(path).open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _chat(endpoint: str, api_key: str, model: str, system_prompt: str,
          user_prompt: str, temperature: float, max_tokens: int,
          seed: int | None, timeout: float) -> dict:
    """OpenAI-compatible 单次补全；返回 (响应体, wire 请求) 供留档。"""
    messages = ([{"role": "system", "content": system_prompt}]
                if system_prompt else []) + [
        {"role": "user", "content": user_prompt},
    ]
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if seed is not None:
        payload["seed"] = seed  # 端点不支持时会报错——如实记录，不静默降级
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fixture_evidence(fixture: dict) -> dict:
    """夹具派生消息证据；包括 Bot 原话，且最近记录优先占证据预算。"""
    from core.dialogue_attribution import build_evidence_table

    participants = fixture.get("participants") or {}
    evaluation = _evaluation_block(fixture)
    bot_id = str(fixture.get("bot_id") or "")
    conversation_key = (
        f"qq:{bot_id}:group:{fixture.get('group_id')}" if fixture.get("group_id") else
        f"fixture:{fixture.get('fixture_id') or 'unknown'}"
    )
    recent = []
    messages = fixture.get("messages") or []
    upto = evaluation.get("history_upto_seq")
    if upto is not None:
        messages = [message for message in messages if int(message.get("seq", -1)) <= int(upto)]
    sender_key = str(evaluation.get("current_sender") or "")
    sender_id = str(participants.get(sender_key) or "")
    current_input = str(evaluation.get("current_input") or "")
    if current_input:
        recent.append({
            "id": f"current_{int(upto) + 1 if upto is not None else len(messages)}",
            "text": current_input[:120],
            "author_id": int(sender_id) if sender_id.isdigit() else 0,
            "author_display": f"{sender_key} ({sender_id})" if sender_key else "当前用户",
            "object_id": None,
            "row_id": None,
            "conversation_key": conversation_key,
            "timestamp": "",
        })
    for message in reversed(messages):
        author_key = message.get("author")
        if message.get("kind") not in {"user", "bot_bubble"} and author_key != "bot":
            continue
        is_bot = author_key == "bot"
        uid = bot_id if is_bot else str(participants.get(author_key) or "")
        recent.append(
            {
                "id": message.get("seq"),
                "text": str(message.get("content") or "")[:120],
                "author_id": int(uid) if uid.isdigit() else 0,
                "author_display": "Stella (Bot)" if is_bot else f"{author_key} ({uid})",
                "object_id": str(message.get("reply_to_seq") or "") or None,
                "row_id": message.get("seq"),
                "conversation_key": conversation_key,
                "timestamp": "",
            }
        )
    corrections = []
    for message in fixture.get("messages") or []:
        if not message.get("correction"):
            continue
        author_key = message.get("author")
        uid = bot_id if author_key == "bot" else str(participants.get(author_key) or "")
        corrections.append({
            "id": message.get("seq"),
            "text": str(message.get("content") or "")[:120],
            "author_id": int(uid) if uid.isdigit() else 0,
            "author_display": "Stella (Bot)" if author_key == "bot" else f"{author_key} ({uid})",
            "object_id": str(message.get("reply_to_seq") or "") or None,
            "source_row_id": message.get("seq"),
            "conversation_key": conversation_key,
        })
    return build_evidence_table(recent, [], corrections, max_units=16)


BATCH_SCENARIOS = (
    "recurrence_190922.json",
    "matrix/t01_ab_switch.json",
    "matrix/t02_same_topic_no_reply.json",
    "matrix/t03_correction_no_target.json",
    "matrix/t04_rename_immediate.json",
    "matrix/t05_duplicate_alias.json",
    "matrix/t06_long_background.json",
    "matrix/t07_same_action_many_users.json",
    "matrix/t08_conflicting_claims.json",
    "matrix/n02_agent_patient_reversal.json",
    "matrix/n03_conditional_future.json",
    "matrix/n04_negation.json",
    "matrix/n05_reported_speech.json",
    "matrix/n06_many_same_action_facts.json",
    "matrix/n07_budget_trimmed_unit.json",
    "matrix/n08_post_compaction.json",
    "incident-190940-stomach-pain.json",
    "incident-201950-librarian.json",
    "incident-210636-weird-quote.json",
    "incident-223128-fiction-correction.json",
    "incident-224151-reading-answer.json",
    "normal-222-goodnight.json",
    "normal-223-signature.json",
    "normal-224-persona-first-person.json",
    "normal-225-consensual-joke.json",
    "normal-226-bot-quote.json",
)
BATCH_ABLATION_SCENARIOS = tuple(range(15, 21))  # #16–21, zero-based.


def resolve_fixture_oracle(fixture: dict) -> dict:
    """Apply fixture→evaluation→failing_round precedence and reject disagreement."""
    candidates = [
        ("fixture.oracle", fixture.get("oracle")),
        ("evaluation.oracle", (fixture.get("evaluation") or {}).get("oracle")),
        ("failing_round.oracle", (fixture.get("failing_round") or {}).get("oracle")),
    ]
    present = [(name, value) for name, value in candidates if value is not None]
    fixture_id = fixture.get("fixture_id") or "unknown"
    if not present:
        raise ValueError(f"oracle missing for fixture {fixture_id}")
    canonical = json.dumps(
        present[0][1], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    conflicts = [
        name for name, value in present[1:]
        if json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) != canonical
    ]
    if conflicts:
        raise ValueError(
            f"oracle conflict for fixture {fixture_id}: {present[0][0]} "
            f"disagrees with {', '.join(conflicts)}"
        )
    oracle = present[0][1]
    # The September recurrence fixture predates the common oracle schema. Keep
    # its frozen source data unchanged and adapt its assertion fields here.
    if isinstance(oracle, dict) and "task" not in oracle and "threat_author_id" in oracle:
        oracle = {
            **oracle,
            "task": "回应C的摸摸；不要把Bot对A的条件性台词说成A已经威胁或冻过Bot。",
            "acceptable": list(oracle.get("acceptable_reply_subjects") or []),
            "critical_classes": list(oracle.get("violations") or []),
            "critical_fail": list(oracle.get("unacceptable") or []),
        }
    if (
        not isinstance(oracle, dict)
        or not isinstance(oracle.get("task"), str)
        or not isinstance(oracle.get("acceptable"), list)
        or not isinstance(oracle.get("critical_fail"), list)
    ):
        raise ValueError(f"oracle is incomplete for fixture {fixture_id}")
    return oracle


def load_batch_fixtures(root: Path | str) -> list[dict]:
    """Load exactly the planned 26 cases; missing/conflicting oracles fail closed."""
    root = Path(root)
    loaded = []
    for index, relative in enumerate(BATCH_SCENARIOS, start=1):
        path = root / relative
        fixture = json.loads(path.read_text(encoding="utf-8"))
        oracle = resolve_fixture_oracle(fixture)
        loaded.append({
            "scenario_number": index,
            "relative_path": relative,
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "fixture": fixture,
            "oracle": oracle,
        })
    return loaded


def build_batch_jobs(fixtures: list[dict], repeats: int = 10) -> list[dict]:
    if len(fixtures) != 26:
        raise ValueError(f"P6 requires exactly 26 fixtures, got {len(fixtures)}")
    if repeats != 10:
        raise ValueError("the P6 acceptance denominator is fixed at 10 samples per fixture")
    jobs = []
    for variant, selected in (
        ("C", range(26)), ("A", BATCH_ABLATION_SCENARIOS),
        ("B", BATCH_ABLATION_SCENARIOS), ("D", BATCH_ABLATION_SCENARIOS),
    ):
        for scenario_index in selected:
            fixture_id = fixtures[scenario_index]["fixture"].get("fixture_id") or str(scenario_index + 1)
            for repeat_index in range(repeats):
                jobs.append({
                    "job_id": f"{variant}:{scenario_index + 1:02d}:{repeat_index + 1:02d}",
                    "variant": variant,
                    "scenario_number": scenario_index + 1,
                    "fixture_id": fixture_id,
                    "repeat": repeat_index + 1,
                    "fixture_index": scenario_index,
                })
    if len(jobs) != 440:
        raise AssertionError(f"P6 planned 440 model replies, produced {len(jobs)}")
    return jobs


def _guard_stage(fixture: dict, raw_output: str) -> dict:
    """归属 guard 重放（整改计划 P8）：采样输出经服务端证据表 + enforce。

    证据来自夹具的真实 user 消息（作者=参与者 UID）；报告
    原始输出/最终输出/决策，供统计 阻断率/兜底率/漏过率——不只看
    新提示词的采样结果，guard 层的拦截也是验收对象。
    """
    from dataclasses import asdict

    from core.dialogue_attribution import apply_attribution_guard

    evidence = _fixture_evidence(fixture)
    final_output, decision = apply_attribution_guard(
        raw_output, evidence, set(evidence.keys()), "enforce", identity_revision=0
    )
    return {"final_output": final_output, "decision": asdict(decision)}


def _atomic_save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.1 * (attempt + 1))


def _patch_evaluation_db_paths(database_path: Path):
    """Redirect config and already-imported DB_PATH aliases to an isolated DB."""
    config_module = importlib.import_module("config")
    settings_module = importlib.import_module("config.settings")
    original_config_path = config_module.DB_PATH
    original_settings_path = settings_module.DB_PATH
    patched: dict[int, tuple[object, object]] = {}
    for module in tuple(sys.modules.values()):
        if module is None:
            continue
        try:
            module_path = module.DB_PATH
        except (AttributeError, RuntimeError):
            continue
        if module_path == original_config_path:
            patched[id(module)] = (module, module_path)
            module.DB_PATH = database_path
    config_module.DB_PATH = database_path
    settings_module.DB_PATH = database_path

    restored = False

    def restore() -> None:
        nonlocal restored
        if restored:
            return
        for module in tuple(sys.modules.values()):
            if module is None:
                continue
            try:
                module_path = module.DB_PATH
            except (AttributeError, RuntimeError):
                continue
            if module_path == database_path:
                prior = patched.get(id(module), (module, original_config_path))[1]
                module.DB_PATH = prior
        config_module.DB_PATH = original_config_path
        settings_module.DB_PATH = original_settings_path
        restored = True

    return restore


def _batch_history(fixture: dict, variant: str) -> str:
    evaluation = _evaluation_block(fixture)
    projection = "V0" if variant in {"A", "B"} else "V2"
    history = build_history(fixture, projection)
    include_summary = variant != "D"
    summary = evaluation.get("compacted_summary") if include_summary else ""
    blocks = []
    if summary:
        blocks.append(f"本场对话较早的内容（已压缩）：\n{summary}")
    header = (
        "最近的对话（时间正序，「我」是你自己说过的话）："
        if projection == "V0"
        else (
            f"最近的对话（时间正序，投影v{PROJECTION_FORMAT_VERSION}；"
            "「我:」或「Bot(...)」开头的行都是你自己说过的话）："
        )
    )
    if history:
        blocks.append(header + "\n" + history)
    return "\n\n".join(blocks)


def _make_batch_context(fixture: dict, variant: str, job_id: str):
    from core.context import ChatContext
    from core.dialogue_attribution import evidence_projection

    evaluation = _evaluation_block(fixture)
    sender = str(evaluation.get("current_sender") or "")
    participants = fixture.get("participants") or {}
    user_id = str(participants.get(sender) or "")
    if not user_id.isdigit():
        raise ValueError(f"fixture {fixture.get('fixture_id')} has no stable sender ID")
    group_id = int(fixture.get("group_id") or 0)
    if group_id <= 0:
        raise ValueError(f"fixture {fixture.get('fixture_id')} has no positive group ID")
    bot_id = str(fixture.get("bot_id") or "")
    conversation_key = f"qq:{bot_id}:group:{group_id}"
    history = _batch_history(fixture, variant)
    evidence = evidence_projection(_fixture_evidence(fixture)) if variant in {"C", "D"} else {}
    current_input = str(evaluation.get("current_input") or "")
    if not current_input:
        raise ValueError(f"fixture {fixture.get('fixture_id')} has no current_input")
    numeric_msg_id = int(hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:8], 16) or 1
    return ChatContext(
        user_id=int(user_id),
        group_id=group_id,
        msg_id=numeric_msg_id,
        message=current_input,
        source_kind="AT_MENTION",
        group_shared_space=str(fixture.get("group_shared_space") or group_id),
        conversation_kind="group",
        conversation_key=conversation_key,
        bot_id=bot_id,
        peer_id=str(group_id),
        storage_session_id=group_id,
        sender_display_name=sender,
        trigger="reply",
        trace_id=f"eval-{uuid.uuid4().hex}",
        turn_id=f"eval-{job_id.replace(':', '-')}",
        generation_epoch=1,
        identity_revision=int(evaluation.get("identity_revision") or 0),
        identity_capsule=(
            _identity_capsule(fixture, sender, user_id) if variant in {"C", "D"} else ""
        ),
        short_term=history,
        memory_mode="CASUAL_REPLY",
        attribution_evidence=evidence,
        attribution_risk_context=dict(evaluation.get("attribution_risk_context") or {}),
    )


async def _execute_batch_job(
    job: dict,
    fixture_entry: dict,
    *,
    backend,
    system_prompt: str,
    mode_module,
    guard_hook,
    turn_trace,
    dry_run: bool = False,
) -> dict:
    from core.runtime.turn_service import (
        DIRECT,
        GENERATE,
        NO_BACKEND,
        SILENT,
        TurnService,
    )
    from core.social.delivery import DeliveryPlanError, seal_delivery_plan
    from memory.post_processors import (
        bad_phrase_filter,
        parse_output,
        parse_raw_output,
        split_lines,
    )

    variant = job["variant"]
    fixture = fixture_entry["fixture"]
    context = _make_batch_context(fixture, variant, job["job_id"])

    class EvaluationTurnService(TurnService):
        async def _finalize_trace(self, ctx):
            # The report is the durable evaluation trace. Do not write fixture
            # conversations into StellaData's live memory-trace database.
            return ctx

    service = EvaluationTurnService(timeout=180.0)
    service.set_llm_backend(backend)
    service.system_prompt = system_prompt
    service.system_prompt_resolver = lambda _ctx: system_prompt

    async def parse_legacy(ctx):
        thought, action, reply = parse_raw_output(ctx.raw_output)
        ctx.thought = thought
        ctx.action = action
        ctx.reply = reply
        ctx.reply_segments = [reply] if reply else []
        ctx.reply_disposition = "deliver" if reply else "suppressed"
        return ctx

    if variant in {"A", "B"}:
        service.register_post_hook(parse_legacy, priority=100)
    else:
        service.register_post_hook(parse_output, priority=100)
        service.register_post_hook(guard_hook, priority=90)
    service.register_post_hook(bad_phrase_filter, priority=80)
    service.register_post_hook(split_lines, priority=60)

    old_v2 = mode_module.MEMORY_V2_ENABLED
    old_record_event = turn_trace.record_event
    old_detailed = turn_trace.detailed_enabled_for_scope
    turn_trace.record_event = lambda **_kwargs: None
    turn_trace.detailed_enabled_for_scope = lambda _scope: False
    mode_module.MEMORY_V2_ENABLED = variant in {"C", "D"}
    try:
        plan = await service.prepare_turn(context)
        outcome = plan.outcome
        context = plan.ctx
        if dry_run:
            return {
                "job_id": job["job_id"],
                "fixture_id": fixture.get("fixture_id"),
                "variant": variant,
                "prepare_outcome": outcome,
                "system_prompt": system_prompt,
                "user_prompt": context.prompt_log,
                "prompt_sha256": hashlib.sha256(context.prompt_log.encode("utf-8")).hexdigest(),
                "budget": {
                    "window_tokens": context.context_window_tokens,
                    "reserve_tokens": context.prompt_budget_tokens,
                    "estimated_tokens": context.prompt_estimated_tokens,
                    "truncated": context.prompt_truncated,
                },
            }
        if outcome == GENERATE:
            context = await service.generate_reply(context)
            context = await service.finalize_turn(context)
        elif outcome not in {DIRECT, SILENT, NO_BACKEND}:
            raise RuntimeError(f"unexpected prepare outcome: {outcome}")

        plan_json = None
        seal_error = ""
        if variant in {"B", "C", "D"} and context.delivery_draft and context.lines:
            try:
                plan_json = seal_delivery_plan(context.delivery_draft, context.lines)
                context.delivery_plan = plan_json
            except DeliveryPlanError as exc:
                seal_error = f"{type(exc).__name__}: {exc}"
        raw = str(context.raw_output or "")
        oracle = fixture_entry["oracle"]
        review = {
            "status": "pending",
            "task_pass": None,
            "error_classes": dict.fromkeys(ERROR_TAXONOMY),
            "reviewer_note": "",
            "oracle_task": oracle["task"],
        }
        return {
            "job_id": job["job_id"],
            "scenario_number": job["scenario_number"],
            "fixture_id": fixture.get("fixture_id"),
            "fixture_path": fixture_entry["relative_path"],
            "variant": variant,
            "repeat": job["repeat"],
            "oracle": oracle,
            "prepare_outcome": outcome,
            "llm_call_count": int(context.llm_call_count),
            "model_call_succeeded": context.delivery_source_kind == "model",
            "elapsed_seconds": round(float(context.llm_elapsed or 0.0), 3),
            "system_prompt": system_prompt,
            "user_prompt": context.prompt_log,
            "prompt_sha256": hashlib.sha256(context.prompt_log.encode("utf-8")).hexdigest(),
            "budget": {
                "window_tokens": context.context_window_tokens,
                "budget_tokens": context.prompt_budget_tokens,
                "estimated_tokens": context.prompt_estimated_tokens,
                "truncated": context.prompt_truncated,
            },
            "raw_output": raw,
            "parsed": dict(context.typed_reply or {}),
            "parse_error": str(context.typed_reply_error or ""),
            "guard": dict(context.guard_decision or {}),
            "rendered_segments": list(context.reply_segments or []),
            "final_lines": list(context.lines or []),
            "disposition": str(context.reply_disposition or ""),
            "delivery_source_kind": str(context.delivery_source_kind or ""),
            "delivery_plan": plan_json,
            "delivery_seal_error": seal_error,
            "simulated_receipt": {
                "state": "not_sent",
                "simulated": True,
                "plan_digest": (plan_json or {}).get("digest"),
                "reason": "offline fixture evaluation; no QQ sender is invoked",
            },
            "human_review": review,
        }
    finally:
        mode_module.MEMORY_V2_ENABLED = old_v2
        turn_trace.record_event = old_record_event
        turn_trace.detailed_enabled_for_scope = old_detailed


def _batch_report_summary(report: dict) -> dict:
    samples = list(report.get("samples") or [])
    return {
        "planned_model_replies": int(report.get("planned_model_replies") or 0),
        "selected_jobs": int(report.get("selected_jobs") or 0),
        "partial_smoke": bool(report.get("partial_smoke")),
        "completed_jobs": len(samples),
        "model_requests_attempted": sum(1 for sample in samples if sample.get("llm_call_count")),
        "model_calls_succeeded": sum(1 for sample in samples if sample.get("model_call_succeeded")),
        "delivery_seal_errors": sum(1 for sample in samples if sample.get("delivery_seal_error")),
        "manual_reviews_pending": sum(
            1 for sample in samples if (sample.get("human_review") or {}).get("status") != "reviewed"
        ),
        "attribution_error_count": None,
        "acceptance": "NOT READY until 440 planned samples are complete, every C sample is human reviewed, and all gates are scored",
    }


async def run_production_batch(args) -> int:
    from core.llm.registry import ROLE_CHAT, backend_for
    from core.llm.registry import describe as describe_backends
    from core.observability import turn_trace

    fixtures = load_batch_fixtures(args.batch_root)
    jobs = build_batch_jobs(fixtures, repeats=args.batch_repeats)
    if args.batch_limit:
        if args.batch_limit < 1:
            raise ValueError("--batch-limit must be positive")
        jobs = jobs[:args.batch_limit]
    output_path = Path(args.output)
    settings = importlib.import_module("config.settings")
    system_prompt_path = Path(args.system_prompt_file).resolve() if args.system_prompt_file else Path(settings.SYSTEM_PROMPT_PATH)
    system_prompt = system_prompt_path.read_text(encoding="utf-8")
    backend_info = describe_backends()
    role_info = dict((backend_info.get("roles") or {}).get(ROLE_CHAT) or {})
    backend = backend_for(ROLE_CHAT)
    if backend is None:
        raise RuntimeError("configured CHAT role has no usable endpoint")


    from core.dialogue_attribution import (
        apply_attribution_guard,
        evidence_table_from_projection,
    )
    from core.runtime import turn_service as turn_service_module

    async def attribution_guard_hook(ctx):
        """Use the production core guard without importing startup plugins."""
        evidence = evidence_table_from_projection(ctx.attribution_evidence)
        final_output, decision = apply_attribution_guard(
            ctx.typed_reply,
            evidence,
            set(ctx.retained_evidence_ids or ()),
            str(settings.REPLY_ATTRIBUTION_GUARD_MODE or "enforce").strip().lower(),
            identity_revision=int(ctx.identity_revision or 0),
            generation_epoch=int(ctx.generation_epoch or 0),
            risk_context=ctx.attribution_risk_context,
            parse_error=str(ctx.typed_reply_error or ""),
        )
        record = {
            "decision": decision.decision,
            "rejection_reason": decision.rejection_reason,
            "invalid_references": decision.invalid_references,
            "original_output_digest": decision.original_output_digest,
            "final_output_digest": decision.final_output_digest,
            "guard_mode": str(settings.REPLY_ATTRIBUTION_GUARD_MODE or "enforce"),
            "identity_revision": decision.identity_revision,
            "generation_epoch": decision.generation_epoch,
            "semantic_status": decision.semantic_status,
            "verified": decision.verified,
            "checked_evidence_ids": decision.checked_evidence_ids,
        }
        ctx.attribution_decision = record
        ctx.guard_decision = dict(record)
        if decision.decision == "reject":
            ctx.reply_disposition = "suppressed"
            ctx.reply = ""
            ctx.lines = []
            ctx.reply_segments = []
        elif decision.decision == "fallback":
            ctx.reply_disposition = "fallback"
            ctx.reply = final_output
            ctx.reply_segments = [final_output] if final_output else []
            ctx.delivery_source_kind = (
                "trusted-server" if decision.semantic_status == "deterministic_render"
                else "trusted-server-fallback"
            )
        else:
            ctx.reply_disposition = (
                "fallback" if ctx.delivery_source_kind == "trusted-server-fallback"
                else "deliver"
            )
            ctx.reply = final_output
            ctx.reply_segments = [final_output] if final_output else []
            if not final_output:
                ctx.reply_disposition = "suppressed"
        return ctx

    old_guard_mode = getattr(settings, "REPLY_ATTRIBUTION_GUARD_MODE", None)
    with tempfile.TemporaryDirectory(prefix="stella-dialogue-attribution-eval-") as temp_dir:
        evaluation_db = Path(temp_dir) / "scope-versions.sqlite3"
        from memory.schema import MEMORY_SCOPE_VERSIONS_TABLE_DDL

        scope_conn = sqlite3.connect(evaluation_db)
        try:
            scope_conn.execute(MEMORY_SCOPE_VERSIONS_TABLE_DDL)
        finally:
            scope_conn.close()
        restore_db_paths = _patch_evaluation_db_paths(evaluation_db)

        persona_hash = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        backend_json = {
            "role": ROLE_CHAT,
            "resolved_role": role_info,
            "backend_class": type(backend).__name__,
            "model": str(getattr(backend, "model", "") or role_info.get("model") or ""),
            "base_url": str(role_info.get("endpoint_url") or role_info.get("base_url") or ""),
            "temperature": role_info.get("temperature"),
            "top_p": role_info.get("top_p"),
            "max_tokens": role_info.get("max_tokens"),
            "seed_support": "unsupported by production LLMBackend.generate contract",
            "model_file_sha256": None,
            "quantization": "not reported by endpoint metadata",
        }
        fingerprint_payload = {
            "fixtures": [{"path": f["relative_path"], "sha256": f["sha256"]} for f in fixtures],
            "backend": backend_json,
            "system_prompt_sha256": persona_hash,
            "window_tokens": settings.LLM_CONTEXT_WINDOW_TOKENS,
            "reserve_tokens": settings.LLM_OUTPUT_RESERVE_TOKENS,
            "safety_tokens": settings.LLM_CONTEXT_SAFETY_TOKENS,
            "planned_jobs": [job["job_id"] for job in jobs],
        }
        run_fingerprint = hashlib.sha256(json.dumps(
            fingerprint_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        if args.batch_dry_run:
            previews = []
            for variant in ("A", "B", "C", "D"):
                job = next((item for item in jobs if item["variant"] == variant), None)
                if job is None:
                    continue
                previews.append(await _execute_batch_job(
                    job, fixtures[job["fixture_index"]], backend=backend,
                    system_prompt=system_prompt, mode_module=turn_service_module,
                    guard_hook=attribution_guard_hook, turn_trace=turn_trace, dry_run=True,
                ))
            report = {
                "schema": "dialogue-attribution-production-batch/1",
                "status": "preflight_only",
                "run_fingerprint": run_fingerprint,
                "planned_model_replies": 440,
                "selected_jobs": len(jobs),
                "partial_smoke": len(jobs) != 440,
                "fixture_count": len(fixtures),
                "persona_path": str(system_prompt_path),
                "persona_sha256": persona_hash,
                "backend": backend_json,
                "fixtures": [{"scenario_number": item["scenario_number"],
                              "id": item["fixture"].get("fixture_id"),
                              "path": item["relative_path"], "sha256": item["sha256"],
                              "oracle": item["oracle"]} for item in fixtures],
                "prompt_previews": previews,
                "samples": [],
            }
            report["summary"] = _batch_report_summary(report)
            _atomic_save_json(output_path, report)
            restore_db_paths()
            print(
                f"preflight complete: acceptance denominator=440; selected={len(jobs)}; "
                f"no model calls; wrote {output_path}"
            )
            return 0

        if output_path.exists() and not args.resume:
            raise FileExistsError(f"{output_path} exists; use --resume to continue that exact run")
        if args.resume and output_path.exists():
            report = json.loads(output_path.read_text(encoding="utf-8"))
            if report.get("run_fingerprint") != run_fingerprint:
                raise ValueError("existing batch fingerprint differs; refusing to mix model/persona/fixture runs")
            if report.get("schema") != "dialogue-attribution-production-batch/1":
                raise ValueError("existing output is not a resumable production batch report")
        else:
            report = {
                "schema": "dialogue-attribution-production-batch/1",
                "status": "running",
                "run_fingerprint": run_fingerprint,
                "planned_model_replies": 440,
                "selected_jobs": len(jobs),
                "partial_smoke": len(jobs) != 440,
                "fixture_count": len(fixtures),
                "resume_policy": "completed and failed jobs are retained; missing job IDs only are resumed",
                "persona_path": str(system_prompt_path),
                "persona_sha256": persona_hash,
                "backend": backend_json,
                "runtime": {
                    "context_window_tokens": settings.LLM_CONTEXT_WINDOW_TOKENS,
                    "output_reserve_tokens": settings.LLM_OUTPUT_RESERVE_TOKENS,
                    "safety_tokens": settings.LLM_CONTEXT_SAFETY_TOKENS,
                    "concurrency": 1,
                    "daily_token_budget": settings.LLM_DAILY_TOKEN_BUDGET,
                },
                "fixtures": [{"scenario_number": item["scenario_number"],
                              "id": item["fixture"].get("fixture_id"),
                              "path": item["relative_path"], "sha256": item["sha256"],
                              "oracle": item["oracle"]} for item in fixtures],
                "planned_job_ids": [job["job_id"] for job in jobs],
                "samples": [],
            }
        completed = {str(sample.get("job_id")) for sample in report.get("samples", [])}
        unknown = completed - {job["job_id"] for job in jobs}
        if unknown:
            raise ValueError(f"resumable report contains jobs outside this matrix: {sorted(unknown)[:3]}")
        settings.REPLY_ATTRIBUTION_GUARD_MODE = "enforce"
        try:
            for index, job in enumerate(jobs, start=1):
                if job["job_id"] in completed:
                    continue
                try:
                    sample = await _execute_batch_job(
                        job, fixtures[job["fixture_index"]], backend=backend,
                        system_prompt=system_prompt, mode_module=turn_service_module,
                        guard_hook=attribution_guard_hook, turn_trace=turn_trace,
                    )
                except Exception as exc:
                    sample = {
                        "job_id": job["job_id"],
                        "scenario_number": job["scenario_number"],
                        "fixture_id": job["fixture_id"],
                        "variant": job["variant"],
                        "repeat": job["repeat"],
                        "error": f"{type(exc).__name__}: {exc}",
                        "human_review": {"status": "pending", "task_pass": None,
                                         "error_classes": dict.fromkeys(ERROR_TAXONOMY),
                                         "reviewer_note": ""},
                    }
                report["samples"].append(sample)
                report["samples"].sort(key=lambda item: str(item.get("job_id") or ""))
                report["status"] = (
                    "sampling_complete" if len(report["samples"]) == len(jobs) and len(jobs) == 440
                    else "partial_smoke_complete" if len(report["samples"]) == len(jobs)
                    else "running"
                )
                report["summary"] = _batch_report_summary(report)
                _atomic_save_json(output_path, report)
                if index % 10 == 0 or len(report["samples"]) == len(jobs):
                    print(
                        f"batch checkpoint: {len(report['samples'])}/{len(jobs)} jobs; "
                        f"model calls={report['summary']['model_requests_attempted']}"
                    )
        finally:
            settings.REPLY_ATTRIBUTION_GUARD_MODE = old_guard_mode
            restore_db_paths()
        report["status"] = (
            "sampling_complete" if len(report["samples"]) == len(jobs) and len(jobs) == 440
            else "partial_smoke_complete" if len(report["samples"]) == len(jobs)
            else "interrupted"
        )
        report["summary"] = _batch_report_summary(report)
        _atomic_save_json(output_path, report)
        return 0 if report["status"] in {"sampling_complete", "partial_smoke_complete"} else 2


def _compact_fixture_rows(fixture: dict, through_seq: int = 16) -> list[tuple]:
    """Build isolated SQLite rows from exact frozen source messages."""
    participants = fixture.get("participants") or {}
    bot_id = str(fixture.get("bot_id") or "")
    group_id = 999_000_001
    conversation_key = f"qq:{bot_id}:group:{group_id}"
    messages = {
        int(message["seq"]): message
        for message in fixture.get("messages") or []
        if int(message["seq"]) <= through_seq
    }
    logical_units: dict[int, tuple[dict, int]] = {}
    for unit in fixture.get("logical_units") or []:
        for part_index, seq in enumerate(unit.get("seqs") or []):
            if int(seq) in messages:
                logical_units[int(seq)] = (unit, part_index)

    def _uid(author: str) -> str:
        return bot_id if author == "bot" else str(participants.get(author) or "")

    rows = []
    for seq, message in sorted(messages.items()):
        author = str(message.get("author") or "")
        user_id = _uid(author)
        if not user_id.isdigit():
            raise ValueError(f"fixture {fixture.get('fixture_id')} has no stable ID for {author}")
        parent_seq = message.get("reply_to_seq")
        parent = messages.get(int(parent_seq)) if parent_seq is not None else None
        parent_uid = _uid(str(parent.get("author") or "")) if parent else ""
        unit, part_index = logical_units.get(seq, ({}, 0))
        mentions = [_uid(str(name)) for name in message.get("mentioned") or []]
        source_kind = (
            "BOT_SELF" if author == "bot"
            else "AT_MENTION" if "bot" in (message.get("mentioned") or [])
            else "PASSIVE"
        )
        platform_msg_id = str(message.get("platform_msg_id") or "")
        parent_platform_id = (
            str(parent.get("platform_msg_id") or f"fixture-{parent_seq}") if parent else ""
        )
        recipient_key = str(unit.get("recipient") or "") if author == "bot" else ""
        rows.append((
            seq + 2,
            str(group_id),
            user_id,
            str(message.get("content") or ""),
            source_kind,
            str(message.get("log_time") or ""),
            platform_msg_id,
            conversation_key,
            bot_id,
            parent_platform_id,
            parent_uid,
            json.dumps(mentions, ensure_ascii=False),
            str(unit.get("unit") or f"fixture-message-{seq}") if author == "bot" else "",
            part_index,
            str(unit.get("origin_msg_id") or "") if author == "bot" else "",
            _uid(recipient_key) if recipient_key else "",
        ))
    if not rows:
        raise ValueError("Compact fixture has no source rows")
    return rows


async def run_compact_evaluation(args) -> int:
    """Call actual compact_once on frozen sources in a separate temporary DB."""
    from core.llm.registry import ROLE_COMPACT, backend_for
    from core.llm.registry import describe as describe_backends
    from memory import session_compact as compact
    from memory import session_context as session_context_module

    fixture_path = Path(args.compact_fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    source_from_seq = int(args.compact_from_seq)
    source_through_seq = int(args.compact_through_seq)
    if source_from_seq < 0 or source_through_seq < source_from_seq:
        raise ValueError("Compact source sequence range is invalid")
    rows = _compact_fixture_rows(fixture, through_seq=source_through_seq)
    output_path = Path(args.output)
    role_info = dict((describe_backends().get("roles") or {}).get(ROLE_COMPACT) or {})
    backend = backend_for(ROLE_COMPACT)
    if backend is None:
        raise RuntimeError("configured COMPACT role has no usable endpoint")

    captured: dict[str, object] = {}

    class RecordingBackend:
        async def generate(self, prompt: str, system_prompt: str = "") -> str:
            captured["prompt"] = prompt
            started = time.monotonic()
            result = await backend.generate(prompt, system_prompt=system_prompt)
            captured["elapsed_seconds"] = round(time.monotonic() - started, 3)
            captured["raw_response"] = str(result)
            return result

    old_threshold = session_context_module.SESSION_COMPACT_THRESHOLD_TOKENS
    old_compact_db_path = compact.DB_PATH
    old_context_enabled = session_context_module.SESSION_CONTEXT_ENABLED
    old_get_backend = compact._get_backend
    compact_group_id = 999_000_001
    source_low_id = source_from_seq + 1
    source_high_id = max(row[0] for row in rows) + 1
    if source_low_id >= source_high_id:
        raise ValueError("Compact fixture has no rows in the requested sequence range")
    summary_packet = None
    source_batch = None
    compacted = False
    with tempfile.TemporaryDirectory(prefix="stella-compact-eval-") as temp_dir:
        evaluation_db = Path(temp_dir) / "compact-eval.sqlite3"
        restore_db_paths = _patch_evaluation_db_paths(evaluation_db)
        compact.DB_PATH = evaluation_db
        try:
            conn = sqlite3.connect(evaluation_db)
            try:
                conn.execute(
                    "CREATE TABLE group_messages ("
                    "id INTEGER PRIMARY KEY, group_id TEXT, user_id TEXT, content TEXT, "
                    "source_kind TEXT, timestamp TEXT, msg_id TEXT, conversation_key TEXT, "
                    "bot_id TEXT, reply_to_msg_id TEXT, reply_target_user_id TEXT, "
                    "mentioned_user_ids_json TEXT, logical_message_id TEXT, part_index INTEGER, "
                    "origin_msg_id TEXT, reply_recipient_user_id TEXT)"
                )
                conn.executemany(
                    "INSERT INTO group_messages (id, group_id, user_id, content, source_kind, "
                    "timestamp, msg_id, conversation_key, bot_id, reply_to_msg_id, "
                    "reply_target_user_id, mentioned_user_ids_json, logical_message_id, "
                    "part_index, origin_msg_id, reply_recipient_user_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
            compact.reset_state()
            session_context_module.reset_state()
            session_context_module.SESSION_CONTEXT_ENABLED = True
            session_context_module.SESSION_COMPACT_THRESHOLD_TOKENS = 0
            session_context_module.ensure_initialized(compact_group_id, source_low_id)
            compact._get_backend = lambda: RecordingBackend()
            source_batch = compact.fetch_pending_records(
                compact_group_id, source_low_id, source_high_id,
                session_context_module.compact_message_limit(),
                session_context_module.compact_guard(compact_group_id),
            )
            compacted = await compact.compact_once(
                compact_group_id, source_high_id
            )
            summary_packet = session_context_module.get_summary_packet(compact_group_id)
            report = {
                "schema": "dialogue-attribution-real-compact/1",
                "status": "compact_committed" if compacted else "compact_not_committed",
                "fixture_id": fixture.get("fixture_id"),
                "fixture_path": str(fixture_path),
                "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                "fixture_sequence_range": {
                    "from_inclusive": source_from_seq,
                    "through_inclusive": source_through_seq,
                },
                "backend": {
                    "role": ROLE_COMPACT,
                    "backend_class": type(backend).__name__,
                    "resolved_role": role_info,
                    "seed_support": "unsupported by production LLMBackend.generate contract",
                },
                "model_requests_attempted": int("raw_response" in captured),
                "elapsed_seconds": captured.get("elapsed_seconds"),
                "trigger_threshold_override": {
                    "value": 0,
                    "reason": "force one isolated contract sample from the frozen source interval",
                },
                "source_interval": {
                    "low_exclusive": source_batch.source_low_id if source_batch else None,
                    "high_exclusive": source_batch.source_high_id if source_batch else None,
                    "watermark": source_batch.source_watermark if source_batch else None,
                    "source_row_count": source_batch.source_row_count if source_batch else 0,
                    "conversation_key": source_batch.conversation_key if source_batch else "",
                    "bot_id": source_batch.bot_id if source_batch else "",
                    "refs": [
                        {"ref_id": entry.ref_id, "source_ids": list(entry.source_ids),
                         "source_digest": entry.source_digest}
                        for entry in (source_batch.entries if source_batch else ())
                    ],
                },
                "prompt": captured.get("prompt"),
                "prompt_sha256": hashlib.sha256(
                    str(captured.get("prompt") or "").encode("utf-8")
                ).hexdigest() if "prompt" in captured else None,
                "raw_response": captured.get("raw_response"),
                "selected_refs": None,
                "summary_packet": None,
                "summary_text": session_context_module.get_summary(compact_group_id),
                "session_stats": session_context_module.session_stats(compact_group_id),
                "human_review": {"status": "pending", "task_pass": None, "note": ""},
                "acceptance": "NOT READY until source selection and attribution are human reviewed",
            }
            if "raw_response" in captured and source_batch:
                allowed = {entry.ref_id for entry in source_batch.entries}
                try:
                    report["selected_refs"] = list(
                        compact.parse_selected_refs(str(captured["raw_response"]), allowed)
                    )
                except ValueError as exc:
                    report["selection_parse_error"] = str(exc)
            if summary_packet is not None:
                from dataclasses import asdict

                report["summary_packet"] = asdict(summary_packet)
            _atomic_save_json(output_path, report)
            print(
                f"real Compact finished: request_attempted={report['model_requests_attempted']}; "
                f"committed={compacted}; wrote {output_path}"
            )
            return 0 if compacted and "raw_response" in captured else 2
        finally:
            compact.reset_state()
            session_context_module.reset_state()
            compact.DB_PATH = old_compact_db_path
            compact._get_backend = old_get_backend
            session_context_module.SESSION_COMPACT_THRESHOLD_TOKENS = old_threshold
            session_context_module.SESSION_CONTEXT_ENABLED = old_context_enabled
            restore_db_paths()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", help="冻结夹具 JSON 路径")
    parser.add_argument("--variant", choices=VARIANTS)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--endpoint", default="", help="OpenAI-compatible base URL")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--system-prompt-file", default="",
                        help="生产人格系统提示文件（可选；缺省如实记录缺失）")
    parser.add_argument("--model-file", default="",
                        help="模型文件路径（能取到才记录 sha256 指纹）")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="只渲染输入字节，不访问网络（CI/验收输入对照用）")
    parser.add_argument("--guard", action="store_true",
                        help="采样输出经归属 guard（enforce）重放，报告阻断/兜底/放行统计")
    parser.add_argument("--output", default="", help="报告 JSON 输出路径")
    parser.add_argument("--production-batch", action="store_true",
                        help="使用生产 TurnService 跑固定的 26×10 + A/B/D 消融批次")
    parser.add_argument("--batch-root", default="tests/fixtures/dialogue_attribution",
                        help="批次冻结夹具目录")
    parser.add_argument("--batch-repeats", type=int, default=10,
                        help="批次每场重复数；验收固定为 10")
    parser.add_argument("--batch-limit", type=int, default=0,
                        help="仅执行前 N 个 job 的局部冒烟；不改变 440 验收分母")
    parser.add_argument("--resume", action="store_true",
                        help="仅在指纹完全相同的批次报告中补跑缺失 job")
    parser.add_argument("--batch-dry-run", action="store_true",
                        help="批次 dry-run：生产 prepare/prompt/预算预检，不发模型请求")
    parser.add_argument("--compact-eval", action="store_true",
                        help="执行一次使用冻结原始消息和临时 SQLite 的真实 Compact 评估")
    parser.add_argument("--compact-fixture", default="tests/fixtures/dialogue_attribution/recurrence_190922.json",
                        help="真实 Compact 使用的冻结来源夹具")
    parser.add_argument("--compact-from-seq", type=int, default=0,
                        help="真实 Compact 开始处理的夹具消息序号（含）")
    parser.add_argument("--compact-through-seq", type=int, default=16,
                        help="真实 Compact 最后处理的夹具消息序号（含）")
    args = parser.parse_args(argv)

    if args.compact_eval:
        if not args.output:
            parser.error("--compact-eval requires --output")
        if args.production_batch or args.fixture or args.variant:
            parser.error("--compact-eval is a separate mode; omit batch/single-fixture arguments")
        return asyncio.run(run_compact_evaluation(args))

    if args.production_batch:
        if not args.output:
            parser.error("--production-batch requires --output")
        if args.fixture or args.variant:
            parser.error("--fixture/--variant cannot be combined with --production-batch")
        return asyncio.run(run_production_batch(args))
    if not args.fixture or not args.variant:
        parser.error("single-fixture mode requires both --fixture and --variant")

    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    system_prompt = ""
    if args.system_prompt_file:
        system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")
    _, user_prompt, budget_meta = build_prompt(fixture, args.variant, system_rules=True)

    # --guard 时把生产同源的协议段拼进 user prompt（复核 F1：生产链路里
    # protocol_instructions 由 prepare 并入受保护块；评估链路必须一致，
    # 否则模型自由文本没有 reply_plan，guard 会结构性全兜底）。
    attribution_protocol_present = False
    if args.guard:
        from core.dialogue_attribution import protocol_instructions

        evidence = _fixture_evidence(fixture)
        protocol_section = protocol_instructions(evidence, set(evidence.keys()))
        if protocol_section:
            user_prompt = f"{user_prompt}\n\n{protocol_section}"
            attribution_protocol_present = True

    report: dict = {
        "schema": "dialogue-attribution-eval/1",
        "fixture": {
            "id": fixture["fixture_id"],
            "path": str(fixture_path),
            "evidence_commit": fixture.get("evidence_commit"),
        },
        "variant": args.variant,
        "input_format": (
            "legacy-reconstruction"
            if args.variant == "V0"
            else f"projection-v{PROJECTION_FORMAT_VERSION}"
        ),
        "wire": {
            "endpoint": args.endpoint or None,
            "model": args.model or None,
            "model_file_sha256": _sha256_file(args.model_file),
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "seed": args.seed,
            "seed_support": "unknown" if args.seed is None else "requested",
            "system_prompt_present": bool(system_prompt),
            "dry_run": args.dry_run,
        },
        "prompt": {
            "system_prompt": system_prompt or None,
            "user_prompt": user_prompt,
            "estimated_tokens": estimate_tokens(user_prompt),
            "budget": budget_meta,
            "attribution_protocol": attribution_protocol_present,
            "oracle": (fixture.get("evaluation") or fixture.get("failing_round", {})).get("oracle"),
        },
        "samples": [],
    }
    exit_code = 0
    for index in range(args.repeats):
        sample: dict = {
            "index": index,
            "output": None,
            "error": None,
            "elapsed_seconds": None,
            "screening_flags": [],
            # 人工语义复核槽位：主评估以此为准；null = 未复核
            "human_review": dict.fromkeys(ERROR_TAXONOMY),
            "reviewer_note": "",
        }
        if args.dry_run:
            sample["error"] = "dry-run"
        else:
            started = time.monotonic()
            try:
                response = _chat(
                    args.endpoint, args.api_key, args.model, system_prompt,
                    user_prompt, args.temperature, args.max_tokens,
                    args.seed, args.timeout,
                )
                sample["elapsed_seconds"] = round(time.monotonic() - started, 3)
                choice = (response.get("choices") or [{}])[0]
                sample["output"] = (choice.get("message") or {}).get("content")
                sample["wire_response"] = {
                    "model": response.get("model"),
                    "usage": response.get("usage"),
                    "finish_reason": choice.get("finish_reason"),
                }
                sample["screening_flags"] = _screen(sample["output"] or "")
                if args.guard:
                    sample["guard"] = _guard_stage(fixture, sample["output"] or "")
            except Exception as exc:  # 采样失败如实记录，继续下一次
                sample["error"] = f"{type(exc).__name__}: {exc}"
                exit_code = 2
        report["samples"].append(sample)

    if args.guard:
        guarded = [s.get("guard") for s in report["samples"] if s.get("guard")]
        report["guard_summary"] = {
            "mode": "enforce",
            "sampled": len(guarded),
            "blocked": sum(1 for g in guarded if g["decision"]["decision"] == "reject"),
            "fallback": sum(1 for g in guarded if g["decision"]["decision"] == "fallback"),
            "passed": sum(1 for g in guarded if g["decision"]["decision"] == "pass"),
        }

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"report written to {args.output} ({len(report['samples'])} samples)")
    else:
        print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
