"""Approvals command and callback handlers."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command

from bot.api_client import api

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("approvals"))
async def cmd_approvals(message: Message, state: FSMContext) -> None:
    """List pending approvals."""
    data = await state.get_data()
    board_id = data.get("active_board_id")

    if not board_id:
        await message.answer(
            "⚠️ Активная доска не выбрана.\n"
            "Используйте `/board <name>` для выбора."
        )
        return

    try:
        approvals = await api.list_approvals(board_id)
    except Exception as exc:
        await message.answer(f"❌ Ошибка: {exc}")
        return

    if not approvals:
        await message.answer("✅ Нет ожидающих подтверждений.")
        return

    for approval in approvals[:10]:
        task_id = str(approval.get("task_id") or "N/A")[:8]
        text = f"🔔 *Approval #{str(approval['id'])[:8]}*\n"
        text += f"Task: `{task_id}...`\n"
        text += f"Reason: {approval.get('reason', 'N/A')}\n"

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
async def cb_approve(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle approve callback."""
    approval_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    board_id = data.get("active_board_id")

    if not board_id:
        await callback.answer("⚠️ Board not selected", show_alert=True)
        return

    try:
        await api.resolve_approval(board_id, approval_id, "approved")
        await callback.answer("✅ Approved")
        if callback.message:
            await callback.message.edit_text(
                (callback.message.text or "") + "\n\n✅ *Approved*",
                parse_mode="Markdown",
            )
    except Exception as exc:
        await callback.answer(f"❌ Error: {exc}", show_alert=True)


@router.callback_query(F.data.startswith("reject:"))
async def cb_reject(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle reject callback."""
    approval_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    board_id = data.get("active_board_id")

    if not board_id:
        await callback.answer("⚠️ Board not selected", show_alert=True)
        return

    try:
        await api.resolve_approval(board_id, approval_id, "rejected")
        await callback.answer("❌ Rejected")
        if callback.message:
            await callback.message.edit_text(
                (callback.message.text or "") + "\n\n❌ *Rejected*",
                parse_mode="Markdown",
            )
    except Exception as exc:
        await callback.answer(f"❌ Error: {exc}", show_alert=True)
