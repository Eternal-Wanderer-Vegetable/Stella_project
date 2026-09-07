from core.context_budget import estimate_tokens, fit_prompt_to_window


def test_short_prompt_is_unchanged():
    prompt = "当前对话很短。"
    result = fit_prompt_to_window(prompt, "系统提示")
    assert result.prompt == prompt
    assert result.truncated is False


def test_long_prompt_keeps_current_input_marker():
    context = "用户(2): 旧消息\n" * 500
    prompt = context + "\n【现在 用户(1) 对你说】请回答最后一句"
    result = fit_prompt_to_window(
        prompt,
        "",
        context_window_tokens=100,
        output_reserve_tokens=10,
        safety_tokens=10,
    )
    assert result.truncated is True
    assert "【现在 用户(1) 对你说】请回答最后一句" in result.prompt
    assert result.estimated_tokens <= result.budget_tokens


def test_estimate_tokens_is_nonzero_for_cjk():
    assert estimate_tokens("你好") >= 2
