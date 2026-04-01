"""Allowlist middleware — blocks unauthorized users."""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from bot.config import settings

logger = logging.getLogger(__name__)


class AllowlistMiddleware(BaseMiddleware):
    """Blocks all messages from users not in the allowed list."""

    async def __call__(
        self,
        handler: Callable[[Message | CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            return

        if settings.allowed_ids and user_id not in settings.allowed_ids:
            logger.warning("Blocked unauthorized user: %s", user_id)
            if isinstance(event, Message):
                await event.answer(
                    "🚫 Доступ запрещён. Вы не авторизованы для использования этого бота."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer("🚫 Доступ запрещён", show_alert=True)
            return

        return await handler(event, data)
