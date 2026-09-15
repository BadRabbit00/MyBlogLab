from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Chat, Message, User

from src.auth import OwnerOnlyMiddleware, allowed_user_ids


@pytest.mark.parametrize("value", ["", " ", "123,", "-100", "0", "name", "１２３", "123,no"])
def test_invalid_owner_configuration_fails_closed(monkeypatch, value):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", value)
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_IDS"):
        allowed_user_ids()


def test_missing_owner_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    with pytest.raises(ValueError):
        allowed_user_ids()


def test_owner_ids_parse(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123, 456,123")
    assert allowed_user_ids() == frozenset({123, 456})


@pytest.mark.asyncio
@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("user_id,chat_type,allowed", [(123, "private", True), (456, "private", False), (123, "group", False)])
async def test_access_gate_precedes_handlers(callback, user_id, chat_type, allowed):
    user = User(id=user_id, is_bot=False, first_name="Test")
    message = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1, type=chat_type), from_user=user)
    event = CallbackQuery(id="test", from_user=user, chat_instance="test", message=message, data="approve:demo-01") if callback else message
    handler = AsyncMock(return_value="handled")
    with patch.object(CallbackQuery, "answer", new_callable=AsyncMock):
        result = await OwnerOnlyMiddleware(frozenset({123}))(handler, event, {})
    if allowed:
        handler.assert_awaited_once_with(event, {})
        assert result == "handled"
    else:
        handler.assert_not_awaited()
