"""File/document handler — receives specs from Telegram and uploads to Artifact Hub."""

from __future__ import annotations

import logging
from pathlib import Path

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
import httpx

from bot.api_client import api
from bot.config import settings

logger = logging.getLogger(__name__)
router = Router()


@router.message(F.document)
async def handle_document(message: Message, state: FSMContext) -> None:
    """Handle document uploads — auto-upload as spec artifact."""
    doc = message.document
    if not doc or not doc.file_id:
        return

    data = await state.get_data()
    board_id = data.get("active_board_id")

    if not board_id:
        await message.answer(
            "⚠️ Активная доска не выбрана.\n"
            "Используйте `/board <name>` перед отправкой файлов."
        )
        return

    await message.answer(f"📥 Загружаю файл: *{doc.file_name}*", parse_mode="Markdown")

    try:
        bot = message.bot
        if not bot:
            await message.answer("❌ Bot не инициализирован.")
            return

        file = await bot.get_file(doc.file_id)
        if not file.file_path:
            await message.answer("❌ Не удалось получить файл.")
            return

        file_content = await bot.download_file(file.file_path)
        file_bytes = file_content.read()

        import io
        form_data = httpx._multipart.MultipartData()
        form_data.add_field("file", file_bytes, filename=doc.file_name or "unnamed")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.api_base_url}/api/v1/artifacts",
                headers={"Authorization": f"Bearer {settings.api_token}"},
                params={"board_id": board_id, "artifact_type": "spec", "source": "telegram"},
                files={"file": (doc.file_name or "unnamed", io.BytesIO(file_bytes))},
            )
            resp.raise_for_status()
            result = resp.json()

        await message.answer(
            f"✅ Файл *{doc.file_name}* загружен как спецификация!\n\n"
            f"ID: `{result.get('id', '')[:8]}...`\n"
            f"Размер: {result.get('size_bytes', 0)} bytes\n\n"
            f"Используйте `/plan` для генерации backlog.",
            parse_mode="Markdown",
        )

    except Exception as exc:
        logger.error("Failed to upload document: %s", exc)
        await message.answer(f"❌ Ошибка загрузки: {exc}")
