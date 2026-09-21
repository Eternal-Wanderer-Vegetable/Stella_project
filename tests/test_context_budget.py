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


# ============================================================
# 知识证据独立预算（KNOWLEDGE_EVIDENCE_*）
# ============================================================


def test_evidence_budget_limits_items():
    from core.context_budget import fit_evidence_to_budget

    evidence = [{"text": f"证据{i}" + "内容" * 50} for i in range(6)]
    kept = fit_evidence_to_budget(evidence, max_items=2, max_tokens=10000)
    assert len(kept) == 2
    assert kept[0]["text"].startswith("证据0")


def test_evidence_budget_limits_tokens_and_keeps_prefix():
    from core.context_budget import fit_evidence_to_budget

    evidence = [
        {"text": "第一条" + "很长" * 200},
        {"text": "第二条" + "也很长" * 200},
        {"text": "第三条"},
    ]
    kept = fit_evidence_to_budget(evidence, max_items=10, max_tokens=150)
    # 第一条约 620 token，单独已超预算：保留首条后循环终止，其余丢弃
    assert [e["text"][:3] for e in kept] == ["第一条"]


def test_evidence_budget_keeps_first_even_if_over():
    """第一条永远保留：宁可一条长证据，不给空段。"""
    from core.context_budget import fit_evidence_to_budget

    evidence = [{"text": "超" * 5000}]
    kept = fit_evidence_to_budget(evidence, max_items=3, max_tokens=10)
    assert len(kept) == 1


def test_evidence_budget_empty():
    from core.context_budget import fit_evidence_to_budget

    assert fit_evidence_to_budget([], max_items=3, max_tokens=100) == []
