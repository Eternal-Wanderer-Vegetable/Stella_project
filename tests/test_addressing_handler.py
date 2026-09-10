from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from memory.addressing_intent import (
    SET_SELF_ADDRESS,
    AddressingRequest,
)


@pytest.fixture(scope="module")
def ai_gateway_module():
    import nonebot

    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()

    from stella_project.plugins.bot_main import ai_gateway

    return ai_gateway


class Event:
    def __init__(
        self,
        text: str,
        *,
        targets: list[str] | None = None,
        user_id: int = 111,
        role: str = "member",
        group_id: int = 1,
    ) -> None:
        self._text = text
        self.group_id = group_id
        self.user_id = user_id
        self.self_id = 9
        self.message_id = 42
        self.sender = SimpleNamespace(role=role)
        self._segments = [
            SimpleNamespace(type="at", data={"qq": str(self.self_id)}),
            *[
                SimpleNamespace(type="at", data={"qq": target})
                for target in (targets or [])
            ],
            SimpleNamespace(type="text", data={"text": text}),
        ]

    def is_tome(self) -> bool:
        return True

    def get_plaintext(self) -> str:
        return self._text

    def get_message(self):
        return self._segments


@pytest.fixture
def handler_env(ai_gateway_module, tmp_path, monkeypatch):
    gateway = ai_gateway_module
    from memory import addressing

    monkeypatch.setattr(gateway, "ADDRESSING_ENABLED", True)
    monkeypatch.setattr(gateway, "ALLOWED_GROUPS", {1})
    monkeypatch.setattr(gateway, "resolve_space", lambda group_id: "space_a")
    monkeypatch.setattr(addressing, "DB_PATH", tmp_path / "addressing.db")
    monkeypatch.setattr(
        gateway,
        "classify_addressing",
        AsyncMock(
            return_value=AddressingRequest(
                SET_SELF_ADDRESS,
                address_term="哥哥",
                confidence=0.95,
            )
        ),
    )
    monkeypatch.setattr(gateway, "_record_bot_lines", AsyncMock())
    monkeypatch.setattr(gateway.addressing_handler, "finish", AsyncMock())
    return gateway


@pytest.mark.asyncio
async def test_self_set_is_persisted_and_finishes_handler(handler_env):
    gateway = handler_env
    bot = SimpleNamespace(self_id="9")
    event = Event("以后叫我哥哥")

    await gateway.handle_addressing(bot, event)

    preference = gateway.addressing.get_preference("space_a", 111)
    assert preference is not None
    assert preference.address_term == "哥哥"
    gateway.addressing_handler.finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_can_set_address_for_explicit_at_target(handler_env):
    gateway = handler_env
    bot = SimpleNamespace(self_id="9")
    event = Event("以后叫他队长", targets=["1002"], role="admin")

    await gateway.handle_addressing(bot, event)

    preference = gateway.addressing.get_preference("space_a", 1002)
    assert preference is not None
    assert preference.address_term == "哥哥"
    assert preference.updated_by_user_id == "111"


@pytest.mark.asyncio
async def test_non_admin_cannot_set_address_for_other_user(handler_env):
    gateway = handler_env
    bot = SimpleNamespace(self_id="9")
    event = Event("以后叫他队长", targets=["1002"], role="member")

    await gateway.handle_addressing(bot, event)

    assert gateway.addressing.get_preference("space_a", 1002) is None
    gateway.addressing_handler.finish.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_address_without_target_is_clarified(handler_env):
    gateway = handler_env
    gateway.classify_addressing.return_value = AddressingRequest(
        "SET_OTHER_ADDRESS",
        address_term="队长",
        confidence=0.9,
    )
    bot = SimpleNamespace(self_id="9")
    event = Event("把用户的称呼改成队长")

    await gateway.handle_addressing(bot, event)

    assert gateway.addressing.get_preference("space_a", 111) is None
    gateway.addressing_handler.finish.assert_awaited_once()
