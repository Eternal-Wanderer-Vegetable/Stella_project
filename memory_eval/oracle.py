# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
"""Oracle 整合后端：机械抽取合同合法句型，替代整合/提取 LLM（无写路径改动）。

用途（两层）：
1. **harness 校验**：不依赖生成模型即可贯通 真实落库 → 证据合同 → 晋升 →
   真实检索 → 作答 → judge 的全链路（模型不可用 / 显存不足时的 smoke 手段）；
2. **Oracle 实验**（SMB 讨论中的定位实验）：把「写侧」替换为机械正确版，
   区分「记忆没写对」和「检索/使用没做对」。

实现：整合 prompt 的消息行为 ``消息ID(mid) 用户(uid): content``（PASSIVE），
从中按 ``memory.evidence_contract`` 的同一组正则抽取 contract-valid 刻板句；
``content`` 即 ``exact_support_span``（逐字来自原文），``source_message_ids``
取 prompt 里的真实行 ID——证据绑定在服务端逐条可验。候选直接走生产
``_write_memory_candidates``（Policy Validator + 证据合同 + 发送者白名单），
不绕过任何治理。模式与合同共享同源正则，杜绝漂移。
"""

from __future__ import annotations

import json
import re
from typing import Any

# 与 consolidator._fetch_next_messages 的 PASSIVE 渲染格式同源
_PROMPT_LINE_RE = re.compile(r"消息ID\((\d+)\) 用户\((\d+)\): (.+)")
MAX_CANDIDATES_PER_BATCH = 20


class OracleConsolidationBackend:
    """实现 LLMBackend 的 ``generate_detailed`` 合同；回复为整合 JSON。"""

    def __init__(self) -> None:
        self.calls = 0
        self.last_candidates: list[dict[str, Any]] = []

    async def generate_detailed(self, prompt: str, *args: Any, **kwargs: Any):
        self.calls += 1
        candidates: list[dict[str, Any]] = []
        summary_lines: list[str] = []
        for mid_raw, uid, text in _PROMPT_LINE_RE.findall(prompt):
            text = text.strip()
            summary_lines.append(text)
            if len(candidates) >= MAX_CANDIDATES_PER_BATCH:
                continue
            for span, cand_type in self._extract_statements(text):
                candidates.append({
                    "user_id": uid,
                    "type": cand_type,
                    "content": span,
                    "usage_tags": ["PERSONALIZE"],
                    "visibility": "OPEN",
                    "importance": 0.6,
                    "confidence": 0.95,
                    "evidence": "oracle：合同刻板句逐字命中（memory_eval oracle 模式）",
                    "source_message_ids": [int(mid_raw)],
                })
        self.last_candidates = candidates
        reply = {
            "short_term": {
                "active_summary": " | ".join(summary_lines[:6])[:300] or "（空批次）",
                "pending_topic": "无",
                "recent_exchanges": [],
            },
            "user_profiles": [],
            "has_self_disclosure": bool(candidates),
            # oracle 模式关闭阶段2：候选已在回复中给足（_extract_backend=None）
            "memory_candidates": candidates,
        }
        return json.dumps(reply, ensure_ascii=False), "stop"

    @staticmethod
    def _extract_statements(text: str) -> list[tuple[str, str]]:
        """从一条消息抽取 (span, 候选类型)；与证据合同共享同源正则。"""
        from memory.evidence_contract import (
            _PREFERENCE_PATTERN,
            _PREFERENCE_PATTERN_EN,
            _SELF_REPORT_PATTERNS,
        )

        out: list[tuple[str, str]] = []
        for pattern in _SELF_REPORT_PATTERNS.values():
            m = pattern.fullmatch(text) or pattern.search(text)
            if m:
                out.append((m.group(0).strip(), "FACT"))
        for pattern in (_PREFERENCE_PATTERN, _PREFERENCE_PATTERN_EN):
            m = pattern.fullmatch(text) or pattern.search(text)
            if m:
                out.append((m.group(0).strip(), "PREFERENCE"))
        return out
