# SPDX-License-Identifier: AGPL-3.0
# Copyright (c) 2026 Stella Project Contributors
# 本文件以 AGPL-3.0 许可证发布，全文见项目根目录 LICENSE。
"""过滤器与装饰器：参数转换、CustomFilter 组合、**kwargs 宽容度。"""

from __future__ import annotations

import pytest

import astrbot_compat.filters as f
from astrbot_compat.filters import (
    GreedyStr,
    parse_handler_params,
    validate_and_convert_params,
)


def _spec(func) -> dict:
    """本文件开了 `from __future__ import annotations`，注解是字符串——
    正好用来验证 parse_handler_params 能把它们还原成真实类型。"""
    return parse_handler_params(func)


def test_bool_annotation_is_converted():
    # 不转换的话 "false" 是 truthy 字符串，插件逻辑会整个反掉
    def h(self, event, flag: bool):
        pass

    assert validate_and_convert_params(["false"], _spec(h)) == {"flag": False}
    assert validate_and_convert_params(["yes"], _spec(h)) == {"flag": True}


def test_bool_rejects_garbage():
    def h(self, event, flag: bool):
        pass

    with pytest.raises(ValueError, match="布尔值"):
        validate_and_convert_params(["maybe"], _spec(h))


def test_default_value_drives_type_inference():
    # 上游用默认值的类型推断，而不是只看注解
    def h(self, event, n=5, ratio=1.5, s="d", flag=False):
        pass

    assert validate_and_convert_params(["7", "2.5", "x", "1"], _spec(h)) == {
        "n": 7,
        "ratio": 2.5,
        "s": "x",
        "flag": True,
    }


def test_defaults_are_used_when_tokens_run_out():
    def h(self, event, a: int, b=3):
        pass

    assert validate_and_convert_params(["1"], _spec(h)) == {"a": 1, "b": 3}


def test_missing_required_param_raises():
    def h(self, event, a: int):
        pass

    with pytest.raises(ValueError, match="必要参数缺失"):
        validate_and_convert_params([], _spec(h))


def test_type_error_reports_full_signature():
    def h(self, event, a: int):
        pass

    with pytest.raises(ValueError, match=r"参数 a 类型错误.*a\(int\)"):
        validate_and_convert_params(["abc"], _spec(h))


def test_greedy_str_absorbs_the_rest():
    def h(self, event, head: str, rest: GreedyStr):
        pass

    assert validate_and_convert_params(["a", "b", "c"], _spec(h)) == {
        "head": "a",
        "rest": "b c",
    }


def test_greedy_str_must_be_last():
    def h(self, event, rest: GreedyStr, tail: str):
        pass

    with pytest.raises(ValueError, match="必须是最后一个参数"):
        validate_and_convert_params(["a", "b"], _spec(h))


def test_optional_annotation_is_unwrapped():
    def h(self, event, n: int | None):
        pass

    assert validate_and_convert_params(["7"], _spec(h)) == {"n": 7}


def test_unannotated_digit_becomes_int():
    def h(self, event, n):
        pass

    assert validate_and_convert_params(["7"], _spec(h)) == {"n": 7}
    assert validate_and_convert_params(["x"], _spec(h)) == {"n": "x"}


def test_permission_type_is_a_flag():
    combined = f.PermissionType.ADMIN | f.PermissionType.MEMBER
    assert f.PermissionType.ADMIN in combined


def test_custom_filter_supports_and_or_at_class_level():
    class Yes(f.CustomFilter):
        def filter(self, event, cfg=None):
            return True

    class No(f.CustomFilter):
        def filter(self, event, cfg=None):
            return False

    assert (Yes & No).filter(None) is False
    assert (Yes | No).filter(None) is True
    assert (Yes() & No()).filter(None) is False


def test_decorators_tolerate_unknown_kwargs():
    # 上游所有 register_* 都是 **kwargs 签名，未知关键字应静默进 extras_configs
    @f.command("demo", alias={"d"}, priority=5, unknown=1)
    async def handler(self, event):
        """描述来自 docstring"""

    md = handler.__astrbot_handler_md__
    assert md.extras_configs["priority"] == 5
    assert md.extras_configs["unknown"] == 1
    assert md.desc == "描述来自 docstring"


def test_desc_kwarg_overrides_docstring():
    @f.command("demo2", desc="显式描述")
    async def handler(self, event):
        """docstring"""

    assert handler.__astrbot_handler_md__.desc == "显式描述"


def test_regex_filter_ignores_wake_state():
    # 上游注释明确：正则过滤器不受 wake_prefix 制约
    class Ev:
        is_at_or_wake_command = False

        def get_message_str(self):
            return "喵喵喵"

    assert f.RegexFilter(r"喵+").filter(Ev()) is True


def test_command_filter_requires_wake():
    class Ev:
        def __init__(self):
            self.is_at_or_wake_command = False
            self.extras = {}

        def get_message_str(self):
            return "demo"

        def set_extra(self, k, v):
            self.extras[k] = v

    filt = f.CommandFilter("demo")
    assert filt.filter(Ev()) is False
    ev = Ev()
    ev.is_at_or_wake_command = True
    assert filt.filter(ev) is True


def test_command_filter_collapses_whitespace():
    class Ev:
        is_at_or_wake_command = True

        def __init__(self):
            self.extras = {}

        def get_message_str(self):
            return "demo   a    b"

        def set_extra(self, k, v):
            self.extras[k] = v

    async def handler(self, event, first: str, second: str):
        pass

    filt = f.CommandFilter("demo")
    md = f._get_or_create_handler_md(handler, f.EventType.AdapterMessageEvent)
    filt.init_handler_md(md)
    ev = Ev()
    assert filt.filter(ev) is True
    assert ev.extras["parsed_params"] == {"first": "a", "second": "b"}
