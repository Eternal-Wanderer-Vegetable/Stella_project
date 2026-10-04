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
import hashlib
import json
import re
import sys
import time
import urllib.request
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
    """按变体渲染历史尾巴（严格时间正序）。只消费冻结夹具，无 DB。"""
    messages = {m["seq"]: m for m in fixture["messages"]}
    bot_id = fixture["bot_id"]
    parts = fixture["participants"]
    units_by_first: dict[int, dict] = {
        u["seqs"][0]: u for u in fixture["logical_units"]
    }
    unit_member_seqs = {s for u in fixture["logical_units"] for s in u["seqs"][1:]}

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


def build_prompt(fixture: dict, variant: str, system_rules: bool) -> tuple[str, str]:
    """返回 (system_prompt, user_prompt)。user prompt 走生产 build_v2_named_sections。"""
    failing = fixture["failing_round"]
    current_sender = fixture["participants"][failing["current_sender"]]
    current_input = next(
        m["content"]
        for m in reversed(fixture["messages"])
        if m["author"] == failing["current_sender"] and m["kind"] == "user"
    )
    history = build_history(fixture, variant)
    short_term = (
        f"最近的对话（时间正序，投影v{PROJECTION_FORMAT_VERSION}；"
        "「我:」或「Bot(...)」开头的行都是你自己说过的话）:\n" + history
        if variant != "V0"
        else "最近的对话（时间正序，「我」是你自己说过的话）:\n" + history
    )
    sections = build_v2_named_sections(
        short_term,
        "",
        [],
        [],
        current_user_id=int(current_sender),
        identity_capsule="",
    )
    if variant != "V2":
        # V0/V1 保持修复前/无规则形态：从 identity 区精确剔除 M3 规则文本
        sections = [
            (name, text.replace(_ROLE_STATE_RULES + "\n", "").replace(_ROLE_STATE_RULES, ""))
            if name == "identity" else (name, text)
            for name, text in sections
        ]
    context_text = "\n\n".join(text for _, text in sections)
    user_prompt = (
        f"{context_text}\n\n"
        f"【现在 用户({current_sender}) 对你说】{current_input}\n"
        "请回应这句话。上面的对话记录只是背景，不要去回应其中的其他内容。"
    )
    return "", user_prompt


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", required=True, help="冻结夹具 JSON 路径")
    parser.add_argument("--variant", choices=VARIANTS, required=True)
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
    parser.add_argument("--output", default="", help="报告 JSON 输出路径")
    args = parser.parse_args(argv)

    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    system_prompt = ""
    if args.system_prompt_file:
        system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")
    _, user_prompt = build_prompt(fixture, args.variant, system_rules=True)

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
            except Exception as exc:  # 采样失败如实记录，继续下一次
                sample["error"] = f"{type(exc).__name__}: {exc}"
                exit_code = 2
        report["samples"].append(sample)

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        print(f"report written to {args.output} ({len(report['samples'])} samples)")
    else:
        print(rendered)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
