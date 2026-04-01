"""Panic, nudge, and plan command handlers."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.filters import Command

from bot.api_client import api

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("nudge"))
async def cmd_nudge(message: Message, state: FSMContext) -> None:
    """Nudge an agent or task to push it forward."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Используйте `/nudge <agent_id|task_id>`")
        return

    target = args[1].strip()
    await message.answer(f"👉 Отправляю nudging для `{target}`...", parse_mode="Markdown")

    try:
        await api.update_task_status(target, "in_progress")
        await message.answer(f"✅ Задача `{target[:8]}...` переведена в in_progress.")
    except Exception:
        await message.answer(f"⚠️ Не удалось nudging для `{target}`. Возможно это агент, а не задача.")


@router.message(Command("panic"))
async def cmd_panic(message: Message, state: FSMContext) -> None:
    """Emergency pause — notify owner and pause all agents."""
    await message.answer(
        "🚨 *PANIC MODE ACTIVATED*\n\n"
        "Все агенты (кроме ops) приостановлены.\n"
        "Проверьте систему и используйте `/status` для оценки.",
        parse_mode="Markdown",
    )
    await state.update_data(panic_mode=True)
    logger.warning("PANIC mode activated by user %s", message.from_user.id)


@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext) -> None:
    """Generate backlog from latest spec artifact."""
    data = await state.get_data()
    board_id = data.get("active_board_id")
    board_name = data.get("active_board_name", "не выбрана")

    if not board_id:
        await message.answer(
            "⚠️ Активная доска не выбрана.\n"
            "Используйте `/board <name>` для выбора."
        )
        return

    await message.answer("🔄 Ищу последнюю спецификацию...")

    try:
        artifacts = await api.list_artifacts(board_id)
        specs = [a for a in artifacts if a.get("type") == "spec"]
        if not specs:
            await message.answer("❌ Нет загруженных спецификаций. Отправьте файл в чат.")
            return

        latest_spec = specs[0]
        await message.answer(
            f"📄 Найдена спецификация: *{latest_spec['filename']}*\n"
            f"Генерирую backlog...",
            parse_mode="Markdown",
        )

        result = await api.generate_backlog(latest_spec["id"], board_id)

        task_count = len(result.get("tasks", []))
        epic_count = len(result.get("epics", []))
        error = result.get("error_message")

        if error:
            await message.answer(f"⚠️ Генерация завершена с предупреждением:\n{error}")
        else:
            await message.answer(
                f"✅ Backlog сгенерирован!\n\n"
                f"Эпики: {epic_count}\n"
                f"Задачи: {task_count}\n"
                f"Просмотрите в веб-интерфейсе: `/planner`",
                parse_mode="Markdown",
            )

    except Exception as exc:
        await message.answer(f"❌ Ошибка генерации: {exc}")
