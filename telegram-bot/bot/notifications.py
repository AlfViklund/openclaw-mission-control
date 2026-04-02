"""Telegram bot notification service — push messages to Telegram."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot

logger = logging.getLogger(__name__)

_bot: Bot | None = None
_allowed_chat_ids: list[int] = []


def init_notifications(bot: Bot, chat_ids: list[int]) -> None:
    global _bot, _allowed_chat_ids
    _bot = bot
    _allowed_chat_ids = chat_ids


async def notify(message: str, parse_mode: str = "Markdown") -> None:
    """Send a notification message to all allowed users."""
    if not _bot:
        logger.warning("Notification bot not initialized")
        return
    for chat_id in _allowed_chat_ids:
        try:
            await _bot.send_message(chat_id, message, parse_mode=parse_mode)
        except Exception as exc:
            logger.error("Failed to notify chat %s: %s", chat_id, exc)


async def notify_approval_pending(approval: dict[str, Any]) -> None:
    """Send notification about a pending approval."""
    reason = approval.get("payload", {}).get("reason", approval.get("reason", "N/A"))
    text = (
        f"🔔 *Новое подтверждение*\n\n"
        f"ID: `{approval.get('id', '')[:8]}...`\n"
        f"Task: `{str(approval.get('task_id') or 'N/A')[:8]}...`\n"
        f"Reason: {reason}\n\n"
        f"Используйте `/approvals` для просмотра."
    )
    await notify(text)


async def notify_build_failed(run: dict[str, Any]) -> None:
    """Send notification about a failed build."""
    text = (
        f"❌ *Build failed*\n\n"
        f"Task: `{run.get('task_id', 'N/A')[:8]}...`\n"
        f"Error: {run.get('error_message', 'Unknown')}"
    )
    await notify(text)


async def notify_agent_offline(agent: dict[str, Any]) -> None:
    """Send notification about an offline agent."""
    text = (
        f"⚠️ *Агент offline*\n\n"
        f"Name: {agent.get('name', 'Unknown')}\n"
        f"Last seen: {agent.get('last_seen_at', 'Never')}"
    )
    await notify(text)


async def notify_task_unblocked(task: dict[str, Any]) -> None:
    """Send notification about an unblocked task."""
    title = task.get("task_title") or task.get("title") or "Untitled"
    status = task.get("task_status") or task.get("status") or "inbox"
    message = task.get("message")
    text = (
        f"✅ *Задача разблокирована*\n\n"
        f"Task: `{title}`\n"
        f"Status: `{status}`"
    )
    if message:
        text += f"\nMessage: {message}"
    await notify(text)


async def notify_pipeline_stage(run: dict[str, Any]) -> None:
    """Send notification about a completed pipeline stage."""
    icon = "✅" if run.get("status") == "succeeded" else "❌"
    text = (
        f"{icon} *Pipeline: {run.get('stage', 'unknown')}*\n\n"
        f"Task: `{run.get('task_id', 'N/A')[:8]}...`\n"
        f"Status: {run.get('status', 'unknown')}\n"
        f"Runtime: {run.get('runtime', 'unknown')}"
    )
    await notify(text)
