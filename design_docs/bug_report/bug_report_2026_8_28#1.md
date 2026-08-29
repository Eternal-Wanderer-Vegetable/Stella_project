(stella) PS E:\stella\stella_project> ruff check
SIM105 Use `contextlib.suppress(KeyError, IndexError, TypeError)` instead of `try`-`except`-`pass`
   --> core\llm\openai_client.py:214:5
    |
212 |       """把响应里的 usage / finish_reason 交给用量上报口。"""
213 |       finish = ""
214 | /     try:
215 | |         finish = data["choices"][0].get("finish_reason") or ""
216 | |     except (KeyError, IndexError, TypeError):
217 | |         pass
    | |____________^
218 |       record_usage(
219 |           role=role,
    |
help: Replace `try`-`except`-`pass` with `with contextlib.suppress(KeyError, IndexError, TypeError): ...`

I001 [*] Import block is un-sorted or un-formatted
  --> tests\test_openai_contract.py:23:1
   |
21 |   """
22 |
23 | / from __future__ import annotations
24 | |
25 | | import asyncio
26 | | import json
27 | |
28 | | import httpx
29 | | import pytest
30 | |
31 | | import core.llm.compat as compat
32 | | import core.llm.usage_sink as usage_sink
33 | | from core.llm.lm_studio import LMStudioBackend
34 | | from core.llm.openai_client import OpenAIClientError, chat_completion, chat_completion_stream
   | |_____________________________________________________________________________________________^
35 |
36 |   # 最小合规请求体允许出现的顶层字段。**改这个集合前先想清楚「换一家还认吗」。**
   |
help: Organize imports
   |
33 | from core.llm.lm_studio import LMStudioBackend
   - from core.llm.openai_client import OpenAIClientError, chat_completion, chat_completion_stream
34 + from core.llm.openai_client import (
35 +     OpenAIClientError,
36 +     chat_completion,
37 +     chat_completion_stream,
38 + )
39 |
   |

F841 Local variable `ep` is assigned to but never used
   --> tests\test_openai_contract.py:383:5
    |
381 | def test_different_slots_learn_independently(monkeypatch):
382 |     """两个槽可能是两家厂商，一个的改法绝不能套到另一个头上。"""
383 |     ep = _install(monkeypatch, _MockEndpoint(_length_field_only))
    |     ^^
384 |     a = LMStudioBackend("http://a", model="m", api_key="k", kind="online", slot="ONLINE_CHAT")
385 |     asyncio.run(a.generate("hi"))
    |
help: Remove assignment to unused variable `ep`

Found 3 errors.
[*] 1 fixable with the `--fix` option (2 hidden fixes can be enabled with the `--unsafe-fixes` option).
(stella) PS E:\stella\stella_project> pytest tests -q
(中间省略)
============================================================================================= FAILURES ==============================================================================================
_______________________________________________________________________________ test_schema_marks_inherited_defaults ________________________________________________________________________________

    def test_schema_marks_inherited_defaults():
        """继承型配置项必须带 inherits，GUI 才知道「留空即继承谁」而不写成 KEY=。
    
        这一步缺失时 GUI 会把继承项写成空串落进 .env，继承链被静默切断
        （见 tests/test_env_inherit.py 的同源回归）。
        """
        schema = build_schema(PROJECT_ROOT / "config" / "settings.py")
        fields = {field["key"]: field for field in schema["fields"]}
        expected = {
            "CONSOLIDATION_LM_STUDIO_BASE_URL": "LM_STUDIO_BASE_URL",
            "CONSOLIDATION_LM_STUDIO_API_KEY": "LM_STUDIO_API_KEY",
            "MEMORY_EXTRACT_LM_STUDIO_BASE_URL": "LM_STUDIO_BASE_URL",
            "MEMORY_EXTRACT_LM_STUDIO_API_KEY": "LM_STUDIO_API_KEY",
            "MEMORY_EXTRACT_LM_STUDIO_MODEL": "LM_STUDIO_MODEL",
            "ASTRBOT_LLM_BASE_URL": "LM_STUDIO_BASE_URL",
            "ASTRBOT_LLM_MODEL": "LM_STUDIO_MODEL",
            "ASTRBOT_LLM_API_KEY": "LM_STUDIO_API_KEY",
        }
        for child, parent in expected.items():
            assert fields[child].get("inherits") == parent, f"{child} 缺 inherits 标记"
            # 继承型默认值无法静态求值，default 必须留空——写成别的值会误导 GUI
            assert fields[child]["default"] == ""
        # 非继承项不许莫名带上这个标记
        assert "inherits" not in fields["LM_STUDIO_BASE_URL"]
        inherited = {f["key"] for f in schema["fields"] if "inherits" in f}
>       assert inherited == set(expected), "继承项集合与预期不一致（新增继承项请同步本用例）"
E       AssertionError: 继承项集合与预期不一致（新增继承项请同步本用例）
E       assert {'ASTRBOT_LLM...API_KEY', ...} == {'ASTRBOT_LLM...API_KEY', ...}
E         
E         Extra items in the left set:
E         'LLM_ROLE_CONSOLIDATION_MAX_TOKENS'
E         'LLM_ENDPOINT_EXTRA_API_KEY'
E         'LLM_ROLE_EXTRACT_MODEL'
E         'LLM_ROLE_CHAT_MODEL'
E         'LLM_ROLE_PLUGIN_TEMPERATURE'...
E         
E         ...Full output truncated (12 lines hidden), use '-vv' to show

tests\test_env_schema.py:86: AssertionError
__________________________________________________ test_learns_to_omit_temperature[\u8be5\u6a21\u578b\u4e0d\u652f\u6301 temperature \u53c2\u6570] ___________________________________________________

message = '该模型不支持 temperature 参数'

    @pytest.mark.parametrize(
        "message",
        [
            "Unsupported value: 'temperature' does not support 0.7 with this model. "
            "Only the default (1) value is supported.",
            "temperature is not supported by this model",
            "该模型不支持 temperature 参数",
        ],
    )
    def test_learns_to_omit_temperature(message):
        state = compat.compat_for("S")
>       assert compat.learn_from_error(state, 400, _body(message)) == compat.FIX_OMIT_TEMPERATURE
E       AssertionError: assert '' == 'omit_temperature'
E         
E         - omit_temperature

tests\test_llm_compat.py:140: AssertionError
========================================================================================= warnings summary ==========================================================================================
C:\Users\Vegetable\.conda\envs\stella\Lib\site-packages\starlette\formparsers.py:12
  C:\Users\Vegetable\.conda\envs\stella\Lib\site-packages\starlette\formparsers.py:12: PendingDeprecationWarning: Please use `import python_multipart` instead.
    import multipart

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
====================================================================================== short test summary info ======================================================================================
FAILED tests/test_env_schema.py::test_schema_marks_inherited_defaults - AssertionError: 继承项集合与预期不一致（新增继承项请同步本用例）
FAILED tests/test_llm_compat.py::test_learns_to_omit_temperature[\u8be5\u6a21\u578b\u4e0d\u652f\u6301 temperature \u53c2\u6570] - AssertionError: assert '' == 'omit_temperature'
2 failed, 1290 passed, 3 skipped, 1 warning in 27.66s