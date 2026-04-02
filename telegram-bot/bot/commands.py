"""Telegram bot command menu helpers."""

from __future__ import annotations

from aiogram.types import BotCommand, MenuButtonCommands


BOT_COMMANDS = [
    BotCommand(command="start", description="Show a quick intro"),
    BotCommand(command="help", description="Show available commands"),
    BotCommand(command="board", description="List or select a board"),
    BotCommand(command="status", description="Show board status"),
    BotCommand(command="approvals", description="List pending approvals"),
    BotCommand(command="task", description="Show task details"),
    BotCommand(command="nudge", description="Wake an agent or task"),
    BotCommand(command="panic", description="Pause the active board"),
    BotCommand(command="resume", description="Resume the active board"),
    BotCommand(command="plan", description="Generate backlog from spec"),
]


def build_help_message() -> str:
    return (
        "*ClawDev Telegram Bot*\n\n"
        "Use `/board <name>` to select a board, then:\n"
        "• `/status` - board summary\n"
        "• `/approvals` - pending approvals\n"
        "• `/task <id>` - task details\n"
        "• `/nudge <agent_id|task_id>` - wake something up\n"
        "• `/panic` - pause the active board\n"
        "• `/resume` - resume the active board\n"
        "• `/plan` - generate backlog from the latest spec\n"
    )


async def register_bot_commands(bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
