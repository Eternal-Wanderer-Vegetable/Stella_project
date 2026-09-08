from core.llm.prefix_cache_estimator import estimate_local_prefix, reset_state


def setup_function():
    reset_state()


def teardown_function():
    reset_state()


def test_first_prompt_has_no_reusable_prefix():
    first = estimate_local_prefix(
        [{"role": "system", "content": "固定系统提示"}, {"role": "user", "content": "甲"}],
        slot="LOCAL",
        model="m",
    )

    assert first.prompt_tokens > 0
    assert first.cached_tokens == 0


def test_repeated_prompt_prefix_is_estimated_without_storing_text():
    messages = [
        {"role": "system", "content": "固定系统提示 " * 20},
        {"role": "user", "content": "动态问题"},
    ]
    first = estimate_local_prefix(messages, slot="LOCAL", model="m")
    second = estimate_local_prefix(messages, slot="LOCAL", model="m")

    assert second.cached_tokens == second.prompt_tokens
    assert first.prompt_tokens == second.prompt_tokens


def test_different_models_do_not_share_prefix_observation():
    messages = [{"role": "system", "content": "固定系统提示 " * 20}]
    estimate_local_prefix(messages, slot="LOCAL", model="a")

    other = estimate_local_prefix(messages, slot="LOCAL", model="b")

    assert other.cached_tokens == 0
