"""Telegram bot main entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import settings
from bot.api_client import api
from bot.middleware import AllowlistMiddleware
from bot.handlers.board import router as board_router
from bot.handlers.approvals import router as approvals_router
from bot.handlers.control import router as control_router
from bot.handlers.files import router as files_router
from bot.notification_watermarks import get_watermark, set_watermark
from bot.notifications import (
    init_notifications,
    notify_agent_offline,
    notify_approval_pending,
    notify_build_failed,
    notify_pipeline_stage,
    notify_task_unblocked,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_notification_redis = None


def create_dispatcher() -> Dispatcher:
    """Create and configure the bot dispatcher."""
    storage = MemoryStorage()

    try:
        from redis.asyncio import Redis
        redis = Redis(host="redis", port=6379, db=1)
        storage = RedisStorage(redis=redis)
        logger.info("Using Redis FSM storage")
    except ImportError:
        logger.info("Using in-memory FSM storage")

    dp = Dispatcher(storage=storage)
    dp.update.middleware(AllowlistMiddleware())

    dp.include_router(board_router)
    dp.include_router(approvals_router)
    dp.include_router(control_router)
    dp.include_router(files_router)

    return dp


async def _escalation_seen(key: str) -> bool:
    global _notification_redis
    if _notification_redis is None:
        return False
    return bool(await _notification_redis.sismember("clawdev:notifications:seen", key))


async def _mark_escalation_seen(key: str) -> None:
    global _notification_redis
    if _notification_redis is None:
        return
    await _notification_redis.sadd("clawdev:notifications:seen", key)


async def _init_notification_redis() -> None:
    global _notification_redis
    if _notification_redis is not None:
        return
    try:
        from redis.asyncio import Redis

        _notification_redis = Redis(host="redis", port=6379, db=2)
        await _notification_redis.ping()
        logger.info("Using Redis escalation dedupe store")
    except Exception:
        _notification_redis = None
        logger.info("Using in-memory escalation dedupe semantics")


def _ts_to_iso(ts: float) -> str:
    """Convert a Unix timestamp to ISO 8601 string for API since parameter."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


async def notification_poll_loop(stop_event: asyncio.Event) -> None:
    """Poll backend for noteworthy events and push them to Telegram."""
    await _init_notification_redis()
    first_poll = True
    import time

    while not stop_event.is_set():
        try:
            now_ts = time.time()
            boards = await api.list_boards()

            for board in boards:
                board_id = board.get("id", "unknown")
                board_wm = await get_watermark(_notification_redis, "approval", destination=board_id)
                board_since = _ts_to_iso(board_wm) if board_wm > 0 else None
                board_approvals = await api.list_approvals(board_id, since=board_since)
                for approval in board_approvals:
                    approval_id = str(approval.get("id"))
                    if not approval_id or first_poll:
                        continue
                    await notify_approval_pending(approval)
                await set_watermark(_notification_redis, "approval", now_ts, destination=board_id)

                wm_build = await get_watermark(_notification_redis, "build_failed", destination=board_id)
                since_build = _ts_to_iso(wm_build) if wm_build > 0 else None
                failed_builds = await api.list_failed_build_runs(since=since_build, board_id=board_id)
                for run in failed_builds:
                    run_id = str(run.get("id"))
                    if not run_id or first_poll:
                        continue
                    await notify_build_failed(run)
                await set_watermark(_notification_redis, "build_failed", now_ts, destination=board_id)

                wm_run = await get_watermark(_notification_redis, "run_success", destination=board_id)
                since_run = _ts_to_iso(wm_run) if wm_run > 0 else None
                successful_runs = await api.list_runs_for_notifications(
                    status="succeeded",
                    since=since_run,
                    board_id=board_id,
                )
                for run in successful_runs:
                    run_id = str(run.get("id"))
                    if not run_id or first_poll:
                        continue
                    await notify_pipeline_stage(run)
                await set_watermark(_notification_redis, "run_success", now_ts, destination=board_id)

                wm_unblocked = await get_watermark(_notification_redis, "unblocked", destination=board_id)
                since_unblocked = _ts_to_iso(wm_unblocked) if wm_unblocked > 0 else None
                tasks = await api.list_unblocked_tasks(since=since_unblocked, board_id=board_id)
                for task in tasks:
                    task_id = str(task.get("id"))
                    if not task_id or first_poll:
                        continue
                    await notify_task_unblocked(task)
                await set_watermark(_notification_redis, "unblocked", now_ts, destination=board_id)

            escalations = await api.get_escalations()
            for event in escalations.get("escalations", []):
                key = f"{event.get('type')}:{event.get('agent_id') or event.get('run_id') or event.get('task_id')}"
                if await _escalation_seen(f"escalation:{key}"):
                    continue
                await _mark_escalation_seen(f"escalation:{key}")
                if not first_poll and event.get("type") == "agent_offline":
                    await notify_agent_offline(event)

            first_poll = False
        except Exception as exc:
            logger.warning("Notification poller failed: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=30)
        except TimeoutError:
            continue


async def main() -> None:
    """Start the Telegram bot."""
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher()

    allowed_ids = list(settings.allowed_ids)
    init_notifications(bot, allowed_ids)
    stop_event = asyncio.Event()
    notification_task = asyncio.create_task(notification_poll_loop(stop_event))

    logger.info("Starting ClawDev Telegram Bot...")
    logger.info("Allowed users: %s", allowed_ids or "NONE — all blocked!")
    logger.info("API URL: %s", settings.api_base_url)

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logger.info("Bot stopped")
    finally:
        stop_event.set()
        notification_task.cancel()
        with suppress(Exception):
            await notification_task
        if _notification_redis is not None:
            with suppress(Exception):
                await _notification_redis.aclose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
