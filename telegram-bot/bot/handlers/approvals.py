"""Approvals command and callback handlers."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command

from bot.api_client import api

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("approvals"))
async def cmd_approvals(message: Message) -> None:
    """List pending approvals."""
    try:
        approvals = await api.list_approvals()
    except Exception as exc:
        await message.answer(f"❌ Ошибка: {exc}")
        return

    if not approvals:
        await message.answer("✅ Нет ожидающих подтверждений.")
        return

    for approval in approvals[:10]:
        text = f"🔔 *Approval #{approval['id'][:8]}*\n"
        text += f"Task: `{approval.get('task_id', 'N/A')[:8]}...`\n"
        text += f"Reason: {approval.get('reason', 'N/A')}\n"
        text += f"Confidence: {approval.get('confidence', 'N/A')}\n"

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Approve",
                        callback_data=f"approve:{approval['id']}",
                    ),
                    InlineKeyboardButton(
                        text="❌ Reject",
                        callback_data=f"reject:{approval['id']}",
                    ),
                ]
            ]
        )
        await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data.startswith("approve:"))
async def cb_approve(callback: CallbackQuery) -> None:
    """Handle approve callback."""
    approval_id = callback.data.split(":", 1)[1]
    try:
        await api.resolve_approval(approval_id, "approved")
        await callback.answer("✅ Approved")
        if callback.message:
            await callback.message.edit_text(
            callback.message.text + "\n\n✅ *Approved*",
            parse_mode="Markdown",
        )
    except Exception as exc:
        await callback.answer(f"❌ Error: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery) -> None:
    """Handle reject callback."""
    approval_id = callback.data.split(":", 1)[1]
    try:
        await api.resolve_approval(approval_id, "rejected")
        await callback.answer("❌ Rejected")
        if callback.message:
            await callback.message.edit_text(
            callback.message.text + "\n\n❌ *Rejected*",
            parse_mode="Markdown",
        )
    except Exception as exc:
        await callback.answer(f"❌ Error: {exc}", show_alert=True)
