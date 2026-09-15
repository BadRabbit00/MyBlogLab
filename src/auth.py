"""Fail-closed access control for Telegram messages and callback buttons."""

import os
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


def allowed_user_ids() -> frozenset[int]:
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "")
    parts = [part.strip() for part in raw.split(",")]
    if not parts or any(not part.isascii() or not part.isdigit() or int(part) <= 0 for part in parts):
        raise ValueError("Set TELEGRAM_ALLOWED_USER_IDS to comma-separated positive Telegram user IDs")
    return frozenset(int(part) for part in parts)


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, user_ids: frozenset[int]):
        self.user_ids = user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, CallbackQuery) else event
        user = event.from_user
        if (
            user is None or user.id not in self.user_ids
            or message is None or message.chat.type != "private"
        ):
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ запрещён", show_alert=True)
            return None
        return await handler(event, data)
