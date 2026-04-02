"""Tests for bot command registration and help text."""

from __future__ import annotations

import pytest

from bot.commands import BOT_COMMANDS, build_help_message, register_bot_commands


class _FakeBot:
    def __init__(self) -> None:
        self.commands = None
        self.menu_button = None

    async def set_my_commands(self, commands):
        self.commands = commands

    async def set_chat_menu_button(self, menu_button=None, **_kwargs):
        self.menu_button = menu_button


@pytest.mark.asyncio
async def test_register_bot_commands_sets_supported_commands() -> None:
    bot = _FakeBot()

    await register_bot_commands(bot)

    assert bot.commands == BOT_COMMANDS
    assert bot.menu_button is not None


def test_help_message_includes_core_commands() -> None:
    message = build_help_message()

    assert "/board <name>" in message
    assert "/status" in message
    assert "/approvals" in message
    assert "/panic" in message
    assert "/resume" in message
