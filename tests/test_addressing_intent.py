from __future__ import annotations

import asyncio

from memory import addressing_intent


class FakeEmbeddingService:
    def __init__(self, model: str = "fake") -> None:
        self.model = model
        self.calls: list[str] = []

    async def embed(self, text: str):
        self.calls.append(text)
        if text in addressing_intent._PROTOTYPES[addressing_intent.SET_SELF_ADDRESS]:
            return [1.0, 0.0, 0.0]
        if text in addressing_intent._PROTOTYPES[addressing_intent.SET_OTHER_ADDRESS]:
            return [0.0, 1.0, 0.0]
        if text in addressing_intent._PROTOTYPES[addressing_intent.CLEAR_ADDRESS]:
            return [0.0, 0.0, 1.0]
        if text in addressing_intent._PROTOTYPES[addressing_intent.QUERY_ADDRESS]:
            return [0.0, 0.0, 0.8]
        if "以后叫我" in text or "称呼我为" in text:
            return [1.0, 0.0, 0.0]
        return None


def test_rule_parser_handles_natural_chinese():
    result = asyncio.run(
        addressing_intent.classify_addressing(
            "以后叫我哥哥", service=FakeEmbeddingService()
        )
    )

    assert result.operation == addressing_intent.SET_SELF_ADDRESS
    assert result.address_term == "哥哥"
    assert result.needs_clarification is False


def test_ordinary_chat_is_rejected_by_prefilter():
    result = asyncio.run(
        addressing_intent.classify_addressing(
            "我哥哥来了", service=FakeEmbeddingService()
        )
    )

    assert result.operation == addressing_intent.NOT_ADDRESS_REQUEST


def test_missing_term_requires_clarification():
    result = asyncio.run(
        addressing_intent.classify_addressing(
            "以后叫我", service=FakeEmbeddingService()
        )
    )

    assert result.operation == addressing_intent.SET_SELF_ADDRESS
    assert result.needs_clarification is True
    assert result.address_term == ""


def test_other_user_natural_expression_extracts_term():
    result = asyncio.run(
        addressing_intent.classify_addressing(
            "以后叫他队长", service=FakeEmbeddingService()
        )
    )

    assert result.operation == addressing_intent.SET_OTHER_ADDRESS
    assert result.address_term == "队长"
    assert result.needs_clarification is False


def test_complete_rule_match_wins_over_semantic_margin(monkeypatch):
    async def ambiguous_match(text: str, service=None):
        return addressing_intent.SET_OTHER_ADDRESS, 0.8, True

    monkeypatch.setattr(addressing_intent, "_semantic_match", ambiguous_match)
    result = asyncio.run(
        addressing_intent.classify_addressing(
            "以后叫他队长", service=FakeEmbeddingService()
        )
    )

    assert result.operation == addressing_intent.SET_OTHER_ADDRESS
    assert result.address_term == "队长"
    assert result.needs_clarification is False


def test_prototype_cache_is_invalidated_when_model_changes():
    addressing_intent.reset_prototype_cache()
    first = FakeEmbeddingService("model-a")
    asyncio.run(addressing_intent.build_prototypes(first))
    first_calls = len(first.calls)

    second = FakeEmbeddingService("model-b")
    asyncio.run(addressing_intent.build_prototypes(second))

    assert first_calls > 0
    assert len(second.calls) == first_calls
