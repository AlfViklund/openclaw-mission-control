"""Telegram bot test shims for optional aiogram dependency."""

from __future__ import annotations

import sys
import types


def _install_aiogram_stub() -> None:
    if "aiogram" in sys.modules:
        return

    aiogram = types.ModuleType("aiogram")

    class _Bot:
        def __init__(self, *args, **kwargs):
            _ = (args, kwargs)

        async def send_message(self, *args, **kwargs):
            _ = (args, kwargs)

        async def set_chat_menu_button(self, *args, **kwargs):
            _ = (args, kwargs)

    setattr(aiogram, "Bot", _Bot)
    setattr(aiogram, "Dispatcher", type("Dispatcher", (), {}))
    setattr(aiogram, "Router", type("Router", (), {}))
    setattr(aiogram, "BaseMiddleware", type("BaseMiddleware", (), {}))
    setattr(aiogram, "F", object())

    fsm = types.ModuleType("aiogram.fsm")
    fsm_context = types.ModuleType("aiogram.fsm.context")
    setattr(fsm_context, "FSMContext", type("FSMContext", (), {}))
    storage = types.ModuleType("aiogram.fsm.storage")
    storage_memory = types.ModuleType("aiogram.fsm.storage.memory")
    setattr(storage_memory, "MemoryStorage", type("MemoryStorage", (), {}))
    storage_redis = types.ModuleType("aiogram.fsm.storage.redis")
    setattr(storage_redis, "RedisStorage", type("RedisStorage", (), {}))

    types_mod = types.ModuleType("aiogram.types")
    for attr in [
        "Message",
        "CallbackQuery",
        "InlineKeyboardButton",
        "InlineKeyboardMarkup",
        "MenuButtonCommands",
    ]:
        setattr(types_mod, attr, type(attr, (), {}))

    class _BotCommand:
        def __init__(self, command: str, description: str) -> None:
            self.command = command
            self.description = description

    setattr(types_mod, "BotCommand", _BotCommand)

    filters = types.ModuleType("aiogram.filters")
    setattr(filters, "Command", type("Command", (), {}))

    sys.modules["aiogram"] = aiogram
    sys.modules["aiogram.fsm"] = fsm
    sys.modules["aiogram.fsm.context"] = fsm_context
    sys.modules["aiogram.fsm.storage"] = storage
    sys.modules["aiogram.fsm.storage.memory"] = storage_memory
    sys.modules["aiogram.fsm.storage.redis"] = storage_redis
    sys.modules["aiogram.types"] = types_mod
    sys.modules["aiogram.filters"] = filters


_install_aiogram_stub()
