"""Board and status command handlers."""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command

from bot.api_client import api

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("board"))
async def cmd_board(message: Message, state: FSMContext) -> None:
    """Select active board or list available boards."""
    args = message.text.split(maxsplit=1)
    board_name = args[1].strip() if len(args) > 1 else None

    try:
        boards = await api.list_boards()
    except Exception as exc:
        await message.answer(f"❌ Ошибка загрузки досок: {exc}")
        return

    if not boards:
        await message.answer("📋 Нет доступных досок.")
        return

    if board_name:
        matching = [b for b in boards if board_name.lower() in b.get("name", "").lower()]
        if matching:
            board = matching[0]
            await state.update_data(active_board_id=board["id"], active_board_name=board["name"])
            await message.answer(
                f"✅ Активная доска: *{board['name']}*\n"
                f"ID: `{board['id'][:8]}...`",
                parse_mode="Markdown",
            )
            return
        await message.answer(f"❌ Доска '{board_name}' не найдена.")
        return

    text = "📋 Доступные доски:\n\n"
    for b in boards:
        text += f"• *{b.get('name', 'Untitled')}*\n  `/board {b.get('name', '').lower()}`\n\n"
    text += "Используйте `/board <name>` для выбора."
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext) -> None:
    """Show project summary for the active board."""
    data = await state.get_data()
    board_id = data.get("active_board_id")
    board_name = data.get("active_board_name", "не выбрана")

    if not board_id:
        await message.answer(
            "⚠️ Активная доска не выбрана.\n"
            "Используйте `/board <name>` для выбора."
        )
        return

    try:
        tasks = await api.list_tasks(board_id)
        agents = await api.list_agents()
        approvals = await api.list_approvals(board_id)
    except Exception as exc:
        await message.answer(f"❌ Ошибка загрузки статуса: {exc}")
        return

    status_counts = {}
    for t in tasks:
        s = t.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    blocked = sum(1 for t in tasks if t.get("is_blocked"))
    board_agents = [a for a in agents if a.get("board_id") == board_id]
    online_agents = sum(1 for a in board_agents if a.get("status") == "online")

    text = f"📊 *Статус: {board_name}*\n\n"
    text += f"*Задачи:* {len(tasks)}\n"
    for s, c in sorted(status_counts.items()):
        text += f"  {s}: {c}\n"
    text += f"\n*Блокеры:* {blocked}"
    text += f"\n*Агенты:* {online_agents}/{len(board_agents)} online"
    text += f"\n*Pending approvals:* {len(approvals)}"

    await message.answer(text, parse_mode="Markdown")


@router.message(Command("task"))
async def cmd_task(message: Message, state: FSMContext) -> None:
    """Show task details."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Используйте `/task <id>`")
        return

    task_id = args[1].strip()
    data = await state.get_data()
    board_id = data.get("active_board_id")

    if not board_id:
        await message.answer(
            "⚠️ Активная доска не выбрана.\n"
            "Используйте `/board <name>` для выбора."
        )
        return

    try:
        task = await api.get_task(board_id, task_id)
        runs = await api.list_runs(task_id)
    except Exception as exc:
        await message.answer(f"❌ Ошибка: {exc}")
        return

    text = f"📌 *{task.get('title', 'Untitled')}*\n\n"
    text += f"ID: `{task_id[:8]}...`\n"
    text += f"Status: *{task.get('status', 'unknown')}*\n"
    text += f"Priority: {task.get('priority', 'medium')}\n"
    if task.get("estimate"):
        text += f"Estimate: {task.get('estimate')}\n"
    if task.get("suggested_agent_role"):
        text += f"Suggested role: {task.get('suggested_agent_role')}\n"
    if task.get("epic_id"):
        text += f"Epic: `{task.get('epic_id')}`\n"

    if task.get("description"):
        desc = task["description"][:200]
        text += f"\n{desc}{'...' if len(task['description']) > 200 else ''}\n"

    acceptance_criteria = task.get("acceptance_criteria") or []
    if acceptance_criteria:
        text += "\n*Acceptance criteria:*\n"
        for item in acceptance_criteria[:5]:
            text += f"  • {item}\n"

    tags = task.get("tags") or []
    if tags:
        tag_labels = ", ".join(tag.get("name", "") for tag in tags if tag.get("name"))
        if tag_labels:
            text += f"\n*Tags:* {tag_labels}\n"

    if runs:
        text += "\n*Pipeline:*\n"
        for r in runs[:5]:
            icon = "✅" if r["status"] == "succeeded" else "❌" if r["status"] == "failed" else "🔄"
            text += f"  {icon} {r['stage']} ({r['runtime']}) — {r['status']}\n"

    await message.answer(text, parse_mode="Markdown")
