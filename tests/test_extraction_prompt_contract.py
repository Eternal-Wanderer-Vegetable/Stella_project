# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""EXTRACTION_PROMPT 契约硬规则块的结构守卫。

2026-10-17 live 回放实证：阶段2 候选契约全 unknown、0 accepted，根因是提示词
没教模型产出闸门（memory/evidence_contract.py）能接受的契约形状。修复是在
提示词末段（分隔线之上）增补「契约硬规则块」。本守卫只钉关键字段——句型枚举、
kind↔type/polarity 绑定措辞、块的位置——不钉正文全部，防止规则块被误删或改残。
"""
from memory.extraction_prompt import EXTRACTION_PROMPT

_SEPARATOR = "===== 以上为固定规则"

# 与 evidence_contract._SELF_REPORT_PATTERNS / _PREFERENCE_PATTERN* 一一对应；
# 闸门句型扩缩时这里同步增删
_AUDITABLE_PREDICATE_KEYS = (
    "profile.residence",
    "profile.origin",
    "profile.nickname",
    "profile.employer",
    "profile.residence.en",
    "profile.origin.en",
    "profile.nickname.en",
    "preference.general",
)


def test_prompt_enumerates_auditable_predicate_keys():
    """闸门支持的每个 predicate_key 都必须出现在提示词里，缺一个模型就学不到。"""
    for key in _AUDITABLE_PREDICATE_KEYS:
        assert key in EXTRACTION_PROMPT, f"契约硬规则块丢失句型枚举：{key}"


def test_prompt_states_kind_type_polarity_bindings():
    """self_report→FACT 与 explicit_preference→PREFERENCE 的绑定措辞必须在。"""
    assert "statement_kind=self_report" in EXTRACTION_PROMPT
    assert "statement_kind=explicit_preference" in EXTRACTION_PROMPT
    for phrase in ("type 必须是 FACT", "type 必须是 PREFERENCE",
                   "polarity=positive", "polarity=negative"):
        assert phrase in EXTRACTION_PROMPT, f"契约硬规则块丢失绑定措辞：{phrase}"


def test_contract_block_sits_above_separator_with_messages_last():
    """硬规则块属于固定指令：在分隔线之上，且 {messages} 仍是最后的数据占位符。"""
    sep = EXTRACTION_PROMPT.index(_SEPARATOR)
    assert EXTRACTION_PROMPT.index("profile.residence") < sep
    assert EXTRACTION_PROMPT.rindex("{messages}") > sep
