# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，详见项目根目录 LICENSE。
"""前缀缓存约束的守卫：三个记忆链路 prompt 的可变数据必须排在最后。

为什么值得单独一个文件守：前缀缓存只能命中「第一处差异之前」的内容。
把 {messages} / {current_summary} 之类每次都变的占位符写在模板开头，
后面**全部固定指令**就每次都按全价重复计费——在线 API 下这是整合链路的
主要成本来源，而且不会报错、不影响输出，纯靠人盯很容易回归。

断言两件事：
1. 渲染两次不同数据，公共前缀必须一直延伸到「固定规则 / 数据」分隔线之后
   （即所有固定指令都落在可缓存前缀里）；
2. 模板里最后一个可变占位符之后不得再堆固定文本（只容许一行输出格式提醒）。
"""
from memory.consolidation_prompt import (
    CONSOLIDATION_PROMPT,
    format_consolidation_prompt,
)
from memory.extraction_prompt import EXTRACTION_PROMPT, format_extraction_prompt
from memory.session_compact import COMPACT_PROMPT, build_compact_prompt

# 三个模板共用的分隔线前缀（各自后半句不同：待分析/待压缩的数据）
SEPARATOR = "===== 以上为固定规则"
# 数据之后允许保留的固定文本长度上限：只够放一行「直接输出…」的格式提醒。
# 这点 token 不进缓存，换来「最后一条指令」的位置优势，是有意的取舍。
MAX_TAIL_CHARS = 60


def _common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b, strict=False):
        if ca != cb:
            break
        n += 1
    return n


def _assert_fixed_part_cacheable(render, first_args: tuple, second_args: tuple):
    """两次不同输入的公共前缀必须覆盖到分隔线，即固定指令全部可缓存。"""
    a = render(*first_args)
    b = render(*second_args)
    assert a != b, "两次渲染应当不同，否则这个用例没在测东西"
    shared = a[: _common_prefix_len(a, b)]
    assert SEPARATOR in shared, (
        "可缓存前缀没能覆盖到固定规则分隔线：说明有可变占位符被写到了固定指令前面。"
        f"公共前缀只有 {len(shared)} 字符"
    )


def _assert_no_fixed_text_after_data(template: str, last_placeholder: str):
    idx = template.rindex(last_placeholder) + len(last_placeholder)
    tail = template[idx:].strip()
    assert len(tail) <= MAX_TAIL_CHARS, (
        f"数据占位符 {last_placeholder} 之后还有 {len(tail)} 字符固定文本，"
        "新增固定文本一律加到分隔线以上"
    )


def test_consolidation_prompt_fixed_part_is_cacheable():
    _assert_fixed_part_cacheable(
        format_consolidation_prompt,
        ("（无）", "消息ID(1) 用户(1001): 我住在杭州"),
        ("上次在聊显卡", "消息ID(2) 用户(1002): 我明天要出差"),
    )


def test_extraction_prompt_fixed_part_is_cacheable():
    _assert_fixed_part_cacheable(
        format_extraction_prompt,
        ("消息ID(1) 用户(1001): 我住在杭州",),
        ("消息ID(2) 用户(1002): 我对花生过敏",),
    )


def test_compact_prompt_fixed_part_is_cacheable():
    _assert_fixed_part_cacheable(
        build_compact_prompt,
        ("用户(1001): 在聊显卡", ""),
        ("用户(1002): 在聊出差", "更早聊过散打"),
    )


def test_no_fixed_instructions_after_data_placeholders():
    _assert_no_fixed_text_after_data(CONSOLIDATION_PROMPT, "{messages}")
    _assert_no_fixed_text_after_data(EXTRACTION_PROMPT, "{messages}")
    _assert_no_fixed_text_after_data(COMPACT_PROMPT, "{messages}")


def test_volatile_placeholders_sit_after_the_separator():
    """逐个确认：每个每次都变的占位符都在分隔线之后。"""
    for template, placeholders in (
        (CONSOLIDATION_PROMPT, ("{current_summary}", "{messages}")),
        (EXTRACTION_PROMPT, ("{messages}",)),
        (COMPACT_PROMPT, ("{existing}", "{messages}")),
    ):
        sep = template.index(SEPARATOR)
        for name in placeholders:
            assert template.index(name) > sep, f"{name} 必须排在分隔线之后"


def test_enum_placeholders_may_stay_in_the_prefix():
    """{types}/{usages}/{visibilities} 由模块常量填充、每次逐字相同，属固定前缀。

    这条不是「允许」而是「确认」：它们若被挪到分隔线之后，可缓存前缀会被
    白白截短一大截，而输出完全正常，没有守卫就发现不了。
    """
    sep = CONSOLIDATION_PROMPT.index(SEPARATOR)
    for name in ("{types}", "{usages}", "{visibilities}"):
        assert CONSOLIDATION_PROMPT.index(name) < sep
