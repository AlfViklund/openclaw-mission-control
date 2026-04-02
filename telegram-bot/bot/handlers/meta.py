"""Meta command handlers for help and onboarding."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.commands import build_help_message

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(build_help_message(), parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(build_help_message(), parse_mode="Markdown")
